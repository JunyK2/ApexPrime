from __future__ import annotations

import math
from typing import Any

from .utils import safe_float


REQUIRED_ENUMS = {
    "signal": {"LONG", "SHORT", "NO_TRADE"},
    "entry_type": {"IMEDIATA", "PULLBACK", "CONFIRMACAO", "NENHUMA"},
    "direction": {"LONG", "SHORT", "NONE"},
    "confidence": {"BAIXA", "MEDIA", "ALTA"},
    "regime": {"TENDENCIA", "RANGE", "TRANSICAO"},
}


def validate_apex_table(data: dict[str, Any], *, minimum_tp1_rr: float = 1.2,
                         maximum_tp1_rr: float = 2.5) -> dict[str, Any]:
    """Validate and normalize the model's APEX_TABLE before it can touch paper balance."""
    result = dict(data)
    for key, allowed in REQUIRED_ENUMS.items():
        value = str(result.get(key, "")).upper()
        if value not in allowed:
            raise ValueError(f"APEX_TABLE inválido: {key}={value!r}")
        result[key] = value

    for key in ("entry", "stop_loss", "tp1", "tp2", "risk_reward_tp1", "score"):
        value = safe_float(result.get(key))
        if value is None or not math.isfinite(value):
            raise ValueError(f"APEX_TABLE: campo numérico {key} inválido")
        result[key] = value

    result["strategy_name"] = str(result.get("strategy_name", "ApexPrime"))[:80]
    result["analysis_summary"] = str(result.get("analysis_summary", ""))[:500]

    # Model routers sometimes return scores slightly outside the requested range.
    # Normalize rather than discarding an otherwise valid signal; all prompts specify 0-10.
    result["score"] = min(10.0, max(0.0, result["score"]))
    if result["signal"] == "NO_TRADE":
        if result["direction"] != "NONE":
            raise ValueError("NO_TRADE precisa usar direction=NONE")
        return result

    if result["signal"] != result["direction"]:
        raise ValueError("signal e direction precisam apontar para o mesmo lado")
    if result["entry_type"] == "NENHUMA":
        raise ValueError("Trade com entry_type=NENHUMA não é executável")
    if min(result["entry"], result["stop_loss"], result["tp1"], result["tp2"]) <= 0:
        raise ValueError("Níveis de preço precisam ser positivos")
    entry, stop, tp1, tp2 = (result[k] for k in ("entry", "stop_loss", "tp1", "tp2"))
    if result["direction"] == "LONG":
        if not stop < entry < tp1 < tp2:
            raise ValueError("Níveis LONG precisam obedecer stop < entry < TP1 < TP2")
        actual_rr = (tp1 - entry) / (entry - stop)
    else:
        if not stop > entry > tp1 > tp2:
            raise ValueError("Níveis SHORT precisam obedecer stop > entry > TP1 > TP2")
        actual_rr = (entry - tp1) / (stop - entry)
    result["calculated_rr_tp1"] = actual_rr
    # Keep the visible APEX_TABLE R:R aligned with the actual entry/stop/TP1 geometry.
    result["risk_reward_tp1"] = actual_rr
    # The experimental nearest-structure profile allows a closer TP1, but not an
    # arbitrarily tiny target. Standard profile preserves the original 1.2R minimum.
    minimum_tp1_rr = max(0.25, min(float(minimum_tp1_rr), 2.5))
    maximum_tp1_rr = max(minimum_tp1_rr, min(float(maximum_tp1_rr), 4.0))
    if actual_rr < minimum_tp1_rr or actual_rr > maximum_tp1_rr:
        raise ValueError(
            f"R:R calculado de TP1 ({actual_rr:.2f}) fora do intervalo aceitável "
            f"{minimum_tp1_rr:.2f}–{maximum_tp1_rr:.2f}"
        )
    return result


def size_position(*, balance: float, available_margin: float, entry: float, stop: float,
                  risk_pct: float, leverage: int, taker_fee: float,
                  entry_fee_rate: float | None = None) -> dict[str, float]:
    """Size by stop loss including entry commission and taker stop commission."""
    if min(balance, available_margin, entry, stop) <= 0:
        raise ValueError("Saldo, margem, entrada e stop devem ser positivos")
    distance = abs(entry - stop)
    if distance <= 0:
        raise ValueError("Distância entre entrada e stop inválida")
    budget = balance * (risk_pct / 100.0)
    actual_entry_fee_rate = taker_fee if entry_fee_rate is None else entry_fee_rate
    cost_per_btc = distance + entry * actual_entry_fee_rate + stop * taker_fee
    qty_by_risk = budget / cost_per_btc
    qty_by_margin = available_margin * leverage / entry
    quantity = min(qty_by_risk, qty_by_margin)
    quantity = math.floor(quantity * 1_000_000_000_000) / 1_000_000_000_000
    if quantity <= 0:
        raise ValueError("Tamanho calculado é zero")
    notional = quantity * entry
    margin_used = notional / leverage
    entry_fee = notional * actual_entry_fee_rate
    stop_fee = quantity * stop * taker_fee
    effective_risk = quantity * distance + entry_fee + stop_fee
    return {
        "quantity": quantity,
        "notional": notional,
        "margin_used": margin_used,
        "entry_fee": entry_fee,
        "risk_amount": effective_risk,
        "risk_pct": effective_risk / balance * 100.0,
        "risk_budget": budget,
        "qty_by_risk": qty_by_risk,
        "qty_by_margin": qty_by_margin,
    }
