from __future__ import annotations

import unittest

from v14.savant_run_value_builder import build


FIELDING="team,inf_of_runs,catching_runs\nCubs,12,3\n"
BASERUN="team_name,runner_runs_tot\nCHC,10\n"


def text_getter(url:str)->str:
    return FIELDING if "fielding-run-value" in url else BASERUN


def json_getter(url:str,params:dict):
    if url.endswith("/teams"):
        return {"teams":[{"id":112,"name":"Chicago Cubs","clubName":"Cubs","abbreviation":"CHC","teamCode":"chn"}]}
    if "/teams/112/stats" in url:
        if params.get("stats")=="byDateRange":
            self_stat={"gamesPlayed":100}
        else:
            self_stat={"plateAppearances":6000}
        return {"stats":[{"splits":[{"stat":self_stat}]}]}
    raise AssertionError(url)


class SavantRunValueBuilderTests(unittest.TestCase):
    def test_builder_normalizes_defense_catcher_and_prior_baserunning(self):
        out=build("2026-08-26",text_getter=text_getter,json_getter=json_getter)
        row=out["teams"]["112"]
        self.assertAlmostEqual(row["fielding_run_value_per_150"],18.0)
        self.assertAlmostEqual(row["catcher_run_value_per_150"],4.5)
        self.assertAlmostEqual(row["baserunning_runs_per_600_pa"],1.0)
        self.assertEqual(out["cutoff_day"],"2026-08-25")
        self.assertEqual(out["baserunning_source"]["source_season"],2025)
        self.assertEqual(out["coverage"]["complete_teams"],1)
        self.assertFalse(out["promotion_ready"])
        self.assertFalse(out["champion_impact"])

    def test_unknown_provider_columns_fail_closed(self):
        def bad_text(url:str)->str:
            return "team,mystery\nCubs,10\n"
        out=build("2026-08-26",text_getter=bad_text,json_getter=json_getter)
        self.assertEqual(out["coverage"]["complete_teams"],0)
        self.assertTrue(out["failures"])


if __name__=="__main__": unittest.main()
