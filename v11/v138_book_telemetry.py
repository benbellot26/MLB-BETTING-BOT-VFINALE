from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import core, market

FILE=Path(os.getenv("V138_BOOK_TELEMETRY_FILE","data/v138_book_probabilities.jsonl"))
SCHEMA="v13-8-book-probability-telemetry-v1"


def _norm(v: Any) -> str:
    return "".join(c.lower() for c in str(v or "") if c.isalnum())


def _canonical_option(result: dict[str,Any], option: dict[str,Any]) -> bool:
    m=str(option.get("market") or "").upper();name=str(option.get("name") or "")
    home=str((result.get("ctx") or {}).get("home") or "")
    if m=="ML":return _norm(name)==_norm(home)
    if m=="RUNLINE":return bool(option.get("is_canonical_line")) and _norm(name)==_norm(home)
    if m=="TOTAL":return bool(option.get("is_canonical_line")) and name.lower()=="over"
    return False


def capture(results: list[dict[str,Any]] | None, observed_at: str | None=None) -> int:
    """Persist one canonical per-book no-vig probability row per game/market snapshot.

    This is market telemetry only. It never feeds the baseball feature path and
    does not change the currently configured sharp consensus weights.
    """
    at=observed_at or datetime.now(timezone.utc).isoformat();rows=[]
    for result in results or []:
        event=result.get("event") or {};ctx=result.get("ctx") or {};as_of=str(result.get("as_of") or at)
        for option in result.get("options") or []:
            if not _canonical_option(result,option):continue
            m=str(option.get("market") or "").upper();name=option.get("name");point=option.get("point")
            try:cons=market.sharp_consensus(event,m,name,point,as_of=as_of)
            except Exception:cons={}
            probs=dict(cons.get("book_probs") or {})
            if not probs:continue
            rows.append({"schema":SCHEMA,"game_pk":str(result.get("game_pk") or ""),
                "game_date":((result.get("game") or {}).get("gameDate") or (event.get("commence_time"))),
                "home":ctx.get("home"),"away":ctx.get("away"),"market":m,"pick":name,"point":point,
                "phase":str(result.get("phase") or "EARLY").upper(),"observation_at":as_of,"recorded_at":at,
                "canonical":True,"p_model":option.get("p_baseball_calibrated",option.get("p_effective")),
                "p_market":option.get("p_market"),"book_probs":probs,"book_ages_min":cons.get("book_ages_min") or {},
                "market_probability_only":True,"baseball_feature":False})
    if not rows:return 0
    FILE.parent.mkdir(parents=True,exist_ok=True)
    with FILE.open("a",encoding="utf-8") as f:
        for row in rows:f.write(json.dumps(row,ensure_ascii=False,sort_keys=True,separators=(",",":"))+"\n")
    return len(rows)


def read(path: Path=FILE) -> list[dict[str,Any]]:
    if not path.exists():return []
    out=[]
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():continue
        try:
            row=json.loads(line)
            if isinstance(row,dict) and row.get("schema")==SCHEMA:out.append(row)
        except Exception:pass
    return out
