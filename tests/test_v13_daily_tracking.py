import json
from pathlib import Path

from v11 import v13_daily_tracking as t


def test_tracking_capture_close_settle_and_bands(tmp_path):
    t.TRACK_FILE = tmp_path / "track.jsonl"
    t.REPORT_FILE = tmp_path / "report.json"
    result = {
        "game_pk": 1,
        "phase": "FINAL",
        "game": {"gameDate": "2026-08-17T20:00:00+00:00"},
        "ctx": {"home": "Home", "away": "Away"},
        "options": [
            {"market":"ML","name":"Home","point":None,"p_baseball_calibrated":.60,"p_baseball_raw":.59,"p_market":.55,
             "model_market_gap":.05,"p_win":.60,"p_push":0,"model_uncertainty":.03,"is_canonical_line":True,
             "winamax_eval":{"price":1.90,"v11_price_gate":{"ev_at_price":.08,"required_price":1.75},"official_selected":False}},
            {"market":"TOTAL","name":"Over","point":8.5,"p_baseball_calibrated":.56,"p_market":.51,
             "p_win":.56,"p_push":0,"winamax_eval":{"price":None,"official_selected":False}},
        ]}
    assert t.capture_results([result], analyzed_at="2026-08-17T18:00:00+00:00", target_date="2026-08-17") == 2
    state=t.fold(); assert len(state)==2
    ml=next(x for x in state.values() if x["market"]=="ML")
    assert abs(ml["nominal_ev"]-.14)<1e-9
    assert t.observe_closing([result], analyzed_at="2026-08-17T19:50:00+00:00") == 2
    journal_rows=[{"game_pk":1,"result_status":"FINAL","analyzed_at":"2026-08-17T18:00:00+00:00","home":"Home","away":"Away","home_score":5,"away_score":3}]
    assert t.settle_from_journal(journal_rows, settled_at="2026-08-17T23:00:00+00:00") == 2
    state=t.fold(); ml=next(x for x in state.values() if x["market"]=="ML")
    assert ml["settled_result"]=="WIN" and abs(ml["flat_1u_pnl"]-.9)<1e-9
    rep=json.loads(t.REPORT_FILE.read_text())
    assert rep["by_market"]["ML"]["priced"]==1
    assert rep["by_nominal_ev_band"]["ML"][">=10%"]["wins"]==1
    assert rep["by_market"]["TOTAL"]["priced"]==0


def test_band_boundaries():
    assert t._band(-.001)=="<0%"
    assert t._band(0)=="0-1%"
    assert t._band(.015)=="1-3%"
    assert t._band(.04)=="3-5%"
    assert t._band(.07)=="5-10%"
    assert t._band(.10)==">=10%"
