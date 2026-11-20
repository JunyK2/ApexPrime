from __future__ import annotations

from apexprime.execution import PaperExecutor


class FakeDB:
    def __init__(self):
        self.trade = {
            "id": "trade-1", "status": "OPEN", "symbol": "BTCUSDT",
            "direction": "LONG", "remaining_quantity": 0.01,
        }
        self.pending = {"id": "pending-1", "status": "PENDING", "direction": "SHORT",
                       "symbol": "BTCUSDT", "entry_type": "PULLBACK"}
        self.updates = []
        self.logs = []

    def select(self, table, filters=None, **kwargs):
        filters = filters or {}
        if table == "trades":
            if self.trade and filters.get("id") == "eq.trade-1" and filters.get("status") == "eq.OPEN":
                return [self.trade]
            return []
        if table == "trade_events":
            return []
        return []

    def active_account(self):
        return {"id": "account-1", "balance": 20}

    def update(self, table, filters, values):
        self.updates.append((table, filters, values))
        if table == "pending_entries" and self.pending and filters.get("id") == "eq.pending-1":
            if self.pending["status"] == "PENDING":
                self.pending.update(values)
                return [self.pending]
        return []

    def log(self, *args, **kwargs):
        self.logs.append((args, kwargs))


class FakeMarket:
    def mark_price(self, symbol):
        return {"markPrice": "62000"}


class FakeTelegram:
    def __init__(self):
        self.messages = []

    def __call__(self, message):
        self.messages.append(message)


def test_manual_close_targets_only_requested_trade(monkeypatch):
    db = FakeDB()
    telegram = FakeTelegram()
    executor = PaperExecutor(db, FakeMarket(), telegram)
    captured = {}

    def fake_close_all(trade, price, reason, settings, account, event_type):
        captured.update(trade=trade, price=price, reason=reason, event_type=event_type)

    monkeypatch.setattr(executor, "_close_all", fake_close_all)
    result = executor.close_trade_manual("trade-1", {"funding_enabled": False})

    assert result is True
    assert captured["price"] == 62000
    assert captured["reason"] == "MANUAL"
    assert captured["event_type"] == "MANUAL_EXIT"


def test_manual_close_returns_false_if_trade_not_open():
    db = FakeDB()
    executor = PaperExecutor(db, FakeMarket(), lambda _: None)
    assert executor.close_trade_manual("missing", {"funding_enabled": False}) is False


def test_cancel_one_pending_entry_updates_status_and_notifies():
    db = FakeDB()
    telegram = FakeTelegram()
    executor = PaperExecutor(db, FakeMarket(), telegram)

    result = executor.cancel_pending_entry_manual("pending-1")

    assert result is True
    assert db.pending["status"] == "CANCELLED"
    assert "CANCELADA" in telegram.messages[0]


def test_cancel_unknown_or_already_processed_entry_returns_false():
    db = FakeDB()
    db.pending["status"] = "FILLED"
    executor = PaperExecutor(db, FakeMarket(), lambda _: None)
    assert executor.cancel_pending_entry_manual("pending-1") is False


def test_daily_loss_guard_blocks_new_entries_after_limit():
    from apexprime.engine import ApexEngine

    class LedgerDB:
        def active_account(self):
            return {"id": "account-1", "initial_balance": 20.0}

        def select(self, table, filters=None, **kwargs):
            assert table == "balance_ledger"
            assert filters["account_id"] == "eq.account-1"
            return [
                {"event_type": "FEE", "amount": -0.10},
                {"event_type": "REALIZED_PNL", "amount": -0.95},
            ]

    engine = object.__new__(ApexEngine)
    engine.db = LedgerDB()
    hit, pnl, limit = engine._daily_loss_guard({"timezone": "America/Sao_Paulo", "max_daily_loss_pct": 5})

    assert hit is True
    assert pnl == -1.05
    assert limit == 1.0
