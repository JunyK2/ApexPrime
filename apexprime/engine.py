from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

from .analysis import (ChartImgClient, GeminiClient, GroqHealthClient, GroqAnalysisClient,
                      OpenRouterClient, candles_to_text, load_prompt, TIMEFRAMES)
from .config import Config
from .db import SupabaseREST
from .execution import PaperExecutor
from .market import BinanceFutures, Candle
from .notify import TelegramNotifier
from .risk import validate_apex_table
from .strategy import detect_latest_trigger, indicators
from .utils import clean_error, iso_utc, utc_now, extract_json_object, safe_timezone_name

log = logging.getLogger("apexprime.engine")


class ApexEngine:
    def __init__(self, config: Config):
        config.validate_paper_only()
        self.config = config
        self.db = SupabaseREST(config.supabase_url, config.supabase_service_role_key)
        self.market = BinanceFutures(config.binance_fapi_base)
        self.telegram = TelegramNotifier(config.telegram_bot_token, config.telegram_chat_id)
        self.executor = PaperExecutor(self.db, self.market, self.telegram.send)
        self.executor.on_trade_closed = self._on_trade_closed

    def _fetch_datasets(self, symbol: str) -> dict[str, list[Candle]]:
        limits = {"1D": 90, "4H": 100, "1H": 100, "15M": 100, "5M": 100}
        return {
            label: self.market.recent_closed_klines(symbol, interval, limits[label])
            for label, interval in TIMEFRAMES
        }

    @staticmethod
    def _snapshot(datasets: dict[str, list[Candle]], mark: dict[str, Any],
                  trigger: dict[str, Any], symbol: str = "BTCUSDT") -> dict[str, Any]:
        frames: dict[str, Any] = {}
        for timeframe, candles in datasets.items():
            if not candles:
                frames[timeframe] = {"count": 0}
                continue
            frames[timeframe] = {
                "count": len(candles),
                "last_closed_open_time": candles[-1].open_time.isoformat(),
                "last_closed_close_time": candles[-1].close_time.isoformat(),
                "last_close": candles[-1].close,
                "high_sample": max(c.high for c in candles[-30:]),
                "low_sample": min(c.low for c in candles[-30:]),
                "indicators": indicators(candles),
            }
        return {"symbol": symbol, "mark_price": mark.get("markPrice"),
                "last_funding_rate": mark.get("lastFundingRate"),
                "next_funding_time": mark.get("nextFundingTime"),
                "timeframes": frames, "trigger": trigger}

    def _create_run(self, *, source: str, settings: dict[str, Any],
                    trigger: dict[str, Any] | None, candle: Candle | None) -> dict[str, Any] | None:
        row = {
            "source": source,
            "status": "running",
            "analysis_mode": settings["analysis_mode"],
            "symbol": settings.get("binance_symbol", "BTCUSDT"),
            "trigger_time": iso_utc(),
            "trigger_candle_open_time": candle.open_time.isoformat() if candle else None,
            "trigger_direction": (trigger or {}).get("direction", "NONE"),
            "trigger_score": (trigger or {}).get("score"),
            "started_at": iso_utc(),
        }
        try:
            rows = self.db.insert("system_runs", row)
            return rows[0] if rows else None
        except Exception as exc:
            # Hourly candle uniqueness makes retries idempotent.
            if source == "hourly_scan" and "duplicate key" in str(exc).lower():
                self.db.log("INFO", "worker", "Candle horária já processada; execução duplicada ignorada")
                return None
            raise

    def _update_run(self, run_id: str, values: dict[str, Any]) -> None:
        self.db.update("system_runs", {"id": f"eq.{run_id}"}, values)

    def _record_gemini(self, *, run_id: str, model: str, mode: str, success: bool,
                       prompt_chars: int, latency_ms: int | None = None,
                       usage: dict[str, Any] | None = None, error: str | None = None) -> None:
        usage = usage or {}
        self.db.insert("gemini_requests", {
            "run_id": run_id,
            "model": model,
            "analysis_mode": mode,
            "success": success,
            "prompt_chars": prompt_chars,
            "input_tokens": usage.get("input_tokens"),
            "output_tokens": usage.get("output_tokens"),
            "total_tokens": usage.get("total_tokens"),
            "latency_ms": latency_ms,
            "error_code": "GEMINI_ERROR" if error else None,
            "error_message": clean_error(error, self.config.gemini_api_key) if error else None,
        })

    def _record_ai_attempt(self, *, run_id: str, provider: str, model: str,
                           mode: str, success: bool, latency_ms: int | None = None,
                           result: dict[str, Any] | None = None,
                           error: str | None = None) -> None:
        result = result or {}
        safe_message = clean_error(error or "", self.config.openrouter_api_key,
                                   self.config.gemini_api_key, self.config.groq_api_key)
        self.db.insert("ai_requests", {
            "run_id": run_id, "provider": provider.upper(), "model": model,
            "analysis_mode": mode, "success": success, "latency_ms": latency_ms,
            "input_tokens": result.get("input_tokens"),
            "output_tokens": result.get("output_tokens"),
            "error_message": safe_message or None,
            "metadata": {"attempted_with_images": bool(result.get("attempted_with_images"))},
        })
        if provider.upper() == "GEMINI":
            self._record_gemini(
                run_id=run_id, model=model, mode=mode, success=success,
                prompt_chars=int(result.get("prompt_chars") or 0),
                latency_ms=latency_ms, usage=result, error=error,
            )

    def _analyze(self, *, run: dict[str, Any], settings: dict[str, Any], prompts: dict[str, Any],
                 datasets: dict[str, list[Candle]], symbol: str,
                 mark: dict[str, Any], snapshot: dict[str, Any]) -> dict[str, Any]:
        requested_mode = str(settings.get("analysis_mode", "chart_img")).lower()
        if requested_mode not in {"chart_img", "text"}:
            raise RuntimeError(f"Modo de análise desconhecido: {requested_mode}")

        timezone_name = safe_timezone_name(settings.get("timezone"))
        text_data = candles_to_text(datasets, symbol=symbol, timezone_name=timezone_name, rows_per_tf=60)
        image_prompt = load_prompt(
            prompts.get("custom_chart_img_prompt"), "default-chart-img.md"
        )
        text_prompt = load_prompt(
            prompts.get("custom_text_prompt"), "default-text.md"
        )

        provider_strategy = str(settings.get("ai_provider_strategy", "auto")).lower()
        fixed_provider = str(settings.get("fixed_ai_provider", "gemini")).lower()
        # Groq's configured fallback model is text-only in this project. In fixed mode,
        # select the matching text graph/prompt rather than falsely labeling images as used.
        fixed_text_only = provider_strategy == "fixed" and fixed_provider == "groq"
        actual_mode = "text" if fixed_text_only else requested_mode
        images: list[dict[str, Any]] = []
        chart_metadata: list[dict[str, Any]] = []
        chart_error: str | None = None

        if actual_mode == "chart_img":
            try:
                if not self.config.chart_img_api_key:
                    raise RuntimeError("CHART_IMG_API_KEY ausente")
                chart_client = ChartImgClient(self.config.chart_img_api_key, self.config.chart_img_api_base)
                images = chart_client.get_five_charts(timezone_name, symbol=self.config.chart_img_symbol)
                for item in images:
                    ext = {"image/png": "png", "image/jpeg": "jpg", "image/webp": "webp"}.get(item["mime_type"], "png")
                    object_path = f"{run['id']}/{item['timeframe'].lower()}.{ext}"
                    metadata = {"timeframe": item["timeframe"], "mime_type": item["mime_type"],
                                "bytes": len(item["data"]), "width": 800, "height": 600,
                                "used_for_analysis": False}
                    try:
                        metadata["url"] = self.db.upload_public_image(
                            "apexprime-charts", object_path, item["data"], item["mime_type"]
                        )
                    except Exception as storage_exc:
                        metadata["storage_error"] = clean_error(
                            str(storage_exc), self.config.supabase_service_role_key
                        )[:300]
                    chart_metadata.append(metadata)
            except Exception as exc:
                chart_error = clean_error(str(exc), self.config.chart_img_api_key)
                actual_mode = "text"
                images = []
                self.db.service_check("CHART_IMG", "WARN",
                    "Chart IMG falhou; fallback automático para gráfico em texto",
                    run_id=run["id"], details={"error": chart_error, "resolution": "800x600"})
                self.db.log("WARN", "analysis", "Chart IMG indisponível; usando dados tabulares",
                    run_id=run["id"], details={"error": chart_error})

        prompt_for = lambda mode: image_prompt if mode == "chart_img" else text_prompt
        provider_strategy = provider_strategy if provider_strategy in {"auto", "fixed"} else "auto"
        attempts: list[tuple[str, str, Any, list[dict[str, Any]], str | None, str, str]] = []

        if provider_strategy == "fixed":
            provider = fixed_provider
            model = str(settings.get("fixed_ai_model") or settings.get(f"{provider}_model") or "").strip()
            attempt_mode = "text" if provider == "groq" else actual_mode
            attempt_images = images if attempt_mode == "chart_img" else []
            attempt_text = None if attempt_images else text_data
            if provider == "gemini":
                if not self.config.gemini_api_key:
                    raise RuntimeError("GEMINI_API_KEY ausente para o provedor fixo")
                client = GeminiClient(self.config.gemini_api_key, model or "gemini-4-hydrogen", self.config.gemini_api_base)
            elif provider == "openrouter":
                if not self.config.openrouter_api_key:
                    raise RuntimeError("OPENROUTER_API_KEY ausente para o provedor fixo")
                client = OpenRouterClient(self.config.openrouter_api_key, model or "openrouter/free", self.config.openrouter_api_base)
            elif provider == "groq":
                if not self.config.groq_api_key:
                    raise RuntimeError("GROQ_API_KEY ausente para o provedor fixo")
                client = GroqAnalysisClient(self.config.groq_api_key, model or "openai/gpt-oss-120b", self.config.groq_api_base)
            else:
                raise RuntimeError(f"Provedor fixo inválido: {provider}")
            attempts.append((provider.upper(), getattr(client, "model", model), client,
                             attempt_images, attempt_text, attempt_mode, prompt_for(attempt_mode)))
            if provider == "openrouter" and attempt_images:
                # A fixed free vision model may resolve to a text-only provider; keep the
                # selected model but retry the same provider with the text chart.
                text_client = OpenRouterClient(self.config.openrouter_api_key, model or "openrouter/free", self.config.openrouter_api_base)
                attempts.append(("OPENROUTER", getattr(text_client, "model", model), text_client,
                                 [], text_data, "text", text_prompt))
        else:
            if self.config.gemini_api_key:
                model = str(settings.get("gemini_model", "gemini-4-hydrogen"))
                client = GeminiClient(self.config.gemini_api_key, model, self.config.gemini_api_base)
                attempts.append(("GEMINI", model, client, images, None if images else text_data,
                                 actual_mode, prompt_for(actual_mode)))
            if self.config.openrouter_api_key:
                model = str(settings.get("openrouter_model", "openrouter/free"))
                # openrouter/free automatically routes to an available free model. First ask
                # for vision when images exist; if the chosen free endpoint cannot accept vision,
                # retry the same router request with the text chart and text-specific prompt.
                client = OpenRouterClient(self.config.openrouter_api_key, model, self.config.openrouter_api_base)
                attempts.append(("OPENROUTER", model, client, images, None if images else text_data,
                                 actual_mode, prompt_for(actual_mode)))
                if images:
                    client_text = OpenRouterClient(self.config.openrouter_api_key, model, self.config.openrouter_api_base)
                    attempts.append(("OPENROUTER", model, client_text, [], text_data, "text", text_prompt))
            if self.config.groq_api_key:
                model = str(settings.get("groq_model", "openai/gpt-oss-120b"))
                client = GroqAnalysisClient(self.config.groq_api_key, model, self.config.groq_api_base)
                attempts.append(("GROQ", model, client, [], text_data, "text", text_prompt))

        if not attempts:
            raise RuntimeError("Nenhum provedor de IA está configurado. Configure Gemini, OpenRouter ou Groq.")

        errors: list[str] = []
        for provider, model, client, attempt_images, attempt_text, attempt_mode, attempt_prompt in attempts:
            try:
                result = client.analyze(attempt_prompt, text_data=attempt_text, images=attempt_images)
                model_used = str(result.get("model") or model)
                data = validate_apex_table(extract_json_object(result["text"]))
                for item in chart_metadata:
                    item["used_for_analysis"] = bool(attempt_images)
                self._record_ai_attempt(
                    run_id=run["id"], provider=provider, model=model_used, mode=attempt_mode,
                    success=True, latency_ms=result.get("latency_ms"), result={
                        **result,
                        "prompt_chars": len(attempt_prompt) + (len(attempt_text) if attempt_text else 0),
                        "attempted_with_images": bool(attempt_images),
                    },
                )
                if provider != "GEMINI":
                    self.db.service_check(provider, "OK", f"Análise concluída via {provider}",
                        latency_ms=result.get("latency_ms"), run_id=run["id"],
                        details={"model": model_used, "mode": attempt_mode, "images": bool(attempt_images)})
                return {
                    "data": data, "raw": result["text"], "latency_ms": result.get("latency_ms"),
                    "provider": provider, "model": model_used, "analysis_mode": attempt_mode,
                    "requested_analysis_mode": requested_mode,
                    "chart_metadata": chart_metadata, "text_data": text_data,
                    "text_chars": len(text_data),
                    "usage": {k: result.get(k) for k in ("input_tokens", "output_tokens", "total_tokens")},
                    "chart_error": chart_error,
                }
            except Exception as exc:
                message = clean_error(str(exc), self.config.gemini_api_key,
                                      self.config.openrouter_api_key, self.config.groq_api_key,
                                      self.config.chart_img_api_key)
                errors.append(f"{provider}/{model}: {message}")
                try:
                    self._record_ai_attempt(run_id=run["id"], provider=provider, model=model,
                        mode=attempt_mode, success=False, error=message,
                        result={"prompt_chars": len(attempt_prompt) + (len(attempt_text) if attempt_text else 0),
                                "attempted_with_images": bool(attempt_images)})
                except Exception:
                    log.exception("Falha registrando tentativa de IA")
                if provider != "GEMINI":
                    try:
                        self.db.service_check(provider, "ERROR", message[:500], run_id=run["id"],
                                              details={"model": model, "mode": attempt_mode})
                    except Exception:
                        pass
                self.db.log("WARN", "ai_failover", f"Falha em {provider}; tentando próximo fallback",
                    run_id=run["id"], details={"provider": provider, "model": model,
                                               "mode": attempt_mode, "error": message[:600]})
        raise RuntimeError("Todos os provedores de análise falharam: " + " | ".join(errors)[-3500:])

    def _health_check_groq(self, settings: dict[str, Any], snapshot: dict[str, Any],
                           run_id: str | None = None) -> None:
        if not settings.get("groq_enabled", True):
            return
        if not self.config.groq_api_key:
            self.db.service_check("GROQ", "WARN", "GROQ_API_KEY não configurada", run_id=run_id)
            return
        model = settings.get("groq_model", "openai/gpt-oss-120b")
        try:
            client = GroqHealthClient(self.config.groq_api_key, model, self.config.groq_api_base)
            result = client.check(snapshot)
            self.db.service_check("GROQ", "OK", "Verificação Groq concluída",
                                  latency_ms=result["latency_ms"], run_id=run_id,
                                  details={"response": result["text"][:1800]})
            if settings.get("groq_alerts_enabled", True):
                low = result["text"].lower()
                if '"healthy": false' in low or '"severity": "critical"' in low:
                    self.telegram.send("⚠️ APEXPRIME — ALERTA DE SAÚDE\n" + result["text"][:3000])
        except Exception as exc:
            message = clean_error(str(exc), self.config.groq_api_key)
            self.db.service_check("GROQ", "ERROR", message, run_id=run_id)
            if settings.get("groq_alerts_enabled", True):
                self.telegram.send("⚠️ APEXPRIME — Groq indisponível\n" + message[:1000])

    def _runtime_settings(self) -> dict[str, Any]:
        settings = self.db.settings()
        settings["max_entry_deviation_pct"] = self.config.max_entry_deviation_pct
        settings["pending_entry_expiry_hours"] = self.config.pending_entry_expiry_hours
        settings["timezone"] = safe_timezone_name(settings.get("timezone"))
        settings.setdefault("groq_health_interval_hours", 4)
        settings.setdefault("ai_provider_strategy", "auto")
        settings.setdefault("fixed_ai_provider", "gemini")
        settings.setdefault("openrouter_model", "openrouter/free")
        return settings

    def _daily_loss_guard(self, settings: dict[str, Any]) -> tuple[bool, float, float]:
        """Return daily ledger guard; excludes unrealized PnL on still-open positions."""
        account = self.db.active_account()
        local_tz = ZoneInfo(safe_timezone_name(settings.get("timezone")))
        now_local = datetime.now(local_tz)
        start_local = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
        start_utc = start_local.astimezone(timezone.utc).isoformat()
        ledger = self.db.select("balance_ledger", {
            "account_id": f"eq.{account['id']}",
            "created_at": f"gte.{start_utc}",
        }, limit=2000)
        today_pnl = sum(
            float(row.get("amount", 0) or 0) for row in ledger
            if row.get("event_type") not in {"INITIAL_BALANCE", "RESET"}
        )
        max_loss_pct = float(settings.get("max_daily_loss_pct", 6.0))
        loss_limit = float(account.get("initial_balance", 20)) * max_loss_pct / 100.0
        return today_pnl <= -loss_limit, today_pnl, loss_limit

    def run_maintenance(self) -> None:
        """Monitor pending entries and open paper trades independently of Gemini scans."""
        settings = self._runtime_settings()
        self.executor.monitor_pending_entries(settings)
        self.executor.monitor_open_trades(settings)

    def run_device_health_check(self, device_snapshot: dict[str, Any]) -> None:
        """Send server telemetry to Groq independently of whether a new 1H candle exists."""
        settings = self._runtime_settings()
        self._health_check_groq(settings, {"server_device": device_snapshot,
                                           "market_provider": "BINANCE_USDM",
                                           "mode": "PAPER_ONLY"})

    def run_hourly(self, *, include_maintenance: bool = True, check_groq: bool = True) -> None:
        settings = self._runtime_settings()
        prompts = self.db.prompts()
        symbol = settings.get("binance_symbol", "BTCUSDT")
        # The Redmi daemon performs this every minute. Keep it enabled for manual/legacy CLI runs.
        if include_maintenance:
            self.executor.monitor_pending_entries(settings)
            self.executor.monitor_open_trades(settings)
        candles = self.market.recent_closed_klines(symbol, "1h", 120)
        trigger_signal = detect_latest_trigger(
            candles,
            vol_mult=float(settings.get("trigger_volume_multiplier", 1.5)),
            sweep_len=int(settings.get("trigger_sweep_length", 16)),
            disp_mult=float(settings.get("trigger_displacement_multiplier", 1.5)),
            cooldown=int(settings.get("trigger_cooldown", 3)),
            min_score=int(settings.get("trigger_min_score", 2)),
        )
        trigger = trigger_signal.to_dict()
        if not candles:
            raise RuntimeError("A Binance não retornou candles 1H fechados")
        try:
            mark = self.market.mark_price(symbol)
        except Exception:
            mark = {}
        snapshot = {
            "symbol": symbol,
            "mark_price": mark.get("markPrice"),
            "last_funding_rate": mark.get("lastFundingRate"),
            "next_funding_time": mark.get("nextFundingTime"),
            "trigger": trigger,
            "timeframes": {"1H": {
                "last_closed_open_time": candles[-1].open_time.isoformat(),
                "last_closed_close_time": candles[-1].close_time.isoformat(),
                "open": candles[-1].open, "high": candles[-1].high,
                "low": candles[-1].low, "close": candles[-1].close,
                "volume": candles[-1].volume,
            }},
        }
        self._record_opportunity(symbol, candles[-1], trigger, settings)
        run = self._create_run(source="hourly_scan", settings=settings,
                               trigger=trigger, candle=candles[-1])
        if not run:
            return
        if trigger_signal.direction == "NONE":
            self._update_run(run["id"], {
                "status": "skipped", "market_snapshot": snapshot,
                "finished_at": iso_utc(), "error_code": "NO_TRIGGER",
                "error_message": trigger_signal.reason,
            })
            self.db.log("INFO", "strategy", trigger_signal.reason, run_id=run["id"], details=trigger)
            if check_groq:
                self._health_check_groq(settings, snapshot, run["id"])
            return
        self._run_analysis(run=run, settings=settings, prompts=prompts,
                           datasets=None, trigger=trigger, source="hourly_scan",
                           check_groq=check_groq)

    def run_manual_analysis(self) -> dict[str, Any]:
        settings = self.db.settings()
        prompts = self.db.prompts()
        settings["max_entry_deviation_pct"] = self.config.max_entry_deviation_pct
        settings["pending_entry_expiry_hours"] = self.config.pending_entry_expiry_hours
        symbol = settings.get("binance_symbol", "BTCUSDT")
        candles = self.market.recent_closed_klines(symbol, "1h", 120)
        signal = detect_latest_trigger(
            candles, vol_mult=float(settings.get("trigger_volume_multiplier", 1.5)),
            sweep_len=int(settings.get("trigger_sweep_length", 16)),
            disp_mult=float(settings.get("trigger_displacement_multiplier", 1.5)),
            cooldown=int(settings.get("trigger_cooldown", 3)),
            min_score=int(settings.get("trigger_min_score", 2)),
        )
        trigger = signal.to_dict()
        run = self._create_run(source="manual", settings=settings, trigger=trigger, candle=None)
        if not run:
            raise RuntimeError("Não foi possível criar execução manual")
        return self._run_analysis(run=run, settings=settings, prompts=prompts,
                                  datasets=None, trigger=trigger, source="manual", check_groq=False)

    def _run_analysis(self, *, run: dict[str, Any], settings: dict[str, Any],
                      prompts: dict[str, Any], datasets: dict[str, list[Candle]] | None,
                      trigger: dict[str, Any], source: str,
                      check_groq: bool = True) -> dict[str, Any]:
        symbol = settings.get("binance_symbol", "BTCUSDT")
        started = time.monotonic()
        try:
            datasets = datasets or self._fetch_datasets(symbol)
            mark = self.market.mark_price(symbol)
            snapshot = self._snapshot(datasets, mark, trigger, symbol=symbol)
            result = self._analyze(run=run, settings=settings, prompts=prompts,
                                   datasets=datasets, symbol=symbol, mark=mark, snapshot=snapshot)
            analysis = result["data"]
            attribution = {"provider": result["provider"], "model": result["model"],
                           "analysis_mode": result["analysis_mode"], "source": "automatic" if source != "manual" else "manual",
                           "raw_response": result["raw"], "text_snapshot": result["text_data"],
                           "chart_images": result["chart_metadata"]}
            trade = None
            pending_entry = None
            local_tz = ZoneInfo(safe_timezone_name(settings.get("timezone")))
            weekend = datetime.now(local_tz).weekday() >= 5
            block_weekend = bool(settings.get("avoid_weekends", False)) and weekend
            if analysis["signal"] in ("LONG", "SHORT"):
                # Automatic scans must agree with the Pine trigger. Manual actions deliberately
                # bypass the trigger gate, but still obey model validation and risk limits.
                expected_direction = trigger.get("direction") if source == "hourly_scan" else analysis["signal"]
                daily_limit_hit, daily_pnl, daily_loss_limit = self._daily_loss_guard(settings)
                if not bool(settings.get("auto_trading_enabled", True)):
                    self.db.log("INFO", "execution", "Execução automática pausada nas configurações",
                                run_id=run["id"])
                    self.telegram.send("⏸️ APEXPRIME — SINAL IDENTIFICADO, MAS NOVAS ENTRADAS ESTÃO PAUSADAS.\nA análise foi registrada; nenhuma posição foi aberta. MODO: SIMULAÇÃO")
                elif daily_limit_hit:
                    self.db.log("WARN", "risk_guard", "Entrada bloqueada pelo limite de perda diária",
                                run_id=run["id"], details={"today_pnl": daily_pnl, "loss_limit": daily_loss_limit})
                    self.telegram.send(f"🛑 APEXPRIME — LIMITE DE PERDA DIÁRIA\nPnL do dia: {daily_pnl:.4f} USDT\nLimite: -{daily_loss_limit:.4f} USDT\nNovas entradas pausadas até o próximo dia. MODO: SIMULAÇÃO")
                elif block_weekend:
                    self.db.log("INFO", "execution", "Entrada bloqueada: configuração evita trades no fim de semana",
                                run_id=run["id"])
                elif analysis.get("entry_type") == "IMEDIATA":
                    trade = self.executor.open_trade(analysis, run_id=run["id"], settings=settings,
                                                     trigger_direction=expected_direction,
                                                     mark_price=float(mark["markPrice"]),
                                                     attribution=attribution)
                else:
                    pending_entry = self.executor.create_pending_entry(
                        analysis, run_id=run["id"], settings=settings,
                        trigger_direction=expected_direction, attribution=attribution,
                    )
            elapsed = int((time.monotonic() - started) * 1000)
            self._update_run(run["id"], {
                "status": "completed", "signal": analysis["signal"],
                "ai_model": result["model"],
                "analysis_provider": result["provider"],
                "analysis_model": result["model"],
                "analysis_source": attribution["source"],
                "chart_source_type": result["analysis_mode"],
                "analysis_mode": result["analysis_mode"],
                "market_snapshot": snapshot,
                "chart_images": result["chart_metadata"],
                "apex_table": analysis,
                "ai_raw_response": result["raw"][:30000],
                "finished_at": iso_utc(), "duration_ms": elapsed,
            })
            self.db.log("INFO", "analysis", "Análise concluída",
                        run_id=run["id"], details={"provider": result["provider"], "model": result["model"],
                                                  "analysis_mode": result["analysis_mode"], "apex_table": analysis,
                                                  "trade_opened": bool(trade), "pending_entry_created": bool(pending_entry)})
            if analysis["signal"] == "NO_TRADE":
                self.telegram.send("⚪ APEXPRIME — NO TRADE\n" + analysis.get("analysis_summary", "Sem oportunidade operacional.")[:1500])
            elif pending_entry is not None:
                pass  # create_pending_entry already notified Telegram.
            elif trade is None:
                self.telegram.send("ℹ️ APEXPRIME — Análise concluída, mas nenhuma posição foi aberta.\n" +
                                   analysis.get("analysis_summary", "Verifique os logs do painel.")[:1200])
            if check_groq:
                self._health_check_groq(settings, snapshot, run["id"])
            return {"run_id": run["id"], "analysis": analysis,
                    "provider": result["provider"], "model": result["model"],
                    "analysis_mode": result["analysis_mode"],
                    "trade_opened": bool(trade), "pending_entry_created": bool(pending_entry)}
        except Exception as exc:
            message = clean_error(str(exc), self.config.gemini_api_key,
                                  self.config.chart_img_api_key, self.config.groq_api_key,
                                  self.config.openrouter_api_key, self.config.supabase_service_role_key,
                                  self.config.telegram_bot_token)
            self._update_run(run["id"], {
                "status": "failed", "finished_at": iso_utc(),
                "duration_ms": int((time.monotonic() - started) * 1000),
                "error_code": "ANALYSIS_FAILED", "error_message": message,
            })
            self.db.log("ERROR", "analysis", message, run_id=run["id"])
            self.telegram.send("🚨 APEXPRIME — ERRO NA ANÁLISE\n" + message[:1200])
            raise

    def process_queue(self, max_requests: int = 10) -> int:
        requests = self.db.select("run_requests", {"status": "eq.pending"},
                                  order="requested_at.asc", limit=max_requests)
        processed = 0
        for item in requests:
            claimed = self.db.update("run_requests", {
                "id": f"eq.{item['id']}", "status": "eq.pending",
            }, {"status": "processing", "started_at": iso_utc()})
            if not claimed:
                continue
            processed += 1
            try:
                settings = self.db.settings()
                settings["max_entry_deviation_pct"] = self.config.max_entry_deviation_pct
                settings["pending_entry_expiry_hours"] = self.config.pending_entry_expiry_hours
                request_type = item["request_type"]
                if request_type == "force_analysis":
                    result = self.run_manual_analysis()
                    result_json = result
                    self.db.update("run_requests", {"id": f"eq.{item['id']}"}, {
                        "status": "completed", "result": result_json,
                        "run_id": result["run_id"], "finished_at": iso_utc(),
                    })
                elif request_type == "close_open_trade":
                    count = self.executor.close_manual(settings)
                    self.db.update("run_requests", {"id": f"eq.{item['id']}"}, {
                        "status": "completed", "result": {"closed_trades": count},
                        "finished_at": iso_utc(),
                    })
                elif request_type == "close_trade":
                    trade_id = str((item.get("payload") or {}).get("trade_id", ""))
                    if not trade_id:
                        raise ValueError("Comando close_trade sem payload.trade_id")
                    closed = self.executor.close_trade_manual(trade_id, settings)
                    self.db.update("run_requests", {"id": f"eq.{item['id']}"}, {
                        "status": "completed", "result": {"closed": closed, "trade_id": trade_id},
                        "finished_at": iso_utc(),
                    })
                elif request_type == "cancel_pending_entry":
                    pending_id = str((item.get("payload") or {}).get("pending_id", ""))
                    if not pending_id:
                        raise ValueError("Comando cancel_pending_entry sem payload.pending_id")
                    cancelled = self.executor.cancel_pending_entry_manual(pending_id)
                    self.db.update("run_requests", {"id": f"eq.{item['id']}"}, {
                        "status": "completed", "result": {"cancelled": cancelled, "pending_id": pending_id},
                        "finished_at": iso_utc(),
                    })
                elif request_type == "manual_external_analysis":
                    result = self.run_manual_external_analysis(item.get("payload") or {})
                    self.db.update("run_requests", {"id": f"eq.{item['id']}"}, {
                        "status": "completed", "result": result, "run_id": result["run_id"],
                        "finished_at": iso_utc(),
                    })
                elif request_type == "export_text":
                    result = self.create_text_export(item.get("payload") or {})
                    self.db.update("run_requests", {"id": f"eq.{item['id']}"}, {
                        "status": "completed", "result": {"export_id": result.get("id"), "export_type": "TEXT_CHART"},
                        "finished_at": iso_utc(),
                    })
                elif request_type == "export_chart_images":
                    result = self.create_chart_export()
                    self.db.update("run_requests", {"id": f"eq.{item['id']}"}, {
                        "status": "completed", "result": {"export_id": result.get("id"), "export_type": "CHART_IMAGES"},
                        "finished_at": iso_utc(),
                    })
                elif request_type == "add_virtual_balance":
                    payload = item.get("payload") or {}
                    result = self.add_virtual_balance(
                        float(payload.get("amount", 0)),
                        str(payload.get("description") or "Adição manual de saldo virtual"),
                    )
                    self.db.update("run_requests", {"id": f"eq.{item['id']}"}, {
                        "status": "completed", "result": result, "finished_at": iso_utc(),
                    })
                elif request_type == "groq_report":
                    result = self.create_groq_report()
                    self.db.update("run_requests", {"id": f"eq.{item['id']}"}, {
                        "status": "completed", "result": result, "finished_at": iso_utc(),
                    })
                elif request_type == "run_tests":
                    result = self.run_service_tests()
                    self.db.update("run_requests", {"id": f"eq.{item['id']}"}, {
                        "status": "completed", "result": result, "finished_at": iso_utc(),
                    })
                else:
                    raise ValueError(f"Tipo de solicitação desconhecido: {request_type}")
            except Exception as exc:
                message = clean_error(str(exc), self.config.gemini_api_key,
                                      self.config.chart_img_api_key, self.config.groq_api_key,
                                      self.config.openrouter_api_key, self.config.supabase_service_role_key,
                                      self.config.telegram_bot_token)
                self.db.update("run_requests", {"id": f"eq.{item['id']}"}, {
                    "status": "failed", "error_message": message, "finished_at": iso_utc(),
                })
                self.db.log("ERROR", "queue", message)
                self.telegram.send("🚨 APEXPRIME — comando manual falhou\n" + message[:1200])
        return processed

    def _record_opportunity(self, symbol: str, candle: Candle, trigger: dict[str, Any],
                            settings: dict[str, Any]) -> None:
        row = {
            "symbol": symbol, "candle_open_time": candle.open_time.isoformat(),
            "direction": trigger.get("direction", "NONE"), "score": int(trigger.get("score", 0)),
            "bullish_score": int(trigger.get("bullish_score", 0)),
            "bearish_score": int(trigger.get("bearish_score", 0)),
            "volume_explosion": bool(trigger.get("volume_explosion")),
            "bull_sweep": bool(trigger.get("bull_sweep")),
            "bear_sweep": bool(trigger.get("bear_sweep")),
            "bull_displacement": bool(trigger.get("bull_displacement")),
            "bear_displacement": bool(trigger.get("bear_displacement")),
            "reason": trigger.get("reason"),
            "settings_snapshot": {
                "volume_multiplier": settings.get("trigger_volume_multiplier", 1.5),
                "sweep_length": settings.get("trigger_sweep_length", 16),
                "displacement_multiplier": settings.get("trigger_displacement_multiplier", 1.5),
                "cooldown": settings.get("trigger_cooldown", 3),
                "min_score": settings.get("trigger_min_score", 2),
            },
        }
        try:
            self.db.insert("opportunity_events", row)
        except Exception as exc:
            if "duplicate" not in str(exc).lower() and "unique" not in str(exc).lower():
                self.db.log("WARN", "opportunity", "Não foi possível registrar o evento do detector",
                            details={"error_type": type(exc).__name__})

    def publish_market_snapshot(self) -> None:
        """Publish fresh 1m candles and mark price for the PWA's live trade chart."""
        settings = self._runtime_settings()
        symbol = settings.get("binance_symbol", "BTCUSDT")
        mark = self.market.mark_price(symbol)
        candles = self.market.recent_closed_klines(symbol, "1m", 80)
        self.db.upsert("market_snapshots", {
            "symbol": symbol,
            "mark_price": float(mark.get("markPrice") or 0) or None,
            "candles": [{
                "time": c.open_time.isoformat(), "open": c.open, "high": c.high,
                "low": c.low, "close": c.close, "volume": c.volume,
            } for c in candles],
            "updated_at": iso_utc(),
        }, on_conflict="symbol")

    def _fetch_datasets_range(self, symbol: str, start: datetime, end: datetime) -> dict[str, list[Candle]]:
        result: dict[str, list[Candle]] = {}
        for label, interval in TIMEFRAMES:
            try:
                candles = self.market.klines(symbol, interval, limit=1000,
                                             start_time=start, end_time=end)
                result[label] = [c for c in candles if c.close_time <= end]
            except Exception as exc:
                self.db.log("WARN", "trade_review", f"Falha consultando candles {label} do período da operação",
                            details={"error_type": type(exc).__name__})
                result[label] = []
        return result

    def _on_trade_closed(self, trade: dict[str, Any]) -> None:
        """Create a Groq post-mortem and send trade context even if Groq is unavailable."""
        trade_id = trade["id"]
        self.db.update("trades", {"id": f"eq.{trade_id}"}, {"post_trade_review_status": "PROCESSING"})
        review_row = {
            "trade_id": trade_id,
            "analysis_provider": trade.get("analysis_provider"),
            "analysis_model": trade.get("analysis_model"),
            "analysis_raw_response": trade.get("analysis_raw_response"),
            "entry_text_snapshot": trade.get("entry_text_snapshot"),
            "result_category": trade.get("result_category"),
            "realized_pnl_net": trade.get("realized_pnl_net"),
            "review_status": "PROCESSING",
        }
        self.db.upsert("trade_reviews", review_row, on_conflict="trade_id")

        try:
            opened = datetime.fromisoformat(str(trade["opened_at"]).replace("Z", "+00:00"))
            closed = datetime.fromisoformat(str(trade.get("closed_at") or iso_utc()).replace("Z", "+00:00"))
            datasets = self._fetch_datasets_range(trade["symbol"], opened, closed)
            exit_text = candles_to_text(
                datasets, symbol=trade["symbol"], timezone_name="America/Sao_Paulo",
                rows_per_tf=120, reference_time=closed,
            )
        except Exception as exc:
            exit_text = (
                "Não foi possível recuperar parte ou todo o histórico de candles entre a entrada e a saída. "
                f"Erro técnico: {type(exc).__name__}. O resultado do trade continua válido no ledger."
            )
            self.db.log("WARN", "trade_review", "Falha montando snapshot de candles pós-trade",
                        details={"trade_id": trade_id, "error_type": type(exc).__name__})

        review_text = "Revisão Groq indisponível; análise original e contexto de mercado foram preservados."
        review_status = "ERROR"
        review_error = None
        latency = None
        if self.config.groq_api_key:
            try:
                groq = GroqAnalysisClient(
                    self.config.groq_api_key, self.db.settings().get("groq_model", "openai/gpt-oss-120b"),
                    self.config.groq_api_base,
                )
                result = groq.review_trade({
                    "trade": {k: trade.get(k) for k in (
                        "symbol", "direction", "entry_type", "entry_price", "initial_stop_loss",
                        "current_stop_loss", "tp1_price", "tp2_price", "exit_price", "close_reason",
                        "result_category", "initial_quantity", "leverage", "risk_pct", "tp1_hit",
                        "break_even_moved", "realized_pnl_gross", "realized_pnl_net", "entry_fee",
                        "exit_fees", "funding_paid", "opened_at", "closed_at",
                    )},
                    "analysis_provider": trade.get("analysis_provider"),
                    "analysis_model": trade.get("analysis_model"),
                    "analysis_mode": trade.get("analysis_mode"),
                    "analysis_source": trade.get("analysis_source"),
                    "original_ai_response": trade.get("analysis_raw_response"),
                    "market_text_from_entry": trade.get("entry_text_snapshot"),
                    "market_text_from_entry_until_exit": exit_text,
                })
                review_text = result["text"]
                review_status = "COMPLETED"
                latency = result.get("latency_ms")
            except Exception as exc:
                review_error = clean_error(str(exc), self.config.groq_api_key,
                                           self.config.openrouter_api_key, self.config.supabase_service_role_key)
                review_text = "Groq não conseguiu concluir a revisão desta operação. " + review_error[:700]
                self.db.log("WARN", "trade_review", "Groq indisponível para revisão; enviando contexto sem resumo de IA",
                            details={"trade_id": trade_id, "error": review_error[:500]})
        else:
            review_error = "GROQ_API_KEY ausente"

        self.db.update("trade_reviews", {"trade_id": f"eq.{trade_id}"}, {
            "exit_text_snapshot": exit_text, "groq_review": review_text,
            "review_status": review_status, "error_message": review_error,
            "completed_at": iso_utc(),
        })
        self.db.update("trades", {"id": f"eq.{trade_id}"}, {
            "post_trade_review_status": "COMPLETED" if review_status == "COMPLETED" else "ERROR",
        })

        net = float(trade.get("realized_pnl_net", 0) or 0)
        outcome = trade.get("result_category") or (
            "FULL_WIN" if net > 0 and trade.get("close_reason") == "TP2" else
            "PARTIAL_WIN" if net > 0 else "LOSS" if net < 0 else "BREAKEVEN"
        )
        outcome_label = {
            "FULL_WIN": "🟢 WIN COMPLETO", "PARTIAL_WIN": "🟢 WIN PARCIAL",
            "LOSS": "🔴 LOSS", "BREAKEVEN": "🟡 BREAK EVEN",
        }.get(outcome, outcome)
        summary = (
            f"{outcome_label} — APEXPRIME\n{trade['direction']} {trade['symbol']}\n"
            f"PnL líquido: {net:+.4f} USDT\nEntrada: {float(trade['entry_price']):.2f} · "
            f"Saída: {float(trade.get('exit_price') or 0):.2f}\n"
            f"Motivo: {trade.get('close_reason')}\nIA: {trade.get('analysis_provider')} / "
            f"{trade.get('analysis_model') or '—'}\n"
            f"Gráfico: {trade.get('analysis_mode') or '—'} · Origem: {trade.get('analysis_source') or 'automatic'}\n"
            f"Revisão Groq ({latency if latency is not None else 'N/D'} ms):\n{review_text}"
        )
        # The first short WIN/LOSS notification is sent by the execution engine at close.
        # These follow-up messages always include the original AI analysis and market context,
        # even if Groq is down, so a provider outage never hides the trade evidence.
        self.telegram.send_long(summary)
        if trade.get("analysis_raw_response"):
            self.telegram.send_long("📄 ANÁLISE ORIGINAL DA IA / ANÁLISE EXTERNA\n" + str(trade["analysis_raw_response"]))
        self.telegram.send_long("📊 GRÁFICO EM TEXTO — DO CONTEXTO DA ENTRADA ATÉ A SAÍDA\n" + exit_text)
        self.db.log("INFO", "trade_review", "Pacote pós-trade enviado ao Telegram",
                    details={"trade_id": trade_id, "review_status": review_status,
                             "result_category": outcome})

    def process_pending_trade_reviews(self, limit: int = 3) -> None:
        pending = self.db.select("trades", {
            "status": "eq.CLOSED", "post_trade_review_status": "eq.PENDING",
        }, order="closed_at.asc", limit=limit)
        for trade in pending:
            try:
                self._on_trade_closed(trade)
            except Exception:
                log.exception("Falha retomando revisão do trade %s", trade.get("id"))

    def run_manual_external_analysis(self, payload: dict[str, Any]) -> dict[str, Any]:
        raw = str(payload.get("raw_response") or "").strip()
        if not payload.get("confirmed"):
            raise ValueError("A análise externa precisa ser confirmada no painel antes de entrar na fila")
        if not raw or len(raw) > 60000:
            raise ValueError("Texto externo vazio ou maior que 60.000 caracteres")
        analysis = validate_apex_table(extract_json_object(raw))
        settings = self._runtime_settings()
        symbol = settings.get("binance_symbol", "BTCUSDT")
        datasets = self._fetch_datasets(symbol)
        mark = self.market.mark_price(symbol)
        trigger = {"direction": analysis["signal"] if analysis["signal"] in ("LONG", "SHORT") else "NONE",
                   "score": 0, "reason": "Análise manual externa confirmada pelo administrador"}
        run = self._create_run(source="manual_external", settings=settings, trigger=trigger, candle=None)
        if not run:
            raise RuntimeError("Não foi possível registrar a análise externa")
        text_data = candles_to_text(datasets, symbol=symbol,
                                    timezone_name=safe_timezone_name(settings.get("timezone")), rows_per_tf=60)
        chart_mode = payload.get("chart_type") if payload.get("chart_type") in ("chart_img", "text") else "text"
        provider_label = str(payload.get("external_provider") or "EXTERNAL").strip()[:60]
        model_label = str(payload.get("external_model") or "Análise externa manual").strip()[:120]
        attribution = {"provider": "EXTERNAL", "model": f"{provider_label}: {model_label}",
                       "analysis_mode": chart_mode, "source": "manual_external",
                       "raw_response": raw, "text_snapshot": text_data, "chart_images": []}
        trade = None
        pending_entry = None
        if analysis["signal"] in ("LONG", "SHORT"):
            if not settings.get("auto_trading_enabled", True):
                raise RuntimeError("Novas entradas estão pausadas nas configurações")
            daily_hit, daily_pnl, daily_limit = self._daily_loss_guard(settings)
            if daily_hit:
                raise RuntimeError(f"Limite de perda diária atingido ({daily_pnl:.4f} / -{daily_limit:.4f} USDT)")
            local_tz = ZoneInfo(safe_timezone_name(settings.get("timezone")))
            if settings.get("avoid_weekends") and datetime.now(local_tz).weekday() >= 5:
                raise RuntimeError("Entradas bloqueadas pela configuração de finais de semana")
            if analysis.get("entry_type") == "IMEDIATA":
                trade = self.executor.open_trade(analysis, run_id=run["id"], settings=settings,
                                                 trigger_direction=analysis["signal"],
                                                 mark_price=float(mark["markPrice"]), attribution=attribution)
            else:
                pending_entry = self.executor.create_pending_entry(
                    analysis, run_id=run["id"], settings=settings,
                    trigger_direction=analysis["signal"], attribution=attribution)
            if not trade and not pending_entry:
                raise RuntimeError("A APEX_TABLE foi reconhecida, mas o gerenciamento de risco bloqueou a entrada")
        self._update_run(run["id"], {
            "status": "completed", "signal": analysis["signal"],
            "analysis_provider": "EXTERNAL", "analysis_model": attribution["model"],
            "ai_model": attribution["model"], "analysis_source": "manual_external",
            "analysis_mode": chart_mode, "chart_source_type": chart_mode,
            "market_snapshot": self._snapshot(datasets, mark, trigger, symbol),
            "apex_table": analysis, "ai_raw_response": raw[:30000],
            "finished_at": iso_utc(),
        })
        self.db.insert("ai_requests", {
            "run_id": run["id"], "provider": "EXTERNAL", "model": attribution["model"],
            "analysis_mode": chart_mode, "success": True,
            "metadata": {"origin": "manual_external", "confirmed_in_pwa": True},
        })
        self.db.log("INFO", "manual_external", "Análise externa reconhecida e processada",
                    run_id=run["id"], details={"provider": provider_label, "model": model_label,
                                               "trade_opened": bool(trade), "pending": bool(pending_entry)})
        self.telegram.send(f"🧾 APEXPRIME — ANÁLISE EXTERNA REGISTRADA\n{analysis['signal']} · {provider_label} / {model_label}\nOrigem: manual externa · MODO: SIMULAÇÃO")
        return {"run_id": run["id"], "analysis": analysis,
                "trade_opened": bool(trade), "pending_entry_created": bool(pending_entry),
                "provider": "EXTERNAL", "model": attribution["model"]}

    def create_text_export(self, payload: dict[str, Any]) -> dict[str, Any]:
        settings = self._runtime_settings()
        symbol = str(payload.get("symbol") or settings.get("binance_symbol", "BTCUSDT")).upper()
        raw_reference = payload.get("reference_at")
        if raw_reference:
            reference = datetime.fromisoformat(str(raw_reference).replace("Z", "+00:00"))
            if reference.tzinfo is None:
                reference = reference.replace(tzinfo=ZoneInfo(safe_timezone_name(settings.get("timezone"))))
            reference = reference.astimezone(timezone.utc)
        else:
            reference = utc_now()
        datasets = {
            label: self.market.historical_closed_klines(symbol, interval, reference, limit=200)
            for label, interval in TIMEFRAMES
        }
        output = candles_to_text(datasets, symbol=symbol,
                                timezone_name=safe_timezone_name(settings.get("timezone")),
                                rows_per_tf=200, reference_time=reference)
        rows = self.db.insert("apex_exports", {
            "export_type": "TEXT_CHART", "status": "COMPLETED", "symbol": symbol,
            "reference_at": reference.isoformat(), "content_text": output,
        })
        return rows[0] if rows else {"content_text": output}

    def create_chart_export(self) -> dict[str, Any]:
        settings = self._runtime_settings()
        if not self.config.chart_img_api_key:
            raise RuntimeError("CHART_IMG_API_KEY não configurada")
        client = ChartImgClient(self.config.chart_img_api_key, self.config.chart_img_api_base)
        images = client.get_five_charts(safe_timezone_name(settings.get("timezone")),
                                        symbol=self.config.chart_img_symbol)
        export_id = str(__import__("uuid").uuid4())
        files = []
        for item in images:
            ext = {"image/png": "png", "image/jpeg": "jpg", "image/webp": "webp"}.get(item["mime_type"], "png")
            url = self.db.upload_public_image("apexprime-charts", f"exports/{export_id}/{item['timeframe'].lower()}.{ext}",
                                              item["data"], item["mime_type"])
            files.append({"timeframe": item["timeframe"], "url": url, "mime_type": item["mime_type"],
                          "bytes": len(item["data"]), "width": 800, "height": 600})
        rows = self.db.insert("apex_exports", {
            "export_type": "CHART_IMAGES", "status": "COMPLETED",
            "symbol": settings.get("binance_symbol", "BTCUSDT"), "reference_at": iso_utc(),
            "files": files,
        })
        return rows[0] if rows else {"files": files}

    def add_virtual_balance(self, amount: float, description: str = "Adição manual de saldo virtual") -> dict[str, Any]:
        amount = float(amount)
        if not 0 < amount <= 100000:
            raise ValueError("A quantia deve ser maior que zero e até 100.000 USDT")
        account = self.db.active_account()
        new_balance = float(account["balance"]) + amount
        self.db.update("paper_accounts", {"id": f"eq.{account['id']}"}, {"balance": new_balance})
        self.db.insert("balance_ledger", {
            "account_id": account["id"], "event_type": "MANUAL_ADJUSTMENT",
            "amount": amount, "balance_after": new_balance,
            "description": description[:200], "metadata": {"source": "pwa_manual_deposit"},
        })
        self.db.log("INFO", "balance", "Saldo virtual adicionado",
                    details={"amount": amount, "balance_after": new_balance})
        self.telegram.send(f"💰 APEXPRIME — SALDO VIRTUAL ADICIONADO\nValor: +{amount:.4f} USDT\nNovo saldo: {new_balance:.4f} USDT")
        return {"added": amount, "balance": new_balance}

    def create_groq_report(self) -> dict[str, Any]:
        if not self.config.groq_api_key:
            raise RuntimeError("GROQ_API_KEY não configurada")
        settings = self._runtime_settings()
        account = self.db.active_account()
        trades = self.db.select("trades", {}, order="opened_at.desc", limit=30)
        runs = self.db.select("system_runs", {}, order="created_at.desc", limit=25)
        logs = self.db.select("apex_logs", {}, order="created_at.desc", limit=60)
        checks = self.db.select("service_checks", {}, order="checked_at.desc", limit=20)
        devices = self.db.select("apex_devices", {}, limit=3)
        snapshot = {
            "account": {"balance": account.get("balance"), "initial_balance": account.get("initial_balance"),
                        "realized_pnl": account.get("realized_pnl"), "total_fees": account.get("total_fees"),
                        "total_funding": account.get("total_funding")},
            "device": devices[0] if devices else None,
            "recent_trades": [{k: t.get(k) for k in ("direction", "status", "analysis_provider", "analysis_model",
                "analysis_mode", "analysis_source", "entry_price", "exit_price", "realized_pnl_net",
                "result_category", "close_reason", "opened_at", "closed_at")} for t in trades],
            "recent_runs": [{k: r.get(k) for k in ("status", "source", "analysis_provider", "analysis_model",
                "analysis_mode", "signal", "error_message", "created_at")} for r in runs],
            "recent_logs": [{k: l.get(k) for k in ("level", "component", "message", "created_at")} for l in logs],
            "service_checks": [{k: c.get(k) for k in ("service", "status", "message", "checked_at")} for c in checks],
            "settings": {k: settings.get(k) for k in ("analysis_mode", "ai_provider_strategy", "fixed_ai_provider",
                "groq_health_interval_hours", "risk_per_trade_pct", "max_leverage", "max_daily_loss_pct")},
        }
        report = self.db.insert("groq_reports", {"status": "PROCESSING", "snapshot": snapshot})
        report_id = report[0]["id"] if report else None
        model = settings.get("groq_model", "openai/gpt-oss-120b")
        prompt = (
            "Gere um relatório operacional objetivo em português para o ApexPrime. Descreva o que ocorreu por último, "
            "se o worker e Redmi parecem saudáveis, resultados recentes, desempenho geral dos trades, distribuição "
            "por provedor/modelo, falhas de serviços, riscos e próximos pontos a acompanhar. Não recomende trades, "
            "não invente valores e diferencie dados ausentes de problemas. Dados:\\n" + str(snapshot)[:20000]
        )
        try:
            result = GroqAnalysisClient(self.config.groq_api_key, model, self.config.groq_api_base).analyze(prompt)
            self.db.update("groq_reports", {"id": f"eq.{report_id}"}, {
                "status": "COMPLETED", "report_text": result["text"], "completed_at": iso_utc(),
            })
            return {"id": report_id, "report_text": result["text"]}
        except Exception as exc:
            message = clean_error(str(exc), self.config.groq_api_key)
            if report_id:
                self.db.update("groq_reports", {"id": f"eq.{report_id}"}, {
                    "status": "ERROR", "error_message": message, "completed_at": iso_utc(),
                })
            raise

    def run_service_tests(self) -> dict[str, Any]:
        results: dict[str, Any] = {}
        settings = self.db.settings()
        def record(service: str, fn) -> None:
            started = time.monotonic()
            try:
                details = fn() or {}
                latency = int((time.monotonic() - started) * 1000)
                self.db.service_check(service, "OK", "Teste concluído", latency_ms=latency,
                                      details=details if isinstance(details, dict) else {"result": str(details)[:500]})
                results[service] = {"status": "OK", "latency_ms": latency}
            except Exception as exc:
                message = clean_error(str(exc), self.config.gemini_api_key,
                                      self.config.chart_img_api_key, self.config.groq_api_key,
                                      self.config.openrouter_api_key, self.config.supabase_service_role_key)
                results[service] = {"status": "ERROR", "message": message}
                try:
                    self.db.service_check(service, "ERROR", message)
                except Exception:
                    # A failed Supabase connection must not prevent remaining providers
                    # from being tested; the console/Actions log remains the fallback.
                    log.exception("Não foi possível persistir resultado do teste %s", service)

        record("BINANCE", lambda: self.market.health())
        record("SUPABASE", lambda: {"settings_loaded": bool(self.db.settings())})
        def text_test():
            symbol = settings.get("binance_symbol", "BTCUSDT")
            sample = {label: self.market.recent_closed_klines(symbol, interval, 40)
                      for label, interval in TIMEFRAMES}
            generated = candles_to_text(sample, symbol=symbol,
                                        timezone_name=settings.get("timezone", "America/Sao_Paulo"))
            return {"characters": len(generated), "timeframes": list(sample)}
        record("TEXT_GENERATOR", text_test)
        if self.config.gemini_api_key:
            def gemini_test():
                model = settings.get("gemini_model", "gemini-4-hydrogen")
                response = GeminiClient(self.config.gemini_api_key, model,
                                        self.config.gemini_api_base).analyze(
                    "Responda apenas: APEXPRIME GEMINI OK."
                )
                return {"model": model, "latency_ms": response["latency_ms"],
                        "response": response["text"][:200]}
            record("GEMINI", gemini_test)
        else:
            results["GEMINI"] = {"status": "WARN", "message": "GEMINI_API_KEY ausente"}
        if self.config.groq_api_key:
            record("GROQ", lambda: GroqHealthClient(
                self.config.groq_api_key, settings.get("groq_model", "openai/gpt-oss-120b"),
                self.config.groq_api_base).check({"test": "health"}))
        else:
            results["GROQ"] = {"status": "WARN", "message": "GROQ_API_KEY ausente"}
        if self.config.openrouter_api_key:
            def openrouter_test():
                response = OpenRouterClient(self.config.openrouter_api_key,
                    settings.get("openrouter_model", "openrouter/free"), self.config.openrouter_api_base).analyze(
                    "Responda apenas: APEXPRIME OPENROUTER OK.")
                return {"model": response.get("model"), "latency_ms": response.get("latency_ms"),
                        "response": response["text"][:200]}
            record("OPENROUTER", openrouter_test)
        else:
            results["OPENROUTER"] = {"status": "WARN", "message": "OPENROUTER_API_KEY ausente"}
            try:
                self.db.service_check("OPENROUTER", "WARN", "OPENROUTER_API_KEY ausente")
            except Exception:
                pass
        if self.config.chart_img_api_key:
            def chart_test():
                data, mime = ChartImgClient(self.config.chart_img_api_key,
                                            self.config.chart_img_api_base).get_chart(
                    "1h", symbol=self.config.chart_img_symbol,
                    timezone_name=settings.get("timezone", "America/Sao_Paulo"))
                return {"mime_type": mime, "bytes": len(data), "symbol": self.config.chart_img_symbol}
            record("CHART_IMG", chart_test)
        else:
            results["CHART_IMG"] = {"status": "WARN", "message": "Chart IMG não selecionado ou sem chave"}
            try:
                self.db.service_check("CHART_IMG", "WARN", "Chart IMG não configurado")
            except Exception:
                pass
        if self.config.telegram_bot_token and self.config.telegram_chat_id:
            def telegram_test():
                sent = self.telegram.send("✅ ApexPrime: teste de conexão Telegram concluído (paper trading).")
                if not sent:
                    raise RuntimeError("Telegram não confirmou o envio da mensagem de teste")
                return {"sent": True}
            record("TELEGRAM", telegram_test)
        else:
            results["TELEGRAM"] = {"status": "WARN", "message": "Telegram sem configuração"}
        return results
