from __future__ import annotations

import logging
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any

import requests

from .utils import from_ms, to_ms

log = logging.getLogger("apexprime.market")


@dataclass
class Candle:
    open_time: datetime
    close_time: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float
    quote_volume: float
    trades: int
    taker_buy_volume: float

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["open_time"] = self.open_time.isoformat()
        result["close_time"] = self.close_time.isoformat()
        return result


class BinanceFutures:
    """Public USDⓈ-M endpoints only. No private/account/order endpoints are used."""

    def __init__(self, base_url: str = "https://fapi.binance.com", timeout: int = 20):
        self.base = base_url.rstrip("/")
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "ApexPrime-Paper/0.2"})

    def _get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        last_error: Exception | None = None
        for attempt in range(3):
            try:
                resp = self.session.get(self.base + path, params=params, timeout=self.timeout)
                if resp.status_code in (418, 429):
                    raise RuntimeError(f"Binance rate limit HTTP {resp.status_code}")
                resp.raise_for_status()
                return resp.json()
            except Exception as exc:
                last_error = exc
                if attempt < 2:
                    time.sleep(1.2 * (attempt + 1))
        raise RuntimeError(f"Binance GET {path} falhou: {last_error}")

    @staticmethod
    def _parse_kline(row: list[Any]) -> Candle:
        return Candle(
            open_time=from_ms(int(row[0])), open=float(row[1]), high=float(row[2]),
            low=float(row[3]), close=float(row[4]), volume=float(row[5]),
            close_time=from_ms(int(row[6])), quote_volume=float(row[7]),
            trades=int(row[8]), taker_buy_volume=float(row[9]),
        )

    def klines(self, symbol: str, interval: str, limit: int = 100,
               start_time: datetime | None = None, end_time: datetime | None = None) -> list[Candle]:
        params: dict[str, Any] = {"symbol": symbol, "interval": interval, "limit": min(max(limit, 1), 1500)}
        if start_time:
            params["startTime"] = to_ms(start_time)
        if end_time:
            params["endTime"] = to_ms(end_time)
        rows = self._get("/fapi/v1/klines", params)
        return [self._parse_kline(row) for row in rows]

    def recent_closed_klines(self, symbol: str, interval: str, limit: int = 100) -> list[Candle]:
        candles = self.klines(symbol, interval, limit=limit)
        now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
        # A candle is closed only after closeTime, not merely after its open time.
        return [c for c in candles if int(c.close_time.timestamp() * 1000) < now_ms]

    def mark_price(self, symbol: str) -> dict[str, Any]:
        return self._get("/fapi/v1/premiumIndex", {"symbol": symbol})

    def exchange_filters(self, symbol: str) -> dict[str, float]:
        """Return public Binance USDⓈ-M quantity and notional filters for a symbol."""
        data = self._get("/fapi/v1/exchangeInfo")
        found = next((item for item in data.get("symbols", []) if item.get("symbol") == symbol), None)
        if not found:
            raise RuntimeError(f"Símbolo {symbol} não encontrado em exchangeInfo")
        filters = {item.get("filterType"): item for item in found.get("filters", [])}
        lot = filters.get("LOT_SIZE", {})
        market_lot = filters.get("MARKET_LOT_SIZE", {})
        notional_filter = filters.get("MIN_NOTIONAL", {}) or filters.get("NOTIONAL", {})
        min_qtys = [float(v) for v in (lot.get("minQty"), market_lot.get("minQty")) if v not in (None, "0", 0)]
        steps = [float(v) for v in (lot.get("stepSize"), market_lot.get("stepSize")) if v not in (None, "0", 0)]
        return {
            "min_qty": max(min_qtys, default=0.0),
            "step_size": max(steps, default=0.0),
            "min_notional": float(notional_filter.get("notional") or notional_filter.get("minNotional") or 0),
        }

    def historical_closed_klines(self, symbol: str, interval: str, reference_time: datetime,
                                 limit: int = 200) -> list[Candle]:
        """Return candles closed at or before a selected historical UTC timestamp."""
        rows = self.klines(symbol, interval, limit=limit, end_time=reference_time)
        ref = reference_time.astimezone(timezone.utc)
        return [c for c in rows if c.close_time <= ref]

    def funding_history(self, symbol: str, start_time: datetime, end_time: datetime,
                        limit: int = 1000) -> list[dict[str, Any]]:
        return self._get("/fapi/v1/fundingRate", {
            "symbol": symbol, "startTime": to_ms(start_time),
            "endTime": to_ms(end_time), "limit": min(limit, 1000),
        })

    def one_minute_since(self, symbol: str, start_time: datetime,
                         max_pages: int = 8) -> list[Candle]:
        """Fetches 1m closed candles since timestamp, with bounded pagination."""
        all_rows: list[Candle] = []
        cursor_ms = to_ms(start_time)
        now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
        for _ in range(max_pages):
            rows = self._get("/fapi/v1/klines", {
                "symbol": symbol, "interval": "1m", "startTime": cursor_ms,
                "endTime": now_ms, "limit": 1000,
            })
            if not rows:
                break
            page = [self._parse_kline(r) for r in rows]
            all_rows.extend(c for c in page if int(c.close_time.timestamp() * 1000) < now_ms)
            next_cursor = int(rows[-1][6]) + 1
            if next_cursor <= cursor_ms or len(rows) < 1000:
                break
            cursor_ms = next_cursor
            time.sleep(0.15)
        return all_rows

    def health(self) -> dict[str, Any]:
        """Probe the same public Futures endpoints used by the trading engine.

        Testing only /time can pass even when market-data routes are region-blocked;
        this probe includes closed klines and mark price so the dashboard exposes that.
        """
        start = time.monotonic()
        server = self._get("/fapi/v1/time")
        candles = self.recent_closed_klines("BTCUSDT", "1h", 3)
        mark = self.mark_price("BTCUSDT")
        if not candles:
            raise RuntimeError("Binance não retornou candles Futures 1H fechados")
        elapsed = int((time.monotonic() - start) * 1000)
        return {
            "server_time": server.get("serverTime"),
            "closed_1h_candles": len(candles),
            "mark_price": mark.get("markPrice"),
            "latency_ms": elapsed,
        }
