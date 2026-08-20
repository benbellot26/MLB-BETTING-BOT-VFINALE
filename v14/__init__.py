"""V14 clean MLB probability engine.

V14 is shadow-only until it independently beats the frozen V13.10 champion on
chronological out-of-sample evidence. Nothing in this package can publish bets
or alter V13 production probabilities.
"""

VERSION = "14.0.0-shadow-foundation"
MODEL_GENERATION = "v14-clean-score-distribution-shadow-v1"
SCHEMA = "v14-shadow-probability-v1"

__all__ = ["VERSION", "MODEL_GENERATION", "SCHEMA"]
