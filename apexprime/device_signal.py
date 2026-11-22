from __future__ import annotations

import json
import logging
import math
import shutil
import array
import sys
import subprocess
import time
import wave
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .db import SupabaseREST
from .utils import iso_utc

log = logging.getLogger("apexprime.device_signal")

SAMPLE_RATE = 44100
FREQUENCY_HZ = 440
AMPLITUDE = 0.90
ONE_SHOT_SECONDS = 2
CONTINUOUS_SECONDS = 60


def write_square_wave(path: str | Path, duration_seconds: int, *, frequency_hz: int = FREQUENCY_HZ,
                      sample_rate: int = SAMPLE_RATE, amplitude: float = AMPLITUDE) -> Path:
    """Create a mono 16-bit PCM square wave for Termux:API media playback."""
    if not 1 <= int(frequency_hz) <= 20000:
        raise ValueError("Frequência fora do intervalo permitido")
    if not 1 <= int(duration_seconds) <= 120:
        raise ValueError("Duração fora do intervalo permitido")
    amplitude = max(0.05, min(0.95, float(amplitude)))
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    peak = int(32767 * amplitude)
    total = sample_rate * int(duration_seconds)
    # array('h') builds a compact PCM buffer without millions of struct.pack calls;
    # this is substantially lighter on the Redmi 6A's Cortex-A53 CPU and RAM.
    frames = array.array("h", (
        peak if ((index * int(frequency_hz)) % sample_rate) < sample_rate // 2 else -peak
        for index in range(total)
    ))
    if sys.byteorder != "little":
        frames.byteswap()
    with wave.open(str(out), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        wav.writeframes(frames.tobytes())
    return out


def _run(command: list[str], timeout: float = 8) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, capture_output=True, text=True, timeout=timeout, check=False)


class DeviceSignalController:
    """Isolated square-wave signal service; intentionally has no Telegram dependency."""

    def __init__(self, db: SupabaseREST, runtime_dir: str | Path = "runtime/device_signal"):
        self.db = db
        self.runtime_dir = Path(runtime_dir)
        self.beep_file = self.runtime_dir / "square_440hz_2s.wav"
        self.continuous_file = self.runtime_dir / "square_440hz_60s.wav"
        self.last_poll = 0.0
        self.poll_interval = 1.0
        self.unlocked = False
        self.continuous_wanted = False
        self.continuous_started = 0.0
        self.active_command_id: str | None = None
        self.active_command_deadline = 0.0
        self.active_continuous = False
        self.last_volume_forced: bool | None = None
        self.previous_music_volume: int | None = None
        self.next_retry_at = 0.0
        self.failure_backoff = 1.0
        self.available = bool(shutil.which("termux-media-player") and shutil.which("termux-volume"))

    def _ensure_audio(self) -> None:
        if not self.beep_file.exists():
            write_square_wave(self.beep_file, ONE_SHOT_SECONDS)
        if not self.continuous_file.exists():
            write_square_wave(self.continuous_file, CONTINUOUS_SECONDS)

    def _force_media_max_volume(self) -> bool:
        """Set the Android media stream to its reported maximum volume."""
        try:
            result = _run(["termux-volume"], timeout=6)
            if result.returncode != 0 or not result.stdout.strip():
                return False
            parsed = json.loads(result.stdout)
            streams = parsed if isinstance(parsed, list) else parsed.get("streams", [])
            music = next((item for item in streams if str(item.get("stream", "")).lower() == "music"), None)
            if not music:
                return False
            max_volume = int(music.get("max_volume"))
            current = int(music.get("volume", -1))
            if max_volume < 1 or current < 0:
                return False
            if self.previous_music_volume is None:
                self.previous_music_volume = current
            if current != max_volume:
                set_result = _run(["termux-volume", "music", str(max_volume)], timeout=6)
                if set_result.returncode != 0:
                    self.previous_music_volume = None
                    return False
            return True
        except Exception as exc:
            log.warning("Não foi possível definir volume máximo da mídia: %s", type(exc).__name__)
            return False

    def _restore_media_volume(self) -> None:
        """Restore the user's media volume after the signal ends."""
        previous = self.previous_music_volume
        self.previous_music_volume = None
        if previous is None or not self.available:
            return
        try:
            _run(["termux-volume", "music", str(previous)], timeout=6)
        except Exception as exc:
            log.warning("Não foi possível restaurar o volume anterior: %s", type(exc).__name__)

    def _play(self, path: Path) -> None:
        if not self.available:
            raise RuntimeError("Termux:API não disponível: instale o app Termux:API e o pacote termux-api")
        self._ensure_audio()
        self.last_volume_forced = self._force_media_max_volume()
        result = _run(["termux-media-player", "play", str(path.resolve())], timeout=12)
        if result.returncode != 0:
            self._restore_media_volume()
            raise RuntimeError((result.stderr or result.stdout or "termux-media-player falhou")[:350])

    def _stop(self) -> None:
        if self.available:
            try:
                _run(["termux-media-player", "stop"], timeout=5)
            except Exception:
                pass
        self._restore_media_volume()
        self.active_continuous = False
        self.continuous_started = 0.0

    def _get_security(self) -> dict[str, Any] | None:
        rows = self.db.select("device_signal_security", {"id": "eq.1"},
                              select="id,is_unlocked,continuous_wanted,updated_at", limit=1)
        return rows[0] if rows else None

    def _set_command(self, command_id: str, status: str, *, result: dict[str, Any] | None = None,
                     error: str | None = None) -> None:
        values: dict[str, Any] = {"status": status}
        if status == "COMPLETED":
            values["completed_at"] = iso_utc()
        if result is not None:
            values["result"] = result
        if error:
            values["error_message"] = error[:500]
            values["completed_at"] = iso_utc()
        self.db.update("device_signal_commands", {"id": f"eq.{command_id}"}, values)

    def _service_result(self, *, mode: str, command_id: str | None = None) -> dict[str, Any]:
        return {
            "mode": mode,
            "frequency_hz": FREQUENCY_HZ,
            "waveform": "square",
            "duration_seconds": ONE_SHOT_SECONDS if mode == "ONE_SHOT" else CONTINUOUS_SECONDS,
            "volume_stream": "music",
            "volume_forced_max": bool(self.last_volume_forced),
            "audio_route": "saída de mídia atual do Android; usa fone se o aparelho o reconhecer",
            "played_at": iso_utc(),
            "command_id": command_id,
        }

    def tick(self, now_monotonic: float | None = None) -> None:
        """Poll lock/schedule state and execute due sound commands. No Telegram messages."""
        now_mono = time.monotonic() if now_monotonic is None else now_monotonic
        if now_mono - self.last_poll < self.poll_interval or now_mono < self.next_retry_at:
            return
        self.last_poll = now_mono
        try:
            state = self._get_security()
            self.failure_backoff = 1.0
            self.next_retry_at = 0.0
            if not state:
                return
            self.unlocked = bool(state.get("is_unlocked"))
            self.continuous_wanted = bool(state.get("continuous_wanted"))

            # A server-side lock always takes priority over completion. If the user
            # locks while a sound is playing, stop it and mark the command CANCELLED.
            if not self.unlocked:
                self._stop()
                if self.active_command_id:
                    self._set_command(self.active_command_id, "CANCELLED", error="Função travada durante a execução")
                    self.active_command_id = None
                    self.active_command_deadline = 0.0
                self.db.update("device_signal_commands", {"status": "in.(PENDING,PROCESSING)"}, {
                    "status": "CANCELLED", "completed_at": iso_utc(),
                    "error_message": "Cancelado porque a função de sinal está travada",
                })
                return

            # Complete a one-shot only after its two-second playback interval.
            if self.active_command_id and now_mono >= self.active_command_deadline:
                command_id = self.active_command_id
                self._set_command(command_id, "COMPLETED", result=self._service_result(mode="ONE_SHOT", command_id=command_id))
                self._restore_media_volume()
                self.active_command_id = None
                self.active_command_deadline = 0.0

            if self.continuous_wanted:
                if self.active_command_id:
                    self._set_command(self.active_command_id, "CANCELLED", error="Modo contínuo ativado")
                    self.active_command_id = None
                if not self.active_continuous or now_mono - self.continuous_started >= 58:
                    self._stop()
                    self._play(self.continuous_file)
                    self.active_continuous = True
                    self.continuous_started = now_mono
                # The continuous signal is the only active playback mode while enabled.
                return

            if self.active_continuous:
                self._stop()

            if self.active_command_id:
                return

            pending = self.db.select("device_signal_commands", {"status": "eq.PENDING"},
                                     order="created_at.asc", limit=25)
            current = datetime.now(timezone.utc)
            due = []
            for item in pending:
                scheduled = item.get("scheduled_at")
                if not scheduled:
                    due.append(item)
                    continue
                due_at = datetime.fromisoformat(str(scheduled).replace("Z", "+00:00"))
                if due_at.tzinfo is None:
                    due_at = due_at.replace(tzinfo=timezone.utc)
                if due_at <= current:
                    due.append(item)
            if not due:
                return
            command = due[0]
            command_id = str(command["id"])
            claimed = self.db.update("device_signal_commands", {
                "id": f"eq.{command_id}", "status": "eq.PENDING",
            }, {"status": "PROCESSING", "started_at": iso_utc()})
            if not claimed:
                return
            # Re-check the server lock immediately before starting playback.
            latest = self._get_security()
            if not latest or not latest.get("is_unlocked"):
                self._set_command(command_id, "CANCELLED", error="Função travada antes da execução")
                return
            try:
                self._play(self.beep_file)
                self.active_command_id = command_id
                self.active_command_deadline = now_mono + ONE_SHOT_SECONDS + 0.35
            except Exception as exc:
                self._restore_media_volume()
                self._set_command(command_id, "FAILED", error=f"Falha ao tocar o sinal: {type(exc).__name__}: {exc}")
        except Exception as exc:
            # Supabase outages must not crash the trading worker or spam the log.
            self.next_retry_at = now_mono + self.failure_backoff
            self.failure_backoff = min(30.0, max(2.0, self.failure_backoff * 2.0))
            log.warning("Módulo de sinal indisponível; próxima tentativa em %.0fs: %s",
                        self.failure_backoff, type(exc).__name__)

    def shutdown(self) -> None:
        """Stop any active audio when the daemon exits or is restarted."""
        try:
            self._stop()
        finally:
            if self.active_command_id:
                try:
                    self._set_command(self.active_command_id, "CANCELLED", error="Servidor encerrado durante o sinal")
                except Exception:
                    pass
                self.active_command_id = None
                self.active_command_deadline = 0.0
