from __future__ import annotations

import argparse
import logging
import sys

from .config import Config
from .engine import ApexEngine
from .utils import setup_logging


def main() -> int:
    parser = argparse.ArgumentParser(description="ApexPrime — worker de paper trading BTCUSDT")
    parser.add_argument("mode", choices=["hourly", "queue", "tests"],
                        help="hourly=scan/gestão; queue=comandos manuais; tests=integrações")
    args = parser.parse_args()
    try:
        config = Config.from_env(require_all=False)
        setup_logging(config.log_level)
        config.validate_paper_only()
        engine = ApexEngine(config)
        if args.mode == "hourly":
            engine.run_hourly()
        elif args.mode == "queue":
            count = engine.process_queue()
            logging.getLogger("apexprime").info("Solicitações processadas: %s", count)
        else:
            print(engine.run_service_tests())
        return 0
    except Exception:
        logging.getLogger("apexprime").exception("Execução ApexPrime falhou")
        return 1


if __name__ == "__main__":
    sys.exit(main())
