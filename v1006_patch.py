#!/usr/bin/env python3
from pathlib import Path

path=Path('bot.py')
text=path.read_text(encoding='utf-8')
marker='''if __name__=="__main__":\n    try:\n        if "--self-test" in sys.argv:v10_self_test()\n        else:main()\n    except KeyboardInterrupt:raise SystemExit(130)\n    except Exception:logging.exception("ERREUR FATALE V10");raise\n'''
assert text.count(marker)==1, f'expected one main marker, got {text.count(marker)}'
block=r'''# ======================== V10.0.6 RESIDUAL RUN SEED =========================
# The historical walk-forward dataset is used ONLY for the FINAL-phase residual
# run model. Calibration, market skill, confidence, dispersion, ledger, Winamax,
# EV/Kelly and staking continue to use the real live history exclusively.
_V1005_TRAINING_GAMES_PHASE=v10_training_games_phase
_V1005_RUN_STATE_PHASE=v10_run_state_phase
_V1005_RUN_MODEL_STATE=run_model_state
_V1005_ANALYZE_BASE=analyze_base
_V1005_BUILD_SNAPSHOT_FINAL=build_snapshot
_V1005_SELF_TEST_FINAL=v10_self_test

VERSION="10.0.6"
RUN_SEED_VERSION="backtest-2026-walkforward-final-v1"
RUN_SEED_FILE=Path(os.getenv("RUN_SEED_FILE","data/mlb_run_seed_2026.jsonl"))
RUN_SEED_ENABLED=os.getenv("RUN_SEED_ENABLED","1").strip().lower() not in ("0","false","no","off")
_V1006_RUN_SEED=None

def v1006_load_run_seed():
    global _V1006_RUN_SEED
    if _V1006_RUN_SEED is not None:return _V1006_RUN_SEED
    if not RUN_SEED_ENABLED:
        _V1006_RUN_SEED=[];return _V1006_RUN_SEED
    if not RUN_SEED_FILE.exists():
        logging.warning("V10.0.6 run seed absent: %s — fallback live-only",RUN_SEED_FILE)
        _V1006_RUN_SEED=[];return _V1006_RUN_SEED
    rows=[];seen=set();bad=[]
    for lineno,line in enumerate(RUN_SEED_FILE.read_text(encoding="utf-8").splitlines(),1):
        if not line.strip():continue
        try:
            r=json.loads(line);gid=str(r["game_pk"])
            if gid in seen:continue
            fh=[float(x) for x in r["run_features_home"]];fa=[float(x) for x in r["run_features_away"]]
            if r.get("phase")!="FINAL" or len(fh)!=17 or len(fa)!=17:raise ValueError("invalid phase/features")
            vals=[num(r["base_home"],float("nan")),num(r["base_away"],float("nan")),*fh,*fa,float(r["home_score"]),float(r["away_score"])]
            if not all(math.isfinite(x) for x in vals):raise ValueError("non-finite seed value")
            rows.append({"game_pk":gid,"game_date":r.get("game_date",""),"home":r.get("home"),"away":r.get("away"),"home_score":float(r["home_score"]),"away_score":float(r["away_score"]),"base_home":float(r["base_home"]),"base_away":float(r["base_away"]),"run_features_home":fh,"run_features_away":fa})
            seen.add(gid)
        except Exception as e:bad.append((lineno,str(e)))
    if bad:raise RuntimeError(f"Run seed V10.0.6 invalide: {len(bad)} ligne(s), première={bad[0]}")
    rows.sort(key=lambda r:(r["game_date"],r["game_pk"]));_V1006_RUN_SEED=rows
    logging.info("V10.0.6 RUN SEED | %d matchs FINAL chargés depuis %s",len(rows),RUN_SEED_FILE)
    return rows

def v1006_live_phase_ids(hist,phase):
    ids=set()
    for r in hist.values():
        if r.get("status")!="FINAL":continue
        if v10_phase_snapshot(r,phase):ids.add(str(r.get("game_pk")))
    return ids

def v10_training_games_phase(hist,phase):
    live=_V1005_TRAINING_GAMES_PHASE(hist,phase)
    if phase!="FINAL" or not RUN_SEED_ENABLED:return live
    live_ids=v1006_live_phase_ids(hist,"FINAL");seed=[]
    for r in v1006_load_run_seed():
        if r["game_pk"] in live_ids:continue
        snap={"run_features_home":r["run_features_home"],"run_features_away":r["run_features_away"],"base_home":r["base_home"],"base_away":r["base_away"],"run_seed_version":RUN_SEED_VERSION,"run_seed":True}
        seed.append((r["game_date"],snap,r["home_score"],r["away_score"]))
    out=seed+live;out.sort(key=lambda x:x[0]);return out

def v10_run_state_phase(hist,phase):
    live_n=len(_V1005_TRAINING_GAMES_PHASE(hist,phase));state=_V1005_RUN_STATE_PHASE(hist,phase)
    state["live_n"]=live_n;state["seed_n"]=max(0,state.get("n",0)-live_n) if phase=="FINAL" else 0
    state["run_seed_version"]=RUN_SEED_VERSION if state["seed_n"] else None
    state["training_source"]="backtest-seed+live" if state["seed_n"] else "live-only"
    return state

def run_model_state(hist):
    out=_V1005_RUN_MODEL_STATE(hist);final=(out.get("phase_states") or {}).get("FINAL",{})
    out["seed_n"]=final.get("seed_n",0);out["live_n"]=sum((x or {}).get("live_n",0) for x in (out.get("phase_states") or {}).values())
    if final.get("seed_n"):
        logging.info("V10.0.6 RUN TRAINING | FINAL seed=%d live=%d total=%d active=%s RMSE %.3f/%.3f gainProb=%.2f",final.get("seed_n",0),final.get("live_n",0),final.get("n",0),final.get("active",False),num(final.get("rmse_model")),num(final.get("rmse_base")),num(final.get("gain_prob")))
    return out

def analyze_base(g,event,delta,states,hist):
    r=_V1005_ANALYZE_BASE(g,event,delta,states,hist);phase=r.get("phase");st=((states[0].get("phase_states") or {}).get(phase) or {})
    r["run_seed_n"]=st.get("seed_n",0);r["run_live_n"]=st.get("live_n",0);r["run_training_source"]=st.get("training_source","live-only");r["run_seed_version"]=st.get("run_seed_version")
    return r

def build_snapshot(result,rec):
    snap=_V1005_BUILD_SNAPSHOT_FINAL(result,rec);snap["run_training_source"]=result.get("run_training_source","live-only");snap["run_seed_n"]=int(num(result.get("run_seed_n"),0));snap["run_live_n"]=int(num(result.get("run_live_n"),0));snap["run_seed_version"]=result.get("run_seed_version");return snap

def v10_self_test():
    _V1005_SELF_TEST_FINAL()
    seed=v1006_load_run_seed()
    if RUN_SEED_ENABLED and RUN_SEED_FILE.exists():
        assert len(seed)>=1700
        assert len({r["game_pk"] for r in seed})==len(seed)
        assert all(len(r["run_features_home"])==17 and len(r["run_features_away"])==17 for r in seed)
        # Historical reconstruction is FINAL-only: EARLY/LATE must remain live-only.
        assert v10_training_games_phase({},"EARLY")==[] and v10_training_games_phase({},"LATE")==[]
        final=v10_training_games_phase({},"FINAL");assert len(final)==len(seed)
        # A genuine live FINAL snapshot with the same game_pk replaces, never duplicates, its seed row.
        r0=seed[0];fake_snap={"seconds_to_game":3600,"phase":"FINAL","feature_version":FEATURE_VERSION,"model_version":MODEL_VERSION,"distribution_version":DIST_VERSION,"run_features_home":r0["run_features_home"],"run_features_away":r0["run_features_away"],"base_home":r0["base_home"],"base_away":r0["base_away"]}
        fake={r0["game_pk"]:{"game_pk":r0["game_pk"],"game_date":r0["game_date"],"status":"FINAL","home_score":r0["home_score"],"away_score":r0["away_score"],"snapshots":[fake_snap]}}
        assert len(v10_training_games_phase(fake,"FINAL"))==len(seed)
        # Betting/calibration paths receive the live history only; seed rows are never injected there.
        assert v10_ml_cal_state_phase({},"FINAL","base-runs")["n"]==0
        assert v10_skill_state_phase({},"FINAL","base-runs")["n"]==0
        assert v10_market_cal_state({},"ML","FINAL")["n"]==0
    print("SELF-TEST MLB BETTING BOT V10.0.6 OK")

'''
path.write_text(text.replace(marker,block+marker,1),encoding='utf-8')
print('V10.0.6 override inserted once')
