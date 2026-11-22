from __future__ import annotations

import os
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class Config:
    supabase_url: str
    supabase_service_role_key: str
    gemini_api_key: str
    groq_api_key: str
    chart_img_api_key: str
    telegram_bot_token: str
    telegram_chat_id: str
    openrouter_api_key: str = ""
    binance_fapi_base: str = "https://fapi.binance.com"
    gemini_api_base: str = "https://generativelanguage.googleapis.com/v1beta"
    groq_api_base: str = "https://api.groq.com/openai/v1"
    openrouter_api_base: str = "https://openrouter.ai/api/v1"
    chart_img_api_base: str = "https://api.chart-img.com"
    max_entry_deviation_pct: float = 0.25
    pending_entry_expiry_hours: int = 12
    paper_trading_only: bool = True
    log_level: str = "INFO"
    device_id: str = "redmi6a-main"
    device_name: str = "Redmi 6A"
    device_heartbeat_interval_seconds: int = 60
    device_telemetry_interval_seconds: int = 300
    device_offline_after_seconds: int = 180
    market_scan_interval_seconds: int = 900
    maintenance_interval_seconds: int = 60
    queue_poll_interval_seconds: int = 30
    device_low_battery_threshold: int = 40
    device_battery_rearm_threshold: int = 45
    device_state_path: str = "runtime/device_state.sqlite3"
    chart_img_symbol: str = "BINANCE:BTCUSDT.P"
    binance_api_key: str = ""
    binance_api_secret: str = ""
    real_trading_enabled: bool = False

    @classmethod
    def from_env(cls, require_all: bool = True) -> "Config":
        values = {
            "supabase_url": os.getenv("SUPABASE_URL", "").rstrip("/"),
            "supabase_service_role_key": os.getenv("SUPABASE_SERVICE_ROLE_KEY", ""),
            "gemini_api_key": os.getenv("GEMINI_API_KEY", ""),
            "groq_api_key": os.getenv("GROQ_API_KEY", ""),
            "chart_img_api_key": os.getenv("CHART_IMG_API_KEY", ""),
            "telegram_bot_token": os.getenv("TELEGRAM_BOT_TOKEN", ""),
            "telegram_chat_id": os.getenv("TELEGRAM_CHAT_ID", ""),
        }
        missing = [k.upper() for k, v in values.items() if not v]
        if require_all and missing:
            raise RuntimeError("Secrets ausentes: " + ", ".join(missing))
        if values["supabase_url"] and not values["supabase_url"].startswith("https://"):
            raise RuntimeError("SUPABASE_URL precisa começar com https://")
        return cls(
            **values,
            openrouter_api_key=os.getenv("OPENROUTER_API_KEY", ""),
            binance_fapi_base=os.getenv("BINANCE_FAPI_BASE", "https://fapi.binance.com").rstrip("/"),
            gemini_api_base=os.getenv("GEMINI_API_BASE", "https://generativelanguage.googleapis.com/v1beta").rstrip("/"),
            groq_api_base=os.getenv("GROQ_API_BASE", "https://api.groq.com/openai/v1").rstrip("/"),
            openrouter_api_base=os.getenv("OPENROUTER_API_BASE", "https://openrouter.ai/api/v1").rstrip("/"),
            chart_img_api_base=os.getenv("CHART_IMG_API_BASE", "https://api.chart-img.com").rstrip("/"),
            max_entry_deviation_pct=float(os.getenv("MAX_ENTRY_DEVIATION_PCT", "0.25")),
            pending_entry_expiry_hours=int(os.getenv("PENDING_ENTRY_EXPIRY_HOURS", "12")),
            paper_trading_only=os.getenv("PAPER_TRADING_ONLY", "true").lower() == "true",
            log_level=os.getenv("LOG_LEVEL", "INFO").upper(),
            device_id=os.getenv("APEX_DEVICE_ID", "redmi6a-main"),
            device_name=os.getenv("APEX_DEVICE_NAME", "Redmi 6A"),
            device_heartbeat_interval_seconds=max(30, int(os.getenv("DEVICE_HEARTBEAT_INTERVAL_SECONDS", "60"))),
            device_telemetry_interval_seconds=max(60, int(os.getenv("DEVICE_TELEMETRY_INTERVAL_SECONDS", "300"))),
            device_offline_after_seconds=max(120, int(os.getenv("DEVICE_OFFLINE_AFTER_SECONDS", "180"))),
            market_scan_interval_seconds=max(300, int(os.getenv("MARKET_SCAN_INTERVAL_SECONDS", "900"))),
            maintenance_interval_seconds=max(30, int(os.getenv("MAINTENANCE_INTERVAL_SECONDS", "60"))),
            queue_poll_interval_seconds=max(15, int(os.getenv("QUEUE_POLL_INTERVAL_SECONDS", "30"))),
            device_low_battery_threshold=min(100, max(1, int(os.getenv("DEVICE_LOW_BATTERY_THRESHOLD", "40")))),
            device_battery_rearm_threshold=min(100, max(1, int(os.getenv("DEVICE_BATTERY_REARM_THRESHOLD", "45")))),
            device_state_path=os.getenv("DEVICE_STATE_PATH", "runtime/device_state.sqlite3"),
            chart_img_symbol=os.getenv("CHART_IMG_SYMBOL", "BINANCE:BTCUSDT.P"),
            binance_api_key=os.getenv("BINANCE_FUTURES_API_KEY", ""),
            binance_api_secret=os.getenv("BINANCE_FUTURES_API_SECRET", ""),
            real_trading_enabled=os.getenv("APEX_REAL_TRADING_ENABLED", "false").lower() == "true",
        )

    def validate_paper_only(self) -> None:
        # Real order placement is intentionally not implemented/enabled in this build.
        if not self.paper_trading_only or self.real_trading_enabled:
            raise RuntimeError(
                "Modo real bloqueado nesta edição. Mantenha PAPER_TRADING_ONLY=true "
                "e APEX_REAL_TRADING_ENABLED=false."
            )
