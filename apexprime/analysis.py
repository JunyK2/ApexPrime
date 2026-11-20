from __future__ import annotations

import base64
import logging
import time
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import requests

from .market import BinanceFutures, Candle
from .strategy import indicators
from .utils import local_time_label

log = logging.getLogger("apexprime.analysis")
PROMPT_DIR = Path(__file__).resolve().parent.parent / "prompts"
TIMEFRAMES = [("1D", "1d"), ("4H", "4h"), ("1H", "1h"), ("15M", "15m"), ("5M", "5m")]
CHART_INTERVALS = {"1D": "1D", "4H": "4h", "1H": "1h", "15M": "15m", "5M": "5m"}


def load_prompt(custom: str | None, filename: str) -> str:
    if custom and custom.strip():
        return custom.strip()
    path = PROMPT_DIR / filename
    return path.read_text(encoding="utf-8")


def _fmt(value: float | None, digits: int = 2) -> str:
    return "N/D" if value is None else f"{value:.{digits}f}"


def candles_to_text(datasets: dict[str, list[Candle]], *, symbol: str,
                    timezone_name: str = "America/Sao_Paulo", rows_per_tf: int = 30,
                    reference_time: datetime | None = None) -> str:
    """Render OHLCV and derived RSI/MACD tables, oldest first."""
    try:
        tz = ZoneInfo(timezone_name)
    except Exception:
        tz = ZoneInfo("America/Sao_Paulo")
    now = reference_time or datetime.now(tz)
    sections = [
        f"APEXPRIME — DADOS TABULARES {symbol}",
        f"Data de referência: {now.astimezone(tz).strftime('%d/%m/%Y %H:%M:%S %Z')}",
        "Todos os candles abaixo estão FECHADOS e ordenados do mais antigo para o mais recente.",
    ]
    for label, _interval in TIMEFRAMES:
        candles = datasets.get(label, [])[-rows_per_tf:]
        if not candles:
            sections.append(f"\n=== {symbol} | {label} | SEM DADOS ===")
            continue
        ind = indicators(datasets[label])
        sections.append(
            f"\n=== {symbol} | {label} | Últimos {len(candles)} candles ===\n"
            f"Preço de referência: {candles[-1].close:.2f} | "
            f"Variação da amostra: {(candles[-1].close / candles[0].open - 1) * 100:.2f}% | "
            f"Máx: {max(c.high for c in candles):.2f} | Mín: {min(c.low for c in candles):.2f} | "
            f"RSI(14): {_fmt(ind['rsi_14'])} | MACD: {_fmt(ind['macd'])} | "
            f"Sinal MACD: {_fmt(ind['macd_signal'])}"
        )
        sections.append("| # | Data/Hora | Open | High | Low | Close | Volume | RSI(14) |")
        sections.append("|---:|---|---:|---:|---:|---:|---:|---:|")
        full_rsi = indicators(datasets[label])  # for snapshot; row RSI computed separately below
        closes = [c.close for c in datasets[label]]
        from .strategy import rsi
        rsi_values = rsi(closes)
        start_idx = len(datasets[label]) - len(candles)
        for index, candle in enumerate(candles):
            rsi_value = rsi_values[start_idx + index]
            sections.append(
                f"| {index + 1} | {local_time_label(candle.open_time, timezone_name)} | "
                f"{candle.open:.2f} | {candle.high:.2f} | {candle.low:.2f} | "
                f"{candle.close:.2f} | {candle.volume:.3f} | {_fmt(rsi_value)} |"
            )
    sections.append("\nNota: não há delta/order flow real neste snapshot; não inferir dados ausentes.")
    return "\n".join(sections)


class ChartImgClient:
    def __init__(self, api_key: str, base_url: str = "https://api.chart-img.com"):
        self.api_key = api_key
        self.base = base_url.rstrip("/")
        self.session = requests.Session()

    def get_chart(self, interval: str, symbol: str = "BINANCE:BTCUSDT",
                  timezone_name: str = "America/Sao_Paulo") -> tuple[bytes, str]:
        response = self.session.post(
            self.base + "/v2/tradingview/advanced-chart",
            headers={"x-api-key": self.api_key, "Content-Type": "application/json"},
            json={
                "symbol": symbol,
                "interval": interval,
                "theme": "dark",
                "style": "candle",
                "timezone": timezone_name,
                "width": 1400,
                "height": 850,
                "format": "png",
                "studies": [
                    {"name": "Volume", "forceOverlay": False},
                    {"name": "Relative Strength Index"},
                    {"name": "MACD"},
                ],
            },
            timeout=75,
        )
        if not response.ok:
            raise RuntimeError(f"Chart IMG HTTP {response.status_code}: {response.text[:700]}")
        mime = response.headers.get("Content-Type", "image/png").split(";")[0]
        if not mime.startswith("image/"):
            raise RuntimeError(f"Chart IMG retornou conteúdo inesperado: {mime}")
        if len(response.content) < 1000:
            raise RuntimeError("Chart IMG retornou uma imagem vazia/pequena demais")
        return response.content, mime

    def get_five_charts(self, timezone_name: str, symbol: str = "BINANCE:BTCUSDT.P") -> list[dict[str, Any]]:
        images: list[dict[str, Any]] = []
        for label, _market_interval in TIMEFRAMES:
            data, mime = self.get_chart(CHART_INTERVALS[label], symbol=symbol,
                                        timezone_name=timezone_name)
            images.append({"timeframe": label, "data": data, "mime_type": mime})
        return images


class GeminiClient:
    def __init__(self, api_key: str, model: str,
                 base_url: str = "https://generativelanguage.googleapis.com/v1beta"):
        self.api_key = api_key
        self.model = model
        self.base = base_url.rstrip("/")
        self.session = requests.Session()

    def analyze(self, prompt: str, *, text_data: str | None = None,
                images: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        parts: list[dict[str, Any]] = [{"text": prompt}]
        if text_data:
            parts.append({"text": "\n\nDADOS TABULARES DOS CANDLES:\n" + text_data})
        for image in images or []:
            parts.append({"text": f"\nPRINT DO GRÁFICO — TIMEFRAME {image['timeframe']}"})
            parts.append({
                # Gemini GenerateContent REST uses the protobuf JSON names
                # (camelCase), not the snake_case names used by some SDKs.
                "inlineData": {
                    "mimeType": image["mime_type"],
                    "data": base64.b64encode(image["data"]).decode("ascii"),
                }
            })
        url = f"{self.base}/models/{self.model}:generateContent"
        started = time.monotonic()
        response = self.session.post(
            url,
            headers={"x-goog-api-key": self.api_key, "Content-Type": "application/json"},
            json={
                "contents": [{"role": "user", "parts": parts}],
                "generationConfig": {"temperature": 0.2, "topP": 0.9, "maxOutputTokens": 12000},
            },
            timeout=150,
        )
        latency = int((time.monotonic() - started) * 1000)
        if not response.ok:
            raise RuntimeError(f"Gemini HTTP {response.status_code}: {response.text[:1000]}")
        payload = response.json()
        texts: list[str] = []
        for candidate in payload.get("candidates", []):
            for part in candidate.get("content", {}).get("parts", []):
                if part.get("text"):
                    texts.append(part["text"])
        output = "\n".join(texts).strip()
        if not output:
            raise RuntimeError("Gemini respondeu sem texto utilizável")
        usage = payload.get("usageMetadata", {})
        return {
            "text": output,
            "latency_ms": latency,
            "input_tokens": usage.get("promptTokenCount"),
            "output_tokens": usage.get("candidatesTokenCount"),
            "total_tokens": usage.get("totalTokenCount"),
            "raw": payload,
        }


class GroqHealthClient:
    def __init__(self, api_key: str, model: str,
                 base_url: str = "https://api.groq.com/openai/v1"):
        self.api_key = api_key
        self.model = model
        self.base = base_url.rstrip("/")

    def check(self, snapshot: dict[str, Any]) -> dict[str, Any]:
        started = time.monotonic()
        response = requests.post(
            self.base + "/chat/completions",
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
            json={
                "model": self.model,
                "temperature": 0.1,
                "max_tokens": 500,
                "messages": [
                    {"role": "system", "content": (
                        "Você é o monitor de saúde operacional do ApexPrime e do servidor Android. "
                        "Avalie conectividade com a Binance, Supabase, Gemini, fila e trades virtuais, "
                        "além da bateria, temperatura da bateria, estado de carga, Wi-Fi, RSSI em dBm, "
                        "uptime e heartbeat do Redmi 6A. Indique se a bateria está abaixo do limite de 40%, "
                        "se o sinal Wi-Fi está fraco (RSSI abaixo de -75 dBm) e se o dispositivo parece offline. "
                        "Não recomende trades e não invente medições ausentes. Responda em JSON: "
                        "{\"healthy\":true|false,\"severity\":\"INFO|WARN|CRITICAL\","
                        "\"issues\":[...],\"summary\":\"...\",\"device_summary\":\"...\"}."
                    )},
                    {"role": "user", "content": str(snapshot)[:12000]},
                ],
            },
            timeout=50,
        )
        latency = int((time.monotonic() - started) * 1000)
        if not response.ok:
            raise RuntimeError(f"Groq HTTP {response.status_code}: {response.text[:700]}")
        content = response.json()["choices"][0]["message"]["content"]
        return {"text": content, "latency_ms": latency}
