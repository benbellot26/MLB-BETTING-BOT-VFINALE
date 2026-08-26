import unittest

from v14.staking import (
    MAX_DAILY_BANKROLL_FRACTION,
    MAX_GAME_BANKROLL_FRACTION,
    MAX_MARKET_BANKROLL_FRACTION,
    size_portfolio,
)


def candidate(game_pk, market, robust=10.0):
    return {
        "game_pk": str(game_pk),
        "market": market,
        "status": "BET",
        "lower_probability": 0.75,
        "price": 2.00,
        "robust_edge_pp": robust,
        "model_edge_pp": robust + 2.0,
    }


class V14StakingTests(unittest.TestCase):
    def test_daily_cap_is_global_across_games(self):
        rows=size_portfolio([
            candidate(1,"M1",10),candidate(2,"M2",9),candidate(3,"M3",8),candidate(4,"M4",7),
        ],certified=True)
        self.assertAlmostEqual(sum(r["stake_fraction"] for r in rows),MAX_DAILY_BANKROLL_FRACTION,places=12)
        self.assertEqual(rows[-1]["stake_fraction"],0.0)

    def test_same_game_correlated_markets_share_game_cap(self):
        rows=size_portfolio([candidate(1,"ML",10),candidate(1,"TOTAL",9)],certified=True)
        self.assertAlmostEqual(sum(r["stake_fraction"] for r in rows),MAX_GAME_BANKROLL_FRACTION,places=12)
        self.assertAlmostEqual(rows[0]["stake_fraction"],0.010,places=12)
        self.assertAlmostEqual(rows[1]["stake_fraction"],0.005,places=12)

    def test_market_cap_applies_across_games(self):
        rows=size_portfolio([candidate(1,"ML",10),candidate(2,"ML",9),candidate(3,"ML",8)],certified=True)
        self.assertAlmostEqual(sum(r["stake_fraction"] for r in rows),MAX_MARKET_BANKROLL_FRACTION,places=12)
        self.assertEqual(rows[-1]["stake_fraction"],0.0)

    def test_existing_daily_exposure_survives_runtime_restart(self):
        rows=size_portfolio([candidate(4,"TOTAL",10)],certified=True,initial_daily_used=0.025)
        self.assertAlmostEqual(rows[0]["stake_fraction"],0.005,places=12)
        self.assertAlmostEqual(rows[0]["portfolio_exposure_after"]["day"],MAX_DAILY_BANKROLL_FRACTION,places=12)

    def test_existing_market_and_game_exposure_are_respected(self):
        rows=size_portfolio(
            [candidate(9,"ML",10)],
            certified=True,
            initial_daily_used=0.020,
            initial_game_used={"9":0.014},
            initial_market_used={"ML":0.019},
        )
        self.assertAlmostEqual(rows[0]["stake_fraction"],0.001,places=12)

    def test_uncertified_portfolio_is_always_zero(self):
        rows=size_portfolio([candidate(1,"ML")],certified=False)
        self.assertEqual(rows[0]["stake_fraction"],0.0)
        self.assertEqual(rows[0]["unit_tier"],0)


if __name__=="__main__": unittest.main()
