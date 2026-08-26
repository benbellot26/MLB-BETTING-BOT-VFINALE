from __future__ import annotations

"""Reconstruct historical player identities without pretending they were live-known.

MLB final boxscores are used only to identify the starting pitcher and original
batting-order slots.  No player performance statistic is taken from the target
boxscore.  The resulting identity envelope is explicitly POSTHOC and therefore
cannot satisfy native-live promotion requirements; it is only a join scaffold
for strictly pregame Statcast priors.
"""

import argparse
import gzip
import hashlib
import json
from pathlib import Path
from typing import Any, Callable, Iterable

from .acquisition import http_json

BOX_URL="https://statsapi.mlb.com/api/v1/game/{game_pk}/boxscore"
JsonGetter=Callable[[str,dict[str,Any]],Any]
ROLE="RESEARCH_ONLY"


def _player_id(row:dict[str,Any])->str|None:
    raw=((row.get("person") or {}).get("id"))
    return str(raw) if raw is not None and str(raw).isdigit() else None


def _starter_pitcher(team:dict[str,Any])->str|None:
    for row in (team.get("players") or {}).values():
        if not isinstance(row,dict):continue
        pitching=((row.get("stats") or {}).get("pitching") or {})
        if int(pitching.get("gamesStarted") or 0)==1:
            return _player_id(row)
    return None


def _starting_lineup(team:dict[str,Any])->list[str]:
    slots=[]
    for row in (team.get("players") or {}).values():
        if not isinstance(row,dict):continue
        pid=_player_id(row);raw=row.get("battingOrder")
        if not pid or raw in (None,""):continue
        try:order=int(str(raw))
        except Exception:continue
        # MLB boxscores encode original starters as 100,200,...,900 and later
        # substitutes in the same slot as 101/102 etc.
        if 100<=order<=900 and order%100==0:slots.append((order,pid))
    slots.sort()
    return [pid for _,pid in slots]


def extract(game_pk:Any,boxscore:dict[str,Any])->dict[str,Any]:
    teams=boxscore.get("teams") or {};home=teams.get("home") or {};away=teams.get("away") or {}
    home_lineup=_starting_lineup(home);away_lineup=_starting_lineup(away);home_starter=_starter_pitcher(home);away_starter=_starter_pitcher(away)
    missing=[]
    if len(home_lineup)!=9:missing.append("home_starting_lineup_9")
    if len(away_lineup)!=9:missing.append("away_starting_lineup_9")
    if not home_starter:missing.append("home_starting_pitcher")
    if not away_starter:missing.append("away_starting_pitcher")
    return {"schema":"pulsar-v14-historical-identity-v1","role":ROLE,"game_pk":str(game_pk),"identity_mode":"POSTHOC_FINAL_BOXSCORE_IDENTITY_ONLY","performance_stats_from_target_game_used":False,"point_in_time_performance_join_required":True,"promotion_eligible":False,"native_live_confirmation_required":True,"status":"READY_DIAGNOSTIC" if not missing else "PARTIAL","missing":missing,"home":{"starter_id":home_starter,"lineup_ids":home_lineup},"away":{"starter_id":away_starter,"lineup_ids":away_lineup}}


def fetch_identity(game_pk:Any,*,getter:JsonGetter=http_json)->dict[str,Any]:
    payload=getter(BOX_URL.format(game_pk=game_pk),{}) or {}
    return extract(game_pk,payload)


def build(features:Iterable[dict[str,Any]],*,getter:JsonGetter=http_json)->dict[str,Any]:
    rows=[];failures=[]
    for feature in features:
        gid=str(feature.get("game_pk") or "")
        if not gid:failures.append({"game_pk":"","reason":"missing_game_pk"});continue
        try:rows.append(fetch_identity(gid,getter=getter))
        except Exception as exc:failures.append({"game_pk":gid,"reason":f"{type(exc).__name__}:{exc}"})
    ready=sum(1 for r in rows if r.get("status")=="READY_DIAGNOSTIC")
    digest=hashlib.sha256(("\n".join(json.dumps(r,sort_keys=True,separators=(",",":")) for r in rows)+"\n").encode()).hexdigest()
    return {"schema":"pulsar-v14-historical-identity-backfill-v1","role":ROLE,"rows":rows,"coverage":{"requested":len(rows)+len(failures),"retrieved":len(rows),"ready_diagnostic":ready,"ready_rate":ready/len(rows) if rows else 0.0},"failures":failures[:200],"content_sha256":digest,"promotion_eligible":False,"native_live_confirmation_required":True,"claim":"Posthoc identity scaffold only; target-game performance is never used."}


def read_features(path:Path|str)->list[dict[str,Any]]:
    out=[]
    with gzip.open(Path(path),"rt",encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                row=json.loads(line)
                if isinstance(row,dict):out.append(row)
    return out


def write(features:Iterable[dict[str,Any]],output:Path|str,*,getter:JsonGetter=http_json)->dict[str,Any]:
    artifact=build(features,getter=getter);target=Path(output);target.parent.mkdir(parents=True,exist_ok=True);target.write_text(json.dumps(artifact,ensure_ascii=False,indent=2,sort_keys=True)+"\n",encoding="utf-8");return artifact


def main()->None:
    parser=argparse.ArgumentParser();parser.add_argument("features_gz");parser.add_argument("--output",required=True);parser.add_argument("--limit",type=int);args=parser.parse_args();features=read_features(args.features_gz);features=features[:args.limit] if args.limit else features;out=write(features,args.output);print(json.dumps({"schema":out["schema"],"coverage":out["coverage"],"failures":out["failures"][:20],"content_sha256":out["content_sha256"]},sort_keys=True))


if __name__=="__main__":main()
