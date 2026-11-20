from __future__ import annotations

import csv
import io
import zipfile
from datetime import date
from typing import Any

import requests

from .market import Candle
from .utils import from_ms


class BinanceVision:
    """Downloader for Binance public UM Futures daily kline archives.

    Use this for historical backfills/research. The live worker uses REST klines
    because Vision archives are published after the trading day closes.
    """

    BASE = "https://data.binance.vision/data/futures/um/daily/klines"

    def __init__(self, timeout: int = 45):
        self.timeout = timeout

    def daily_klines(self, symbol: str, interval: str, day: date) -> list[Candle]:
        filename = f"{symbol}-{interval}-{day.isoformat()}.zip"
        url = f"{self.BASE}/{symbol}/{interval}/{filename}"
        response = requests.get(url, timeout=self.timeout)
        if response.status_code == 404:
            return []
        response.raise_for_status()
        with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
            names = [name for name in archive.namelist() if name.lower().endswith(".csv")]
            if not names:
                raise ValueError("Arquivo Vision não contém CSV")
            with archive.open(names[0]) as raw:
                text = io.TextIOWrapper(raw, encoding="utf-8")
                rows = list(csv.reader(text))
        candles: list[Candle] = []
        for row in rows:
            if not row or not row[0].strip().isdigit():
                continue
            # Futures daily kline columns follow Binance's 12-field kline format.
            candles.append(Candle(
                open_time=from_ms(int(row[0])), open=float(row[1]), high=float(row[2]),
                low=float(row[3]), close=float(row[4]), volume=float(row[5]),
                close_time=from_ms(int(row[6])), quote_volume=float(row[7]),
                trades=int(row[8]), taker_buy_volume=float(row[9]),
            ))
        return candles
