from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

from .analysis import (ChartImgClient, GeminiClient, GroqHealthClient,
                      candles_to_text, load_prompt, TIMEFRAMES)
from .config import Config
from .db import SupabaseREST
from .execution import PaperExecutor
from .market import BinanceFutures, Candle
from .notify import TelegramNotifier
from .risk import validate_apex_table
from .strategy import detect_latest_trigger, indicators
from .utils import clean_error, iso_utc, utc_now, extract_json_object

log = logging.getLogger("apexprime.engine")


class ApexEngine:
    def __init__(self, config: Config):
        config.validate_paper_only()
        self.config = config
        self.db = SupabaseREST(config.supabase_url, config.supabase_service_role_key)
        self.market = BinanceFutures(config.binance_fapi_base)
        self.telegram = TelegramNotifier(config.telegram_bot_token, config.telegram_chat_id)
        self.executor = PaperExecutor(self.db, self.market, self.telegram.send)

    def _fetch_datasets(self, symbol: str) -> dict[str, list[Candle]]:
        limits = {"1D": 90, "4H": 100, "1H": 100, "15M": 100, "5M": 100}
        return {
            label: self.market.recent_closed_klines(symbol, interval, limits[label])
            for label, interval in TIMEFRAMES
        }

    @staticmethod
    def _snapshot(datasets: dict[str, list[Candle]], mark: dict[str, Any],
                  trigger: dict[str, Any]) -> dict[str, Any]:
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
        return {"symbol": "BTCUSDT", "mark_price": mark.get("markPrice"),
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

    def _analyze(self, *, run: dict[str, Any], settings: dict[str, Any], prompts: dict[str, Any],
                 datasets: dict[str, list[Candle]], symbol: str,
                 mark: dict[str, Any], snapshot: dict[str, Any]) -> dict[str, Any]:
        mode = settings["analysis_mode"]
        model = settings.get("gemini_model", "gemini-4-hydrogen")
        timezone_name = settings.get("timezone", "America/Sao_Paulo")
        images: list[dict[str, Any]] = []
        text_data: str | None = None
        chart_metadata: list[dict[str, Any]] = []

        if mode == "chart_img":
            if not self.config.chart_img_api_key:
                raise RuntimeError("CHART_IMG_API_KEY ausente; modo atual é Chart IMG")
            chart_client = ChartImgClient(self.config.chart_img_api_key, self.config.chart_img_api_base)
            images = chart_client.get_five_charts(timezone_name)
            for item in images:
                ext = {"image/png": "png", "image/jpeg": "jpg", "image/webp": "webp"}.get(
                    item["mime_type"], "png"
                )
                object_path = f"{run['id']}/{item['timeframe'].lower()}.{ext}"
                metadata = {"timeframe": item["timeframe"], "mime_type": item["mime_type"],
                            "bytes": len(item["data"])}
                try:
                    metadata["url"] = self.db.upload_public_image(
                        "apexprime-charts", object_path, item["data"], item["mime_type"]
                    )
                except Exception as storage_exc:
                    # Image delivery to Gemini must still work if optional history storage
                    # is temporarily unavailable. The run log will surface missing URLs.
                    metadata["storage_error"] = clean_error(
                        str(storage_exc), self.config.supabase_service_role_key
                    )[:400]
                    self.db.log("WARN", "chart_storage", "Não foi possível persistir imagem do gráfico",
                                run_id=run["id"], details={"timeframe": item["timeframe"],
                                                           "error": metadata["storage_error"]})
                chart_metadata.append(metadata)
            prompt = load_prompt(prompts.get("custom_chart_img_prompt"), "default-chart-img.md")
        elif mode == "text":
            text_data = candles_to_text(datasets, symbol=symbol, timezone_name=timezone_name)
            prompt = load_prompt(prompts.get("custom_text_prompt"), "default-text.md")
        else:
            raise RuntimeError(f"Modo de análise desconhecido: {mode}")

        client = GeminiClient(self.config.gemini_api_key, model, self.config.gemini_api_base)
        try:
            result = client.analyze(prompt, text_data=text_data, images=images)
            data = validate_apex_table(extract_json_object(result["text"]))
            self._record_gemini(run_id=run["id"], model=model, mode=mode, success=True,
                                prompt_chars=len(prompt) + (len(text_data) if text_data else 0),
                                latency_ms=result["latency_ms"], usage=result)
            return {
                "data": data, "raw": result["text"], "latency_ms": result["latency_ms"],
                "chart_metadata": chart_metadata,
                "text_chars": len(text_data) if text_data else None,
                "usage": {k: result.get(k) for k in ("input_tokens", "output_tokens", "total_tokens")},
            }
        except Exception as exc:
            self._record_gemini(run_id=run["id"], model=model, mode=mode, success=False,
                                prompt_chars=len(prompt) + (len(text_data) if text_data else 0),
                                error=str(exc))
            raise

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

    def run_hourly(self) -> None:
        settings = self.db.settings()
        prompts = self.db.prompts()
        settings["max_entry_deviation_pct"] = self.config.max_entry_deviation_pct
        settings["pending_entry_expiry_hours"] = self.config.pending_entry_expiry_hours
        symbol = settings.get("binance_symbol", "BTCUSDT")
        # Process pending setups first, then manage any positions that were already open
        # or have just been filled from a pending setup.
        self.executor.monitor_pending_entries(settings)
        self.executor.monitor_open_trades(settings)
        candles = self.market.recent_closed_klines(symbol, "1h", 120)
        trigger_signal = detect_latest_trigger(candles)
        trigger = trigger_signal.to_dict()
        snapshot = {"trigger": trigger}
        if not candles:
            raise RuntimeError("A Binance não retornou candles 1H fechados")
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
            self._health_check_groq(settings, snapshot, run["id"])
            return
        self._run_analysis(run=run, settings=settings, prompts=prompts,
                           datasets=None, trigger=trigger, source="hourly_scan")

    def run_manual_analysis(self) -> dict[str, Any]:
        settings = self.db.settings()
        prompts = self.db.prompts()
        settings["max_entry_deviation_pct"] = self.config.max_entry_deviation_pct
        settings["pending_entry_expiry_hours"] = self.config.pending_entry_expiry_hours
        symbol = settings.get("binance_symbol", "BTCUSDT")
        candles = self.market.recent_closed_klines(symbol, "1h", 120)
        signal = detect_latest_trigger(candles)
        trigger = signal.to_dict()
        run = self._create_run(source="manual", settings=settings, trigger=trigger, candle=None)
        if not run:
            raise RuntimeError("Não foi possível criar execução manual")
        return self._run_analysis(run=run, settings=settings, prompts=prompts,
                                  datasets=None, trigger=trigger, source="manual")

    def _run_analysis(self, *, run: dict[str, Any], settings: dict[str, Any],
                      prompts: dict[str, Any], datasets: dict[str, list[Candle]] | None,
                      trigger: dict[str, Any], source: str) -> dict[str, Any]:
        symbol = settings.get("binance_symbol", "BTCUSDT")
        started = time.monotonic()
        try:
            datasets = datasets or self._fetch_datasets(symbol)
            mark = self.market.mark_price(symbol)
            snapshot = self._snapshot(datasets, mark, trigger)
            result = self._analyze(run=run, settings=settings, prompts=prompts,
                                   datasets=datasets, symbol=symbol, mark=mark, snapshot=snapshot)
            analysis = result["data"]
            trade = None
            pending_entry = None
            try:
                local_tz = ZoneInfo(settings.get("timezone", "America/Sao_Paulo"))
            except Exception:
                local_tz = ZoneInfo("America/Sao_Paulo")
            weekend = datetime.now(local_tz).weekday() >= 5
            block_weekend = bool(settings.get("avoid_weekends", False)) and weekend
            if analysis["signal"] in ("LONG", "SHORT"):
                # Automatic scans must agree with the Pine trigger. Manual actions deliberately
                # bypass the trigger gate, but still obey model validation and risk limits.
                expected_direction = trigger.get("direction") if source == "hourly_scan" else analysis["signal"]
                if block_weekend:
                    self.db.log("INFO", "execution", "Entrada bloqueada: configuração evita trades no fim de semana",
                                run_id=run["id"])
                elif analysis.get("entry_type") == "IMEDIATA":
                    trade = self.executor.open_trade(analysis, run_id=run["id"], settings=settings,
                                                     trigger_direction=expected_direction,
                                                     mark_price=float(mark["markPrice"]))
                else:
                    pending_entry = self.executor.create_pending_entry(
                        analysis, run_id=run["id"], settings=settings,
                        trigger_direction=expected_direction,
                    )
            elapsed = int((time.monotonic() - started) * 1000)
            self._update_run(run["id"], {
                "status": "completed", "signal": analysis["signal"],
                "ai_model": settings.get("gemini_model", "gemini-4-hydrogen"),
                "market_snapshot": snapshot,
                "chart_images": result["chart_metadata"],
                "apex_table": analysis,
                "ai_raw_response": result["raw"][:30000],
                "finished_at": iso_utc(), "duration_ms": elapsed,
            })
            self.db.log("INFO", "analysis", "Análise Gemini concluída",
                        run_id=run["id"], details={"apex_table": analysis,
                                                  "trade_opened": bool(trade),
                                                  "pending_entry_created": bool(pending_entry)})
            if analysis["signal"] == "NO_TRADE":
                self.telegram.send("⚪ APEXPRIME — NO TRADE\n" + analysis.get("analysis_summary", "Sem oportunidade operacional.")[:1500])
            elif pending_entry is not None:
                pass  # create_pending_entry already notified Telegram.
            elif trade is None:
                self.telegram.send("ℹ️ APEXPRIME — Análise concluída, mas nenhuma posição foi aberta.\n" +
                                   analysis.get("analysis_summary", "Verifique os logs do painel.")[:1200])
            self._health_check_groq(settings, snapshot, run["id"])
            return {"run_id": run["id"], "analysis": analysis,
                    "trade_opened": bool(trade), "pending_entry_created": bool(pending_entry)}
        except Exception as exc:
            message = clean_error(str(exc), self.config.gemini_api_key,
                                  self.config.chart_img_api_key, self.config.groq_api_key,
                                  self.config.supabase_service_role_key, self.config.telegram_bot_token)
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
                                      self.config.supabase_service_role_key, self.config.telegram_bot_token)
                self.db.update("run_requests", {"id": f"eq.{item['id']}"}, {
                    "status": "failed", "error_message": message, "finished_at": iso_utc(),
                })
                self.db.log("ERROR", "queue", message)
                self.telegram.send("🚨 APEXPRIME — comando manual falhou\n" + message[:1200])
        return processed

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
                                      self.config.supabase_service_role_key)
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
        if settings.get("groq_enabled") and self.config.groq_api_key:
            record("GROQ", lambda: GroqHealthClient(
                self.config.groq_api_key, settings.get("groq_model", "openai/gpt-oss-120b"),
                self.config.groq_api_base).check({"test": "health"}))
        else:
            results["GROQ"] = {"status": "WARN", "message": "Groq desativado ou sem chave"}
        if settings.get("analysis_mode") == "chart_img" and self.config.chart_img_api_key:
            def chart_test():
                data, mime = ChartImgClient(self.config.chart_img_api_key,
                                            self.config.chart_img_api_base).get_chart("1h",
                                            timezone_name=settings.get("timezone", "America/Sao_Paulo"))
                return {"mime_type": mime, "bytes": len(data)}
            record("CHART_IMG", chart_test)
        else:
            results["CHART_IMG"] = {"status": "WARN", "message": "Chart IMG não selecionado ou sem chave"}
        if self.config.telegram_bot_token and self.config.telegram_chat_id:
            record("TELEGRAM", lambda: {"sent": self.telegram.send("✅ ApexPrime: teste de conexão Telegram concluído (paper trading).")})
        else:
            results["TELEGRAM"] = {"status": "WARN", "message": "Telegram sem configuração"}
        return results
