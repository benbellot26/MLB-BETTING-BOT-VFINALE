from __future__ import annotations

"""Run the V14 contextual residual layer in strict shadow mode."""

import argparse
import json
from pathlib import Path
from typing import Any

from .context_overlay import context_overlay_from_feature_row
from .distribution import probability_surface
from .feature_row import compact_feature_identity, feature_row_is_usable, load_latest_feature_row
from .model import RunProjection, shadow_payload
from .shadow import projection_from_v13_result

CONTEXT_SHADOW_SCHEMA = "v14-context-shadow-v1"
DEFAULT_PAYLOAD = Path("runtime/v11/discord_payload.json")
DEFAULT_JOURNAL = Path("data/v11_3_live.jsonl")
DEFAULT_FEATURE_STORE = Path("data/v13_feature_store.jsonl")
DEFAULT_OUTPUT = Path("data/v14_context_shadow.jsonl")


def build_context_shadow(result: dict[str, Any], *, feature_row: dict[str, Any] | None = None, feature_store: Path | str = DEFAULT_FEATURE_STORE, analyzed_at: str | None = None) -> dict[str, Any]:
    base = projection_from_v13_result(result, analyzed_at=analyzed_at)
    if feature_row is not None:
        selected = feature_row if feature_row_is_usable(feature_row, game_pk=base.game_pk, as_of=base.analyzed_at) else None
    else:
        selected = load_latest_feature_row(feature_store, game_pk=base.game_pk, as_of=base.analyzed_at)

    overlay = context_overlay_from_feature_row(selected, base.home_mu, base.away_mu)
    contextual = RunProjection(
        game_pk=base.game_pk, game_date=base.game_date, analyzed_at=base.analyzed_at,
        home=base.home, away=base.away, home_mu=overlay["home_mu"], away_mu=overlay["away_mu"],
        total_line=base.total_line, phase=base.phase, dispersion=base.dispersion,
        environment_sigma=base.environment_sigma,
        extra_innings_home_probability=base.extra_innings_home_probability,
        source_generation=base.source_generation,
    ).validated()
    surface, tail = probability_surface(contextual)
    out = shadow_payload(contextual, surface, tail_mass=tail)
    out["schema"] = CONTEXT_SHADOW_SCHEMA
    out["software_version"] = "PULSAR_V14_CONTEXT_SHADOW"
    out["role"] = "SHADOW_ONLY"
    out["affects_production"] = False
    out["market_probability_used_as_feature"] = False
    out["transition_adapter"] = "Frozen V13.10 champion run means plus a tightly capped PIT contextual residual. No V13 probability, bookmaker probability, selector or staking decision is accepted as a V14 predictive feature."
    out["champion_reference"] = {"game_pk": base.game_pk, "home_mu": base.home_mu, "away_mu": base.away_mu, "source_generation": base.source_generation, "used_as_context_baseline": True}
    out["feature_row"] = compact_feature_identity(selected)
    out["context_overlay"] = overlay
    out["parity_migration"] = {"v13_10_remains_production_champion": True, "contextual_layer_promoted": False, "promotion_requires_out_of_sample_evidence": True}
    return out


def run_context_results(results: list[dict[str, Any]], *, feature_store: Path | str = DEFAULT_FEATURE_STORE, analyzed_at: str | None = None, strict: bool = False) -> dict[str, Any]:
    built, skipped = [], []
    for result in results:
        try:
            built.append(build_context_shadow(result, feature_store=feature_store, analyzed_at=analyzed_at))
        except Exception as exc:
            skipped.append({"game_pk": result.get("game_pk"), "reason": str(exc)})
    if strict and skipped:
        raise ValueError(f"V14 contextual shadow rejected inputs: {skipped[:3]}")
    return {"rows": built, "skipped": skipped, "shadow_only": True, "affects_production": False}


def run_payload(payload: dict[str, Any], *, feature_store: Path | str = DEFAULT_FEATURE_STORE, strict: bool = False) -> dict[str, Any]:
    report = payload.get("report") or {}
    analyzed_at = report.get("analyzed_at") or report.get("as_of")
    return run_context_results(list(payload.get("results") or []), feature_store=feature_store, analyzed_at=analyzed_at, strict=strict)


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except Exception:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def _key(row: dict[str, Any]) -> tuple[str, str, str]:
    return str(row.get("game_pk") or ""), str(row.get("phase") or ""), str(row.get("analyzed_at") or "")


def write_context_shadows(rows: list[dict[str, Any]], path: Path | str = DEFAULT_OUTPUT) -> int:
    target = Path(path)
    existing: dict[tuple[str, str, str], dict[str, Any]] = {}
    if target.exists():
        for row in _read_jsonl(target):
            if row.get("schema") == CONTEXT_SHADOW_SCHEMA:
                existing[_key(row)] = row
    before = len(existing)
    for row in rows:
        existing[_key(row)] = row
    ordered = sorted(existing.values(), key=lambda row: (str(row.get("game_date") or ""), str(row.get("game_pk") or ""), str(row.get("analyzed_at") or "")))
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("".join(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n" for row in ordered), encoding="utf-8")
    return len(existing) - before


def main() -> None:
    parser = argparse.ArgumentParser(description="Build isolated V14 contextual shadow predictions from V13.10 pregame state")
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--payload", default=None)
    source.add_argument("--journal", default=None)
    parser.add_argument("--feature-store", default=str(DEFAULT_FEATURE_STORE))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--strict", action="store_true")
    args = parser.parse_args()

    feature_store = Path(args.feature_store)
    if args.journal:
        result = run_context_results(_read_jsonl(Path(args.journal)), feature_store=feature_store, strict=args.strict)
    else:
        payload_path = Path(args.payload) if args.payload else DEFAULT_PAYLOAD
        if not payload_path.exists():
            print(json.dumps({"built": 0, "written": 0, "skipped": [{"reason": "payload absent"}], "shadow_only": True, "affects_production": False}, ensure_ascii=False, indent=2))
            return
        payload = json.loads(payload_path.read_text(encoding="utf-8"))
        result = run_payload(payload, feature_store=feature_store, strict=args.strict)

    written = write_context_shadows(result["rows"], Path(args.output)) if result["rows"] else 0
    print(json.dumps({"built": len(result["rows"]), "written": written, "skipped": result["skipped"], "shadow_only": True, "affects_production": False, "feature_store": str(feature_store), "output": str(args.output)}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
