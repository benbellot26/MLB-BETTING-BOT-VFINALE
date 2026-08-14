from __future__ import annotations
import os
from pathlib import Path

VERSION = "12.1-professional-foundation-v2"
SCHEMA_VERSION = "v12-professional-v2"
LIVE_FILE = Path(os.getenv("V11_LIVE_FILE", "data/v11_3_live.jsonl"))
REPORT_FILE = Path(os.getenv("V11_REPORT_FILE", "data/v11_3_live_report.json"))
CANDIDATE_MODEL_FILE = Path(os.getenv("V11_CANDIDATE_MODEL_FILE", "data/v11_candidate_model.json"))
CHAMPION_MODEL_FILE = Path(os.getenv("V11_CHAMPION_MODEL_FILE", "data/v11_champion_model.json"))

MIN_EV = float(os.getenv("V11_MIN_EV", os.getenv("MIN_EV", "0.03")) or .03)
MIN_EDGE = float(os.getenv("V11_MIN_EDGE", os.getenv("MIN_EDGE", "0.025")) or .025)
MAX_OFFICIAL_BETS = int(os.getenv("V11_MAX_OFFICIAL_BETS", "3") or 3)
MAX_DAILY_UNITS = float(os.getenv("V11_MAX_DAILY_UNITS", "4") or 4)
MAX_BET_UNITS = float(os.getenv("V11_MAX_BET_UNITS", "1.5") or 1.5)
COMBO_UNITS = float(os.getenv("V11_COMBO_UNITS", "0.35") or .35)
MIN_COMBO_EV = float(os.getenv("V11_MIN_COMBO_EV", "0.05") or .05)
FRACTIONAL_KELLY = float(os.getenv("V11_FRACTIONAL_KELLY", "0.125") or .125)
MIN_STAKE_UNITS = float(os.getenv("V11_MIN_STAKE_UNITS", "0.25") or .25)

RUN_DISPERSION = float(os.getenv("V11_RUN_DISPERSION", "7.5") or 7.5)
MAX_RUNS_MATRIX = int(os.getenv("V11_MAX_RUNS_MATRIX", "24") or 24)
MAX_OPERATIONAL_RUN_ADJ = float(os.getenv("V11_MAX_OPERATIONAL_RUN_ADJ", "0.05") or .05)
MAX_LEARNED_RUN_ADJ = float(os.getenv("V11_MAX_LEARNED_RUN_ADJ", "0.75") or .75)

MAX_SHARP_AGE_MIN = float(os.getenv("V11_MAX_SHARP_AGE_MIN", "90") or 90)
SHARP_DISAGREEMENT_SCALE = float(os.getenv("V11_SHARP_DISAGREEMENT_SCALE", "0.10") or .10)
SHARP_BOOK_WEIGHTS = {
    "pinnacle": float(os.getenv("V11_WEIGHT_PINNACLE", "1.20") or 1.20),
    "betfair_ex_eu": float(os.getenv("V11_WEIGHT_BETFAIR", "1.05") or 1.05),
    "matchbook": float(os.getenv("V11_WEIGHT_MATCHBOOK", "1.00") or 1.00),
    "betonlineag": float(os.getenv("V11_WEIGHT_BETONLINE", "0.90") or .90),
}
EXCHANGE_COMMISSION = {
    "betfair_ex_eu": float(os.getenv("V11_COMMISSION_BETFAIR", "0.02") or .02),
    "matchbook": float(os.getenv("V11_COMMISSION_MATCHBOOK", "0.02") or .02),
}
MAX_MARKET_BLEND_WEIGHT = float(os.getenv("V11_MAX_MARKET_BLEND_WEIGHT", "0.30") or .30)
MIN_MARKET_BLEND_WEIGHT = float(os.getenv("V11_MIN_MARKET_BLEND_WEIGHT", "0.08") or .08)

MIN_DATA_QUALITY = float(os.getenv("V11_MIN_DATA_QUALITY", "0.68") or .68)
MIN_FINAL_LINEUP_PLAYERS = int(os.getenv("V11_MIN_FINAL_LINEUP_PLAYERS", "16") or 16)
MIN_SHARP_REFS = int(os.getenv("V11_MIN_SHARP_REFS", "1") or 1)
FALLBACK_MODEL_UNCERTAINTY = float(os.getenv("V11_FALLBACK_MODEL_UNCERTAINTY", "0.035") or .035)
MIN_MODEL_UNCERTAINTY = float(os.getenv("V11_MIN_MODEL_UNCERTAINTY", "0.008") or .008)
UNCERTAINTY_EDGE_MULTIPLIER = float(os.getenv("V11_UNCERTAINTY_EDGE_MULTIPLIER", "1.25") or 1.25)

MIN_RESIDUAL_TRAIN_GAMES = int(os.getenv("V11_MIN_RESIDUAL_TRAIN_GAMES", "180") or 180)
MIN_RESIDUAL_RMSE_GAIN = float(os.getenv("V11_MIN_RESIDUAL_RMSE_GAIN", "0.015") or .015)
MIN_CALIBRATION_GAMES = int(os.getenv("V11_MIN_CALIBRATION_GAMES", "140") or 140)
MIN_CALIBRATION_HOLDOUT = int(os.getenv("V11_MIN_CALIBRATION_HOLDOUT", "35") or 35)
MIN_CALIBRATION_BRIER_GAIN = float(os.getenv("V11_MIN_CALIBRATION_BRIER_GAIN", "0.001") or .001)
MIN_DISPERSION_TRAIN_GAMES = int(os.getenv("V11_MIN_DISPERSION_TRAIN_GAMES", "100") or 100)
MIN_DISPERSION_HOLDOUT = int(os.getenv("V11_MIN_DISPERSION_HOLDOUT", "35") or 35)
MIN_DISPERSION_NLL_GAIN = float(os.getenv("V11_MIN_DISPERSION_NLL_GAIN", "0.002") or .002)

CLOSING_CANDIDATE_WINDOW_MIN = float(os.getenv("V11_CLOSING_CANDIDATE_WINDOW_MIN", "10") or 10)
T60_WINDOW_MIN = float(os.getenv("V11_T60_WINDOW_MIN", "60") or 60)
T15_WINDOW_MIN = float(os.getenv("V11_T15_WINDOW_MIN", "15") or 15)

# Backward-compatible names kept so old external configuration does not crash.
PRICE_SAFETY_MARGIN = 0.0
SHARP_WEIGHT_1 = MIN_MARKET_BLEND_WEIGHT
SHARP_WEIGHT_2 = min(.18, MAX_MARKET_BLEND_WEIGHT)
SHARP_WEIGHT_3PLUS = min(.25, MAX_MARKET_BLEND_WEIGHT)
OFFICIAL_SCORE_THRESHOLDS = (68.0, 72.0, 76.0)
