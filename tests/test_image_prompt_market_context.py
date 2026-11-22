from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_chart_img_prompt_appends_measured_derivatives_context_values():
    source = (ROOT / "apexprime" / "engine.py").read_text(encoding="utf-8")
    assert 'formatted_market_context = self._format_market_context(market_context)' in source
    assert 'image_prompt += (' in source
    assert 'CONTEXTO DERIVATIVO E DE SESSÃO — DADOS MEDIDOS' in source
    assert '+ formatted_market_context' in source


def test_continuous_signal_actions_show_site_confirmation():
    source = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")
    block = source.split('async function setContinuousSignal(enabled) {', 1)[1].split('\n}', 1)[0]
    assert 'notifyToast(message, \'success\')' in block
