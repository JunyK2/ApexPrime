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


    def open_interest(self, symbol: str) -> dict[str, Any]:
        return self._get("/fapi/v1/openInterest", {"symbol": symbol})

    def open_interest_history(self, symbol: str, period: str = "1h",
                              start_time: datetime | None = None,
                              end_time: datetime | None = None,
                              limit: int = 2) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"symbol": symbol, "period": period,
                                  "limit": min(max(int(limit), 1), 500)}
        if start_time:
            params["startTime"] = to_ms(start_time)
        if end_time:
            params["endTime"] = to_ms(end_time)
        return self._get("/futures/data/openInterestHist", params)

    def global_long_short_ratio(self, symbol: str, period: str = "1h",
                                start_time: datetime | None = None,
                                end_time: datetime | None = None,
                                limit: int = 2) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"symbol": symbol, "period": period,
                                  "limit": min(max(int(limit), 1), 500)}
        if start_time:
            params["startTime"] = to_ms(start_time)
        if end_time:
            params["endTime"] = to_ms(end_time)
        return self._get("/futures/data/globalLongShortAccountRatio", params)

    def advanced_market_context(self, symbol: str, candles_1h: list[Candle],
                                reference_time: datetime | None = None) -> dict[str, Any]:
        """Best-effort OI/funding/LSR/ATR/ICT context; missing endpoints never fail chart export."""
        from statistics import mean
        from zoneinfo import ZoneInfo
        from datetime import timedelta

        now = reference_time or datetime.now(timezone.utc)
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)
        now = now.astimezone(timezone.utc)
        context: dict[str, Any] = {
            "reference_time_utc": now.isoformat(), "open_interest": None,
            "open_interest_change_pct": None, "funding_rate": None,
            "long_short_ratio": None, "long_account_pct": None, "short_account_pct": None,
            "atr_14": None, "atr_pct": None, "atr_compression_ratio": None,
            "volatility_state": "N/D", "premium_discount": "N/D",
            "range_high": None, "range_low": None, "range_midpoint": None,
            "ict_killzone": "N/D", "data_notes": [],
        }
        # ATR(14), Wilder smoothing is not needed for a descriptive prompt; simple mean TR.
        if len(candles_1h) >= 15:
            trs = []
            for idx in range(1, len(candles_1h)):
                c = candles_1h[idx]
                prev = candles_1h[idx - 1].close
                trs.append(max(c.high - c.low, abs(c.high - prev), abs(c.low - prev)))
            atr14 = mean(trs[-14:])
            context["atr_14"] = atr14
            context["atr_pct"] = (atr14 / candles_1h[-1].close * 100) if candles_1h[-1].close else None
            if len(trs) >= 50:
                atr_base = mean(trs[-50:])
                ratio = atr14 / atr_base if atr_base else None
                context["atr_compression_ratio"] = ratio
                context["volatility_state"] = "COMPRESSAO" if ratio is not None and ratio < 0.75 else "EXPANSAO" if ratio and ratio > 1.25 else "NORMAL"
            else:
                context["volatility_state"] = "ATR calculado; histórico curto para compressão"
        else:
            context["data_notes"].append("Poucos candles 1H para ATR(14).")

        recent = candles_1h[-20:]
        if recent:
            hi = max(c.high for c in recent); lo = min(c.low for c in recent)
            mid = (hi + lo) / 2
            price = recent[-1].close
            context.update({"range_high": hi, "range_low": lo, "range_midpoint": mid,
                            "premium_discount": "PREMIUM" if price > mid else "DISCOUNT" if price < mid else "EQUILIBRIO"})

        # ICT reference windows in New York local time (DST-aware): Asia 19-23,
        # London 02-05, New York AM 08:30-11:00, New York PM 13:30-16:00.
        try:
            ny = now.astimezone(ZoneInfo("America/New_York"))
            minute = ny.hour * 60 + ny.minute
            if 19 * 60 <= minute < 23 * 60:
                killzone = "ASIA"
            elif 2 * 60 <= minute < 5 * 60:
                killzone = "LONDON"
            elif 8 * 60 + 30 <= minute < 11 * 60:
                killzone = "NEW_YORK_AM"
            elif 13 * 60 + 30 <= minute < 16 * 60:
                killzone = "NEW_YORK_PM"
            else:
                killzone = "FORA_DAS_KILLZONES"
            context["ict_killzone"] = f"{killzone} ({ny.strftime('%H:%M')} New York)"
        except Exception:
            context["ict_killzone"] = "N/D (timezone indisponível)"

        # Historical endpoints are best-effort. For old requested snapshots the API may
        # not retain the requested date; then the exact field stays N/D rather than using now.
        try:
            if abs((datetime.now(timezone.utc) - now).total_seconds()) <= 900:
                oi = self.open_interest(symbol)
                context["open_interest"] = float(oi.get("openInterest"))
            oi_hist = self.open_interest_history(symbol, "1h", now - timedelta(hours=2), now, 2)
            if len(oi_hist) >= 2:
                old = float(oi_hist[0].get("sumOpenInterest", 0) or 0)
                new = float(oi_hist[-1].get("sumOpenInterest", 0) or 0)
                if old:
                    context["open_interest_change_pct"] = (new / old - 1) * 100
                if context["open_interest"] is None:
                    context["open_interest"] = new
            elif context["open_interest"] is None:
                context["data_notes"].append("Open Interest histórico indisponível para o horário de referência.")
        except Exception as exc:
            context["data_notes"].append(f"Open Interest indisponível ({type(exc).__name__}).")

        try:
            lsr = self.global_long_short_ratio(symbol, "1h", now - timedelta(hours=2), now, 2)
            if lsr:
                latest = lsr[-1]
                context["long_short_ratio"] = float(latest.get("longShortRatio"))
                context["long_account_pct"] = float(latest.get("longAccount")) * 100
                context["short_account_pct"] = float(latest.get("shortAccount")) * 100
        except Exception as exc:
            context["data_notes"].append(f"Long/Short Ratio indisponível ({type(exc).__name__}).")

        try:
            funding = self._get("/fapi/v1/fundingRate", {
                "symbol": symbol, "startTime": to_ms(now - timedelta(hours=16)),
                "endTime": to_ms(now), "limit": 3,
            })
            if funding:
                context["funding_rate"] = float(funding[-1].get("fundingRate"))
        except Exception as exc:
            context["data_notes"].append(f"Funding Rate indisponível ({type(exc).__name__}).")
        return context

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
