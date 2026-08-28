from __future__ import annotations

"""Strict historical point-in-time dataset loader for V14 research.

This module intentionally consumes only immutable, pre-existing V137 feature
rows and separately stored labels. It never calls live MLB season endpoints
while reconstructing old games.

The current-season files are refreshed by the free-data collector.  A manifest
created before the most recent refresh may therefore temporarily differ only on
the newest season.  That state is accepted for research *only* after the full
row-level PIT audit passes, is reported explicitly as unverified, and is healed
by ``refresh-manifest`` in the collector itself.  Any mismatch in an older
season remains a hard integrity failure.
"""

import argparse
from datetime import datetime, timezone
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
from typing import Any, Iterable

DATA_DIR=Path("data/v137"); MANIFEST=Path("data/v138_dataset_manifest.json")
FORBIDDEN_LABEL_KEYS=frozenset({"home_score","away_score","home_win","total_runs","run_margin_home","result","winner","label","target"})
REQUIRED_PROVENANCE_RULE="strictly earlier officialDate only"
_SOURCE_RE=re.compile(r"team_(?:features|labels)_(\d{4})\.jsonl\.gz$")


def _dt(value:Any)->datetime:
    dt=datetime.fromisoformat(str(value).replace("Z","+00:00"));
    if dt.tzinfo is None: dt=dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)

def sha256_file(path:Path)->str:
    h=hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda:fh.read(1024*1024),b""): h.update(chunk)
    return h.hexdigest()
def _read_gz(path:Path)->list[dict[str,Any]]:
    rows=[]
    with gzip.open(path,"rt",encoding="utf-8") as fh:
        for line_number,line in enumerate(fh,1):
            if not line.strip(): continue
            try: row=json.loads(line)
            except Exception as exc: raise ValueError(f"invalid JSONL row {path}:{line_number}") from exc
            if not isinstance(row,dict): raise ValueError(f"non-object JSONL row {path}:{line_number}")
            rows.append(row)
    return rows
def source_paths(base:Path=DATA_DIR)->list[Path]: return sorted(base.glob("team_features_*.jsonl.gz"))+sorted(base.glob("team_labels_*.jsonl.gz"))

def _source_season(path:Path)->int|None:
    match=_SOURCE_RE.search(path.name)
    return int(match.group(1)) if match else None

def _dataset_content_sha256(paths:list[Path])->str:
    h=hashlib.sha256()
    for path in sorted((Path(p) for p in paths),key=lambda p:str(p)):
        h.update(str(path).encode("utf-8"));h.update(b"\0");h.update(sha256_file(path).encode("ascii"));h.update(b"\n")
    return h.hexdigest()

def _is_source_manifest_path(value:Any)->bool:
    normalized=str(value or "").replace("\\","/")
    return bool(re.search(r"(?:^|/)data/v137/team_(?:features|labels)_\d{4}\.jsonl\.gz$",normalized))


def verify_manifest(manifest_path:Path=MANIFEST,base:Path=DATA_DIR)->dict[str,Any]:
    manifest=json.loads(manifest_path.read_text(encoding="utf-8")); expected={str(item.get("path")):str(item.get("sha256")) for item in manifest.get("files") or [] if _is_source_manifest_path(item.get("path"))}; actual_paths=source_paths(base)
    if len(actual_paths)!=len(expected): raise ValueError(f"historical source-count mismatch actual={len(actual_paths)} expected={len(expected)}")
    seasons=[s for s in (_source_season(path) for path in actual_paths) if s is not None]
    latest_season=max(seasons) if seasons else None; checked=[]; current_season_refresh=[]
    for path in actual_paths:
        key=str(path).replace("\\","/")
        if key not in expected: raise ValueError(f"historical source absent from manifest: {key}")
        digest=sha256_file(path); matches=digest==expected[key]
        if not matches:
            season=_source_season(path)
            if latest_season is None or season!=latest_season: raise ValueError(f"historical source hash mismatch: {key}")
            current_season_refresh.append({"path":key,"manifest_sha256":expected[key],"actual_sha256":digest,"season":season})
        checked.append({"path":key,"sha256":digest,"matches_manifest":matches})
    exact=not current_season_refresh
    return {"schema":"pulsar-v14-historical-source-integrity-v2","verified":exact,"accepted":True,"integrity_mode":"EXACT_MANIFEST" if exact else "CURRENT_SEASON_REFRESH_PENDING_MANIFEST","dataset_content_sha256":manifest.get("dataset_content_sha256"),"feature_contract_sha256":manifest.get("feature_contract_sha256"),"source_files":checked,"source_file_count":len(checked),"latest_source_season":latest_season,"current_season_refresh":current_season_refresh,"policy":{"older_season_hash_mismatch_fails_closed":True,"current_season_hash_mismatch_requires_full_pit_audit":True,"collector_refreshes_manifest_after_team_history":True}}

def refresh_manifest(manifest_path:Path=MANIFEST,base:Path=DATA_DIR)->dict[str,Any]:
    """Refresh source hashes after an intentional current-season data rebuild.

    This does not change feature values and does not create model evidence.  It
    only binds the already-persisted source bytes to the versioned manifest.
    Generated DuckDB/Parquet entries are retained exactly as recorded because
    they are not consumed by the strict V14 historical loader.
    """
    try: manifest=json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception: manifest={}
    if not isinstance(manifest,dict): manifest={}
    paths=source_paths(base)
    if not paths: raise ValueError("no historical team source files found")
    features,labels=load_raw(base)
    audit_report=audit(features,labels)
    if not audit_report["passed"]: raise ValueError(f"refusing to manifest invalid PIT dataset: {audit_report['failures'][:5]}")
    retained=[item for item in manifest.get("files") or [] if isinstance(item,dict) and not _is_source_manifest_path(item.get("path"))]
    entries=[{"path":str(path).replace("\\","/"),"bytes":path.stat().st_size,"sha256":sha256_file(path)} for path in paths]
    now=datetime.now(timezone.utc).isoformat(); revision=os.getenv("GITHUB_SHA") or manifest.get("dataset_version") or "local"
    manifest.update({"dataset_version":revision,"code_sha":os.getenv("GITHUB_SHA") or manifest.get("code_sha"),"dataset_content_sha256":_dataset_content_sha256(paths),"dataset_fingerprint_policy":"SHA256 over path + SHA256 of every compressed source feature/label file; any feature or label byte changes the fingerprint","feature_rows":len(features),"label_rows":len(labels),"files":entries+retained,"source_manifest_refreshed_at":now,"source_manifest_refresh_policy":"after intentional team-history rebuild and successful full PIT audit"})
    manifest_path.parent.mkdir(parents=True,exist_ok=True);manifest_path.write_text(json.dumps(manifest,ensure_ascii=False,indent=2,sort_keys=True)+"\n",encoding="utf-8")
    integrity=verify_manifest(manifest_path,base)
    if not integrity.get("verified"): raise ValueError("manifest refresh did not produce an exact source-byte match")
    return {"schema":"pulsar-v14-historical-manifest-refresh-v1","refreshed":True,"feature_rows":len(features),"label_rows":len(labels),"dataset_content_sha256":manifest.get("dataset_content_sha256"),"integrity":integrity}

def _forbidden_paths(value:Any,prefix:str="")->list[str]:
    hits=[]
    if isinstance(value,dict):
        for key,child in value.items():
            path=f"{prefix}.{key}" if prefix else str(key)
            if str(key).lower() in FORBIDDEN_LABEL_KEYS: hits.append(path)
            hits.extend(_forbidden_paths(child,path))
    elif isinstance(value,list):
        for i,child in enumerate(value): hits.extend(_forbidden_paths(child,f"{prefix}[{i}]"))
    return hits

def _feature_provenance_ok(row:dict[str,Any])->bool:
    provenance=row.get("feature_provenance") or row.get("provenance") or {}; prior=provenance.get("mlb_prior_results") or {}
    return str(prior.get("point_in_time_rule") or "")==REQUIRED_PROVENANCE_RULE and prior.get("same_day_games_excluded") is True

def _envelope_safe(row:dict[str,Any])->bool:
    return row.get("target_labels_embedded") is False and row.get("market_data_embedded") is False

def _season(row:dict[str,Any])->int:
    raw=row.get("season") or str(row.get("official_date") or row.get("game_date") or "")[:4]; return int(raw)
def load_raw(base:Path=DATA_DIR)->tuple[list[dict[str,Any]],list[dict[str,Any]]]:
    features=[];labels=[]
    for path in sorted(base.glob("team_features_*.jsonl.gz")): features.extend(_read_gz(path))
    for path in sorted(base.glob("team_labels_*.jsonl.gz")): labels.extend(_read_gz(path))
    return features,labels

def audit(features:list[dict[str,Any]],labels:list[dict[str,Any]])->dict[str,Any]:
    failures=[];feature_ids=set();label_ids=set();seasons=set()
    for row in features:
        gid=str(row.get("game_pk") or "")
        if not gid: failures.append("feature_missing_game_pk"); continue
        if gid in feature_ids: failures.append(f"duplicate_feature_game_pk:{gid}")
        feature_ids.add(gid)
        try:
            seasons.add(_season(row))
            if not (_dt(row.get("as_of"))<_dt(row.get("game_date"))): failures.append(f"feature_not_strictly_pregame:{gid}")
        except Exception: failures.append(f"feature_bad_timestamp:{gid}")
        hits=_forbidden_paths(row.get("features") or {})
        if hits: failures.append(f"feature_contains_label:{gid}:{hits[0]}")
        if not _feature_provenance_ok(row): failures.append(f"feature_provenance_not_j1_safe:{gid}")
        if not _envelope_safe(row): failures.append(f"feature_envelope_embeds_target_or_market:{gid}")
    for row in labels:
        gid=str(row.get("game_pk") or "")
        if not gid: failures.append("label_missing_game_pk"); continue
        if gid in label_ids: failures.append(f"duplicate_label_game_pk:{gid}")
        label_ids.add(gid)
        if row.get("home_score") is None or row.get("away_score") is None: failures.append(f"label_missing_score:{gid}")
    missing_labels=sorted(feature_ids-label_ids);missing_features=sorted(label_ids-feature_ids)
    if missing_labels: failures.append(f"features_without_labels:{len(missing_labels)}")
    if missing_features: failures.append(f"labels_without_features:{len(missing_features)}")
    return {"schema":"pulsar-v14-historical-dataset-audit-v2","passed":not failures,"feature_rows":len(features),"label_rows":len(labels),"unique_feature_games":len(feature_ids),"unique_label_games":len(label_ids),"seasons":sorted(seasons),"failures":failures[:100],"failure_count":len(failures),"policy":{"features_labels_physically_separate":True,"strictly_pregame_as_of_required":True,"same_day_results_excluded":True,"target_labels_embedded_forbidden":True,"market_data_embedded_forbidden":True,"live_season_endpoint_backfill_forbidden":True}}
def paired_rows(features:list[dict[str,Any]],labels:list[dict[str,Any]])->list[tuple[dict[str,Any],dict[str,Any]]]:
    report=audit(features,labels)
    if not report["passed"]: raise ValueError(f"historical dataset audit failed: {report['failures'][:3]}")
    by_label={str(row["game_pk"]):row for row in labels}; pairs=[(row,by_label[str(row["game_pk"])]) for row in features]; return sorted(pairs,key=lambda pair:(_dt(pair[0].get("game_date")),str(pair[0].get("game_pk"))))
def split_by_season(pairs:Iterable[tuple[dict[str,Any],dict[str,Any]]])->dict[str,list[tuple[dict[str,Any],dict[str,Any]]]]:
    out={"tuning":[],"validation":[],"frozen_test":[]}
    for pair in pairs:
        season=_season(pair[0])
        if season<=2024: out["tuning"].append(pair)
        elif season==2025: out["validation"].append(pair)
        elif season==2026: out["frozen_test"].append(pair)
    return out
def load_verified(base:Path=DATA_DIR,manifest_path:Path=MANIFEST)->tuple[list[tuple[dict[str,Any],dict[str,Any]]],dict[str,Any]]:
    integrity=verify_manifest(manifest_path,base);features,labels=load_raw(base);report=audit(features,labels)
    if not report["passed"]: raise ValueError(f"historical PIT audit failed: {report['failures'][:5]}")
    if not integrity.get("verified") and integrity.get("integrity_mode")!="CURRENT_SEASON_REFRESH_PENDING_MANIFEST": raise ValueError("historical source integrity is not acceptable")
    pairs=paired_rows(features,labels);return pairs,{"integrity":integrity,"audit":report}


def main()->None:
    parser=argparse.ArgumentParser(description="Audit or refresh V14 historical PIT source manifest")
    parser.add_argument("command",nargs="?",choices=("audit","refresh-manifest"),default="audit")
    parser.add_argument("--base",default=str(DATA_DIR));parser.add_argument("--manifest",default=str(MANIFEST));args=parser.parse_args()
    if args.command=="refresh-manifest": out=refresh_manifest(Path(args.manifest),Path(args.base))
    else:
        pairs,evidence=load_verified(Path(args.base),Path(args.manifest));out={"schema":"pulsar-v14-historical-dataset-cli-v1","pairs":len(pairs),**evidence}
    print(json.dumps(out,ensure_ascii=False,indent=2,sort_keys=True))


if __name__=="__main__": main()
