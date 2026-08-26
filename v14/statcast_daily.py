from __future__ import annotations

"""Build the rolling enriched Statcast artifact consumed by V14 shadows.

The refresh is data-only. It cannot modify MODEL_GENERATION or betting status.
All raw pitches are fetched through the bounded/cap-aware V137 provider layer,
then V14 adds hitter pitch-type splits under the same strict cutoff.
"""

import argparse
from datetime import date, timedelta
import gzip
import json
from pathlib import Path
from typing import Any, Callable

from .statcast_pit_backfill import build

DEFAULT_PRIORS=Path("data/v14_statcast_priors_latest.json.gz")
DEFAULT_REPORT=Path("data/v14_statcast_priors_report.json")
Builder=Callable[...,dict[str,Any]]


def _write_deterministic_gzip(payload:dict[str,Any],path:Path)->None:
    path.parent.mkdir(parents=True,exist_ok=True)
    raw=(json.dumps(payload,ensure_ascii=False,sort_keys=True,separators=(",",":"))+"\n").encode("utf-8")
    with path.open("wb") as fh:
        with gzip.GzipFile(filename="",mode="wb",fileobj=fh,mtime=0) as gz: gz.write(raw)


def refresh(cutoff_day:str,*,lookback_days:int=45,priors_path:Path|str=DEFAULT_PRIORS,report_path:Path|str=DEFAULT_REPORT,builder:Builder=build)->dict[str,Any]:
    cutoff=date.fromisoformat(str(cutoff_day)[:10]); days=max(7,min(120,int(lookback_days))); start=cutoff-timedelta(days=days)
    artifact=builder(cutoff.isoformat(),season_start=start.isoformat()); priors=dict(artifact.get("priors") or {}); coverage=artifact.get("coverage") or {}
    if artifact.get("point_in_time") is not True or artifact.get("stable_id_only") is not True or artifact.get("champion_impact") is not False:
        raise ValueError("Statcast backfill envelope lost strict shadow PIT contract")
    if priors.get("schema")!="pulsar-v14-statcast-id-priors-v2" or priors.get("point_in_time") is not True or priors.get("stable_id_only") is not True:
        raise ValueError("enriched Statcast priors lost schema/PIT/stable-ID contract")
    if int(coverage.get("hitter_pitch_split_players") or 0)<=0 or int(coverage.get("hitter_pitch_split_buckets") or 0)<=0:
        raise ValueError("enriched Statcast artifact contains no hitter pitch-type splits")
    source_end=str(artifact.get("source_end") or "")
    if source_end and source_end>=cutoff.isoformat(): raise ValueError("enriched Statcast artifact source_end crossed cutoff")
    priors["rolling_window_days"]=days; priors["source_start"]=artifact.get("source_start"); priors["source_end"]=artifact.get("source_end"); priors["champion_impact"]=False; priors["auto_activation"]=False
    target=Path(priors_path); _write_deterministic_gzip(priors,target)
    report={"schema":"pulsar-v14-statcast-daily-report-v1","role":"SHADOW_DATA_ONLY","cutoff_day":cutoff.isoformat(),"lookback_days":days,"source_start":artifact.get("source_start"),"source_end":artifact.get("source_end"),"raw_pitch_rows":artifact.get("raw_pitch_rows"),"raw_rows_sha256":artifact.get("raw_rows_sha256"),"coverage":coverage,"request_chunks":len(artifact.get("requests") or []),"point_in_time":True,"stable_id_only":True,"champion_impact":False,"auto_activation":False,"artifact_path":str(target)}
    rp=Path(report_path);rp.parent.mkdir(parents=True,exist_ok=True);rp.write_text(json.dumps(report,ensure_ascii=False,indent=2,sort_keys=True)+"\n",encoding="utf-8");return report


def main()->None:
    parser=argparse.ArgumentParser(description="Refresh enriched V14 rolling Statcast priors")
    parser.add_argument("--cutoff",required=True);parser.add_argument("--lookback-days",type=int,default=45);parser.add_argument("--priors",default=str(DEFAULT_PRIORS));parser.add_argument("--report",default=str(DEFAULT_REPORT));args=parser.parse_args()
    out=refresh(args.cutoff,lookback_days=args.lookback_days,priors_path=args.priors,report_path=args.report);print(json.dumps(out,sort_keys=True))


if __name__=="__main__":main()
