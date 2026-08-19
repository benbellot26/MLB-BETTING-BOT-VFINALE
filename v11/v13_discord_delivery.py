from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

FILE=Path("data/v13_discord_delivery.json")
SCHEMA="v13-discord-delivery-v1"


def load(path: Path=FILE) -> dict[str,Any]:
    if not path.exists():return {"schema":SCHEMA,"games":{}}
    try:
        d=json.loads(path.read_text(encoding="utf-8"))
        if d.get("schema")!=SCHEMA:return {"schema":SCHEMA,"games":{}}
        d.setdefault("games",{})
        return d
    except Exception:return {"schema":SCHEMA,"games":{}}


def key(game_pk: Any) -> str:
    return str(game_pk or "")


def sent(game_pk: Any,path: Path=FILE) -> bool:
    k=key(game_pk)
    return bool(k and (load(path).get("games") or {}).get(k,{}).get("sent"))


def mark_sent(game_pk: Any, *, phase: str | None=None, model_generation: str | None=None,
              sent_at: str | None=None, path: Path=FILE) -> dict[str,Any]:
    k=key(game_pk)
    if not k:raise ValueError("game_pk required for Discord delivery checkpoint")
    d=load(path);games=d.setdefault("games",{})
    games[k]={"sent":True,"sent_at":sent_at or datetime.now(timezone.utc).isoformat(),
              "phase":str(phase or ""),"model_generation":model_generation}
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(d,ensure_ascii=False,indent=2,sort_keys=True),encoding="utf-8")
    return games[k]
