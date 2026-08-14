from __future__ import annotations

import argparse
import json
from . import config, pro_model
from .journal import load_rows


def build_candidate(rows=None):
    return pro_model.build_candidate(load_rows() if rows is None else rows)


def write_candidate(rows=None, path=config.CANDIDATE_MODEL_FILE):
    rows = load_rows() if rows is None else rows
    return pro_model.write_candidate(rows, path)


def main():
    parser = argparse.ArgumentParser(description="V12 Champion/Challenger trainer")
    parser.add_argument("--promote", action="store_true", help="promote the candidate only if holdout gates pass")
    parser.add_argument("--dry-run", action="store_true", help="validate training pipeline without writing artifacts")
    args = parser.parse_args()
    rows = load_rows()
    candidate = pro_model.build_candidate(rows)
    if not args.dry_run:
        pro_model.write_candidate(rows)
    if args.promote:
        if args.dry_run:
            raise SystemExit("--promote et --dry-run sont incompatibles")
        promoted = pro_model.promote_candidate()
        print(json.dumps(promoted, ensure_ascii=False, indent=2, sort_keys=True))
        return
    print(json.dumps(candidate, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
