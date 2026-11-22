from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_canvas_uses_stable_authored_height_not_mutating_canvas_height():
    app = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")
    assert "canvas.dataset.logicalHeight" in app
    assert "canvas.getAttribute('height')" in app
    assert "canvas.clientHeight" not in app


def test_mobile_layout_prevents_horizontal_overflow_and_truncates_email():
    css = (ROOT / "frontend" / "style.css").read_text(encoding="utf-8")
    assert "overflow-x:hidden" in css
    assert "#session-state" in css
    assert "text-overflow:ellipsis" in css
    assert "calc(100vw - 20px)" in css


def test_tradingview_timeframes_are_embedded():
    html = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
    for interval in ("5", "15", "60", "240", "1D"):
        assert f'data-tv-interval="{interval}"' in html
    app = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")
    assert "BINANCE:BTCUSDT.P" in app


def test_ai_automatic_toggle_is_separate_from_auto_trade_toggle():
    html = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
    app = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")
    assert 'id="setting-ai-auto-analysis"' in html
    assert 'id="setting-auto-trading"' in html
    assert "ai_auto_analysis_enabled" in app


def test_single_beep_buttons_are_disabled_during_continuous_mode():
    app = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")
    assert "!unlocked || !!state?.continuous_wanted" in app


def test_single_beep_buttons_are_disabled_during_continuous_mode():
    app = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")
    assert "!unlocked || !!state?.continuous_wanted" in app


def test_service_worker_cache_was_bumped_for_this_release():
    worker = (ROOT / "frontend" / "sw.js").read_text(encoding="utf-8")
    assert "apexprime-pwa-v8" in worker
