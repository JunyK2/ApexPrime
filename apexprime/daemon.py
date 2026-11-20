from __future__ import annotations

import logging
import signal
import time
from datetime import datetime, timezone

from .config import Config
from .db import SupabaseREST
from .device import DeviceReporter
from .engine import ApexEngine
from .notify import TelegramNotifier
from .utils import setup_logging

log = logging.getLogger("apexprime.daemon")


def _next_due(last: float, interval: int, now: float) -> bool:
    return now - last >= interval


def run() -> int:
    config = Config.from_env(require_all=False)
    config.validate_paper_only()
    setup_logging(config.log_level)

    engine = ApexEngine(config)
    telegram = TelegramNotifier(config.telegram_bot_token, config.telegram_chat_id)
    reporter = DeviceReporter(engine.db, telegram, config)

    stopping = False
    def stop_handler(signum, frame):
        nonlocal stopping
        stopping = True
        log.warning("Sinal %s recebido; encerrando daemon", signum)
    signal.signal(signal.SIGTERM, stop_handler)
    signal.signal(signal.SIGINT, stop_handler)

    try:
        reporter.announce_start()
        telegram.send(f"🟢 APEXPRIME ONLINE\nServidor: {config.device_name}\nModo: SIMULAÇÃO\nScan: a cada {config.market_scan_interval_seconds // 60} min")
    except Exception as exc:
        # A boot-time network outage must not prevent the local worker from starting.
        log.warning("Sem conexão no início; heartbeat será reenviado automaticamente: %s", type(exc).__name__)

    now = time.monotonic()
    last_heartbeat = 0.0
    last_telemetry = 0.0
    last_maintenance = 0.0
    last_scan = 0.0
    last_queue = 0.0
    last_groq = 0.0
    last_snapshot = {}

    log.info("Daemon iniciado. heartbeat=%ss telemetry=%ss maintenance=%ss scan=%ss queue=%ss",
             config.device_heartbeat_interval_seconds, config.device_telemetry_interval_seconds,
             config.maintenance_interval_seconds, config.market_scan_interval_seconds,
             config.queue_poll_interval_seconds)

    try:
        while not stopping:
            now = time.monotonic()
            try:
                telemetry_due = _next_due(last_telemetry, config.device_telemetry_interval_seconds, now)
                heartbeat_due = _next_due(last_heartbeat, config.device_heartbeat_interval_seconds, now)
                if telemetry_due or heartbeat_due:
                    last_snapshot = reporter.publish(heartbeat=heartbeat_due, telemetry=telemetry_due)
                    if telemetry_due:
                        last_telemetry = now
                    if heartbeat_due:
                        last_heartbeat = now
            except Exception as exc:
                # Back off to the next heartbeat tick instead of retrying every 5 seconds.
                last_heartbeat = now
                if telemetry_due:
                    last_telemetry = now
                log.warning("Falha publicando telemetria/heartbeat; nova tentativa automática: %s", type(exc).__name__)

            if _next_due(last_maintenance, config.maintenance_interval_seconds, now):
                try:
                    engine.run_maintenance()
                except Exception as exc:
                    log.exception("Falha na manutenção de posições: %s", type(exc).__name__)
                    engine.db.log("ERROR", "daemon", "Falha na manutenção de posições", details={"error_type": type(exc).__name__})
                last_maintenance = now

            if _next_due(last_queue, config.queue_poll_interval_seconds, now):
                try:
                    engine.process_queue(max_requests=5)
                except Exception as exc:
                    log.warning("Fila indisponível; será consultada novamente: %s", type(exc).__name__)
                last_queue = now

            if _next_due(last_scan, config.market_scan_interval_seconds, now):
                try:
                    # 1H candles are the strategy source; this job checks for a newly closed 1H candle every 15m.
                    engine.run_hourly(include_maintenance=False, check_groq=False)
                except Exception as exc:
                    log.exception("Falha no scan 15m: %s", type(exc).__name__)
                    try:
                        engine.db.log("ERROR", "market_scan", "Falha no scan de mercado", details={"error_type": type(exc).__name__})
                    except Exception:
                        pass
                last_scan = now

            if _next_due(last_groq, config.market_scan_interval_seconds, now):
                try:
                    if not last_snapshot:
                        last_snapshot = reporter.reader.collect(config.device_id, config.device_name)
                    # Send Groq only the telemetry needed for server-health analysis.
                    # The local IP and raw API payload are deliberately not forwarded.
                    groq_snapshot = {
                        key: last_snapshot.get(key) for key in (
                            "device_id", "device_name", "device_model", "android_version",
                            "battery_percentage", "battery_status", "battery_plugged",
                            "is_charging", "battery_temperature_c", "battery_health",
                            "wifi_ssid", "wifi_rssi_dbm", "wifi_link_speed_mbps",
                            "wifi_frequency_mhz", "wifi_connected", "uptime_seconds",
                            "collected_at", "last_offline_gap_seconds", "reconnected_after_offline",
                        )
                    }
                    groq_snapshot.update({
                        "worker_status": "RUNNING",
                        "heartbeat_interval_seconds": config.device_heartbeat_interval_seconds,
                        "market_scan_interval_seconds": config.market_scan_interval_seconds,
                        "strategy_timeframe": "1h",
                    })
                    engine.run_device_health_check(groq_snapshot)
                except Exception as exc:
                    log.warning("Verificação Groq falhou: %s", type(exc).__name__)
                last_groq = now

            time.sleep(5)
    finally:
        try:
            reporter._event("SERVICE_STOPPED", {"reason": "daemon_shutdown"})
        except Exception:
            pass
        reporter.close()
        log.info("Daemon encerrado")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
