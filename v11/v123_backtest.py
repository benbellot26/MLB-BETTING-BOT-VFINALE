from __future__ import annotations

import json

from .methodology_v123 import install

install()

from . import backtest


if __name__ == "__main__":
    print(json.dumps(backtest.write_report(), ensure_ascii=False, indent=2, sort_keys=True))
