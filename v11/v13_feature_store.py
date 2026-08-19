from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from . import journal
from . import point_in_time_v13 as pit
from .probability_contract_v13 import row_is_predictively_compatible

FEATURES_OUT=Path("data/v13_feature_store.jsonl")
LABELS_OUT=Path("data/v13_label_store.jsonl")
FEATURE_SCHEMA="v13-pit-feature-store-v1"
LABEL_SCHEMA="v13-label-store-v1"


def _key(r: dict[str,Any]) -> tuple[str,str,str,str]:
    return (str(r.get("game_pk") or ""),str(r.get("analyzed_at") or r.get("as_of") or ""),
            str(r.get("phase") or "EARLY").upper(),str(r.get("model_generation") or r.get("model_generation_fingerprint") or ""))


def _feature_row(r: dict[str,Any]) -> dict[str,Any] | None:
    if not row_is_predictively_compatible(r):return None
    valid,reasons=pit.validate_pregame_row(r)
    if not valid:return None
    ctx=r.get("ctx") or {}
    features=r.get("features") or {}
    return {
        "schema":FEATURE_SCHEMA,
        "game_pk":r.get("game_pk"),"game_date":r.get("game_date"),"as_of":r.get("analyzed_at") or r.get("as_of"),
        "phase":str(r.get("phase") or "EARLY").upper(),
        "model_generation":r.get("model_generation") or r.get("model_generation_fingerprint"),
        "feature_contract":((r.get("predictive_contract") or {}).get("feature_contract_version")),
        "point_in_time":True,"point_in_time_validation_reasons":reasons,
        "home":r.get("home") or ctx.get("home"),"away":r.get("away") or ctx.get("away"),
        "context":{
            "home_id":ctx.get("home_id"),"away_id":ctx.get("away_id"),
            "home_sp":ctx.get("home_sp"),"away_sp":ctx.get("away_sp"),
            "home_starter":ctx.get("home_starter"),"away_starter":ctx.get("away_starter"),
            "home_lineup":ctx.get("home_lineup"),"away_lineup":ctx.get("away_lineup"),
        },
        # Persist the values seen by the model, not the post-game label. Nested
        # operational/weather/bullpen payloads retain player IDs and raw inputs
        # when the live engine collected them.
        "features":features,
        "rich_modules":((r.get("shadow_v124") or {}).get("modules") or {}),
        "feature_provenance":r.get("feature_provenance") or {},
        "data_quality":r.get("data_quality") or {},
    }


def _label_row(r: dict[str,Any]) -> dict[str,Any] | None:
    if r.get("result_status")!="FINAL" or r.get("home_score") is None or r.get("away_score") is None:return None
    if not r.get("game_pk"):return None
    return {"schema":LABEL_SCHEMA,"game_pk":r.get("game_pk"),"game_date":r.get("game_date"),
            "home":r.get("home") or ((r.get("ctx") or {}).get("home")),"away":r.get("away") or ((r.get("ctx") or {}).get("away")),
            "home_score":r.get("home_score"),"away_score":r.get("away_score"),"winner":r.get("winner"),
            "settled_at":r.get("settled_at"),"label_source":"settled MLB result; never part of pregame feature payload"}


def build(rows: list[dict[str,Any]] | None=None) -> tuple[list[dict[str,Any]],list[dict[str,Any]],dict[str,Any]]:
    rows=journal.load_rows() if rows is None else rows
    features={};labels={}
    rejected={}
    for r in rows:
        f=_feature_row(r)
        if f is not None:
            features[_key(r)]=f
        else:
            if row_is_predictively_compatible(r):
                valid,reasons=pit.validate_pregame_row(r)
                if not valid:
                    for reason in reasons:rejected[reason]=rejected.get(reason,0)+1
        label=_label_row(r)
        if label is not None:
            gid=str(label["game_pk"]);rank=str(label.get("settled_at") or r.get("analyzed_at") or "")
            if gid not in labels or rank>labels[gid][0]:labels[gid]=(rank,label)
    fs=[features[k] for k in sorted(features,key=lambda x:(x[1],x[0],x[2],x[3]))]
    ls=[x[1] for x in sorted(labels.values(),key=lambda z:str(z[1].get("game_date") or ""))]
    report={"feature_rows":len(fs),"unique_feature_games":len({str(x.get('game_pk')) for x in fs}),
            "label_rows":len(ls),"feature_rejection_reasons":dict(sorted(rejected.items())),
            "separation_policy":"feature store contains no home_score/away_score/winner; labels are written to a separate store"}
    return fs,ls,report


def _write_jsonl(path: Path,rows):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text("\n".join(json.dumps(x,ensure_ascii=False,separators=(",",":"),sort_keys=True) for x in rows)+("\n" if rows else ""),encoding="utf-8")


def main():
    fs,ls,report=build();_write_jsonl(FEATURES_OUT,fs);_write_jsonl(LABELS_OUT,ls)
    print(json.dumps(report,ensure_ascii=False,indent=2,sort_keys=True))


if __name__=="__main__":main()
