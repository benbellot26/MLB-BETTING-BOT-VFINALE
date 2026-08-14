from __future__ import annotations
import os
from pathlib import Path
VERSION="11.5-standalone-all-markets-v1"
LIVE_FILE=Path(os.getenv("V11_LIVE_FILE",os.getenv("V11_3_LIVE_FILE","data/v11_live.jsonl")))
REPORT_FILE=Path(os.getenv("V11_REPORT_FILE",os.getenv("V11_3_LIVE_REPORT","data/v11_live_report.json")))
MIN_EV=float(os.getenv("V11_MIN_EV",os.getenv("MIN_EV","0.03")) or .03)
MIN_EDGE=float(os.getenv("V11_MIN_EDGE",os.getenv("MIN_EDGE","0.025")) or .025)
PRICE_SAFETY_MARGIN=float(os.getenv("V11_PRICE_SAFETY_MARGIN","0.01") or .01)
MAX_OFFICIAL_BETS=int(os.getenv("V11_MAX_OFFICIAL_BETS","3") or 3)
MAX_DAILY_UNITS=float(os.getenv("V11_MAX_DAILY_UNITS","4") or 4)
COMBO_UNITS=float(os.getenv("V11_COMBO_UNITS","0.5") or .5)
MIN_COMBO_EV=float(os.getenv("V11_MIN_COMBO_EV","0.04") or .04)
OFFICIAL_SCORE_THRESHOLDS=(72.0,74.0,76.0)
