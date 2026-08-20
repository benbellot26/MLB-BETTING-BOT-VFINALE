"""V14 clean MLB probability engine.

V14 starts from behavioral parity with the frozen V13.10 production champion,
then removes or replaces components only when evidence shows no predictive
regression. Nothing in this package can publish bets or alter V13 production
probabilities while V14 remains shadow-only.
"""

VERSION = "14.0.0-v13.10-champion-parity-shadow"
MODEL_GENERATION = "v14-v13.10-champion-parity-shadow-v1"
SCHEMA = "v14-shadow-probability-v2"

__all__ = ["VERSION", "MODEL_GENERATION", "SCHEMA"]
