import unittest
from datetime import datetime, timedelta, timezone

from apexprime.market import Candle
from apexprime.strategy import detect_latest_trigger


class StrategyTests(unittest.TestCase):
    def make_candles(self, count=25):
        base = datetime(2026, 11, 1, tzinfo=timezone.utc)
        candles = []
        for i in range(count):
            candles.append(Candle(
                open_time=base + timedelta(hours=i),
                close_time=base + timedelta(hours=i, minutes=59, seconds=59),
                open=100.0, high=101.0, low=99.0, close=100.1,
                volume=100.0, quote_volume=10000.0, trades=10,
                taker_buy_volume=50.0,
            ))
        return candles

    def test_returns_none_when_insufficient_history(self):
        signal = detect_latest_trigger(self.make_candles(10))
        self.assertEqual(signal.direction, "NONE")

    def test_detects_volume_and_bull_sweep_like_pine(self):
        candles = self.make_candles(25)
        last = candles[-1]
        last.open = 98.1
        last.high = 100.3
        last.low = 98.0
        last.close = 100.0
        last.volume = 500.0
        signal = detect_latest_trigger(candles)
        self.assertEqual(signal.direction, "LONG")
        self.assertTrue(signal.volume_explosion)
        self.assertTrue(signal.bull_sweep)
        self.assertGreaterEqual(signal.bullish_score, 2)


if __name__ == "__main__":
    unittest.main()
