from __future__ import annotations

"""Immutable official-bet ledger for Pulsar V14.

Rows are created only from statistically certified BET decisions. The ledger is
kept separate from user-reported outcomes. A game/market can be entered only
once, so repeated EARLY/LATE/FINAL snapshots cannot accidentally duplicate a
real wager. Closing prices are captured prospectively and never fabricated.
"""

import argparse
from collections import defaultdict
from datetime import datetime, timezone
import json
import math
from pathlib import Path
from typing import Any, Callable

from .acquisition import mlb_schedule
from .staking import size_candidates

LEDGER = Path("data/v14_bet_ledger.jsonl")
REPORT = Path("data/v14_bet_performance.json")


def _num(value: Any) -> float | None:
    try:
        out = float(value)
    except Exception:
        return None
    return out if math.isfinite(out) else None


def _read(path: Path | str = LEDGER) -> list[dict[str, Any]]:
    target = Path(path)
    if not target.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in target.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except Exception:
            continue
        if isinstance(row, dict) and row.get("schema") in {"pulsar-v14-official-bet-v1","pulsar-v14-official-bet-v2"}:
            rows.append(row)
    return rows


def _write(rows: list[dict[str, Any]], path: Path | str = LEDGER) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        "".join(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n" for row in rows),
        encoding="utf-8",
    )


def _execution_book(result: dict[str, Any], market: str) -> str | None:
    return ((((result.get("market_snapshot") or {}).get("markets") or {}).get(market) or {}).get("bookmaker"))


def _canonical_market(candidate:dict[str,Any])->str:
    explicit=str(candidate.get("canonical_market") or "")
    if explicit: return explicit
    market=str(candidate.get("market") or "")
    selection=str(candidate.get("selection") or "")
    if market=="TOTAL": return "TOTAL_OVER"
    if market=="ML": return "ML"
    if selection in {"home_minus_1_5","away_plus_1_5"}: return "RL_HOME_-1.5"
    if selection in {"away_minus_1_5","home_plus_1_5"}: return "RL_AWAY_-1.5"
    return market or selection


def _existing_market_key(row:dict[str,Any])->tuple[str,str]:
    market=str(row.get("canonical_market") or "")
    if not market:
        market=_canonical_market({"market":row.get("market"),"selection":row.get("selection")})
    return str(row.get("game_pk") or ""),market


def record_payload(payload: dict[str, Any], path: Path | str = LEDGER) -> int:
    certification = payload.get("betting_certification") or {}
    if certification.get("certified") is not True:
        return 0

    rows = _read(path)
    occupied={_existing_market_key(row) for row in rows}
    added=0

    for result in payload.get("results") or []:
        if (result.get("starter_fallback") or {}).get("degraded"):
            continue
        decision = result.get("decision") or {}
        sized = size_candidates(list(decision.get("candidates") or []), certified=True)
        prediction = result.get("v14_prediction") or {}
        raw = prediction.get("raw_probabilities") or prediction.get("probabilities") or {}
        sharp = (result.get("sharp_market") or {}).get("selections") or {}

        for candidate in sized:
            if candidate.get("status") != "BET" or float(candidate.get("stake_fraction") or 0) <= 0:
                continue
            selection = str(candidate.get("selection") or "")
            market = str(candidate.get("market") or "")
            canonical_market=_canonical_market(candidate)
            game_pk=str(result.get("game_pk") or "")
            market_key=(game_pk,canonical_market)
            if market_key in occupied:
                continue
            analyzed_at = str(result.get("analyzed_at") or payload.get("analyzed_at") or "")
            execution_book=candidate.get("execution_book") or _execution_book(result,market)
            line=(result.get("canonical_lines") or {}).get("TOTAL") if market=="TOTAL" else None
            rows.append({
                "schema": "pulsar-v14-official-bet-v2",
                "bet_id": f"{game_pk}:{canonical_market}",
                "model_generation": payload.get("model_generation"),
                "game_pk": game_pk,
                "odds_event_id": result.get("odds_event_id"),
                "target_date": str(payload.get("target_date") or ""),
                "game_date": result.get("game_date"),
                "analyzed_at": analyzed_at,
                "home": result.get("home"),
                "away": result.get("away"),
                "market": market,
                "canonical_market": canonical_market,
                "selection": selection,
                "line": line,
                "bookmaker": execution_book,
                "execution_source": candidate.get("execution_source"),
                "odds": candidate.get("price"),
                "probability": candidate.get("probability"),
                "raw_probability": _num(raw.get(selection)),
                "lower_probability": candidate.get("lower_probability"),
                "sharp_probability": _num((sharp.get(selection) or {}).get("fair_probability")),
                "model_edge_pp": candidate.get("model_edge_pp"),
                "robust_edge_pp": candidate.get("robust_edge_pp"),
                "stake_fraction": candidate.get("stake_fraction"),
                "unit_tier": candidate.get("unit_tier"),
                "result": None,
                "profit_stake_units": None,
                "home_score": None,
                "away_score": None,
                "settled_at": None,
                "close_history": [],
                "close_quality": None,
                "close_minutes_to_game": None,
                "close_captured_at": None,
                "closing_odds": None,
                "closing_source": None,
                "clv_implied_probability_pp": None,
                "sharp_fair_close_probability": None,
                "sharp_information_clv_pp": None,
                "execution_close_odds": None,
                "execution_price_clv_pp": None,
                "certification_snapshot": certification,
            })
            occupied.add(market_key); added+=1

    rows.sort(key=lambda row:(str(row.get("game_date") or row.get("target_date") or ""),str(row.get("game_pk") or ""),str(row.get("canonical_market") or ""),str(row.get("analyzed_at") or "")))
    _write(rows,path)
    return added


def _grade(selection: str, home_score: int, away_score: int, line: float | None) -> str:
    if selection == "home_ml": return "WIN" if home_score > away_score else "LOSS"
    if selection == "away_ml": return "WIN" if away_score > home_score else "LOSS"
    if selection == "home_minus_1_5": return "WIN" if home_score - away_score >= 2 else "LOSS"
    if selection == "away_plus_1_5": return "WIN" if home_score - away_score <= 1 else "LOSS"
    if selection == "away_minus_1_5": return "WIN" if away_score - home_score >= 2 else "LOSS"
    if selection == "home_plus_1_5": return "WIN" if away_score - home_score <= 1 else "LOSS"
    if selection == "over" and line is not None:
        total=home_score+away_score; return "WIN" if total>line else ("PUSH" if total==line else "LOSS")
    if selection == "under" and line is not None:
        total=home_score+away_score; return "WIN" if total<line else ("PUSH" if total==line else "LOSS")
    return "UNRESOLVED"


def settle(path: Path | str = LEDGER, *, schedule_loader: Callable[[str], list[dict[str, Any]]] | None = None) -> int:
    rows = _read(path); loader = schedule_loader or (lambda day: mlb_schedule(day, hydrate="linescore")); pending: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        if not row.get("result"): pending[str(row.get("target_date") or "")].append(row)
    now=datetime.now(timezone.utc).isoformat(); count=0
    for day,items in pending.items():
        if not day: continue
        games={str(game.get("gamePk") or ""):game for game in loader(day)}
        for row in items:
            game=games.get(str(row.get("game_pk") or "")); status=str(((game or {}).get("status") or {}).get("abstractGameState") or "").lower()
            if status!="final": continue
            teams=(game or {}).get("teams") or {}; home_score=_num((teams.get("home") or {}).get("score")); away_score=_num((teams.get("away") or {}).get("score"))
            if home_score is None or away_score is None: continue
            result=_grade(str(row.get("selection") or ""),int(home_score),int(away_score),_num(row.get("line")))
            if result=="UNRESOLVED": continue
            odds=float(row.get("odds") or 0); profit=(odds-1.0) if result=="WIN" else (-1.0 if result=="LOSS" else 0.0)
            row.update({"result":result,"profit_stake_units":profit,"home_score":int(home_score),"away_score":int(away_score),"settled_at":now}); count+=1
    _write(rows,path); return count


def attach_closing_price(*,game_pk:str,selection:str,analyzed_at:str,closing_odds:float,source:str,path:Path|str=LEDGER)->bool:
    """Compatibility/manual close attachment; explicit values only."""
    odds=float(closing_odds)
    if odds<=1: raise ValueError("closing_odds must be > 1")
    rows=_read(path); changed=False
    for row in rows:
        if str(row.get("game_pk"))==str(game_pk) and str(row.get("selection"))==str(selection) and str(row.get("analyzed_at"))==str(analyzed_at):
            entry=float(row.get("odds") or 0); row["closing_odds"]=odds; row["closing_source"]=str(source); row["clv_implied_probability_pp"]=(1/odds-1/entry)*100 if entry>1 else None; changed=True
    if changed: _write(rows,path)
    return changed


def _clv_summary(values:list[float])->dict[str,Any]:
    return {"status":"AVAILABLE" if values else "UNAVAILABLE","n":len(values),"mean_clv":sum(values)/len(values) if values else None}


def report(rows: list[dict[str, Any]]) -> dict[str, Any]:
    settled_rows=[row for row in rows if row.get("result") in {"WIN","LOSS","PUSH"}]; decisions=[row for row in settled_rows if row.get("result")!="PUSH"]
    profit=sum(float(row.get("profit_stake_units") or 0)*float(row.get("stake_fraction") or 0) for row in settled_rows); staked=sum(float(row.get("stake_fraction") or 0) for row in decisions)
    sharp=[_num(row.get("sharp_information_clv_pp") if row.get("sharp_information_clv_pp") is not None else row.get("clv_implied_probability_pp")) for row in rows if row.get("close_quality") in {None,"CERTIFIED_CLOSE"}]; sharp=[v for v in sharp if v is not None]
    execution=[_num(row.get("execution_price_clv_pp")) for row in rows if row.get("close_quality")=="CERTIFIED_CLOSE"]; execution=[v for v in execution if v is not None]
    by_market={}
    for market in sorted({str(row.get("canonical_market") or "") for row in rows if row.get("canonical_market")}):
        subset=[row for row in rows if str(row.get("canonical_market"))==market]; settled=[row for row in subset if row.get("result") in {"WIN","LOSS","PUSH"}]; market_profit=sum(float(row.get("profit_stake_units") or 0)*float(row.get("stake_fraction") or 0) for row in settled); market_staked=sum(float(row.get("stake_fraction") or 0) for row in settled if row.get("result")!="PUSH"); by_market[market]={"bets":len(subset),"settled":len(settled),"roi":market_profit/market_staked if market_staked else None}
    return {"schema":"pulsar-v14-official-bet-performance-v2","bets":len(rows),"settled":len(settled_rows),"wins":sum(row.get("result")=="WIN" for row in settled_rows),"losses":sum(row.get("result")=="LOSS" for row in settled_rows),"pushes":sum(row.get("result")=="PUSH" for row in settled_rows),"profit_bankroll_fraction":profit,"staked_bankroll_fraction":staked,"roi":profit/staked if staked else None,"sharp_information_clv":_clv_summary(sharp),"execution_clv":_clv_summary(execution),"clv":{**_clv_summary(sharp),"definition":"compatibility alias for sharp-information CLV; use execution_clv for tradable price quality"},"by_market":by_market,"dedupe_policy":"one official bet per game x canonical market"}


def write_report(path:Path|str=LEDGER,output:Path|str=REPORT)->dict[str,Any]:
    out=report(_read(path)); target=Path(output); target.parent.mkdir(parents=True,exist_ok=True); target.write_text(json.dumps(out,ensure_ascii=False,indent=2,sort_keys=True)+"\n",encoding="utf-8"); return out


def main()->None:
    parser=argparse.ArgumentParser(); sub=parser.add_subparsers(dest="cmd",required=True); record=sub.add_parser("record"); record.add_argument("--payload",default="runtime/v14/discord_payload.json"); record.add_argument("--ledger",default=str(LEDGER)); settle_parser=sub.add_parser("settle"); settle_parser.add_argument("--ledger",default=str(LEDGER)); settle_parser.add_argument("--report",default=str(REPORT)); args=parser.parse_args()
    if args.cmd=="record":
        payload=json.loads(Path(args.payload).read_text(encoding="utf-8")); print(f"PULSAR_V14_BET_LEDGER added={record_payload(payload,args.ledger)}")
    else:
        settled_n=settle(args.ledger); out=write_report(args.ledger,args.report); print(f"PULSAR_V14_BET_LEDGER settled={settled_n} bets={out['bets']}")


if __name__=="__main__": main()
