from __future__ import annotations

import argparse
import json
import logging
import sys

from .config import Config
from .engine import ApexEngine
from .utils import setup_logging


def main() -> int:
    parser = argparse.ArgumentParser(description="ApexPrime — worker de paper trading BTCUSDT")
    parser.add_argument(
        "mode", choices=["hourly", "queue", "tests", "daemon", "device"],
        help="hourly=consulta candle 1H; queue=fila; tests=serviços; daemon=servidor contínuo; device=telemetria única",
    )
    args = parser.parse_args()
    try:
        config = Config.from_env(require_all=False)
        setup_logging(config.log_level)
        config.validate_paper_only()

        if args.mode == "daemon":
            from .daemon import run as run_daemon
            return run_daemon()

        engine = ApexEngine(config)
        if args.mode == "hourly":
            engine.run_hourly()
        elif args.mode == "queue":
            count = engine.process_queue()
            logging.getLogger("apexprime").info("Solicitações processadas: %s", count)
        elif args.mode == "device":
            from .device import DeviceReporter
            from .notify import TelegramNotifier
            reporter = DeviceReporter(
                engine.db,
                TelegramNotifier(config.telegram_bot_token, config.telegram_chat_id),
                config,
            )
            try:
                reporter.announce_start()
                snapshot = reporter.publish(heartbeat=True, telemetry=True)
                print(json.dumps(snapshot, ensure_ascii=False, indent=2, default=str))
            finally:
                reporter.close()
        else:
            print(engine.run_service_tests())
        return 0
    except Exception:
        logging.getLogger("apexprime").exception("Execução ApexPrime falhou")
        return 1


if __name__ == "__main__":
    sys.exit(main())
