from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

FILE=Path("data/v13_discord_delivery.json")
SCHEMA="v13-discord-delivery-v2"
LEGACY_SCHEMA="v13-discord-delivery-v1"


def load(path: Path=FILE) -> dict[str,Any]:
    if not path.exists():return {"schema":SCHEMA,"games":{}}
    try:
        d=json.loads(path.read_text(encoding="utf-8"))
        if d.get("schema") not in {SCHEMA,LEGACY_SCHEMA}:return {"schema":SCHEMA,"games":{}}
        d["schema"]=SCHEMA
        d.setdefault("games",{})
        return d
    except Exception:return {"schema":SCHEMA,"games":{}}


def key(game_pk: Any) -> str:
    return str(game_pk or "")


def record(game_pk: Any,path: Path=FILE) -> dict[str,Any]:
    return dict((load(path).get("games") or {}).get(key(game_pk),{}) or {})


def sent(game_pk: Any,path: Path=FILE) -> bool:
    k=key(game_pk)
    return bool(k and record(k,path).get("sent"))


def delivery_decision(game_pk: Any,current_result: dict[str,Any] | None=None,path: Path=FILE) -> dict[str,Any]:
    """Suppress true duplicates but permit a material starter/lineup correction."""
    previous=record(game_pk,path)
    if not previous.get("sent"):
        return {"send":True,"reason":"NOT_SENT","critical_change":False,"previous":previous}
    if current_result is None:
        return {"send":False,"reason":"ALREADY_SENT","critical_change":False,"previous":previous}
    try:
        from . import v138_live_change
        change=v138_live_change.classify(previous,current_result)
    except Exception:
        return {"send":False,"reason":"ALREADY_SENT_CHANGE_CHECK_FAILED","critical_change":False,"previous":previous}
    if change.get("critical"):
        return {"send":True,"reason":str(change.get("reason") or "CRITICAL_CHANGE"),"critical_change":True,
                "previous":previous,"change":change}
    return {"send":False,"reason":str(change.get("reason") or "ALREADY_SENT"),"critical_change":False,
            "previous":previous,"change":change}


def mark_sent(game_pk: Any, *, phase: str | None=None, model_generation: str | None=None,
              sent_at: str | None=None, analysis_signature: str | None=None,
              personnel_state: dict[str,Any] | None=None, delivery_reason: str | None=None,
              path: Path=FILE) -> dict[str,Any]:
    k=key(game_pk)
    if not k:raise ValueError("game_pk required for Discord delivery checkpoint")
    d=load(path);games=d.setdefault("games",{});prior=dict(games.get(k) or {})
    history=list(prior.get("history") or [])
    if prior.get("sent_at"):
        history.append({x:prior.get(x) for x in ("sent_at","phase","model_generation","analysis_signature","delivery_reason")})
        history=history[-10:]
    games[k]={"sent":True,"sent_at":sent_at or datetime.now(timezone.utc).isoformat(),
              "phase":str(phase or ""),"model_generation":model_generation,
              "analysis_signature":analysis_signature,"personnel_state":personnel_state or {},
              "delivery_reason":delivery_reason or "NORMAL","history":history}
    d["schema"]=SCHEMA
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(d,ensure_ascii=False,indent=2,sort_keys=True),encoding="utf-8")
    return games[k]
