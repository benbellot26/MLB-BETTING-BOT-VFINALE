#!/usr/bin/env python3
from v11.backtest import write_report

if __name__ == "__main__":
    import json
    report = write_report()
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
