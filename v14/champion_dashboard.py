from __future__ import annotations

"""Single longitudinal, read-only V14 champion dashboard.

The dashboard aggregates already-authoritative artifacts. It never certifies,
authorizes, settles or fabricates a wager. Missing samples stay missing.
"""

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any

from . import MODEL_GENERATION, PROBABILITY_POLICY_ID, VERSION

DEFAULT_OUTPUT_JSON = Path("data/v14_champion_dashboard.json")
DEFAULT_OUTPUT_MD = Path("data/v14_champion_dashboard.md")
DEFAULT_HISTORY = Path("data/v14_champion_dashboard_history.jsonl")

ARTIFACTS = {
    "performance": Path("data/v14_performance.json"),
    "certification": Path("data/v14_betting_certification.json"),
    "paper": Path("data/v14_paper_bet_performance.json"),
    "authorized": Path("data/v14_bet_performance.json"),
    "sharp": Path("data/v14_sharp_benchmark_report.json"),
    "coverage": Path("data/v14_coverage_report.json"),
    "data_quality": Path("data/v14_data_quality_dashboard.json"),
    "research": Path("data/v14_research_diagnostics.json"),
    "promotion": Path("data/v14_promotion_guard.json"),
}


def _load(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return value if isinstance(value, dict) else None


def _first(mapping: dict[str, Any] | None, *paths: str) -> Any:
    if not mapping:
        return None
    for dotted in paths:
        value: Any = mapping
        ok = True
        for part in dotted.split("."):
            if not isinstance(value, dict) or part not in value:
                ok = False
                break
            value = value[part]
        if ok and value is not None:
            return value
    return None


def _market_summary(certification: dict[str, Any] | None) -> dict[str, Any]:
    if not certification:
        return {}
    raw = certification.get("markets") or certification.get("market_status") or {}
    if not isinstance(raw, dict):
        return {}
    out: dict[str, Any] = {}
    for market, row in raw.items():
        if not isinstance(row, dict):
            continue
        failures = row.get("failures") or row.get("betting_failures") or []
        out[str(market)] = {
            "certified": bool(row.get("certified") or row.get("betting_certified")),
            "n": _first(row, "n", "model.n", "performance.n"),
            "ece": _first(row, "ece", "model.ece", "performance.ece"),
            "failures": list(failures) if isinstance(failures, list) else [],
        }
    return out


def _execution_summary(paper: dict[str, Any] | None, authorized: dict[str, Any] | None) -> dict[str, Any]:
    return {
        "paper": {
            "observations": _first(paper, "observations", "n", "settled"),
            "independent_games": _first(paper, "independent_games"),
            "primary_clv_mean": _first(paper, "primary_clv.mean", "clv.primary.mean", "clv_mean"),
            "execution_clv_mean": _first(paper, "execution_clv.mean", "clv.execution.mean"),
        },
        "authorized_hypothetical": {
            "bets": _first(authorized, "bets", "n"),
            "settled": _first(authorized, "settled"),
            "roi": _first(authorized, "roi", "roi_fraction"),
        },
        "interpretation": (
            "Paper/system-authorized outcomes are not user-realized ROI. "
            "Execution quality must be evaluated separately from prediction quality."
        ),
    }


def build_dashboard(artifact_paths: dict[str, Path] | None = None) -> dict[str, Any]:
    paths = artifact_paths or ARTIFACTS
    artifacts = {name: _load(path) for name, path in paths.items()}
    cert = artifacts.get("certification")
    performance = artifacts.get("performance")
    research = artifacts.get("research")
    data_quality = artifacts.get("data_quality")
    paper = artifacts.get("paper")
    authorized = artifacts.get("authorized")

    betting_status = _first(cert, "betting_status") or "UNKNOWN"
    probability_status = _first(cert, "probability_status") or _first(performance, "status") or "UNKNOWN"
    independent_games = _first(research, "evidence_health.independent_games")
    if independent_games is None:
        independent_games = _first(performance, "independent_games", "games", "n")

    return {
        "schema": "pulsar-v14-champion-dashboard-v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "software_version": VERSION,
        "model_generation": MODEL_GENERATION,
        "probability_policy_id": PROBABILITY_POLICY_ID,
        "authoritative_status": {
            "probability_status": probability_status,
            "betting_status": betting_status,
            "certified": bool(_first(cert, "certified")) if cert else False,
            "source": "data/v14_betting_certification.json",
        },
        "sample_maturity": {
            "independent_games": independent_games,
            "sample_size_is_not_certification": True,
            "research_maturity": _first(research, "evidence_health.maturity"),
        },
        "market_certification": _market_summary(cert),
        "prediction_quality": {
            "performance": performance,
            "baseline_and_regime_diagnostics": research,
            "sharp_benchmark": artifacts.get("sharp"),
        },
        "execution_and_clv": _execution_summary(paper, authorized),
        "coverage_and_data_quality": {
            "coverage": artifacts.get("coverage"),
            "data_quality": data_quality,
        },
        "research_governance": {
            "promotion_guard": artifacts.get("promotion"),
            "champion_impact": False,
        },
        "artifact_availability": {
            name: {"path": str(paths[name]), "available": artifacts[name] is not None}
            for name in paths
        },
        "guardrails": [
            "No sample-size threshold alone certifies betting.",
            "No dashboard field authorizes a wager; certification remains authoritative.",
            "Missing ROI/CLV stays null rather than being inferred.",
            "Champion, paper/system-authorized and real execution evidence remain distinct.",
        ],
    }


def _history_row(report: dict[str, Any]) -> dict[str, Any]:
    markets = report.get("market_certification") or {}
    return {
        "schema": "pulsar-v14-champion-dashboard-history-v1",
        "date": str(report.get("generated_at") or "")[:10],
        "generated_at": report.get("generated_at"),
        "software_version": report.get("software_version"),
        "model_generation": report.get("model_generation"),
        "probability_policy_id": report.get("probability_policy_id"),
        "betting_status": (report.get("authoritative_status") or {}).get("betting_status"),
        "certified": (report.get("authoritative_status") or {}).get("certified"),
        "independent_games": (report.get("sample_maturity") or {}).get("independent_games"),
        "paper_observations": ((report.get("execution_and_clv") or {}).get("paper") or {}).get("observations"),
        "primary_clv_mean": ((report.get("execution_and_clv") or {}).get("paper") or {}).get("primary_clv_mean"),
        "execution_clv_mean": ((report.get("execution_and_clv") or {}).get("paper") or {}).get("execution_clv_mean"),
        "authorized_bets": ((report.get("execution_and_clv") or {}).get("authorized_hypothetical") or {}).get("bets"),
        "hypothetical_roi": ((report.get("execution_and_clv") or {}).get("authorized_hypothetical") or {}).get("roi"),
        "markets": {
            name: {"n": row.get("n"), "ece": row.get("ece"), "certified": row.get("certified")}
            for name, row in markets.items()
        },
    }


def update_history(report: dict[str, Any], path: Path | str = DEFAULT_HISTORY, *, keep: int = 400) -> list[dict[str, Any]]:
    """Persist one canonical dashboard snapshot per UTC calendar day."""
    target = Path(path)
    rows: list[dict[str, Any]] = []
    if target.exists():
        for line in target.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except Exception:
                continue
            if isinstance(row, dict):
                rows.append(row)
    current = _history_row(report)
    by_date = {str(row.get("date") or ""): row for row in rows if row.get("date")}
    if current.get("date"):
        by_date[str(current["date"])] = current
    ordered = [by_date[key] for key in sorted(by_date)][-max(1, int(keep)):]
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        "".join(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n" for row in ordered),
        encoding="utf-8",
    )
    return ordered


def _fmt(value: Any) -> str:
    if value is None:
        return "—"
    if isinstance(value, float):
        return f"{value:.4f}"
    return str(value)


def render_markdown(report: dict[str, Any]) -> str:
    status = report["authoritative_status"]
    maturity = report["sample_maturity"]
    lines = [
        "# Pulsar V14 Champion Dashboard",
        "",
        f"- Software: **V{report['software_version']}**",
        f"- Generation: `{report['model_generation']}`",
        f"- Probability policy: `{report['probability_policy_id']}`",
        f"- Betting status: **{status['betting_status']}**",
        f"- Probability status: **{status['probability_status']}**",
        f"- Independent current-policy games: **{_fmt(maturity.get('independent_games'))}**",
        "",
        "## Market certification",
        "",
        "| Market | Certified | n | ECE | Main blockers |",
        "|---|---:|---:|---:|---|",
    ]
    markets = report.get("market_certification") or {}
    if markets:
        for market, row in sorted(markets.items()):
            failures = ", ".join((row.get("failures") or [])[:4]) or "—"
            lines.append(
                f"| {market} | {'yes' if row.get('certified') else 'no'} | "
                f"{_fmt(row.get('n'))} | {_fmt(row.get('ece'))} | {failures} |"
            )
    else:
        lines.append("| — | no | — | — | certification artifact unavailable |")

    execution = report["execution_and_clv"]
    lines += [
        "",
        "## Execution / CLV",
        "",
        f"- Paper observations: **{_fmt(execution['paper'].get('observations'))}**",
        f"- Paper independent games: **{_fmt(execution['paper'].get('independent_games'))}**",
        f"- PRIMARY CLV mean: **{_fmt(execution['paper'].get('primary_clv_mean'))}**",
        f"- EXECUTION CLV mean: **{_fmt(execution['paper'].get('execution_clv_mean'))}**",
        f"- System-authorized hypothetical bets: **{_fmt(execution['authorized_hypothetical'].get('bets'))}**",
        f"- Hypothetical ROI: **{_fmt(execution['authorized_hypothetical'].get('roi'))}**",
        "",
        "## Longitudinal history",
        "",
        f"- Daily snapshots retained: **{len(report.get('longitudinal_history') or [])}**",
        "",
        "## Interpretation",
        "",
        "Sample size is context, not a pass button. Read calibration, proper-score gain vs sharp, "
        "prospective CLV, confidence intervals, temporal/regime stability and execution quality together.",
        "",
        "> This dashboard is read-only. `data/v14_betting_certification.json` remains the authoritative betting gate.",
        "",
    ]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the unified read-only V14 champion dashboard")
    parser.add_argument("--json", default=str(DEFAULT_OUTPUT_JSON))
    parser.add_argument("--markdown", default=str(DEFAULT_OUTPUT_MD))
    parser.add_argument("--history", default=str(DEFAULT_HISTORY))
    args = parser.parse_args()
    report = build_dashboard()
    report["longitudinal_history"] = update_history(report, args.history)
    json_path = Path(args.json)
    md_path = Path(args.markdown)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    md_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    md_path.write_text(render_markdown(report), encoding="utf-8")
    print(json.dumps({"json": str(json_path), "markdown": str(md_path), "betting_status": report["authoritative_status"]["betting_status"]}, sort_keys=True))


if __name__ == "__main__":
    main()
