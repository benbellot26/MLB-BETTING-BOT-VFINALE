from __future__ import annotations

"""Explicit real-execution ledger for Pulsar V14.

This module is deliberately never populated by the prediction runtime. A row is
accepted only from an explicit execution confirmation (manual tracker/importer
or a future authenticated bookmaker integration). This keeps model-authorized
bets separate from money actually wagered.
"""

from datetime import datetime, timezone
import json
import math
from pathlib import Path
from typing import Any

from . import MODEL_GENERATION

LEDGER=Path("data/v14_executed_bet_ledger.jsonl")


def _num(value:Any)->float|None:
    try: out=float(value)
    except Exception: return None
    return out if math.isfinite(out) else None


def _read(path:Path|str=LEDGER)->list[dict[str,Any]]:
    target=Path(path)
    if not target.exists(): return []
    rows=[]
    for line in target.read_text(encoding="utf-8").splitlines():
        if not line.strip(): continue
        try: row=json.loads(line)
        except Exception: continue
        if isinstance(row,dict) and row.get("schema")=="pulsar-v14-executed-bet-v1": rows.append(row)
    return rows


def _write(rows:list[dict[str,Any]],path:Path|str=LEDGER)->None:
    target=Path(path); target.parent.mkdir(parents=True,exist_ok=True)
    target.write_text("".join(json.dumps(row,ensure_ascii=False,separators=(",",":"))+"\n" for row in rows),encoding="utf-8")


def record_execution(execution:dict[str,Any],path:Path|str=LEDGER)->bool:
    """Persist one explicitly confirmed real-money execution.

    Required identity: authorized_bet_id/game_pk/canonical_market/selection.
    Required execution facts: executed_at, bookmaker, odds and either stake_units
    or stake_cash. The function never infers these values from an authorized bet.
    """
    required=("authorized_bet_id","game_pk","canonical_market","selection","executed_at","bookmaker")
    if any(not str(execution.get(key) or "") for key in required): raise ValueError("missing required real-execution identity")
    odds=_num(execution.get("odds")); stake_units=_num(execution.get("stake_units")); stake_cash=_num(execution.get("stake_cash"))
    if odds is None or odds<=1: raise ValueError("real execution odds must be > 1")
    if (stake_units is None or stake_units<=0) and (stake_cash is None or stake_cash<=0): raise ValueError("real execution requires positive stake_units or stake_cash")
    try:
        executed_at=datetime.fromisoformat(str(execution["executed_at"]).replace("Z","+00:00"))
        if executed_at.tzinfo is None: executed_at=executed_at.replace(tzinfo=timezone.utc)
    except Exception as exc: raise ValueError("invalid executed_at") from exc
    rows=_read(path); execution_id=str(execution.get("execution_id") or execution["authorized_bet_id"])
    if any(str(row.get("execution_id") or "")==execution_id for row in rows): return False
    row={"schema":"pulsar-v14-executed-bet-v1","ledger_role":"REAL_EXECUTION","execution_confirmed":True,"execution_id":execution_id,"authorized_bet_id":str(execution["authorized_bet_id"]),"model_generation":str(execution.get("model_generation") or MODEL_GENERATION),"game_pk":str(execution["game_pk"]),"canonical_market":str(execution["canonical_market"]),"selection":str(execution["selection"]),"line":execution.get("line"),"executed_at":executed_at.astimezone(timezone.utc).isoformat(),"bookmaker":str(execution["bookmaker"]),"odds":float(odds),"stake_units":float(stake_units) if stake_units is not None else None,"stake_cash":float(stake_cash) if stake_cash is not None else None,"unit_value":_num(execution.get("unit_value")),"source":str(execution.get("source") or "EXPLICIT_CONFIRMATION"),"result":execution.get("result"),"return_cash":_num(execution.get("return_cash")),"profit_cash":_num(execution.get("profit_cash")),"profit_units":_num(execution.get("profit_units"))}
    rows.append(row); rows.sort(key=lambda r:(str(r.get("executed_at") or ""),str(r.get("execution_id") or ""))); _write(rows,path); return True


def report(rows:list[dict[str,Any]])->dict[str,Any]:
    confirmed=[row for row in rows if row.get("execution_confirmed") is True]; settled=[row for row in confirmed if row.get("result") in {"WIN","LOSS","PUSH"}]
    profit_cash=sum(float(_num(row.get("profit_cash")) or 0) for row in settled); stake_cash=sum(float(_num(row.get("stake_cash")) or 0) for row in settled if row.get("result")!="PUSH"); profit_units=sum(float(_num(row.get("profit_units")) or 0) for row in settled)
    return {"schema":"pulsar-v14-executed-bet-performance-v1","ledger_role":"REAL_EXECUTION","execution_confirmed":True,"bets":len(confirmed),"settled":len(settled),"profit_cash":profit_cash,"profit_units":profit_units,"cash_roi":profit_cash/stake_cash if stake_cash else None,"note":"Only explicitly confirmed real-money executions are included."}
