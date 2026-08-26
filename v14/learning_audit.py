from __future__ import annotations

"""Standalone audit entrypoint for Pulsar controlled learning."""

import argparse
import json
from pathlib import Path

from . import MODEL_GENERATION
from .governance import promotion_contract
from .learning import learning_report

DEFAULT_PREDICTIONS = Path("data/v14_predictions.jsonl")
DEFAULT_REPORT = Path("data/v14_learning_report.json")
DEFAULT_REGISTRY = Path("data/v14_model_registry.json")


def _read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    rows=[]
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            value=json.loads(line)
        except Exception:
            continue
        if isinstance(value,dict): rows.append(value)
    return rows


def _validate_registry(path: Path) -> dict:
    registry=json.loads(path.read_text(encoding="utf-8"))
    champion=registry.get("champion") or {}
    governance=registry.get("governance") or {}
    if champion.get("model_generation") != MODEL_GENERATION:
        raise RuntimeError("model registry champion does not match production generation")
    if champion.get("status") != "PRODUCTION":
        raise RuntimeError("model registry champion is not PRODUCTION")
    if governance.get("automatic_promotion") is not False:
        raise RuntimeError("automatic promotion must remain disabled")
    if governance.get("automatic_production_mutation") is not False:
        raise RuntimeError("automatic production mutation must remain disabled")
    return registry


def build_audit(predictions: Path=DEFAULT_PREDICTIONS, registry_path: Path=DEFAULT_REGISTRY) -> dict:
    registry=_validate_registry(registry_path)
    report=learning_report(_read_jsonl(predictions),MODEL_GENERATION)
    return {
        "schema":"pulsar-v14-learning-audit-v1",
        "champion":registry["champion"],
        "challenger":registry.get("challenger"),
        "controlled_learning":report,
        "promotion_contract":promotion_contract(),
        "production_changed":False,
    }


def main() -> None:
    parser=argparse.ArgumentParser(description="Pulsar V14 controlled-learning audit")
    parser.add_argument("--predictions",default=str(DEFAULT_PREDICTIONS))
    parser.add_argument("--registry",default=str(DEFAULT_REGISTRY))
    parser.add_argument("--output",default=str(DEFAULT_REPORT))
    args=parser.parse_args()
    audit=build_audit(Path(args.predictions),Path(args.registry))
    target=Path(args.output); target.parent.mkdir(parents=True,exist_ok=True)
    target.write_text(json.dumps(audit,ensure_ascii=False,indent=2,sort_keys=True)+"\n",encoding="utf-8")
    print(f"PULSAR_V14_LEARNING stage={audit['controlled_learning']['stage']} games={audit['controlled_learning']['games']} production_changed=false")


if __name__=="__main__": main()
