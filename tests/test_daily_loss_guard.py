from types import SimpleNamespace

from apexprime.engine import ApexEngine


class LedgerDB:
    def active_account(self):
        return {"id": "account-1", "initial_balance": 100.0}

    def select(self, table, filters, **kwargs):
        assert table == "balance_ledger"
        return [
            {"event_type": "MANUAL_ADJUSTMENT", "amount": 80.0},
            {"event_type": "TRADE_CLOSED", "amount": -1.25},
            {"event_type": "FUNDING", "amount": -0.15},
        ]


def test_daily_loss_guard_does_not_count_virtual_deposits_as_profit():
    engine = object.__new__(ApexEngine)
    engine.db = LedgerDB()
    hit, pnl, limit = engine._daily_loss_guard({"timezone": "America/Sao_Paulo", "max_daily_loss_pct": 6})
    assert pnl == -1.40
    assert limit == 6
    assert hit is False
