from __future__ import annotations

import json

from .v123_runtime import activate

activate()

from . import backtest


if __name__ == "__main__":
    print(json.dumps(backtest.write_report(), ensure_ascii=False, indent=2, sort_keys=True))
