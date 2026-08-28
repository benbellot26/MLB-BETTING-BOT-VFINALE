from __future__ import annotations

"""Leakage-safe, freshness-aware Statcast shadow features for V14.

Small samples are shrunk continuously toward league priors instead of crossing a
hard 29/30-PA cliff. A stale artifact remains causally safe but is explicitly
not promotion-ready. V14 prefers its enriched stable-ID artifact containing
pitch-type and handedness splits and falls back to the audited V137 artifact for
basic shadow features when the enriched refresh is unavailable.
"""

from datetime import date
import gzip
import json
import math
from pathlib import Path
from typing import Any

STATCAST_PRIORS=Path("data/v14_statcast_priors_latest.json.gz")
LEGACY_STATCAST_PRIORS=Path("data/v137_statcast_priors_latest.json.gz")
EXPECTED_SCHEMAS={"pulsar-v14-statcast-id-priors-v2","v13-7-statcast-id-priors-v1"}
FRESH_DAYS=3
AGING_DAYS=10
MIN_HITTER_RAW_PA=10
MIN_PITCHER_RAW_PA=20
HITTER_SHRINK_PA=80.0
PITCHER_SHRINK_PA=120.0
LEAGUE={"xwoba":.320,"hard_hit_rate":.38,"barrel_rate":.08,"k_minus_bb_rate":.12,"avg_release_speed":93.5}


def _num(value:Any)->float|None:
    try:out=float(value)
    except Exception:return None
    return out if math.isfinite(out) else None


def _read(path:Path)->dict[str,Any]:
    if not path.exists():return {}
    try:
        with gzip.open(path,"rt",encoding="utf-8") as fh:payload=json.load(fh)
    except Exception:return {}
    if not isinstance(payload,dict) or payload.get("schema") not in EXPECTED_SCHEMAS or payload.get("point_in_time") is not True or payload.get("stable_id_only") is not True:return {}
    return payload


def load_priors(path:Path|str|None=None)->dict[str,Any]:
    if path is not None:return _read(Path(path))
    enriched=_read(STATCAST_PRIORS);return enriched if enriched else _read(LEGACY_STATCAST_PRIORS)


def _artifact_state(payload:dict[str,Any],target_date:str)->tuple[bool,str,int|None]:
    try:target=date.fromisoformat(str(target_date)[:10]);cutoff=date.fromisoformat(str(payload.get("cutoff_day")))
    except Exception:return False,"INVALID",None
    if cutoff>target:return False,"FUTURE_LEAKAGE",(target-cutoff).days
    age=(target-cutoff).days;return True,("FRESH" if age<=FRESH_DAYS else "AGING" if age<=AGING_DAYS else "STALE"),age


def _shrink(value:Any,pa:int,prior:float,k:float)->float:
    raw=_num(value);weight=max(0.0,float(pa))/(max(0.0,float(pa))+k);return prior if raw is None else weight*raw+(1-weight)*prior


def _weighted_mean(rows:list[tuple[float,float]])->float|None:
    total=sum(w for _v,w in rows);return sum(v*w for v,w in rows)/total if total>0 else None


def _lineup_feature(lineup:dict[str,Any],hitters:dict[str,Any],freshness:str)->dict[str,Any]:
    order_weights=(1.04,1.05,1.08,1.10,1.06,1.00,.96,.93,.90);covered=[];buckets={k:[] for k in ("xwoba","hard_hit_rate","barrel_rate","k_minus_bb_rate")}
    for i,player in enumerate((lineup.get("players") or [])[:9]):
        pid=str(player.get("id") or "");prior=hitters.get(pid) or {};pa=int(_num(prior.get("pa")) or 0)
        if not pid or pa<MIN_HITTER_RAW_PA:continue
        reliability=pa/(pa+HITTER_SHRINK_PA);w=order_weights[min(i,8)]*max(.10,reliability);covered.append({"id":pid,"pa":pa,"reliability":reliability,"pitch_type_split_count":len(prior.get("pitch_type_splits") or {}),"pitcher_hand_split_count":len(prior.get("pitcher_hand_splits") or {})})
        for key in buckets:buckets[key].append((_shrink(prior.get(key),pa,LEAGUE[key],HITTER_SHRINK_PA),w))
    status="READY" if len(covered)>=5 and freshness!="STALE" else ("STALE" if freshness=="STALE" else "INSUFFICIENT_COVERAGE")
    return {"status":status,"promotion_ready":status=="READY","coverage":len(covered)/9.0,"covered_hitters":len(covered),"xwoba":_weighted_mean(buckets["xwoba"]),"hard_hit_rate":_weighted_mean(buckets["hard_hit_rate"]),"barrel_rate":_weighted_mean(buckets["barrel_rate"]),"k_minus_bb_rate":_weighted_mean(buckets["k_minus_bb_rate"]),"players":covered,"shrinkage":{"method":"PA/(PA+k)","k":HITTER_SHRINK_PA,"league_priors":LEAGUE}}


def _starter_feature(starter:dict[str,Any],pitchers:dict[str,Any],freshness:str)->dict[str,Any]:
    pid=str(starter.get("id") or "");prior=pitchers.get(pid) or {};pa=int(_num(prior.get("pa")) or 0)
    if not pid or pa<MIN_PITCHER_RAW_PA:return {"status":"INSUFFICIENT_COVERAGE","id":pid or None,"pa":pa,"promotion_ready":False}
    reliability=pa/(pa+PITCHER_SHRINK_PA);status="READY" if freshness!="STALE" else "STALE"
    return {"status":status,"promotion_ready":status=="READY","id":pid,"pa":pa,"reliability":reliability,"xwoba_allowed":_shrink(prior.get("xwoba"),pa,LEAGUE["xwoba"],PITCHER_SHRINK_PA),"hard_hit_rate_allowed":_shrink(prior.get("hard_hit_rate"),pa,LEAGUE["hard_hit_rate"],PITCHER_SHRINK_PA),"barrel_rate_allowed":_shrink(prior.get("barrel_rate"),pa,LEAGUE["barrel_rate"],PITCHER_SHRINK_PA),"k_minus_bb_rate":_shrink(prior.get("k_minus_bb_rate"),pa,LEAGUE["k_minus_bb_rate"],PITCHER_SHRINK_PA),"avg_release_speed":_shrink(prior.get("avg_release_speed"),pa,LEAGUE["avg_release_speed"],PITCHER_SHRINK_PA),"pitch_mix":prior.get("pitch_mix") or {},"pitch_hand":prior.get("pitch_hand"),"batter_side_splits":prior.get("batter_side_splits") or {},"max_game_date":prior.get("max_game_date"),"shrinkage":{"method":"PA/(PA+k)","k":PITCHER_SHRINK_PA}}


def _bullpen_feature(snapshot:dict[str,Any],pitchers:dict[str,Any],freshness:str)->dict[str,Any]:
    rows=[];buckets={k:[] for k in ("xwoba","hard_hit_rate","barrel_rate","k_minus_bb_rate")}
    for reliever in snapshot.get("relievers") or []:
        if reliever.get("likely_unavailable") is True or reliever.get("available") is False:continue
        pid=str(reliever.get("id") or "");prior=pitchers.get(pid) or {};pa=int(_num(prior.get("pa")) or 0)
        if not pid or pa<MIN_PITCHER_RAW_PA:continue
        reliability=pa/(pa+PITCHER_SHRINK_PA);pitches=float(_num(reliever.get("pitches_last_3d")) or 0.0);availability=max(.25,1.0-min(.65,pitches/100.0));w=max(.10,reliability)*availability;rows.append({"id":pid,"pa":pa,"weight":w,"reliability":reliability})
        for key in buckets:buckets[key].append((_shrink(prior.get(key),pa,LEAGUE[key],PITCHER_SHRINK_PA),w))
    status="READY" if len(rows)>=3 and freshness!="STALE" else ("STALE" if freshness=="STALE" else "INSUFFICIENT_COVERAGE")
    return {"status":status,"promotion_ready":status=="READY","covered_available_relievers":len(rows),"xwoba_allowed":_weighted_mean(buckets["xwoba"]),"hard_hit_rate_allowed":_weighted_mean(buckets["hard_hit_rate"]),"barrel_rate_allowed":_weighted_mean(buckets["barrel_rate"]),"k_minus_bb_rate":_weighted_mean(buckets["k_minus_bb_rate"]),"relievers":rows}


def build_shadow_features(feature_row:dict[str,Any],*,target_date:str,artifact:dict[str,Any]|None=None)->dict[str,Any]:
    priors=load_priors() if artifact is None else artifact;safe,freshness,age=_artifact_state(priors,target_date) if priors else (False,"UNAVAILABLE",None)
    enrichment=priors.get("v14_enrichment",{}) if priors else {};base={"schema":"pulsar-v14-statcast-shadow-v3","role":"SHADOW_ONLY","auto_activation":False,"point_in_time":safe,"target_date":str(target_date),"artifact_schema":priors.get("schema") if priors else None,"artifact_cutoff_day":priors.get("cutoff_day") if priors else None,"artifact_age_days":age,"freshness":freshness,"promotion_ready":safe and freshness!="STALE","pitch_matchup_data_available":bool(enrichment.get("hitter_pitch_type_splits")),"handedness_data_available":bool(enrichment.get("hitter_pitcher_hand_splits")),"reason":"safe_prior_cutoff" if safe else "artifact_unavailable_or_unsafe"}
    if not safe:return base
    ctx=feature_row.get("context") or {};features=feature_row.get("features") or {};hitters=priors.get("hitters") or {};pitchers=priors.get("pitchers") or {}
    return {**base,"home":{"lineup":_lineup_feature(ctx.get("home_lineup") or {},hitters,freshness),"starter":_starter_feature(ctx.get("home_starter") or {},pitchers,freshness),"bullpen":_bullpen_feature(((features.get("bullpen") or {}).get("home") or {}),pitchers,freshness)},"away":{"lineup":_lineup_feature(ctx.get("away_lineup") or {},hitters,freshness),"starter":_starter_feature(ctx.get("away_starter") or {},pitchers,freshness),"bullpen":_bullpen_feature(((features.get("bullpen") or {}).get("away") or {}),pitchers,freshness)}}
