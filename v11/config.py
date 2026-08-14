from __future__ import annotations
import os
from pathlib import Path

VERSION = "11.4-production-framework-v1"
MODEL_VERSION = "11.3-directional-recent400-v1"
LIVE_FILE = Path(os.getenv("V11_3_LIVE_FILE", "data/v11_3_live.jsonl"))
REPORT_FILE = Path(os.getenv("V11_3_LIVE_REPORT", "data/v11_3_live_report.json"))
MODEL_FILE = Path(os.getenv("V11_3_MODEL_FILE", "data/v11_3_direction_model.json"))

MIN_HOLDOUT_N = int(os.getenv("V11_MIN_HOLDOUT_N", "120"))
MIN_LIVE_N = int(os.getenv("V11_MIN_LIVE_N", "100"))
MIN_BRIER_GAIN = float(os.getenv("V11_MIN_BRIER_GAIN", "0.0015"))
MIN_GAIN_PROB = float(os.getenv("V11_MIN_GAIN_PROB", "0.85"))
MAX_LOGLOSS_DEGRADATION = float(os.getenv("V11_MAX_LOGLOSS_DEGRADATION", "0.0"))

MIN_EV = float(os.getenv("V11_MIN_EV", os.getenv("MIN_EV", "0.03")) or 0.03)
MIN_EDGE = float(os.getenv("V11_MIN_EDGE", os.getenv("MIN_EDGE", "0.025")) or 0.025)
PRICE_SAFETY_MARGIN = float(os.getenv("V11_PRICE_SAFETY_MARGIN", "0.01") or 0.01)
MAX_OFFICIAL_BETS = int(os.getenv("V11_MAX_OFFICIAL_BETS", "3") or 3)
MAX_DAILY_UNITS = float(os.getenv("V11_MAX_DAILY_UNITS", "4") or 4)
COMBO_UNITS = float(os.getenv("V11_COMBO_UNITS", "0.5") or 0.5)
MIN_COMBO_EV = float(os.getenv("V11_MIN_COMBO_EV", "0.04") or 0.04)
