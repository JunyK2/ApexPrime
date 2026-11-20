from __future__ import annotations

import json
import logging
import os
import re
import sqlite3
import subprocess
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

from .utils import iso_utc

log = logging.getLogger("apexprime.device")


def _run(command: list[str], timeout: int = 8) -> str | None:
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=timeout)
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    except Exception:
        return None
    return None


def _termux_json(command: str) -> dict[str, Any] | None:
    raw = _run([command], timeout=10)
    if not raw:
        return None
    try:
        value = json.loads(raw)
        return value if isinstance(value, dict) else None
    except (ValueError, TypeError):
        log.warning("Saída JSON inválida de %s", command)
        return None


def _number(value: Any) -> float | None:
    if value is None:
        return None
    try:
        if isinstance(value, str):
            value = value.strip().replace(",", ".")
        n = float(value)
        return n if n == n and abs(n) != float("inf") else None
    except (TypeError, ValueError):
        return None


class TermuxDeviceReader:
    """Reads telemetry via Termux:API; root-based getprop is only a fallback."""

    def collect(self, device_id: str, device_name: str) -> dict[str, Any]:
        battery = _termux_json("termux-battery-status") or {}
        wifi = _termux_json("termux-wifi-connectioninfo") or {}

        percentage = battery.get("percentage")
        try:
            percentage = int(percentage) if percentage is not None else None
        except (TypeError, ValueError):
            percentage = None

        temperature = _number(battery.get("temperature"))
        status = str(battery.get("status") or "UNKNOWN").upper()
        plugged = str(battery.get("plugged") or "UNKNOWN").upper()
        charging = status in {"CHARGING", "FULL"} or plugged.startswith("PLUGGED_")

        rssi = _number(wifi.get("rssi"))
        if rssi is not None:
            rssi = int(rssi)
        ssid = wifi.get("ssid")
        if not ssid or str(ssid).strip().lower() in {"<unknown ssid>", "unknown ssid", "0x"}:
            ssid = None
        if isinstance(ssid, str):
            ssid = ssid.strip().strip('"')

        model = (_run(["getprop", "ro.product.model"]) or
                 _run(["su", "-c", "getprop ro.product.model"]) or "Redmi 6A")
        android_version = (_run(["getprop", "ro.build.version.release"]) or
                           _run(["su", "-c", "getprop ro.build.version.release"]) or "8")
        uptime_raw = _run(["cat", "/proc/uptime"])
        uptime_seconds = None
        if uptime_raw:
            try:
                uptime_seconds = int(float(uptime_raw.split()[0]))
            except (ValueError, IndexError):
                pass

        wifi_connected = bool(ssid or rssi is not None) and str(wifi.get("supplicant_state", "")).upper() in {"COMPLETED", ""}
        return {
            "device_id": device_id,
            "device_name": device_name,
            "device_model": model,
            "android_version": android_version,
            "battery_percentage": percentage,
            "battery_status": status,
            "battery_plugged": plugged,
            "is_charging": bool(charging),
            "battery_temperature_c": temperature,
            "battery_health": battery.get("health"),
            "wifi_ssid": ssid,
            "wifi_rssi_dbm": rssi,
            "wifi_link_speed_mbps": _number(wifi.get("link_speed_mbps")),
            "wifi_frequency_mhz": _number(wifi.get("frequency_mhz")),
            "wifi_ip": wifi.get("ip"),
            "wifi_connected": wifi_connected,
            "uptime_seconds": uptime_seconds,
            "collected_at": iso_utc(),
            "telemetry_source": "termux-api",
            "raw_battery": battery,
            "raw_wifi": {k: v for k, v in wifi.items() if k not in {"bssid", "mac_address"}},
        }


class DeviceReporter:
    def __init__(self, db, telegram, config):
        self.db = db
        self.telegram = telegram
        self.config = config
        self.reader = TermuxDeviceReader()
        self.state_path = Path(config.device_state_path)
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.state_path))
        self.conn.execute("CREATE TABLE IF NOT EXISTS kv (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        self.conn.commit()

    def _get(self, key: str) -> str | None:
        row = self.conn.execute("SELECT value FROM kv WHERE key=?", (key,)).fetchone()
        return row[0] if row else None

    def _set(self, key: str, value: str) -> None:
        self.conn.execute("INSERT INTO kv(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, value))
        self.conn.commit()

    def _event(self, event_type: str, details: dict[str, Any] | None = None,
               occurred_at: str | None = None) -> None:
        self.db.insert("device_events", {
            "device_id": self.config.device_id,
            "event_type": event_type,
            "occurred_at": occurred_at or iso_utc(),
            "details": details or {},
        })

    def announce_start(self) -> None:
        # Ensure FK parent exists even when the first event is emitted before telemetry.
        self.db.upsert("apex_devices", {
            "device_id": self.config.device_id,
            "device_name": self.config.device_name,
            "status": "ONLINE",
        }, on_conflict="device_id")
        self._event("SERVICE_STARTED", {"device_name": self.config.device_name})

    def publish(self, *, heartbeat: bool = True, telemetry: bool = True) -> dict[str, Any]:
        snapshot = self.reader.collect(self.config.device_id, self.config.device_name)
        device_id = self.config.device_id
        now = iso_utc()

        previous = self.db.select("apex_devices", {"device_id": f"eq.{device_id}"}, limit=1)
        previous = previous[0] if previous else {}
        was_low_alerted = bool(previous.get("low_battery_alert_active", False))

        if telemetry:
            payload = {
                "device_id": device_id,
                "device_name": self.config.device_name,
                "device_model": snapshot.get("device_model"),
                "android_version": snapshot.get("android_version"),
                "status": "ONLINE",
                "battery_percentage": snapshot.get("battery_percentage"),
                "battery_status": snapshot.get("battery_status"),
                "battery_plugged": snapshot.get("battery_plugged"),
                "is_charging": snapshot.get("is_charging"),
                "battery_temperature_c": snapshot.get("battery_temperature_c"),
                "battery_health": snapshot.get("battery_health"),
                "wifi_ssid": snapshot.get("wifi_ssid"),
                "wifi_rssi_dbm": snapshot.get("wifi_rssi_dbm"),
                "wifi_link_speed_mbps": snapshot.get("wifi_link_speed_mbps"),
                "wifi_frequency_mhz": snapshot.get("wifi_frequency_mhz"),
                "wifi_ip": snapshot.get("wifi_ip"),
                "wifi_connected": snapshot.get("wifi_connected"),
                "uptime_seconds": snapshot.get("uptime_seconds"),
                "last_seen_at": now,
                "last_telemetry_at": now,
                "low_battery_alert_active": was_low_alerted,
                "metadata": {"telemetry_source": snapshot.get("telemetry_source")},
            }
            self.db.upsert("apex_devices", payload, on_conflict="device_id")

            old_ssid = self._get("last_wifi_ssid")
            new_ssid = snapshot.get("wifi_ssid") or ""
            if old_ssid is not None and old_ssid != new_ssid:
                self._event("WIFI_CHANGED", {"from": old_ssid or None, "to": new_ssid or None})
            self._set("last_wifi_ssid", new_ssid)

            pct = snapshot.get("battery_percentage")
            if pct is not None and pct < self.config.device_low_battery_threshold and not was_low_alerted:
                message = (f"🔋 APEXPRIME — BATERIA BAIXA\n{self.config.device_name}: {pct}%\n"
                           f"Carregando: {'sim' if snapshot.get('is_charging') else 'não'}\n"
                           f"Temperatura: {snapshot.get('battery_temperature_c') or 'N/D'} °C\n"
                           "Conecte o servidor ao carregador para evitar interrupções.")
                if self.telegram.send(message):
                    self.db.update("apex_devices", {"device_id": f"eq.{device_id}"}, {"low_battery_alert_active": True})
                    self._event("LOW_BATTERY_ALERT", {"percentage": pct, "threshold": self.config.device_low_battery_threshold})
                    snapshot["low_battery_alert_active"] = True
            elif pct is not None and pct >= self.config.device_battery_rearm_threshold and was_low_alerted:
                self.db.update("apex_devices", {"device_id": f"eq.{device_id}"}, {"low_battery_alert_active": False})
                self._event("BATTERY_RECOVERED", {"percentage": pct, "rearm_threshold": self.config.device_battery_rearm_threshold})
                snapshot["low_battery_alert_active"] = False

        if heartbeat:
            # Detect outages from the last successful heartbeat persisted on-device.
            last_local = self._get("last_successful_heartbeat")
            if last_local:
                try:
                    last_dt = datetime.fromisoformat(last_local.replace("Z", "+00:00"))
                    gap = max(0, int((datetime.now(timezone.utc) - last_dt).total_seconds()))
                    if gap >= self.config.device_offline_after_seconds:
                        estimated = last_dt + timedelta(seconds=self.config.device_offline_after_seconds)
                        self._event("OFFLINE_GAP", {
                            "estimated_offline_at": iso_utc(estimated),
                            "reconnected_at": now,
                            "gap_seconds": gap,
                            "precision": "estimativa baseada no último heartbeat confirmado pelo Supabase",
                        }, occurred_at=iso_utc(estimated))
                        self._event("ONLINE", {"recovered_after_gap_seconds": gap})
                        snapshot["last_offline_gap_seconds"] = gap
                        snapshot["reconnected_after_offline"] = True
                except Exception:
                    pass
            self.db.insert("device_heartbeats", {
                "device_id": device_id,
                "seen_at": now,
                "network_online": True,
                "worker_status": "RUNNING",
                "metadata": {
                    "battery_percentage": snapshot.get("battery_percentage"),
                    "wifi_connected": snapshot.get("wifi_connected"),
                    "uptime_seconds": snapshot.get("uptime_seconds"),
                },
            })
            self.db.update("apex_devices", {"device_id": f"eq.{device_id}"}, {
                "last_seen_at": now, "status": "ONLINE"
            })
            self._set("last_successful_heartbeat", now)

        return snapshot

    def close(self):
        try:
            self.conn.close()
        except Exception:
            pass
