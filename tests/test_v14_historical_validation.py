from __future__ import annotations

import unittest

from v14.historical_dataset import audit, paired_rows, split_by_season
from v14.historical_team_challenger import baseline_runs, candidate_runs, historical_gate, tune


def feature(gid:int,season:int,home_rf:float=5.2,away_rf:float=3.8,home_ra:float=3.9,away_ra:float=5.1):
    date=f"{season}-06-{(gid%20)+1:02d}T20:00:00+00:00"; as_of=f"{season}-06-{(gid%20)+1:02d}T18:00:00+00:00"
    def team(rf,ra): return {"season_to_date":{"games":40,"runs_for_pg":rf,"runs_against_pg":ra,"win_pct":.5},"last_14_games":{"games":14,"runs_for_pg":rf,"runs_against_pg":ra,"win_pct":.5},"last_7_games":{"games":7,"runs_for_pg":rf,"runs_against_pg":ra,"win_pct":.5},"rest_days":1}
    return {"schema":"v13-7-free-reconstructed-feature-v1","game_pk":str(gid),"season":season,"official_date":date[:10],"game_date":date,"as_of":as_of,"features":{"home_team_form":team(home_rf,home_ra),"away_team_form":team(away_rf,away_ra),"park_prior":{}},"feature_provenance":{"mlb_prior_results":{"point_in_time_rule":"strictly earlier officialDate only","same_day_games_excluded":True}},"target_labels_embedded":False,"market_data_embedded":False}
def label(gid:int,season:int,hs:int=5,aws:int=4): return {"game_pk":str(gid),"game_date":f"{season}-06-{(gid%20)+1:02d}T20:00:00+00:00","home_score":hs,"away_score":aws,"home_win":int(hs>aws),"total_runs":hs+aws,"run_margin_home":hs-aws}

class HistoricalDatasetTests(unittest.TestCase):
    def test_strict_pregame_feature_label_separation_passes(self):
        f=feature(1,2024);l=label(1,2024);report=audit([f],[l]);self.assertTrue(report["passed"]);self.assertEqual(len(paired_rows([f],[l])),1)
    def test_label_leak_inside_feature_payload_fails(self):
        f=feature(2,2024);f["features"]["home_score"]=5;report=audit([f],[label(2,2024)]);self.assertFalse(report["passed"]);self.assertTrue(any("feature_contains_label" in x for x in report["failures"]))
    def test_postgame_as_of_fails(self):
        f=feature(3,2024);f["as_of"]="2024-06-04T22:00:00+00:00";report=audit([f],[label(3,2024)]);self.assertFalse(report["passed"]);self.assertTrue(any("feature_not_strictly_pregame" in x for x in report["failures"]))
    def test_embedded_target_or_market_flag_fails(self):
        f=feature(4,2024);f["target_labels_embedded"]=True;report=audit([f],[label(4,2024)]);self.assertFalse(report["passed"]);self.assertTrue(any("feature_envelope_embeds" in x for x in report["failures"]))
    def test_split_keeps_2026_frozen(self):
        pairs=[(feature(10+s,s),label(10+s,s)) for s in (2024,2025,2026)];out=split_by_season(pairs);self.assertEqual(len(out["tuning"]),1);self.assertEqual(len(out["validation"]),1);self.assertEqual(len(out["frozen_test"]),1)

class HistoricalTeamChallengerTests(unittest.TestCase):
    def test_candidate_shrinks_early_team_rates(self):
        f=feature(20,2024,home_rf=8.0,away_rf=1.0,home_ra=1.0,away_ra=8.0);f["features"]["home_team_form"]["season_to_date"]["games"]=2;f["features"]["away_team_form"]["season_to_date"]["games"]=2;params={"season_prior_games":45,"recent14_weight":0,"recent7_weight":0,"offense_weight":.5,"home_advantage_runs":.12,"park_weight":0};bh,ba=baseline_runs(f);ch,ca=candidate_runs(f,params);self.assertLess(abs(ch-4.57),abs(bh-4.57));self.assertLess(abs(ca-4.45),abs(ba-4.45))
    def test_tuner_is_research_only(self):
        pairs=[]
        for i in range(1100):
            f=feature(1000+i,2024);pairs.append((f,label(1000+i,2024,5 if i%2==0 else 4,4)))
        out=tune(pairs);self.assertEqual(out["status"],"TUNED_RESEARCH_ONLY");self.assertIn("parameters",out)
    def test_historical_gate_requires_validation_and_frozen_nonregression(self):
        good={"paired":{"team_mse_gain":{"mean":.2,"ci95_lower":.05},"total_mae_gain":{"mean":.1,"ci95_lower":-.01}}};frozen={"paired":{"team_mse_gain":{"mean":.1,"ci95_lower":-.01},"total_mae_gain":{"mean":0.0,"ci95_lower":-.1}}};out=historical_gate(good,frozen);self.assertTrue(out["passes"]);self.assertFalse(out["auto_activation"])

if __name__=="__main__": unittest.main()
