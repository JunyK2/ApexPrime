from __future__ import annotations

import json
import logging
import math
import re
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo


def setup_logging(level: str = "INFO") -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso_utc(value: datetime | None = None) -> str:
    value = value or utc_now()
    return value.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def from_ms(ms: int) -> datetime:
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc)


def to_ms(value: datetime) -> int:
    return int(value.timestamp() * 1000)


def json_safe(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, datetime):
        return iso_utc(value)
    if isinstance(value, dict):
        return {k: json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(v) for v in value]
    return value


def clean_error(message: str, *secrets: str) -> str:
    text = str(message)
    for secret in secrets:
        if secret:
            text = text.replace(secret, "[REDACTED]")
    text = re.sub(r"(?i)\b(api_key|token|authorization|key)[=: ]+[^\s,;]+", r"\1=[REDACTED]", text)
    return text[:1500]


def safe_float(value: Any, default: float | None = None) -> float | None:
    try:
        result = float(value)
        return result if math.isfinite(result) else default
    except (TypeError, ValueError):
        return default



def safe_timezone_name(value: Any, default: str = "America/Sao_Paulo") -> str:
    """Return a valid IANA timezone; corrupted DB values never crash chart generation."""
    candidate = str(value or default).strip()
    try:
        ZoneInfo(candidate)
        return candidate
    except Exception:
        ZoneInfo(default)
        return default


def local_time_label(value: datetime, timezone_name: str) -> str:
    tz = ZoneInfo(safe_timezone_name(timezone_name))
    return value.astimezone(tz).strftime("%d/%m %H:%M")


def extract_json_object(raw: str) -> dict[str, Any]:
    """Extract exactly one JSON object from an APEX_TABLE response."""
    match = re.search(r"\[APEX_TABLE\](.*?)\[/APEX_TABLE\]", raw, flags=re.I | re.S)
    source = match.group(1).strip() if match else raw.strip()
    source = re.sub(r"^```(?:json)?\s*|\s*```$", "", source, flags=re.I)
    start = source.find("{")
    if start < 0:
        raise ValueError("Bloco APEX_TABLE sem objeto JSON")
    depth = 0
    in_string = False
    escaped = False
    end = None
    for i in range(start, len(source)):
        ch = source[i]
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                end = i + 1
                break
    if end is None:
        raise ValueError("JSON APEX_TABLE incompleto")
    parsed = json.loads(source[start:end])
    if not isinstance(parsed, dict):
        raise ValueError("APEX_TABLE deve ser um objeto JSON")
    return parsed
