from types import SimpleNamespace
from datetime import datetime, timezone

from apexprime.engine import ApexEngine


class FakeDB:
    def __init__(self):
        self.updates = []
        self.upserts = []
        self.logs = []

    def update(self, table, filters, values):
        self.updates.append((table, filters, values))
        return []

    def upsert(self, table, values, on_conflict=None):
        self.upserts.append((table, values, on_conflict))
        return []

    def log(self, *args, **kwargs):
        self.logs.append((args, kwargs))


class FakeTelegram:
    def __init__(self):
        self.messages = []

    def send_long(self, message):
        self.messages.append(message)


def test_trade_close_sends_original_analysis_and_chart_even_without_groq(monkeypatch):
    import apexprime.engine as engine_module

    db = FakeDB()
    telegram = FakeTelegram()
    engine = object.__new__(ApexEngine)
    engine.db = db
    engine.telegram = telegram
    engine.config = SimpleNamespace(
        groq_api_key="", openrouter_api_key="", supabase_service_role_key=""
    )
    engine._fetch_datasets_range = lambda *_args, **_kwargs: {"1H": []}
    monkeypatch.setattr(engine_module, "candles_to_text", lambda *a, **k: "CANDLES ENTRE ENTRADA E SAIDA")

    trade = {
        "id": "trade-123", "opened_at": datetime.now(timezone.utc).isoformat(),
        "closed_at": datetime.now(timezone.utc).isoformat(), "symbol": "BTCUSDT",
        "direction": "LONG", "entry_price": 90000, "exit_price": 91000,
        "realized_pnl_net": 0.5, "result_category": "PARTIAL_WIN", "close_reason": "MANUAL",
        "analysis_provider": "EXTERNAL", "analysis_model": "OpenRouter: modelo X",
        "analysis_mode": "text", "analysis_source": "manual_external",
        "analysis_raw_response": "RESPOSTA ORIGINAL APEX_TABLE",
    }

    engine._on_trade_closed(trade)

    assert len(telegram.messages) == 3
    assert "WIN PARCIAL" in telegram.messages[0]
    assert "RESPOSTA ORIGINAL APEX_TABLE" in telegram.messages[1]
    assert "CANDLES ENTRE ENTRADA E SAIDA" in telegram.messages[2]
    review_update = [row for row in db.updates if row[0] == "trade_reviews"][-1]
    assert review_update[2]["review_status"] == "ERROR"
    assert review_update[2]["exit_text_snapshot"].startswith("CANDLES ENTRE ENTRADA E SAIDA")
