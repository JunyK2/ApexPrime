import unittest
from datetime import datetime, timedelta, timezone

from apexprime.execution import PaperExecutor
from apexprime.market import Candle


class PendingEntryTests(unittest.TestCase):
    def candle(self, *, open_, high, low, close):
        start = datetime(2026, 11, 20, 12, 0, tzinfo=timezone.utc)
        return Candle(start, start + timedelta(minutes=1) - timedelta(milliseconds=1),
                      open_, high, low, close, 100.0, 10000.0, 50, 40.0)

    def test_long_pullback_fills_at_limit_price(self):
        pending = {"direction": "LONG", "entry_type": "PULLBACK", "entry_price": 100}
        bar = self.candle(open_=102, high=103, low=99.5, close=101)
        self.assertEqual(PaperExecutor.pending_fill_price(pending, bar), 100)

    def test_long_pullback_gap_gets_price_improvement(self):
        pending = {"direction": "LONG", "entry_type": "PULLBACK", "entry_price": 100}
        bar = self.candle(open_=99.8, high=101, low=99.5, close=100.5)
        self.assertAlmostEqual(PaperExecutor.pending_fill_price(pending, bar), 99.8)

    def test_short_confirmation_requires_closed_cross(self):
        pending = {"direction": "SHORT", "entry_type": "CONFIRMACAO", "entry_price": 100}
        confirmed = self.candle(open_=101, high=102, low=98, close=99)
        no_confirmation = self.candle(open_=99, high=101, low=98, close=99.5)
        self.assertEqual(PaperExecutor.pending_fill_price(pending, confirmed), 99)
        self.assertIsNone(PaperExecutor.pending_fill_price(pending, no_confirmation))


if __name__ == "__main__":
    unittest.main()


class _CursorDb:
    def __init__(self, trade):
        self.trade = trade
        self.updated = []

    def active_account(self):
        return {"id": "acct", "balance": 20, "total_fees": 0, "total_funding": 0, "realized_pnl": 0}

    def select(self, table, filters=None, **kwargs):
        if table == "trades" and filters and filters.get("status") == "eq.OPEN":
            return [self.trade]
        if table == "trades" and filters and filters.get("id") == f"eq.{self.trade['id']}":
            return [self.trade]
        return []

    def update(self, table, filters, values):
        self.updated.append((table, values))
        self.trade.update(values)
        return [self.trade]

    def log(self, *args, **kwargs):
        return None


class _CursorMarket:
    def __init__(self):
        self.start_time = None

    def mark_price(self, _symbol):
        return {"markPrice": "62000"}

    def one_minute_since(self, _symbol, start_time):
        self.start_time = start_time
        return []


class MarketCursorTests(unittest.TestCase):
    def test_open_trade_monitor_uses_market_cursor_not_updated_at(self):
        from datetime import datetime, timedelta, timezone
        from apexprime.execution import PaperExecutor

        opened = datetime(2026, 11, 19, 10, 0, tzinfo=timezone.utc)
        market_cursor = datetime(2026, 11, 19, 11, 0, tzinfo=timezone.utc)
        trade = {
            "id": "trade-1", "symbol": "BTCUSDT", "status": "OPEN",
            "opened_at": opened.isoformat(), "last_market_candle_at": market_cursor.isoformat(),
            "updated_at": datetime(2026, 11, 20, 0, 0, tzinfo=timezone.utc).isoformat(),
            "direction": "LONG", "entry_price": 62000, "initial_stop_loss": 61000,
            "current_stop_loss": 61000, "tp1_price": 63500, "tp2_price": 65000,
            "initial_quantity": 0.001, "remaining_quantity": 0.001,
            "margin_used": 3.1, "tp1_fraction": 0.5, "tp1_hit": False,
            "break_even_moved": False, "entry_fee": 0.01, "exit_fees": 0,
            "funding_paid": 0, "realized_pnl_gross": 0, "realized_pnl_net": -0.01,
        }
        db = _CursorDb(trade)
        market = _CursorMarket()
        PaperExecutor(db, market).monitor_open_trades({"funding_enabled": False})
        self.assertEqual(market.start_time, market_cursor - timedelta(minutes=2))

