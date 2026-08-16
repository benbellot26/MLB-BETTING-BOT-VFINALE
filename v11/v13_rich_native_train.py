from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from . import journal
from . import v13_rich_run_residual as rich

OUT = Path("data/v13_rich_native_candidate.json")
SCHEMA = "v13-rich-native-candidate-v2"
TARGET_PHASE = "FINAL"
MIN_GAMES = 300
MIN_HOLDOUT = 100
MIN_WF_GAMES = 180
MIN_WF_WINDOWS = 4
MIN_WF_PASS_RATE = .75
NATIVE_MODULES = ("starter_ip","platoon","statcast","bullpen_player","lineup_player","weather_park")
NATIVE_CANDIDATE_SETS = (
    ("starter_ip",),("platoon",),("statcast",),("bullpen_player",),("lineup_player",),("weather_park",),
    ("starter_ip","statcast"),("starter_ip","platoon"),("lineup_player","platoon"),
    ("bullpen_player","lineup_player"),("statcast","weather_park"),
    ("starter_ip","platoon","statcast"),NATIVE_MODULES,
)


def _day(r: dict[str,Any]) -> str:
    return str(r.get("game_date") or "")[:10]


def _native_rows(rows: list[dict[str,Any]]) -> list[dict[str,Any]]:
    best={}
    for r in rows:
        if r.get("result_status") != "FINAL" or r.get("home_score") is None or r.get("away_score") is None: continue
        if str(r.get("phase") or "").upper() != TARGET_PHASE: continue
        if not r.get("point_in_time") or r.get("features_from_postgame") is True: continue
        mods=(r.get("shadow_v124") or {}).get("modules") or {}
        if not mods: continue
        hm=r.get("projected_home_runs");am=r.get("projected_away_runs")
        if hm is None or am is None: continue
        gid=str(r.get("game_pk") or "");rank=str(r.get("analyzed_at") or "")
        if gid and (gid not in best or rank>best[gid][0]):best[gid]=(rank,r)
    out=[]
    for _,r in best.values():
        out.append({"game_pk":r.get("game_pk"),"game_date":r.get("game_date"),
                    "home_mu":rich._num(r.get("projected_home_runs")),"away_mu":rich._num(r.get("projected_away_runs")),
                    "home_score":r.get("home_score"),"away_score":r.get("away_score"),
                    "modules":(r.get("shadow_v124") or {}).get("modules") or {}})
    return sorted(out,key=lambda r:(_day(r),str(r.get("game_pk"))))


def _split_outer(rows):
    days=sorted({_day(r) for r in rows});hold_days=max(1,int(len(days)*.25));cut=max(1,len(days)-hold_days)
    tr=set(days[:cut]);te=set(days[cut:])
    return [r for r in rows if _day(r) in tr],[r for r in rows if _day(r) in te]


def _walk_forward(rows,selected,ridge):
    days=sorted({_day(r) for r in rows});wins=[]
    if len(rows)<MIN_WF_GAMES:return {"windows":[],"pass_rate":0.0,"passes":False}
    for frac in (.45,.55,.65,.75,.85):
        cut=max(1,int(len(days)*frac));end=min(len(days),cut+max(4,int(len(days)*.08)))
        trd=set(days[:cut]);ted=set(days[cut:end]);tr=[r for r in rows if _day(r) in trd];te=[r for r in rows if _day(r) in ted]
        if len(tr)<120 or len(te)<25:continue
        model=rich._fit(tr,ridge,selected);ev=rich._eval(te,model);passed=rich._passes(ev,25)
        wins.append({"train_games":len(tr),"test_games":len(te),**ev,"passes":passed})
    rate=sum(1 for w in wins if w["passes"])/len(wins) if wins else 0.0
    return {"windows":wins,"pass_rate":rate,"passes":len(wins)>=MIN_WF_WINDOWS and rate>=MIN_WF_PASS_RATE}


def build(rows: list[dict[str,Any]] | None = None) -> dict[str,Any]:
    native=_native_rows(journal.load_rows() if rows is None else rows)
    coverage={name:(sum(max(0.0,min(1.0,rich._num((r.get("modules") or {}).get(name,{}).get("coverage"),0.0))) for r in native)/len(native) if native else 0.0) for name in NATIVE_MODULES}
    base={"schema":SCHEMA,"target_phase":TARGET_PHASE,"native_games":len(native),"minimum_games":MIN_GAMES,"active_for_production":False,"status":"COLLECTING",
          "native_feature_coverage":coverage,"available_native_modules":list(NATIVE_MODULES),
          "safety":{"market_probability_used":False,"historical_reconstruction_used_for_promotion":False,"point_in_time_required":True,
                    "phase_specific_training":True,"selector_unchanged_until_promotion":True,"weather_requires_native_pregame_snapshot":True}}
    if len(native)<MIN_GAMES:return base
    train,hold=_split_outer(native)
    if len(hold)<MIN_HOLDOUT:return base
    candidates=[]
    for selected in NATIVE_CANDIDATE_SETS:
        for ridge in rich.RIDGES:
            wf=_walk_forward(train,selected,ridge)
            if wf.get("passes"):
                gains=[rich._num(w.get("nll_gain")) for w in wf.get("windows") or []]
                candidates.append((sum(gains)/len(gains),-len(selected),-ridge,selected,ridge,wf))
    if not candidates:
        base.update({"status":"NO_STABLE_NATIVE_CANDIDATE","train_games":len(train),"holdout_games":len(hold)})
        return base
    candidates.sort(reverse=True,key=lambda z:z[:3]);_,_,_,selected,ridge,wf=candidates[0]
    model=rich._fit(train,ridge,selected);outer=rich._eval(hold,model);passed=rich._passes(outer,MIN_HOLDOUT)
    base.update({"status":"PROMOTION_ELIGIBLE" if passed else "OUTER_HOLDOUT_REJECTED","active_for_production":bool(passed),
                 "train_games":len(train),"holdout_games":len(hold),"selection":{"selected_modules":list(selected),"ridge":ridge,"walk_forward":wf},
                 "model":model,"outer_holdout":outer,
                 "promotion_rule":"FINAL only; >=300 exact point-in-time games; train-only walk-forward >=75% pass; >=100-game untouched outer holdout improves RMSE and NB NLL with MAE regression <=0.01"})
    return base


def main():
    report=build();OUT.parent.mkdir(parents=True,exist_ok=True);OUT.write_text(json.dumps(report,ensure_ascii=False,indent=2,sort_keys=True),encoding="utf-8")
    print(json.dumps(report,ensure_ascii=False,indent=2,sort_keys=True))

if __name__=="__main__":main()
