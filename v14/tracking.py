from __future__ import annotations

"""Native prediction tracking and settlement for Pulsar V14."""

import argparse
from collections import defaultdict
from datetime import datetime, timezone
import json
import math
from pathlib import Path
from typing import Any, Callable

from . import MODEL_GENERATION
from .acquisition import mlb_schedule, parse_time
from .pick_tracking import load_pick_performance

PREDICTIONS = Path("data/v14_predictions.jsonl")
PERFORMANCE = Path("data/v14_performance.json")


def _num(value: Any) -> float | None:
    try:
        out = float(value)
    except Exception:
        return None
    return out if math.isfinite(out) else None


def _read_jsonl(path: Path | str) -> list[dict[str, Any]]:
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
        if isinstance(row, dict):
            rows.append(row)
    return rows


def _write_jsonl(path: Path | str, rows: list[dict[str, Any]]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("".join(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n" for row in rows), encoding="utf-8")


def _is_strictly_pregame(row: dict[str, Any]) -> bool:
    try:
        return parse_time(row.get("analyzed_at")) < parse_time(row.get("game_date"))
    except Exception:
        return False


def snapshot_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    if payload.get("model_generation") != MODEL_GENERATION:
        raise ValueError("tracking only accepts current V14 generation")
    target_date = str(payload.get("target_date") or "")
    rows: list[dict[str, Any]] = []
    for result in payload.get("results") or []:
        prediction = result.get("v14_prediction") or {}
        if prediction.get("model_generation") != MODEL_GENERATION:
            raise ValueError(f"game {result.get('game_pk')} is not current V14")
        analyzed_at = result.get("analyzed_at") or payload.get("analyzed_at")
        game_date = result.get("game_date")
        probe = {"analyzed_at": analyzed_at, "game_date": game_date}
        if not _is_strictly_pregame(probe):
            raise ValueError(f"game {result.get('game_pk')} tracking snapshot is not strictly pregame")
        probabilities = prediction.get("probabilities") or {}
        raw_probabilities = prediction.get("raw_probabilities") or probabilities
        projection = prediction.get("run_projection") or {}
        total_line = _num(projection.get("total_line"))
        if total_line is None:
            total_line = _num((result.get("canonical_lines") or {}).get("TOTAL"))
        keys = ("home_ml", "away_ml", "home_minus_1_5", "away_plus_1_5", "away_minus_1_5", "home_plus_1_5", "over", "under")
        rows.append({
            "schema": "pulsar-v14-prediction-record-v4",
            "model_generation": MODEL_GENERATION,
            "game_pk": str(result.get("game_pk") or ""),
            "target_date": target_date or str(game_date or "")[:10],
            "game_date": game_date,
            "analyzed_at": analyzed_at,
            "phase": result.get("phase") or prediction.get("phase"),
            "home": result.get("home"), "away": result.get("away"),
            "home_mu": _num(projection.get("home_mu")), "away_mu": _num(projection.get("away_mu")),
            "total_line": total_line,
            "probabilities": {key: _num(probabilities.get(key)) for key in keys},
            "raw_probabilities": {key: _num(raw_probabilities.get(key)) for key in keys},
            "calibration": prediction.get("calibration") or {},
            "probability_intervals": prediction.get("probability_intervals") or {},
            "market_snapshot": result.get("market_snapshot") or {},
            "market_diagnostics": result.get("market_diagnostics") or {},
            "sharp_market": result.get("sharp_market") or {},
            "decision": result.get("decision") or {},
            "training_features": result.get("training_features") or {},
            "starter_fallback": result.get("starter_fallback") or {},
            "settled": False, "home_score": None, "away_score": None, "settled_at": None,
        })
    return rows


def append_snapshot(payload: dict[str, Any], path: Path | str = PREDICTIONS) -> int:
    existing = _read_jsonl(path)
    index = {(str(row.get("game_pk") or ""), str(row.get("analyzed_at") or "")): row for row in existing}
    before = len(index)
    for row in snapshot_rows(payload):
        key=(str(row.get("game_pk") or ""), str(row.get("analyzed_at") or ""))
        previous=index.get(key)
        # Never erase settlement state when re-snapshotting the exact same PIT row.
        if previous and previous.get("settled"):
            row["settled"]=True; row["home_score"]=previous.get("home_score"); row["away_score"]=previous.get("away_score"); row["settled_at"]=previous.get("settled_at")
        index[key] = row
    ordered = sorted(index.values(), key=lambda row: (str(row.get("target_date") or ""), str(row.get("game_pk") or ""), str(row.get("analyzed_at") or "")))
    _write_jsonl(path, ordered)
    return len(index) - before


def _final_scores(game: dict[str, Any]) -> tuple[int, int] | None:
    status = ((game.get("status") or {}).get("abstractGameState") or "").lower()
    detailed = ((game.get("status") or {}).get("detailedState") or "").lower()
    if status != "final" and "final" not in detailed and "completed" not in detailed:
        return None
    teams = game.get("teams") or {}
    home = _num((teams.get("home") or {}).get("score")); away = _num((teams.get("away") or {}).get("score"))
    if home is None or away is None:
        return None
    return int(home), int(away)


def settle_predictions(path: Path | str = PREDICTIONS, *, schedule_loader: Callable[[str], list[dict[str, Any]]] | None = None) -> int:
    rows = _read_jsonl(path)
    loader = schedule_loader or (lambda day: mlb_schedule(day, hydrate="linescore"))
    by_day: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        if not row.get("settled"):
            by_day[str(row.get("target_date") or "")].append(row)
    settled = 0; now = datetime.now(timezone.utc).isoformat()
    for day, pending in by_day.items():
        if not day:
            continue
        games = {str(game.get("gamePk") or ""): game for game in loader(day)}
        for row in pending:
            game = games.get(str(row.get("game_pk") or "")); scores = _final_scores(game or {}) if game else None
            if scores is None:
                continue
            row["home_score"], row["away_score"] = scores
            row["settled"] = True; row["settled_at"] = now; settled += 1
    _write_jsonl(path, rows)
    return settled


def _calibration(items: list[tuple[float,int]], bins: int=10) -> list[dict[str,Any]]:
    grouped=[[] for _ in range(bins)]
    for p,y in items: grouped[min(bins-1,max(0,int(p*bins)))].append((p,y))
    return [{"lower":i/bins,"upper":(i+1)/bins,"n":len(v),"mean_probability":sum(p for p,_ in v)/len(v),"observed_rate":sum(y for _,y in v)/len(v)} for i,v in enumerate(grouped) if v]


def _binary_metrics(items: list[tuple[float, int]]) -> dict[str, Any]:
    if not items:
        return {"n": 0, "brier": None, "log_loss": None, "accuracy_50": None, "mean_probability": None, "observed_rate": None, "ece": None}
    eps = 1e-12
    calibration=_calibration(items)
    ece=sum((row["n"]/len(items))*abs(row["mean_probability"]-row["observed_rate"]) for row in calibration)
    return {
        "n": len(items),
        "brier": sum((p-y)**2 for p,y in items)/len(items),
        "log_loss": -sum(y*math.log(max(eps,min(1-eps,p)))+(1-y)*math.log(max(eps,min(1-eps,1-p))) for p,y in items)/len(items),
        "accuracy_50": sum((p>=.5)==bool(y) for p,y in items)/len(items),
        "mean_probability": sum(p for p,_ in items)/len(items),
        "observed_rate": sum(y for _,y in items)/len(items),
        "ece": ece,
    }


def _canonical_settled(rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], int]:
    settled_records=[r for r in rows if r.get("settled") and r.get("model_generation")==MODEL_GENERATION and _is_strictly_pregame(r)]
    latest: dict[str,dict[str,Any]]={}
    for row in settled_records:
        key=str(row.get("game_pk") or ""); cur=latest.get(key)
        if cur is None or parse_time(row.get("analyzed_at")) > parse_time(cur.get("analyzed_at")): latest[key]=row
    return sorted(latest.values(), key=lambda r:(str(r.get("target_date") or ""),str(r.get("game_pk") or ""))), len(settled_records)


def _price(row: dict[str, Any], market: str, selection: str) -> float | None:
    markets=((row.get("market_snapshot") or {}).get("markets") or {})
    return _num((((markets.get(market) or {}).get("selections") or {}).get(selection) or {}).get("price"))


def _sharp_probability(row: dict[str, Any], selection: str) -> float | None:
    return _num((((row.get("sharp_market") or {}).get("selections") or {}).get(selection) or {}).get("fair_probability"))


def _market_movement_proxy(rows: list[dict[str, Any]]) -> dict[str, Any]:
    by_game: dict[str,list[dict[str,Any]]]=defaultdict(list)
    for row in rows:
        if row.get("model_generation")==MODEL_GENERATION and _is_strictly_pregame(row): by_game[str(row.get("game_pk") or "")].append(row)
    diffs=[]
    for game_rows in by_game.values():
        ordered=sorted(game_rows,key=lambda r:parse_time(r.get("analyzed_at")))
        if len(ordered)<2: continue
        close=ordered[-1]
        for early in ordered[:-1]:
            for market,selection in (("ML","home"),("ML","away"),("TOTAL","over"),("TOTAL","under")):
                old,new=_price(early,market,selection),_price(close,market,selection)
                if old and new and old>1 and new>1: diffs.append((1/new-1/old)*100)
    return {"status":"AVAILABLE_PROXY" if diffs else "UNAVAILABLE","definition":"market-wide movement to latest persisted pregame price; not bet CLV","n":len(diffs),"mean_implied_probability_move_pp":sum(diffs)/len(diffs) if diffs else None}


def performance_report(rows: list[dict[str, Any]]) -> dict[str, Any]:
    settled, settled_record_count=_canonical_settled(rows)
    markets: dict[str,list[tuple[float,int]]]=defaultdict(list); sharp_markets: dict[str,list[tuple[float,int]]]=defaultdict(list); run_errors=[]; total_errors=[]
    for row in settled:
        hs=int(row["home_score"]); aws=int(row["away_score"]); probs=row.get("probabilities") or {}; line=_num(row.get("total_line"))
        vals=(("ML","home_ml","home_ml",int(hs>aws)),("RL_HOME_-1.5","home_minus_1_5","home_minus_1_5",int(hs-aws>=2)),("RL_AWAY_-1.5","away_minus_1_5","away_minus_1_5",int(aws-hs>=2)))
        for name,key,sharp_key,y in vals:
            p=_num(probs.get(key))
            if p is not None: markets[name].append((p,y))
            sp=_sharp_probability(row,sharp_key)
            if sp is not None: sharp_markets[name].append((sp,y))
        over=_num(probs.get("over"))
        if over is not None and line is not None: markets["TOTAL_OVER"].append((over,int(hs+aws>line)))
        sharp_over=_sharp_probability(row,"over")
        if sharp_over is not None and line is not None: sharp_markets["TOTAL_OVER"].append((sharp_over,int(hs+aws>line)))
        hmu,amu=_num(row.get("home_mu")),_num(row.get("away_mu"))
        if hmu is not None and amu is not None:
            run_errors.extend((abs(hmu-hs),abs(amu-aws))); total_errors.append(abs(hmu+amu-hs-aws))
    all_items=[item for values in markets.values() for item in values]; overall=_binary_metrics(all_items); overall["interpretation"]="dashboard-only; correlated markets must not drive model promotion"
    market_report={}
    for name,values in sorted(markets.items()):
        model_metrics=_binary_metrics(values); model_metrics["calibration"]=_calibration(values); sharp_metrics=_binary_metrics(sharp_markets.get(name,[]))
        if sharp_metrics.get("n"):
            sharp_block={**sharp_metrics,"brier_gain_vs_sharp":float(sharp_metrics["brier"])-float(model_metrics["brier"]),"logloss_gain_vs_sharp":float(sharp_metrics["log_loss"])-float(model_metrics["log_loss"])}
        else:
            sharp_block={**sharp_metrics,"brier_gain_vs_sharp":None,"logloss_gain_vs_sharp":None}
        model_metrics["sharp_benchmark"]=sharp_block; market_report[name]=model_metrics
    return {
        "schema":"pulsar-v14-performance-v4","model_generation":MODEL_GENERATION,"generated_at":datetime.now(timezone.utc).isoformat(),
        "prediction_records_settled":settled_record_count,"games_settled":len(settled),"canonical_snapshot_policy":"latest strictly-pregame snapshot per game",
        "overall":overall,"calibration":_calibration(all_items),"markets":market_report,
        "runs":{"team_run_mae":sum(run_errors)/len(run_errors) if run_errors else None,"total_run_mae":sum(total_errors)/len(total_errors) if total_errors else None},
        "roi":{"status":"UNAVAILABLE","reason":"No official bet/stake ledger in V14 analytics-only production."},
        "clv":{"status":"UNAVAILABLE","n":0,"mean_clv":None,"reason":"No official bet ledger plus canonical closing-price feed; market movement proxy is reported separately."},
        "market_movement_proxy":_market_movement_proxy(rows),
    }


def write_performance(path: Path | str=PREDICTIONS, report_path: Path | str=PERFORMANCE) -> dict[str,Any]:
    report=performance_report(_read_jsonl(path)); report["selection_feedback"] = load_pick_performance()
    try:
        from .certification import evaluate as evaluate_certification
        from .probability_calibration import load_artifact
        report["betting_certification"]=evaluate_certification(report,load_artifact())
    except Exception as exc:
        report["betting_certification"]={"certified":False,"betting_status":"RESEARCH_ONLY","reasons":[f"certification_error:{type(exc).__name__}"]}
    target=Path(report_path); target.parent.mkdir(parents=True,exist_ok=True); target.write_text(json.dumps(report,ensure_ascii=False,indent=2,sort_keys=True)+"\n",encoding="utf-8"); return report


def main() -> None:
    parser=argparse.ArgumentParser(description="Pulsar V14 native prediction tracking"); sub=parser.add_subparsers(dest="command",required=True)
    snap=sub.add_parser("snapshot"); snap.add_argument("--payload",default="runtime/v14/discord_payload.json"); snap.add_argument("--predictions",default=str(PREDICTIONS))
    settle=sub.add_parser("settle"); settle.add_argument("--predictions",default=str(PREDICTIONS)); settle.add_argument("--report",default=str(PERFORMANCE))
    report_cmd=sub.add_parser("report"); report_cmd.add_argument("--predictions",default=str(PREDICTIONS)); report_cmd.add_argument("--report",default=str(PERFORMANCE))
    args=parser.parse_args()
    if args.command=="snapshot":
        payload=json.loads(Path(args.payload).read_text(encoding="utf-8")); added=append_snapshot(payload,args.predictions); print(f"PULSAR_V14_TRACKING snapshot_added={added}")
    elif args.command=="settle":
        settled=settle_predictions(args.predictions); report=write_performance(args.predictions,args.report); print(f"PULSAR_V14_TRACKING settled={settled} games={report['games_settled']}")
    else:
        report=write_performance(args.predictions,args.report); print(f"PULSAR_V14_TRACKING report games={report['games_settled']}")

if __name__=="__main__": main()
