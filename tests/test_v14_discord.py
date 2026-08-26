import unittest

from v14 import MODEL_GENERATION
from v14.discord import build_game_embed


class V14DiscordTests(unittest.TestCase):
    def _result(self,phase="FINAL"):
        return {"game_pk":"123","phase":phase,"ctx":{"away":"Away","home":"Home","away_lineup":{"count":9},"home_lineup":{"count":9}},"v14_prediction":{"role":"PRODUCTION","model_generation":MODEL_GENERATION,"total_line":8.5,"run_projection":{"away_mu":4.1,"home_mu":4.6},"context_adjustment":{"eligible":True,"feature_as_of":"2026-08-25T18:00:00+00:00"},"probabilities":{"away_ml":.44,"home_ml":.56,"away_plus_1_5":.61,"home_minus_1_5":.39,"home_plus_1_5":.70,"away_minus_1_5":.30,"over":.53,"under":.47}}}

    def test_embed_reads_native_prediction_surface(self):
        embed=build_game_embed(self._result()); text="\n".join(f["value"] for f in embed["fields"]); self.assertIn("56.0%",text); self.assertIn("53.0%",text); self.assertIn("Pulsar V14",embed["footer"]["text"]); self.assertIn("FINAL UPDATE",embed["title"]); self.assertNotIn("•  FINAL$",embed["title"])

    def test_early_remains_early(self): self.assertIn("EARLY",build_game_embed(self._result("EARLY"))["title"])

    def test_embed_rejects_non_v14_prediction(self):
        with self.assertRaisesRegex(ValueError,"V14"): build_game_embed({"v14_prediction":{"role":"PRODUCTION","model_generation":"legacy"}})

    def test_probability_and_paper_clv_status_are_market_specific(self):
        result=self._result(); result["decision"]={"best":{"canonical_market":"ML","status":"RESEARCH_ONLY"}}; result["betting_certification"]={"probability_status":"PROBABILITY_CERTIFIED","betting_status":"BETTING_CERTIFIED","paper_clv":{"n":999,"mean_clv":9.9,"positive_rate":.99},"markets":{"ML":{"probability_status":"PROBABILITY_CERTIFIED","betting_status":"RESEARCH_ONLY","paper_clv":{"n":42,"mean_clv":.37,"positive_rate":.571}},"TOTAL_OVER":{"probability_status":"PROBABILITY_RESEARCH","betting_status":"RESEARCH_ONLY","paper_clv":{"n":3,"mean_clv":-.2,"positive_rate":.33}}}}
        embed=build_game_embed(result); text="\n".join(f["value"] for f in embed["fields"])
        self.assertIn("Scope **ML**",text); self.assertIn("PROBABILITY_CERTIFIED",text); self.assertIn("RESEARCH_ONLY",text); self.assertIn("**ML**",text); self.assertIn("42/100",text); self.assertIn("+0.37 pp",text); self.assertIn("57.1%",text); self.assertNotIn("999/100",text)

    def test_total_best_candidate_does_not_inherit_ml_certification(self):
        result=self._result(); result["decision"]={"best":{"canonical_market":"TOTAL_OVER","status":"NO_BET"}}; result["betting_certification"]={"probability_status":"PROBABILITY_CERTIFIED","betting_status":"BETTING_CERTIFIED","markets":{"ML":{"probability_status":"PROBABILITY_CERTIFIED","betting_status":"BETTING_CERTIFIED","paper_clv":{"n":120,"mean_clv":.4,"positive_rate":.58}},"TOTAL_OVER":{"probability_status":"PROBABILITY_RESEARCH","betting_status":"RESEARCH_ONLY","paper_clv":{"n":7,"mean_clv":-.1,"positive_rate":.43}}}}
        text="\n".join(f["value"] for f in build_game_embed(result)["fields"])
        self.assertIn("Scope **TOTAL_OVER**",text); self.assertIn("Probability **PROBABILITY_RESEARCH**",text); self.assertIn("Betting **RESEARCH_ONLY**",text); self.assertIn("7/100",text); self.assertNotIn("120/100",text)


if __name__=="__main__": unittest.main()
