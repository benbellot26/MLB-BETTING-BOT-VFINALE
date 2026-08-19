from __future__ import annotations

import csv
import gzip
import hashlib
import json
import os
from pathlib import Path
from typing import Any

from . import v138_research_models as rm

SCHEMA="v13-8-versioned-dataset-store-v1"
OUT_DIR=Path("data/v138")
MANIFEST=Path("data/v138_dataset_manifest.json")


def sha256_file(path: Path) -> str:
    h=hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda:f.read(1024*1024),b""):h.update(chunk)
    return h.hexdigest()


def _read_gz(path: Path) -> list[dict[str,Any]]:
    out=[]
    with gzip.open(path,"rt",encoding="utf-8") as f:
        for line in f:
            if line.strip():
                try:out.append(json.loads(line))
                except Exception:pass
    return out


def flatten_feature(r: dict[str,Any]) -> dict[str,Any]:
    vec=rm.vectorize(r);out={"game_pk":str(r.get("game_pk") or ""),"game_date":r.get("game_date"),
        "official_date":r.get("official_date"),"season":r.get("season"),"home":r.get("home"),"away":r.get("away"),
        "home_id":r.get("home_id"),"away_id":r.get("away_id"),"as_of":r.get("as_of"),"cohort":r.get("cohort"),
        "native_live":bool(r.get("native_live")),"promotion_eligible":bool(r.get("promotion_eligible"))}
    for name,value in zip(rm.FEATURE_NAMES,vec):out[name]=value
    return out


def flatten_label(r: dict[str,Any]) -> dict[str,Any]:
    return {k:r.get(k) for k in ("game_pk","game_date","official_date","home","away","home_score","away_score","home_win","total_runs","run_margin_home")}


def load_flat(base: Path=Path("data/v137")) -> tuple[list[dict[str,Any]],list[dict[str,Any]]]:
    features=[];labels=[]
    for p in sorted(base.glob("team_features_*.jsonl.gz")):features.extend(flatten_feature(r) for r in _read_gz(p))
    for p in sorted(base.glob("team_labels_*.jsonl.gz")):labels.extend(flatten_label(r) for r in _read_gz(p))
    return features,labels


def _csv(path: Path,rows: list[dict[str,Any]]) -> None:
    path.parent.mkdir(parents=True,exist_ok=True)
    fields=list(rows[0]) if rows else []
    with path.open("w",encoding="utf-8",newline="") as f:
        if fields:
            w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(rows)


def _sql_path(path: Path) -> str:
    return str(path.resolve()).replace("'","''")


def build_duckdb(features: list[dict[str,Any]],labels: list[dict[str,Any]],out_dir: Path=OUT_DIR) -> dict[str,Any]:
    """Materialize open-source DuckDB + Parquet analytical copies.

    duckdb is imported lazily so core production never acquires this dependency.
    """
    try:import duckdb
    except Exception as exc:return {"status":"DEPENDENCY_NOT_INSTALLED","error":type(exc).__name__}
    if not features or not labels:
        return {"status":"NO_DATA","feature_rows":len(features),"label_rows":len(labels)}
    out_dir.mkdir(parents=True,exist_ok=True)
    fcsv=out_dir/"team_features.csv";lcsv=out_dir/"team_labels.csv";_csv(fcsv,features);_csv(lcsv,labels)
    db=out_dir/"v138.duckdb";fp=out_dir/"team_features.parquet";lp=out_dir/"team_labels.parquet"
    con=duckdb.connect(str(db))
    try:
        con.execute("DROP TABLE IF EXISTS team_features");con.execute("DROP TABLE IF EXISTS team_labels")
        con.execute(f"CREATE TABLE team_features AS SELECT * FROM read_csv_auto('{_sql_path(fcsv)}')")
        con.execute(f"CREATE TABLE team_labels AS SELECT * FROM read_csv_auto('{_sql_path(lcsv)}')")
        con.execute(f"COPY team_features TO '{_sql_path(fp)}' (FORMAT PARQUET, COMPRESSION ZSTD)")
        con.execute(f"COPY team_labels TO '{_sql_path(lp)}' (FORMAT PARQUET, COMPRESSION ZSTD)")
        fc=int(con.execute("SELECT COUNT(*) FROM team_features").fetchone()[0]);lc=int(con.execute("SELECT COUNT(*) FROM team_labels").fetchone()[0])
    finally:con.close()
    fcsv.unlink(missing_ok=True);lcsv.unlink(missing_ok=True)
    return {"status":"BUILT","duckdb":str(db),"feature_parquet":str(fp),"label_parquet":str(lp),"feature_rows":fc,"label_rows":lc}


def manifest(source_paths: list[Path],generated: dict[str,Any],feature_rows: int,label_rows: int) -> dict[str,Any]:
    files=[]
    for p in source_paths+[Path(x) for x in (generated.get("duckdb"),generated.get("feature_parquet"),generated.get("label_parquet")) if x]:
        if p.exists():files.append({"path":str(p),"bytes":p.stat().st_size,"sha256":sha256_file(p)})
    contract=json.dumps({"schema":rm.SCHEMA,"features":list(rm.FEATURE_NAMES)},sort_keys=True,separators=(",",":"))
    return {"schema":SCHEMA,"dataset_version":os.getenv("GITHUB_SHA") or "local","code_sha":os.getenv("GITHUB_SHA"),
        "feature_contract_sha256":hashlib.sha256(contract.encode()).hexdigest(),"feature_rows":feature_rows,"label_rows":label_rows,
        "files":files,"storage":generated,"training_seed":138,"split_policy":"strict temporal / walk-forward",
        "separation_policy":"features and labels remain separate physical tables"}


def main() -> None:
    features,labels=load_flat();generated=build_duckdb(features,labels)
    sources=sorted(Path("data/v137").glob("team_features_*.jsonl.gz"))+sorted(Path("data/v137").glob("team_labels_*.jsonl.gz"))
    m=manifest(sources,generated,len(features),len(labels));MANIFEST.parent.mkdir(parents=True,exist_ok=True)
    MANIFEST.write_text(json.dumps(m,ensure_ascii=False,indent=2,sort_keys=True),encoding="utf-8")
    print(json.dumps({"schema":SCHEMA,"feature_rows":len(features),"label_rows":len(labels),"storage":generated,"files":len(m["files"])},indent=2,sort_keys=True))


if __name__=="__main__":main()
