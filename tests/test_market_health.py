from apexprime.market import BinanceFutures, Candle
from datetime import datetime, timezone


def test_binance_health_checks_time_klines_and_mark_price(monkeypatch):
    market = BinanceFutures()
    candle = Candle(
        open_time=datetime(2026, 11, 20, 10, tzinfo=timezone.utc),
        close_time=datetime(2026, 11, 20, 10, 59, 59, tzinfo=timezone.utc),
        open=90000, high=90500, low=89900, close=90300,
        volume=123, quote_volume=11000000, trades=1000, taker_buy_volume=60,
    )
    calls = []

    def fake_get(path, params=None):
        calls.append((path, params))
        if path == "/fapi/v1/time":
            return {"serverTime": 1}
        raise AssertionError("Only time is fetched via _get; methods are patched below")

    monkeypatch.setattr(market, "_get", fake_get)
    monkeypatch.setattr(market, "recent_closed_klines", lambda *a, **k: [candle])
    monkeypatch.setattr(market, "mark_price", lambda symbol: {"markPrice": "90301.2"})

    result = market.health()

    assert result["server_time"] == 1
    assert result["closed_1h_candles"] == 1
    assert result["mark_price"] == "90301.2"
    assert calls == [("/fapi/v1/time", None)]


def test_binance_health_fails_if_futures_klines_missing(monkeypatch):
    market = BinanceFutures()
    monkeypatch.setattr(market, "_get", lambda *a, **k: {"serverTime": 1})
    monkeypatch.setattr(market, "recent_closed_klines", lambda *a, **k: [])
    monkeypatch.setattr(market, "mark_price", lambda symbol: {"markPrice": "90000"})

    try:
        market.health()
    except RuntimeError as exc:
        assert "candles Futures" in str(exc)
    else:
        raise AssertionError("Health test should fail without closed futures candles")
