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
    binance_fapi_base: str = "https://fapi.binance.com"
    gemini_api_base: str = "https://generativelanguage.googleapis.com/v1beta"
    groq_api_base: str = "https://api.groq.com/openai/v1"
    chart_img_api_base: str = "https://api.chart-img.com"
    max_entry_deviation_pct: float = 0.25
    pending_entry_expiry_hours: int = 12
    paper_trading_only: bool = True
    log_level: str = "INFO"

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
            binance_fapi_base=os.getenv("BINANCE_FAPI_BASE", "https://fapi.binance.com").rstrip("/"),
            gemini_api_base=os.getenv("GEMINI_API_BASE", "https://generativelanguage.googleapis.com/v1beta").rstrip("/"),
            groq_api_base=os.getenv("GROQ_API_BASE", "https://api.groq.com/openai/v1").rstrip("/"),
            chart_img_api_base=os.getenv("CHART_IMG_API_BASE", "https://api.chart-img.com").rstrip("/"),
            max_entry_deviation_pct=float(os.getenv("MAX_ENTRY_DEVIATION_PCT", "0.25")),
            pending_entry_expiry_hours=int(os.getenv("PENDING_ENTRY_EXPIRY_HOURS", "12")),
            paper_trading_only=os.getenv("PAPER_TRADING_ONLY", "true").lower() == "true",
            log_level=os.getenv("LOG_LEVEL", "INFO").upper(),
        )

    def validate_paper_only(self) -> None:
        if not self.paper_trading_only:
            raise RuntimeError("PAPER_TRADING_ONLY precisa permanecer true. Este projeto não envia ordens reais.")
