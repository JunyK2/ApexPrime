from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .market import Candle


@dataclass
class TriggerSignal:
    direction: str  # LONG, SHORT, NONE
    score: int
    bullish_score: int
    bearish_score: int
    volume_explosion: bool
    bull_sweep: bool
    bear_sweep: bool
    bull_displacement: bool
    bear_displacement: bool
    candle: Candle | None
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "direction": self.direction,
            "score": self.score,
            "bullish_score": self.bullish_score,
            "bearish_score": self.bearish_score,
            "volume_explosion": self.volume_explosion,
            "bull_sweep": self.bull_sweep,
            "bear_sweep": self.bear_sweep,
            "bull_displacement": self.bull_displacement,
            "bear_displacement": self.bear_displacement,
            "candle_open_time": self.candle.open_time.isoformat() if self.candle else None,
            "reason": self.reason,
        }


def sma(values: list[float], end_idx: int, length: int) -> float | None:
    start = end_idx - length + 1
    if start < 0:
        return None
    return sum(values[start:end_idx + 1]) / length


def detect_latest_trigger(candles: list[Candle], *, vol_mult: float = 1.5,
                          sweep_len: int = 16, disp_mult: float = 1.5,
                          disp_len: int = 10, cooldown: int = 3) -> TriggerSignal:
    """Port of the user's Pine v6 detector; all calculations use closed candles.

    As in Pine, SMA(volume, 20) and SMA(abs(body), disp_len) include the current
    candle. The liquidity window uses only the preceding `sweep_len` candles.
    Cooldown is independent for bullish and bearish signals and requires a
    distance strictly greater than the configured cooldown.
    """
    if not candles:
        return TriggerSignal("NONE", 0, 0, 0, False, False, False, False, False, None,
                             "Nenhum candle fechado disponível")

    volumes = [c.volume for c in candles]
    bodies = [abs(c.close - c.open) for c in candles]
    last_bull_bar = -10**9
    last_bear_bar = -10**9
    emitted: dict[int, TriggerSignal] = {}

    for i, candle in enumerate(candles):
        vol_avg = sma(volumes, i, 20)
        body_avg = sma(bodies, i, disp_len)
        if vol_avg is None or body_avg is None or i < max(sweep_len, 2):
            continue

        prev = candles[i - sweep_len:i]
        lowest_prev = min(c.low for c in prev)
        highest_prev = max(c.high for c in prev)

        volume_explosion = candle.volume >= vol_mult * vol_avg
        bull_sweep = candle.low < lowest_prev and candle.close > lowest_prev
        bear_sweep = candle.high > highest_prev and candle.close < highest_prev
        is_disp_body = bodies[i] >= disp_mult * body_avg
        bull_fvg = candle.low > candles[i - 2].high
        bear_fvg = candle.high < candles[i - 2].low
        bull_disp = is_disp_body and bull_fvg
        bear_disp = is_disp_body and bear_fvg

        bull_score = int(volume_explosion) + int(bull_sweep) + int(bull_disp)
        bear_score = int(volume_explosion) + int(bear_sweep) + int(bear_disp)
        bull_trigger = bull_score >= 2
        bear_trigger = bear_score >= 2
        bull_signal = bull_trigger and (i - last_bull_bar > cooldown)
        bear_signal = bear_trigger and (i - last_bear_bar > cooldown)

        direction = "NONE"
        reason = "Sem gatilho (score inferior a 2)"
        if bull_signal and bear_signal:
            direction = "NONE"
            reason = "Gatilhos LONG e SHORT simultâneos; conflito conservador"
            # The Pine source updates both cooldown counters when both are true.
            last_bull_bar = i
            last_bear_bar = i
        elif bull_signal:
            direction = "LONG"
            reason = "Gatilho bullish confirmado pelo detector Pine"
            last_bull_bar = i
        elif bear_signal:
            direction = "SHORT"
            reason = "Gatilho bearish confirmado pelo detector Pine"
            last_bear_bar = i
        elif bull_trigger or bear_trigger:
            reason = "Gatilho detectado, mas bloqueado pelo cooldown"

        emitted[i] = TriggerSignal(
            direction=direction,
            score=max(bull_score, bear_score),
            bullish_score=bull_score,
            bearish_score=bear_score,
            volume_explosion=volume_explosion,
            bull_sweep=bull_sweep,
            bear_sweep=bear_sweep,
            bull_displacement=bull_disp,
            bear_displacement=bear_disp,
            candle=candle,
            reason=reason,
        )

    last = emitted.get(len(candles) - 1)
    if last:
        return last
    return TriggerSignal("NONE", 0, 0, 0, False, False, False, False, False,
                         candles[-1], "Histórico insuficiente para calcular todos os pilares")


def rsi(values: list[float], period: int = 14) -> list[float | None]:
    out: list[float | None] = [None] * len(values)
    if len(values) <= period:
        return out
    gains = [0.0]
    losses = [0.0]
    for i in range(1, len(values)):
        delta = values[i] - values[i - 1]
        gains.append(max(delta, 0.0))
        losses.append(max(-delta, 0.0))
    avg_gain = sum(gains[1:period + 1]) / period
    avg_loss = sum(losses[1:period + 1]) / period
    out[period] = 100.0 if avg_loss == 0 else 100 - (100 / (1 + avg_gain / avg_loss))
    for i in range(period + 1, len(values)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
        out[i] = 100.0 if avg_loss == 0 else 100 - (100 / (1 + avg_gain / avg_loss))
    return out


def ema(values: list[float], period: int) -> list[float | None]:
    out: list[float | None] = [None] * len(values)
    if len(values) < period:
        return out
    seed = sum(values[:period]) / period
    out[period - 1] = seed
    alpha = 2 / (period + 1)
    prev = seed
    for i in range(period, len(values)):
        prev = values[i] * alpha + prev * (1 - alpha)
        out[i] = prev
    return out


def indicators(candles: list[Candle]) -> dict[str, float | None]:
    closes = [c.close for c in candles]
    rsis = rsi(closes)
    fast = ema(closes, 12)
    slow = ema(closes, 26)
    macd_line = [None if fast[i] is None or slow[i] is None else fast[i] - slow[i]
                 for i in range(len(closes))]
    valid_macd = [v for v in macd_line if v is not None]
    signal_line = ema(valid_macd, 9) if valid_macd else []
    return {
        "rsi_14": rsis[-1] if rsis else None,
        "macd": macd_line[-1] if macd_line else None,
        "macd_signal": signal_line[-1] if signal_line else None,
    }
