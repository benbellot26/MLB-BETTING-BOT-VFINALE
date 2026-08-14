from __future__ import annotations
import os
from pathlib import Path
VERSION="11.5-standalone-all-markets-v3"
LIVE_FILE=Path(os.getenv("V11_LIVE_FILE",os.getenv("V11_3_LIVE_FILE","data/v11_3_live.jsonl")))
REPORT_FILE=Path(os.getenv("V11_REPORT_FILE",os.getenv("V11_3_LIVE_REPORT","data/v11_3_live_report.json")))
MIN_EV=float(os.getenv("V11_MIN_EV",os.getenv("MIN_EV","0.03")) or .03)
MIN_EDGE=float(os.getenv("V11_MIN_EDGE",os.getenv("MIN_EDGE","0.025")) or .025)
PRICE_SAFETY_MARGIN=float(os.getenv("V11_PRICE_SAFETY_MARGIN","0.01") or .01)
MAX_OFFICIAL_BETS=int(os.getenv("V11_MAX_OFFICIAL_BETS","3") or 3)
MAX_DAILY_UNITS=float(os.getenv("V11_MAX_DAILY_UNITS","4") or 4)
COMBO_UNITS=float(os.getenv("V11_COMBO_UNITS","0.5") or .5)
MIN_COMBO_EV=float(os.getenv("V11_MIN_COMBO_EV","0.04") or .04)
OFFICIAL_SCORE_THRESHOLDS=(72.0,74.0,76.0)
RUN_DISPERSION=float(os.getenv("V11_RUN_DISPERSION","7.5") or 7.5)
MAX_RUNS_MATRIX=int(os.getenv("V11_MAX_RUNS_MATRIX","22") or 22)
SHARP_WEIGHT_1=float(os.getenv("V11_SHARP_WEIGHT_1","0.12") or .12)
SHARP_WEIGHT_2=float(os.getenv("V11_SHARP_WEIGHT_2","0.20") or .20)
SHARP_WEIGHT_3PLUS=float(os.getenv("V11_SHARP_WEIGHT_3PLUS","0.25") or .25)
MAX_SHARP_AGE_MIN=float(os.getenv("V11_MAX_SHARP_AGE_MIN","90") or 90)
SHARP_DISAGREEMENT_SCALE=float(os.getenv("V11_SHARP_DISAGREEMENT_SCALE","0.10") or .10)
MAX_OPERATIONAL_RUN_ADJ=float(os.getenv("V11_MAX_OPERATIONAL_RUN_ADJ","0.05") or .05)
