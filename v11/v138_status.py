from __future__ import annotations

from .v138_audit_closure import build


def summary():
    d=build()
    return {k:d.get(k) for k in ("total_points","engineering_closed","engineering_open","overall_closed","evidence_gates_pending")}
