from __future__ import annotations

"""Point-in-time selector for V14 contextual feature-store rows."""

from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any, Iterable


def _parse_time(value: Any) -> datetime | None:
    if value is None:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except Exception:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def feature_row_is_usable(row: dict[str, Any] | None, *, game_pk: Any, as_of: Any) -> bool:
    if not isinstance(row, dict):
        return False
    if str(row.get("game_pk") or "") != str(game_pk or ""):
        return False
    if row.get("point_in_time") is not True:
        return False
    if row.get("point_in_time_validation_reasons"):
        return False
    if (row.get("data_quality") or {}).get("eligible") is False:
        return False
    cutoff = _parse_time(as_of)
    observed = _parse_time(row.get("as_of") or row.get("analyzed_at"))
    if cutoff is None or observed is None or observed > cutoff:
        return False
    return True


def iter_feature_rows(path: Path | str) -> Iterable[dict[str, Any]]:
    path = Path(path)
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except Exception:
            continue
        if isinstance(row, dict):
            yield row


def load_latest_feature_row(path: Path | str, *, game_pk: Any, as_of: Any) -> dict[str, Any] | None:
    best: tuple[datetime, dict[str, Any]] | None = None
    for row in iter_feature_rows(path):
        if not feature_row_is_usable(row, game_pk=game_pk, as_of=as_of):
            continue
        observed = _parse_time(row.get("as_of") or row.get("analyzed_at"))
        if observed is None:
            continue
        if best is None or observed > best[0]:
            best = (observed, row)
    return best[1] if best else None


def compact_feature_identity(row: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(row, dict):
        return {"available": False}
    return {
        "available": True,
        "schema": row.get("schema"),
        "game_pk": row.get("game_pk"),
        "as_of": row.get("as_of") or row.get("analyzed_at"),
        "phase": row.get("phase"),
        "model_generation": row.get("model_generation"),
        "feature_contract": row.get("feature_contract"),
        "point_in_time": row.get("point_in_time") is True,
    }
