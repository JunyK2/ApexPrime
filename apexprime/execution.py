from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Callable
from zoneinfo import ZoneInfo

from .db import SupabaseREST
from .market import BinanceFutures, Candle
from .risk import size_position
from .utils import iso_utc, safe_float, utc_now

log = logging.getLogger("apexprime.execution")


class PaperExecutor:
    """Local paper-trading ledger. This class has no exchange order functionality."""

    def __init__(self, db: SupabaseREST, market: BinanceFutures,
                 notify: Callable[[str], Any] | None = None):
        self.db = db
        self.market = market
        self.notify = notify or (lambda _message: None)

    def _account(self) -> dict[str, Any]:
        return self.db.active_account()

    def _ledger(self, account_id: str, trade_id: str | None, event_type: str,
                amount: float, balance_after: float, description: str,
                metadata: dict[str, Any] | None = None) -> None:
        self.db.insert("balance_ledger", {
            "account_id": account_id,
            "trade_id": trade_id,
            "event_type": event_type,
            "amount": amount,
            "balance_after": balance_after,
            "description": description,
            "metadata": metadata or {},
        })

    def _event(self, trade_id: str, event_type: str, *, price: float | None = None,
               quantity: float | None = None, gross: float = 0.0, fee: float = 0.0,
               funding: float = 0.0, metadata: dict[str, Any] | None = None) -> None:
        self.db.insert("trade_events", {
            "trade_id": trade_id, "event_type": event_type, "price": price,
            "quantity": quantity, "realized_pnl_gross": gross, "fee": fee,
            "funding": funding, "metadata": metadata or {},
        })

    def open_trade(self, analysis: dict[str, Any], *, run_id: str,
                   settings: dict[str, Any], trigger_direction: str,
                   mark_price: float, pending_fill: bool = False,
                   opened_at: str | None = None,
                   entry_fee_type: str | None = None) -> dict[str, Any] | None:
        if analysis.get("signal") not in ("LONG", "SHORT"):
            return None
        if analysis["signal"] != trigger_direction:
            self.db.log("WARN", "execution", "Trade ignorado: direção da IA diverge do gatilho TradingView", run_id=run_id,
                        details={"ai_signal": analysis["signal"], "trigger_direction": trigger_direction})
            return None
        entry_type = analysis.get("entry_type")
        if pending_fill and entry_type not in {"PULLBACK", "CONFIRMACAO"}:
            self.db.log("WARN", "execution", "Preenchimento pendente com entry_type incompatível", run_id=run_id)
            return None
        if not pending_fill and entry_type != "IMEDIATA":
            self.db.log("INFO", "execution", "Entrada não imediata deve passar pelo monitor de setups pendentes", run_id=run_id)
            return None

        deviation = abs(mark_price - analysis["entry"]) / mark_price * 100.0
        allowed = float(settings.get("max_entry_deviation_pct", 0.25))
        if deviation > allowed:
            self.db.log("WARN", "execution", f"Trade ignorado: preço se afastou {deviation:.3f}% da entrada da IA", run_id=run_id,
                        details={"mark_price": mark_price, "ai_entry": analysis["entry"], "allowed_pct": allowed})
            return None
        direction = analysis["direction"]
        entry = mark_price
        # Keep the AI's structural distances, shifted to the actual simulated fill price.
        delta = entry - analysis["entry"]
        stop = analysis["stop_loss"] + delta
        tp1 = analysis["tp1"] + delta
        tp2 = analysis["tp2"] + delta
        if direction == "LONG" and not stop < entry < tp1 < tp2:
            self.db.log("WARN", "execution", "Níveis ficaram inválidos após ajuste para preço de mercado", run_id=run_id)
            return None
        if direction == "SHORT" and not stop > entry > tp1 > tp2:
            self.db.log("WARN", "execution", "Níveis ficaram inválidos após ajuste para preço de mercado", run_id=run_id)
            return None

        account = self._account()
        balance = float(account["balance"])
        if balance <= 0:
            self.db.log("ERROR", "execution", "Saldo virtual zerado/negativo; trade bloqueado", run_id=run_id)
            return None
        open_trades = self.db.select("trades", {
            "account_id": f"eq.{account['id']}", "status": "eq.OPEN",
        })
        pending_filters = {
            "account_id": f"eq.{account['id']}",
            "status": "in.(PENDING,PROCESSING)",
        }
        pending_entries = self.db.select("pending_entries", pending_filters)
        if pending_entries and not pending_fill:
            self.db.log("INFO", "execution", "Trade imediato bloqueado: já existe uma entrada pendente", run_id=run_id)
            return None
        max_open = int(settings.get("max_open_trades", 1))
        if len(open_trades) >= max_open:
            self.db.log("INFO", "execution", "Limite de operações simultâneas atingido", run_id=run_id)
            return None
        committed_margin = sum(float(t.get("margin_used", 0)) for t in open_trades)
        available_margin = max(0.0, balance - committed_margin)
        leverage = min(int(settings.get("max_leverage", 20)), 20)
        taker_fee = float(settings.get("taker_fee_rate", 0.0005))
        maker_fee = float(settings.get("maker_fee_rate", 0.0002))
        if entry_fee_type not in {"MAKER", "TAKER"}:
            # Pullback touches are modeled as resting limit fills. Gap-through fills
            # are marketable and therefore charged as taker; all other entry types
            # are market executions.
            if pending_fill and entry_type == "PULLBACK" and abs(mark_price - float(analysis["entry"])) < 1e-8:
                entry_fee_type = "MAKER"
            else:
                entry_fee_type = "TAKER"
        entry_fee_rate = maker_fee if entry_fee_type == "MAKER" else taker_fee
        risk_pct = min(float(settings.get("risk_per_trade_pct", 2.0)), 2.0)
        try:
            size = size_position(balance=balance, available_margin=available_margin,
                                 entry=entry, stop=stop, risk_pct=risk_pct,
                                 leverage=leverage, taker_fee=taker_fee,
                                 entry_fee_rate=entry_fee_rate)
        except ValueError as exc:
            self.db.log("WARN", "execution", f"Trade bloqueado pelo dimensionamento: {exc}", run_id=run_id)
            return None
        if size["risk_pct"] > 2.000001:
            self.db.log("ERROR", "execution", "Proteção: risco calculado ultrapassou 2%", run_id=run_id)
            return None

        new_balance = balance - size["entry_fee"]
        effective_opened_at = opened_at or iso_utc()
        trade_row = {
            "account_id": account["id"], "run_id": run_id,
            "symbol": settings.get("binance_symbol", "BTCUSDT"),
            "direction": direction, "entry_type": analysis["entry_type"],
            "status": "OPEN", "entry_price": entry,
            "initial_stop_loss": stop, "current_stop_loss": stop,
            "tp1_price": tp1, "tp2_price": tp2,
            "initial_quantity": size["quantity"], "remaining_quantity": size["quantity"],
            "leverage": leverage, "notional": size["notional"],
            "margin_used": size["margin_used"], "risk_amount": size["risk_amount"],
            "risk_pct": size["risk_pct"], "tp1_fraction": 0.5,
            "confidence": analysis.get("confidence"), "score": analysis.get("score"),
            "regime": analysis.get("regime"), "strategy_name": analysis.get("strategy_name"),
            "analysis_summary": analysis.get("analysis_summary"),
            "entry_fee": size["entry_fee"],
            "opened_at": effective_opened_at,
            "last_market_candle_at": effective_opened_at,
        }
        rows = self.db.insert("trades", trade_row)
        if not rows:
            raise RuntimeError("Supabase não retornou a operação criada")
        trade = rows[0]
        self.db.update("paper_accounts", {"id": f"eq.{account['id']}"}, {
            "balance": new_balance,
            "total_fees": float(account.get("total_fees", 0)) + size["entry_fee"],
        })
        self._ledger(account["id"], trade["id"], "FEE", -size["entry_fee"], new_balance,
                     f"Taxa {entry_fee_type.lower()} simulada na entrada",
                     {"fee_type": entry_fee_type, "fee_rate": entry_fee_rate, "notional": size["notional"]})
        self._event(trade["id"], "OPENED", price=entry, quantity=size["quantity"], fee=size["entry_fee"],
                    metadata={"leverage": leverage, "margin_used": size["margin_used"],
                              "risk_pct": size["risk_pct"], "risk_budget": size["risk_budget"],
                              "entry_fee_type": entry_fee_type, "entry_fee_rate": entry_fee_rate})
        self._event(trade["id"], "FEE_CHARGED", price=entry, quantity=size["quantity"], fee=size["entry_fee"])
        self.notify(
            f"🟢 APEXPRIME — TRADE VIRTUAL ABERTO\n{direction} {trade_row['symbol']}\n"
            f"Entrada: {entry:.2f}\nStop: {stop:.2f}\nTP1: {tp1:.2f} | TP2: {tp2:.2f}\n"
            f"Qtd: {size['quantity']:.8f} BTC | Alavancagem: {leverage}x\n"
            f"Risco estimado: {size['risk_pct']:.2f}% ({size['risk_amount']:.4f} USDT)\n"
            f"Saldo após taxa de entrada: {new_balance:.4f} USDT\nMODO: SIMULAÇÃO"
        )
        self.db.log("INFO", "execution", "Trade virtual aberto", run_id=run_id,
                    details={"trade_id": trade["id"], "size": size, "entry": entry})
        return trade

    def create_pending_entry(self, analysis: dict[str, Any], *, run_id: str,
                             settings: dict[str, Any], trigger_direction: str) -> dict[str, Any] | None:
        """Persist a virtual pullback/confirmation setup; no order is sent to Binance."""
        if analysis.get("signal") not in {"LONG", "SHORT"} or analysis.get("entry_type") not in {"PULLBACK", "CONFIRMACAO"}:
            return None
        if analysis["signal"] != trigger_direction:
            self.db.log("WARN", "execution", "Setup pendente ignorado: direção da IA diverge do gatilho TradingView",
                        run_id=run_id, details={"ai_signal": analysis["signal"],
                                               "trigger_direction": trigger_direction})
            return None
        account = self._account()
        open_trades = self.db.select("trades", {
            "account_id": f"eq.{account['id']}", "status": "eq.OPEN",
        })
        pending = self.db.select("pending_entries", {
            "account_id": f"eq.{account['id']}", "status": "in.(PENDING,PROCESSING)",
        })
        if len(open_trades) >= int(settings.get("max_open_trades", 1)) or pending:
            self.db.log("INFO", "execution", "Setup pendente não criado: já existe trade ou setup ativo", run_id=run_id)
            return None

        hours = max(1, min(int(settings.get("pending_entry_expiry_hours", 12)), 72))
        expires_at = (utc_now() + timedelta(hours=hours)).isoformat()
        row = {
            "account_id": account["id"], "run_id": run_id,
            "symbol": settings.get("binance_symbol", "BTCUSDT"),
            "direction": analysis["direction"], "entry_type": analysis["entry_type"],
            "status": "PENDING", "entry_price": analysis["entry"],
            "stop_loss": analysis["stop_loss"], "tp1_price": analysis["tp1"],
            "tp2_price": analysis["tp2"], "confidence": analysis.get("confidence"),
            "score": analysis.get("score"), "regime": analysis.get("regime"),
            "strategy_name": analysis.get("strategy_name"),
            "analysis_summary": analysis.get("analysis_summary"),
            "expires_at": expires_at, "last_checked_at": iso_utc(),
        }
        rows = self.db.insert("pending_entries", row)
        if not rows:
            raise RuntimeError("Supabase não retornou o setup pendente criado")
        pending_row = rows[0]
        self.db.log("INFO", "execution", "Setup virtual pendente criado", run_id=run_id,
                    details={"pending_id": pending_row["id"], "entry_type": row["entry_type"],
                             "entry": row["entry_price"], "expires_at": expires_at})
        self.notify(
            f"🟠 APEXPRIME — ENTRADA VIRTUAL PENDENTE\n{row['direction']} {row['symbol']}\n"
            f"Tipo: {row['entry_type']}\nEntrada gatilho: {float(row['entry_price']):.2f}\n"
            f"Stop: {float(row['stop_loss']):.2f} | TP1: {float(row['tp1_price']):.2f} | TP2: {float(row['tp2_price']):.2f}\n"
            f"Expira em: {hours}h\nMODO: SIMULAÇÃO"
        )
        return pending_row

    @staticmethod
    def pending_fill_price(pending: dict[str, Any], candle: Candle) -> float | None:
        """Return a conservative simulated fill price when a closed candle confirms setup."""
        entry = float(pending["entry_price"])
        direction = pending["direction"]
        entry_type = pending["entry_type"]
        if entry_type == "PULLBACK":
            touched = candle.low <= entry <= candle.high
            if not touched:
                return None
            # A limit order receives opening-price improvement if the market gaps through it.
            return min(entry, candle.open) if direction == "LONG" else max(entry, candle.open)
        if entry_type == "CONFIRMACAO":
            if direction == "LONG" and candle.open <= entry and candle.close >= entry:
                return candle.close
            if direction == "SHORT" and candle.open >= entry and candle.close <= entry:
                return candle.close
        return None

    def monitor_pending_entries(self, settings: dict[str, Any]) -> None:
        """Fill, expire or retain pending virtual setups using closed 1m candles."""
        now = utc_now()
        # Recover claims left behind if a prior Actions job was terminated unexpectedly.
        stale_before = (now - timedelta(minutes=20)).isoformat()
        stale = self.db.select("pending_entries", {
            "status": "eq.PROCESSING", "updated_at": f"lt.{stale_before}",
        })
        for item in stale:
            self.db.update("pending_entries", {
                "id": f"eq.{item['id']}", "status": "eq.PROCESSING",
            }, {"status": "PENDING", "resolution_message": "Retomado após processamento interrompido"})

        candidates = self.db.select("pending_entries", {
            "status": "eq.PENDING",
        }, order="created_at.asc")
        for item in candidates:
            pending = dict(item)
            try:
                expiry = datetime.fromisoformat(str(pending["expires_at"]).replace("Z", "+00:00"))
                if expiry <= now:
                    self.db.update("pending_entries", {"id": f"eq.{pending['id']}", "status": "eq.PENDING"}, {
                        "status": "EXPIRED", "last_checked_at": iso_utc(),
                        "resolution_message": "Prazo de validade do setup encerrado",
                    })
                    self.notify(f"⌛ APEXPRIME — SETUP EXPIRADO\n{pending['direction']} {pending['symbol']} ({pending['entry_type']})")
                    continue

                claimed = self.db.update("pending_entries", {
                    "id": f"eq.{pending['id']}", "status": "eq.PENDING",
                }, {"status": "PROCESSING"})
                if not claimed:
                    continue

                created = datetime.fromisoformat(str(pending["created_at"]).replace("Z", "+00:00"))
                last_checked = datetime.fromisoformat(str(pending.get("last_checked_at") or pending["created_at"]).replace("Z", "+00:00"))
                scan_from = max(created, last_checked - timedelta(minutes=2))
                candles = self.market.one_minute_since(pending["symbol"], scan_from)
                filled = False
                try:
                    local_tz = ZoneInfo(settings.get("timezone", "America/Sao_Paulo"))
                except Exception:
                    local_tz = ZoneInfo("America/Sao_Paulo")
                for candle in candles:
                    # Ignore a minute bar that began before the setup was created; OHLC
                    # cannot prove whether its touch happened before or after creation.
                    if candle.open_time < created:
                        continue
                    if settings.get("avoid_weekends", False) and candle.open_time.astimezone(local_tz).weekday() >= 5:
                        continue
                    entry_price = float(pending["entry_price"])
                    stop_price = float(pending["stop_loss"])
                    stop_touched = (candle.low <= stop_price if pending["direction"] == "LONG"
                                    else candle.high >= stop_price)
                    target1 = float(pending["tp1_price"])
                    target_touched = (candle.high >= target1 if pending["direction"] == "LONG"
                                      else candle.low <= target1)
                    # A pending setup is invalid if its structural stop or TP1 was
                    # reached before a fill. OHLC cannot prove intrabar event order.
                    ambiguous_or_invalid = stop_touched or target_touched
                    if ambiguous_or_invalid:
                        self.db.update("pending_entries", {
                            "id": f"eq.{pending['id']}", "status": "eq.PROCESSING",
                        }, {
                            "status": "CANCELLED", "last_checked_at": candle.close_time.isoformat(),
                            "resolution_message": "Stop ou TP1 alcançado antes do preenchimento; setup cancelado por segurança",
                        })
                        self.notify("⚠️ APEXPRIME — SETUP PENDENTE INVALIDADO\nStop ou TP1 foi alcançado antes do preenchimento; entrada cancelada.")
                        filled = True
                        break
                    fill_price = self.pending_fill_price(pending, candle)
                    if fill_price is None:
                        continue
                    analysis = {
                        "signal": pending["direction"], "direction": pending["direction"],
                        "entry_type": pending["entry_type"], "entry": float(pending["entry_price"]),
                        "stop_loss": float(pending["stop_loss"]),
                        "tp1": float(pending["tp1_price"]), "tp2": float(pending["tp2_price"]),
                        "confidence": pending.get("confidence"), "score": float(pending.get("score") or 0),
                        "regime": pending.get("regime") or "TRANSICAO",
                        "strategy_name": pending.get("strategy_name") or "ApexPrime",
                        "analysis_summary": pending.get("analysis_summary") or "Entrada pendente preenchida por candle fechado.",
                    }
                    trade = self.open_trade(
                        analysis, run_id=pending["run_id"], settings=settings,
                        trigger_direction=pending["direction"], mark_price=fill_price,
                        pending_fill=True, opened_at=candle.close_time.isoformat(),
                    )
                    if trade:
                        self.db.update("pending_entries", {"id": f"eq.{pending['id']}", "status": "eq.PROCESSING"}, {
                            "status": "FILLED", "filled_trade_id": trade["id"],
                            "last_checked_at": candle.close_time.isoformat(),
                            "resolution_message": f"Preenchido em {fill_price:.8f}",
                        })
                        self.db.log("INFO", "execution", "Setup pendente preenchido como trade virtual",
                                    run_id=pending.get("run_id"),
                                    details={"pending_id": pending["id"], "trade_id": trade["id"],
                                             "fill_price": fill_price})
                        filled = True
                    else:
                        self.db.update("pending_entries", {"id": f"eq.{pending['id']}", "status": "eq.PROCESSING"}, {
                            "status": "CANCELLED", "last_checked_at": candle.close_time.isoformat(),
                            "resolution_message": "Gatilho ocorreu, mas as proteções de risco bloquearam a entrada",
                        })
                        self.notify("⚠️ APEXPRIME — ENTRADA PENDENTE CANCELADA\nO gatilho ocorreu, mas o controle de risco bloqueou a posição.")
                        filled = True
                    break

                if not filled:
                    # Keep the last *market candle* cursor, not wall-clock now. The
                    # next hourly run must replay every 1m bar since the previous run.
                    last_closed = max((c.close_time for c in candles), default=None)
                    progress = last_closed.isoformat() if last_closed else pending.get("last_checked_at")
                    values = {"status": "PENDING"}
                    if progress:
                        values["last_checked_at"] = progress
                    self.db.update("pending_entries", {"id": f"eq.{pending['id']}", "status": "eq.PROCESSING"}, values)
            except Exception as exc:
                self.db.update("pending_entries", {"id": f"eq.{pending['id']}", "status": "eq.PROCESSING"}, {
                    "status": "PENDING",
                    "resolution_message": f"Falha temporária: {type(exc).__name__}",
                })
                self.db.log("ERROR", "pending_entries", f"Falha ao monitorar entrada pendente: {exc}",
                            run_id=pending.get("run_id"), details={"pending_id": pending["id"]})

    def _apply_cashflow(self, account: dict[str, Any], trade: dict[str, Any],
                        amount: float, kind: str, description: str,
                        metadata: dict[str, Any] | None = None) -> dict[str, Any]:
        """amount is the signed cashflow credited to account balance."""
        new_balance = float(account["balance"]) + amount
        fee_total = float(account.get("total_fees", 0))
        funding_total = float(account.get("total_funding", 0))
        values: dict[str, Any] = {"balance": new_balance}
        if kind == "FEE":
            fee_total += -amount
            values["total_fees"] = fee_total
        elif kind == "FUNDING":
            funding_total += -amount
            values["total_funding"] = funding_total
        self.db.update("paper_accounts", {"id": f"eq.{account['id']}"}, values)
        self._ledger(account["id"], trade["id"], kind, amount, new_balance, description, metadata)
        account.update(values)
        return account

    def _partial_close(self, trade: dict[str, Any], price: float, quantity: float,
                       settings: dict[str, Any], event_type: str,
                       account: dict[str, Any], fee_type: str = "TAKER") -> tuple[dict[str, Any], dict[str, Any]]:
        quantity = min(quantity, float(trade["remaining_quantity"]))
        if quantity <= 0:
            return trade, account
        direction_sign = 1.0 if trade["direction"] == "LONG" else -1.0
        gross = (price - float(trade["entry_price"])) * quantity * direction_sign
        fee_type = fee_type.upper()
        fee_rate = float(settings.get("maker_fee_rate", 0.0002) if fee_type == "MAKER"
                         else settings.get("taker_fee_rate", 0.0005))
        fee = price * quantity * fee_rate

        # Book gross realized PnL and commission as separate cash movements.
        balance_after_gross = float(account["balance"]) + gross
        realized_total = float(account.get("realized_pnl", 0)) + gross
        self.db.update("paper_accounts", {"id": f"eq.{account['id']}"}, {
            "balance": balance_after_gross, "realized_pnl": realized_total,
        })
        self._ledger(account["id"], trade["id"], "REALIZED_PNL", gross, balance_after_gross,
                     "PnL bruto realizado", {"price": price, "quantity": quantity})
        account["balance"] = balance_after_gross
        account["realized_pnl"] = realized_total
        balance_after_fee = balance_after_gross - fee
        total_fees = float(account.get("total_fees", 0)) + fee
        self.db.update("paper_accounts", {"id": f"eq.{account['id']}"}, {
            "balance": balance_after_fee, "total_fees": total_fees,
        })
        self._ledger(account["id"], trade["id"], "FEE", -fee, balance_after_fee,
                     f"Taxa {fee_type.lower()} simulada na saída", {"price": price, "quantity": quantity,
                                                                     "fee_type": fee_type, "fee_rate": fee_rate})
        account["balance"] = balance_after_fee
        account["total_fees"] = total_fees

        new_remaining = max(0.0, float(trade["remaining_quantity"]) - quantity)
        gross_total = float(trade.get("realized_pnl_gross", 0)) + gross
        exit_fees = float(trade.get("exit_fees", 0)) + fee
        net_total = gross_total - float(trade.get("entry_fee", 0)) - exit_fees - float(trade.get("funding_paid", 0))
        initial_qty = float(trade.get("initial_quantity", 0))
        remaining_fraction = (new_remaining / initial_qty) if initial_qty > 0 else 0.0
        updates = {
            "remaining_quantity": new_remaining,
            "margin_used": float(trade.get("margin_used", 0)) * remaining_fraction,
            "realized_pnl_gross": gross_total,
            "exit_fees": exit_fees,
            "realized_pnl_net": net_total,
            "tp1_hit": True if event_type == "TP1_PARTIAL" else bool(trade.get("tp1_hit")),
        }
        self.db.update("trades", {"id": f"eq.{trade['id']}"}, updates)
        trade.update(updates)
        # Full-exit events are recorded by _close_all; only TP1 is recorded here.
        if event_type == "TP1_PARTIAL":
            self._event(trade["id"], event_type, price=price, quantity=quantity, gross=gross, fee=fee)
        self._event(trade["id"], "FEE_CHARGED", price=price, quantity=quantity, fee=fee)
        return trade, account

    def _close_all(self, trade: dict[str, Any], price: float, reason: str,
                   settings: dict[str, Any], account: dict[str, Any], event_type: str) -> None:
        quantity = float(trade.get("remaining_quantity", 0))
        if quantity > 0:
            # Keep the partial-close bookkeeping path; close reason is finalized below.
            fee_type = "MAKER" if reason == "TP2" else "TAKER"
            trade, account = self._partial_close(trade, price, quantity, settings,
                                                 event_type, account, fee_type=fee_type)
        # Update final status after the cashflows have been posted.
        reason = reason if reason in {"TP2", "STOP_LOSS", "MANUAL", "SIGNAL_REVERSAL", "RISK_GUARD", "CANCELLED"} else "MANUAL"
        self.db.update("trades", {"id": f"eq.{trade['id']}"}, {
            "status": "CLOSED", "remaining_quantity": 0,
            "exit_price": price, "close_reason": reason,
            "closed_at": iso_utc(),
        })
        self._event(trade["id"], event_type, price=price, quantity=quantity,
                    metadata={"close_reason": reason})
        self.notify(
            f"🔴 APEXPRIME — TRADE VIRTUAL FECHADO\n{trade['direction']} {trade['symbol']}\n"
            f"Saída: {price:.2f}\nMotivo: {reason}\n"
            f"PnL líquido acumulado: {float(trade.get('realized_pnl_net', 0)):.4f} USDT\nMODO: SIMULAÇÃO"
        )

    def charge_funding(self, trade: dict[str, Any], settings: dict[str, Any],
                       account: dict[str, Any], mark_price: float) -> tuple[dict[str, Any], dict[str, Any]]:
        if not settings.get("funding_enabled", True):
            return trade, account
        opened = datetime.fromisoformat(str(trade["opened_at"]).replace("Z", "+00:00"))
        events = self.db.select("trade_events", {
            "trade_id": f"eq.{trade['id']}", "event_type": "eq.FUNDING_CHARGED",
        }, order="created_at.desc", limit=1)
        if events:
            last_ms = int(events[0].get("metadata", {}).get("funding_time_ms", 0))
            start = datetime.fromtimestamp(last_ms / 1000, tz=timezone.utc)
        else:
            start = opened
        try:
            records = self.market.funding_history(trade["symbol"], start, utc_now())
        except Exception as exc:
            self.db.log("WARN", "funding", f"Falha ao consultar funding: {exc}",
                        details={"trade_id": trade["id"]})
            return trade, account
        for record in records:
            funding_ms = int(record["fundingTime"])
            if events and funding_ms <= int(events[0].get("metadata", {}).get("funding_time_ms", 0)):
                continue
            if funding_ms < int(opened.timestamp() * 1000):
                continue
            rate = float(record["fundingRate"])
            mark = float(record.get("markPrice") or mark_price)
            sign = 1.0 if trade["direction"] == "LONG" else -1.0
            funding_cost = float(trade["remaining_quantity"]) * mark * rate * sign
            cashflow = -funding_cost
            account = self._apply_cashflow(account, trade, cashflow, "FUNDING",
                                           "Funding simulado conforme taxa histórica da Binance",
                                           {"funding_time_ms": funding_ms, "funding_rate": rate,
                                            "mark_price": mark, "signed_funding_cost": funding_cost})
            trade["funding_paid"] = float(trade.get("funding_paid", 0)) + funding_cost
            trade["realized_pnl_net"] = float(trade.get("realized_pnl_gross", 0)) - float(trade.get("entry_fee", 0)) - float(trade.get("exit_fees", 0)) - trade["funding_paid"]
            self.db.update("trades", {"id": f"eq.{trade['id']}"}, {
                "funding_paid": trade["funding_paid"], "realized_pnl_net": trade["realized_pnl_net"],
            })
            self._event(trade["id"], "FUNDING_CHARGED", price=mark,
                        quantity=float(trade["remaining_quantity"]), funding=funding_cost,
                        metadata={"funding_time_ms": funding_ms, "funding_rate": rate})
        return trade, account

    def monitor_open_trades(self, settings: dict[str, Any]) -> None:
        trades = self.db.select("trades", {"status": "eq.OPEN"}, order="opened_at.asc")
        for original in trades:
            trade = dict(original)
            try:
                account = self._account()
                mark_info = self.market.mark_price(trade["symbol"])
                mark_price = float(mark_info["markPrice"])
                trade, account = self.charge_funding(trade, settings, account, mark_price)
                cursor = datetime.fromisoformat(str(trade.get("last_market_candle_at") or trade["opened_at"]).replace("Z", "+00:00"))
                # Re-read two minutes of overlap: the previous scheduled job may
                # have run before the latest 1m candle finished. Trade flags/status
                # make event replay idempotent.
                candles = self.market.one_minute_since(trade["symbol"], cursor - timedelta(minutes=2))
                opened_at = datetime.fromisoformat(str(trade["opened_at"]).replace("Z", "+00:00"))
                processed_candles = [c for c in candles if c.open_time >= opened_at]
                for candle in processed_candles:
                    if candle.open_time < opened_at:
                        continue
                    trade = self.db.select("trades", {"id": f"eq.{trade['id']}"}, limit=1)[0]
                    if trade["status"] != "OPEN":
                        break
                    direction = trade["direction"]
                    stop = float(trade["current_stop_loss"])
                    entry = float(trade["entry_price"])
                    tp1 = float(trade["tp1_price"])
                    tp2 = float(trade["tp2_price"])
                    risk = abs(entry - float(trade["initial_stop_loss"]))

                    # Conservative OHLC rule: if stop and target are both touched in
                    # the same 1m candle, stop wins because intrabar order is unknown.
                    stop_hit = candle.low <= stop if direction == "LONG" else candle.high >= stop
                    if stop_hit:
                        account = self._account()
                        self._close_all(trade, stop, "STOP_LOSS", settings, account, "STOP_LOSS")
                        break

                    be_already = bool(trade.get("break_even_moved"))
                    one_r = entry + risk if direction == "LONG" else entry - risk
                    hit_one_r = candle.high >= one_r if direction == "LONG" else candle.low <= one_r
                    if not be_already and hit_one_r:
                        self.db.update("trades", {"id": f"eq.{trade['id']}"}, {
                            "current_stop_loss": entry, "break_even_moved": True,
                        })
                        self._event(trade["id"], "STOP_TO_BREAKEVEN", price=entry,
                                    metadata={"trigger": "1R"})
                        trade["current_stop_loss"] = entry
                        trade["break_even_moved"] = True
                        # If same candle also revisits entry, treat as BE stop.
                        be_hit = candle.low <= entry if direction == "LONG" else candle.high >= entry
                        if be_hit:
                            account = self._account()
                            self._close_all(trade, entry, "STOP_LOSS", settings, account, "STOP_LOSS")
                            break

                    tp1_hit_now = candle.high >= tp1 if direction == "LONG" else candle.low <= tp1
                    if not bool(trade.get("tp1_hit")) and tp1_hit_now:
                        qty = float(trade["initial_quantity"]) * float(trade.get("tp1_fraction", 0.5))
                        account = self._account()
                        trade, account = self._partial_close(trade, tp1, qty, settings,
                                                             "TP1_PARTIAL", account, fee_type="MAKER")
                        self.notify(f"🟡 APEXPRIME — TP1 atingido\n{trade['direction']} {trade['symbol']}\n50% fechado em {tp1:.2f}; stop protegido em breakeven.\nMODO: SIMULAÇÃO")

                    if bool(trade.get("tp1_hit")):
                        tp2_hit_now = candle.high >= tp2 if direction == "LONG" else candle.low <= tp2
                        if tp2_hit_now:
                            account = self._account()
                            trade = self.db.select("trades", {"id": f"eq.{trade['id']}"}, limit=1)[0]
                            self._close_all(trade, tp2, "TP2", settings, account, "TP2_CLOSED")
                            break
                # Persist the last closed market candle separately from updated_at;
                # the database updated_at trigger records wall-clock changes only.
                still_open = self.db.select("trades", {"id": f"eq.{original['id']}", "status": "eq.OPEN"}, limit=1)
                if still_open and processed_candles:
                    last_candle = max(processed_candles, key=lambda c: c.close_time)
                    self.db.update("trades", {"id": f"eq.{original['id']}"}, {
                        "last_market_candle_at": last_candle.close_time.isoformat()
                    })
            except Exception as exc:
                log.exception("Falha monitorando trade %s", trade.get("id"))
                self.db.log("ERROR", "execution", f"Falha ao monitorar trade: {exc}",
                            details={"trade_id": trade.get("id")})

    def close_manual(self, settings: dict[str, Any]) -> int:
        trades = self.db.select("trades", {"status": "eq.OPEN"})
        pending = self.db.select("pending_entries", {"status": "in.(PENDING,PROCESSING)"})
        for item in pending:
            self.db.update("pending_entries", {"id": f"eq.{item['id']}", "status": f"in.(PENDING,PROCESSING)"}, {
                "status": "CANCELLED", "last_checked_at": iso_utc(),
                "resolution_message": "Cancelado manualmente pelo painel",
            })
        if pending:
            self.notify(f"⛔ APEXPRIME — {len(pending)} entrada(s) pendente(s) cancelada(s) manualmente.")
        closed = 0
        for trade in trades:
            mark = float(self.market.mark_price(trade["symbol"])["markPrice"])
            account = self._account()
            trade, account = self.charge_funding(trade, settings, account, mark)
            self._close_all(trade, mark, "MANUAL", settings, account, "MANUAL_EXIT")
            closed += 1
        return closed
