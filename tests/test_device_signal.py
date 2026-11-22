import wave
import struct

import pytest

from apexprime.device_signal import FREQUENCY_HZ, ONE_SHOT_SECONDS, SAMPLE_RATE, write_square_wave


def test_square_wave_is_44100hz_mono_16bit_two_seconds(tmp_path):
    path = write_square_wave(tmp_path / "signal.wav", ONE_SHOT_SECONDS)
    with wave.open(str(path), "rb") as wav:
        assert wav.getnchannels() == 1
        assert wav.getsampwidth() == 2
        assert wav.getframerate() == SAMPLE_RATE
        assert wav.getnframes() == SAMPLE_RATE * ONE_SHOT_SECONDS
        samples = wav.readframes(1000)
        assert len(samples) == 2000
        signed = struct.unpack("<1000h", samples)
        assert max(signed) > 20000
        assert min(signed) < -20000


def test_square_wave_rejects_unsafe_frequency_or_duration(tmp_path):
    with pytest.raises(ValueError):
        write_square_wave(tmp_path / "bad.wav", 2, frequency_hz=0)
    with pytest.raises(ValueError):
        write_square_wave(tmp_path / "bad.wav", 0)


def test_square_wave_frequency_constant_is_440hz():
    assert FREQUENCY_HZ == 440


def test_signal_restores_previous_android_media_volume(monkeypatch, tmp_path):
    import json
    import subprocess
    import apexprime.device_signal as module

    calls = []
    responses = [
        subprocess.CompletedProcess([], 0, stdout=json.dumps([
            {"stream": "music", "volume": 4, "max_volume": 15}
        ]), stderr=""),
        subprocess.CompletedProcess([], 0, stdout="", stderr=""),
        subprocess.CompletedProcess([], 0, stdout="", stderr=""),
    ]

    def fake_run(command, timeout=8):
        calls.append(command)
        return responses.pop(0)

    monkeypatch.setattr(module, "_run", fake_run)
    controller = module.DeviceSignalController(db=object(), runtime_dir=tmp_path)
    controller.available = True
    assert controller._force_media_max_volume() is True
    assert calls[1] == ["termux-volume", "music", "15"]
    assert controller.previous_music_volume == 4
    controller._restore_media_volume()
    assert calls[2] == ["termux-volume", "music", "4"]
    assert controller.previous_music_volume is None


def test_signal_module_does_not_import_or_send_telegram():
    from pathlib import Path
    source = (Path(__file__).resolve().parents[1] / "apexprime" / "device_signal.py").read_text(encoding="utf-8")
    assert "TelegramNotifier" not in source
    assert "telegram.send" not in source


def test_signal_module_does_not_import_or_send_telegram():
    from pathlib import Path
    source = (Path(__file__).resolve().parents[1] / "apexprime" / "device_signal.py").read_text(encoding="utf-8")
    assert "TelegramNotifier" not in source
    assert "telegram.send" not in source
