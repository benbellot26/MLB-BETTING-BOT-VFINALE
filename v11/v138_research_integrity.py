from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

MANIFEST = Path("data/v138_dataset_manifest.json")
MODEL = Path("data/v138_research_models.json")
VALIDATION = Path("data/v138_validation.json")
SCHEMA = "v13-10-research-dataset-integrity-v1"


def _load(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise RuntimeError(f"invalid JSON artifact {path}: {type(exc).__name__}") from exc


def _write(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


def bind(
    manifest_path: Path = MANIFEST,
    model_path: Path = MODEL,
    validation_path: Path = VALIDATION,
) -> dict[str, Any]:
    """Bind research results to a SHA256 of the actual feature/label source bytes.

    The historical ``dataset_fingerprint`` inside the research artifact is kept
    for backward compatibility, but it is no longer accepted as the sole data
    identity because it did not include every feature value. The versioned
    dataset manifest hashes each compressed source file byte-for-byte; this
    binding copies that strong identity into every report that can be used to
    interpret research model performance.
    """
    manifest = _load(manifest_path)
    content_hash = str(manifest.get("dataset_content_sha256") or "")
    if len(content_hash) != 64:
        raise RuntimeError("dataset manifest missing strong dataset_content_sha256")
    feature_rows = int(manifest.get("feature_rows") or 0)
    label_rows = int(manifest.get("label_rows") or 0)
    if feature_rows <= 0 or label_rows <= 0:
        raise RuntimeError("dataset manifest has no feature/label rows")

    bound = []
    for path, kind in ((model_path, "research_model"), (validation_path, "validation")):
        payload = _load(path)
        if not payload:
            raise RuntimeError(f"required research artifact missing: {path}")
        games = int(payload.get("games") or 0)
        if games and games != feature_rows:
            raise RuntimeError(f"{kind} row-count mismatch: artifact={games} manifest={feature_rows}")
        legacy = payload.get("dataset_fingerprint")
        payload["dataset_content_sha256"] = content_hash
        payload["dataset_integrity"] = {
            "schema": SCHEMA,
            "bound": True,
            "source": str(manifest_path),
            "feature_rows": feature_rows,
            "label_rows": label_rows,
            "content_sha256": content_hash,
            "feature_contract_sha256": manifest.get("feature_contract_sha256"),
            "legacy_identity_fingerprint": legacy,
            "legacy_identity_fingerprint_sufficient": False,
            "policy": "model/validation evidence is bound to SHA256 of every compressed source feature/label file",
        }
        _write(path, payload)
        bound.append(str(path))
    return {
        "schema": SCHEMA,
        "dataset_content_sha256": content_hash,
        "feature_rows": feature_rows,
        "label_rows": label_rows,
        "bound_artifacts": bound,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Bind V13 research artifacts to strong dataset content identity")
    parser.add_argument("--manifest", default=str(MANIFEST))
    parser.add_argument("--model", default=str(MODEL))
    parser.add_argument("--validation", default=str(VALIDATION))
    args = parser.parse_args()
    report = bind(Path(args.manifest), Path(args.model), Path(args.validation))
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
