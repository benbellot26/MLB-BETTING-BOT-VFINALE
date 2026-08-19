from __future__ import annotations

from typing import Any


def validate_optional_provider(name: str,payload: dict[str,Any] | None,required_fields: tuple[str,...]=()) -> dict[str,Any]:
    """Optional context is neutral when absent, invalid when falsely marked available."""
    p=payload or {}
    if not p:
        return {"provider":name,"status":"UNAVAILABLE_NEUTRAL","usable":False}
    if p.get("available") is False:
        return {"provider":name,"status":"UNAVAILABLE_NEUTRAL","usable":False,"reason":p.get("reason")}
    missing=[k for k in required_fields if p.get(k) is None]
    if missing:
        return {"provider":name,"status":"INVALID_FAIL_CLOSED","usable":False,"missing":missing}
    return {"provider":name,"status":"READY","usable":True}


def validate_point_in_time(payload: dict[str,Any] | None) -> dict[str,Any]:
    p=payload or {}
    if not p:return {"usable":False,"status":"UNAVAILABLE_NEUTRAL"}
    if p.get("point_in_time") is not True:return {"usable":False,"status":"INVALID_NOT_POINT_IN_TIME"}
    return {"usable":True,"status":"READY"}
