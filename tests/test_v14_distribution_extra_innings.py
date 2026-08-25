import unittest
from unittest.mock import patch

from v14.distribution import extra_innings_terminal_kernel, probability_surface
from v14.model import RunProjection


class V14ExtraInningsDistributionTests(unittest.TestCase):
    def test_terminal_kernel_has_no_ties_and_respects_home_prior(self):
        kernel=extra_innings_terminal_kernel(4.5,4.5,.496)
        self.assertAlmostEqual(sum(p for _,_,p in kernel),1.0,places=10)
        self.assertTrue(all(h!=a for h,a,_ in kernel))
        self.assertAlmostEqual(sum(p for h,a,p in kernel if h>a),.496,places=8)

    def test_regulation_tie_mass_is_settled_for_ml_rl_and_total(self):
        projection=RunProjection(game_pk="1",game_date="2026-08-25T20:00:00Z",analyzed_at="2026-08-25T12:00:00Z",home="Home",away="Away",home_mu=4.5,away_mu=4.5,total_line=.5,phase="EARLY",extra_innings_home_probability=.5)
        with patch("v14.distribution.joint_score_matrix",return_value=([[1.0]],0.0)):
            surface,_=probability_surface(projection)
        self.assertAlmostEqual(surface.home_ml,.5,places=8)
        self.assertGreater(surface.home_minus_1_5,0.0)
        self.assertGreater(surface.away_minus_1_5,0.0)
        self.assertGreater(surface.over,0.0)
        self.assertAlmostEqual(surface.over+surface.under,1.0,places=10)

if __name__=="__main__": unittest.main()
