from types import SimpleNamespace

from apexprime.engine import ApexEngine


class MinimalDB:
    def __init__(self):
        self.updates = []
        self.logs = []
        self.inserted = []

    def settings(self):
        return {"ai_auto_analysis_enabled": False}

    def log(self, *args, **kwargs):
        self.logs.append((args, kwargs))

    def active_account(self):
        return {"balance": 100, "initial_balance": 100, "realized_pnl": 0,
                "total_fees": 0, "total_funding": 0}

    def select(self, table, *args, **kwargs):
        return []

    def insert(self, table, values):
        self.inserted.append((table, values))
        return [{"id": "report-1"}]

    def update(self, table, filters, values):
        self.updates.append((table, filters, values))
        return []


class FakeTelegram:
    def __init__(self):
        self.messages = []

    def send(self, message):
        self.messages.append(message)


def test_ai_off_blocks_forced_api_analysis_but_does_not_fail_queue(monkeypatch):
    engine = object.__new__(ApexEngine)
    engine.db = MinimalDB()
    engine.telegram = FakeTelegram()
    engine.config = SimpleNamespace()
    result = engine.run_manual_analysis()
    assert result["status"] == "skipped"
    assert result["reason"] == "AI_AUTOMATION_DISABLED"
    assert engine.telegram.messages
    assert "nenhum gráfico/texto foi enviado" in engine.telegram.messages[0]


def test_groq_operational_report_sends_small_digest_only(monkeypatch):
    import apexprime.engine as engine_module

    captured = {}

    class FakeGroq:
        def __init__(self, *_args):
            pass

        def analyze(self, prompt, max_tokens=10000):
            captured["prompt"] = prompt
            captured["max_tokens"] = max_tokens
            return {"text": "Resumo operacional curto"}

    monkeypatch.setattr(engine_module, "GroqAnalysisClient", FakeGroq)
    engine = object.__new__(ApexEngine)
    engine.config = SimpleNamespace(groq_api_key="gk", groq_api_base="https://example.test", 
                                    supabase_service_role_key="service-secret")
    engine.db = MinimalDB()
    engine._runtime_settings = lambda: {
        "analysis_mode": "text", "ai_auto_analysis_enabled": True,
        "ai_provider_strategy": "auto", "fixed_ai_provider": "gemini",
        "groq_health_interval_hours": 4, "risk_per_trade_pct": 2,
        "max_leverage": 20, "max_daily_loss_pct": 6, "groq_model": "openai/gpt-oss-120b",
    }

    result = engine.create_groq_report()
    assert result["report_text"] == "Resumo operacional curto"
    assert captured["max_tokens"] == 450
    assert len(captured["prompt"]) < 5000
    assert "candles" not in captured["prompt"].lower()
    assert "chart" not in captured["prompt"].lower()
    assert "service-secret" not in captured["prompt"]
