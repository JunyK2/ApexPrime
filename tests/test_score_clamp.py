from apexprime.risk import validate_apex_table


def _trade(score):
    return {
        "signal": "LONG", "entry_type": "IMEDIATA", "direction": "LONG",
        "entry": 100, "stop_loss": 98, "tp1": 103, "tp2": 106,
        "risk_reward_tp1": 1.5, "confidence": "ALTA", "score": score,
        "regime": "TENDENCIA", "strategy_name": "teste", "analysis_summary": "ok",
    }


def test_score_above_ten_is_clamped_before_openrouter_fallback_is_rejected():
    assert validate_apex_table(_trade(12))["score"] == 10


def test_negative_score_is_clamped_to_zero():
    assert validate_apex_table(_trade(-3))["score"] == 0


def test_reported_tp1_rr_is_replaced_with_actual_price_geometry():
    row = _trade(8)
    row["risk_reward_tp1"] = 99
    checked = validate_apex_table(row)
    assert checked["risk_reward_tp1"] == 1.5
    assert checked["calculated_rr_tp1"] == 1.5
