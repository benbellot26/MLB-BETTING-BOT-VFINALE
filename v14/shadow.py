from __future__ import annotations

import argparse
from datetime import datetime
import json
from pathlib import Path
from typing import Any

from . import MODEL_GENERATION
from .benchmark import CHAMPION_GENERATION, benchmark_payload
from .champion_contract import parameters_from_champion_result
from .distribution import probability_surface
from .model import RunProjection, shadow_payload

DEFAULT_PAYLOAD = Path("runtime/v11/discord_payload.json")
DEFAULT_JOURNAL = Path("data/v11_3_live.jsonl")
DEFAULT_OUTPUT = Path("data/v14_shadow_predictions.jsonl")


def _dt(value: Any):
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except Exception:
        return None


def _num(value: Any):
    try:
        return float(value)
    except Exception:
        return None


def _total_line(result: dict[str, Any]) -> float | None:
    candidates = []
    for opt in result.get("options") or []:
        if str(opt.get("market") or "").upper() != "TOTAL":
            continue
        if str(opt.get("name") or "").lower() != "over":
            continue
        point = _num(opt.get("point"))
        if point is None:
            continue
        half_line = abs(point * 2 - round(point * 2)) <= 1e-9 and round(point * 2) % 2 == 1
        if half_line:
            candidates.append((0 if opt.get("is_canonical_line") else 1, abs(point - 8.5), point))
    return sorted(candidates)[0][2] if candidates else None


def projection_from_v13_result(result: dict[str, Any], *, analyzed_at: str | None = None) -> RunProjection:
    """Parity-migration adapter for the frozen V13.10 champion.

    Until the V13 run stack has been cleanly reimplemented inside V14, the
    champion run means are accepted as migration inputs. The only additional
    state allowed across the boundary is the score-distribution configuration
    required to reproduce V13.10 behavior. V13 probabilities, market values,
    calibration outputs, selectors and staking decisions remain forbidden model
    inputs.
    """
    ctx = result.get("ctx") or {}
    game = result.get("game") or {}
    event = result.get("event") or {}
    game_date = result.get("game_date") or game.get("gameDate") or event.get("commence_time")
    observed = result.get("analyzed_at") or result.get("as_of") or analyzed_at
    home_mu = _num(result.get("hmu"))
    away_mu = _num(result.get("amu"))
    for key in ("home_mu", "projected_home_runs"):
        if home_mu is None:
            home_mu = _num(result.get(key))
    for key in ("away_mu", "projected_away_runs"):
        if away_mu is None:
            away_mu = _num(result.get(key))
    line = _total_line(result)
    if home_mu is None or away_mu is None:
        raise ValueError("V14 parity shadow requires explicit V13.10 home/away run means")
    if line is None:
        raise ValueError("V14 parity shadow requires a canonical half-run total line")
    if not observed or not game_date:
        raise ValueError("V14 parity shadow requires analyzed_at and game_date")
    obs_dt, game_dt = _dt(observed), _dt(game_date)
    if obs_dt is None or game_dt is None or obs_dt >= game_dt:
        raise ValueError("V14 parity input must be a valid pregame snapshot")

    parameters = parameters_from_champion_result(result)
    return RunProjection(
        game_pk=str(result.get("game_pk") or game.get("gamePk") or ""),
        game_date=str(game_date), analyzed_at=str(observed),
        home=str(ctx.get("home") or result.get("home") or ""),
        away=str(ctx.get("away") or result.get("away") or ""),
        home_mu=home_mu, away_mu=away_mu, total_line=line,
        phase=str(result.get("phase") or "FINAL"),
        dispersion=parameters["dispersion"],
        environment_sigma=parameters["environment_sigma"],
        extra_innings_home_probability=parameters["extra_innings_home_probability"],
        source_generation=result.get("model_generation"),
    ).validated()


def build_shadow(result: dict[str, Any], *, analyzed_at: str | None = None) -> dict[str, Any]:
    projection = projection_from_v13_result(result, analyzed_at=analyzed_at)
    surface, tail = probability_surface(projection)
    out = shadow_payload(projection, surface, tail_mass=tail)
    out["transition_adapter"] = (
        "V13.10 champion run means + score-distribution configuration only; "
        "V13 probabilities/market/calibration/selection/staking are forbidden V14 model inputs"
    )
    out["parity_migration"] = {
        "target": CHAMPION_GENERATION,
        "run_stack_native_in_v14": False,
        "score_distribution_native_in_v14": True,
        "purpose": "preserve champion performance before legacy removal",
    }
    if result.get("model_generation") == CHAMPION_GENERATION:
        out["champion_reference"] = benchmark_payload(result, total_line=projection.total_line)
    else:
        out["champion_reference"] = {
            "role": "UNAVAILABLE_NON_CHAMPION_GENERATION",
            "source_generation": result.get("model_generation"),
            "used_as_v14_model_input": False,
        }
    return out


def _key(row: dict[str, Any]) -> tuple[str, str, str]:
    return str(row.get("game_pk") or ""), str(row.get("phase") or ""), str(row.get("analyzed_at") or "")


def write_shadows(rows: list[dict[str, Any]], path: Path = DEFAULT_OUTPUT) -> int:
    existing: dict[tuple[str, str, str], dict[str, Any]] = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                row = json.loads(line)
                if isinstance(row, dict) and row.get("model_generation") == MODEL_GENERATION:
                    existing[_key(row)] = row
            except Exception:
                continue
    before = len(existing)
    for row in rows:
        existing[_key(row)] = row
    ordered = sorted(existing.values(), key=lambda r: (str(r.get("game_date") or ""), str(r.get("game_pk") or ""), str(r.get("analyzed_at") or "")))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n" for row in ordered), encoding="utf-8")
    return len(existing) - before


def run_results(results: list[dict[str, Any]], *, analyzed_at: str | None = None,
                strict: bool = False, champion_only: bool = False) -> dict[str, Any]:
    built, skipped = [], []
    for result in results:
        if champion_only and result.get("model_generation") != CHAMPION_GENERATION:
            continue
        try:
            built.append(build_shadow(result, analyzed_at=analyzed_at))
        except Exception as exc:
            skipped.append({"game_pk": result.get("game_pk"), "reason": str(exc)})
    if strict and skipped:
        raise ValueError(f"V14 strict shadow rejected inputs: {skipped[:3]}")
    return {"rows": built, "skipped": skipped, "shadow_only": True, "affects_production": False}


def run_payload(payload: dict[str, Any], *, strict: bool = False) -> dict[str, Any]:
    report = payload.get("report") or {}
    analyzed_at = report.get("analyzed_at") or report.get("as_of")
    return run_results(list(payload.get("results") or []), analyzed_at=analyzed_at, strict=strict)


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
            if isinstance(row, dict):
                rows.append(row)
        except Exception:
            continue
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description="Build V14 V13.10-champion-parity shadows from persisted pregame state")
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--payload", default=None)
    source.add_argument("--journal", default=None)
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--strict", action="store_true")
    args = parser.parse_args()

    if args.journal:
        rows = _read_jsonl(Path(args.journal))
        result = run_results(rows, strict=args.strict, champion_only=True)
    else:
        payload_path = Path(args.payload) if args.payload else DEFAULT_PAYLOAD
        if not payload_path.exists():
            print(json.dumps({"written": 0, "skipped": [{"reason": "payload absent"}], "shadow_only": True}))
            return
        payload = json.loads(payload_path.read_text(encoding="utf-8"))
        result = run_payload(payload, strict=args.strict)

    written = write_shadows(result["rows"], Path(args.output)) if result["rows"] else 0
    print(json.dumps({"built": len(result["rows"]), "written": written, "skipped": result["skipped"],
                      "shadow_only": True, "affects_production": False}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
