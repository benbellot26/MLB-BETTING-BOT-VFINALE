from __future__ import annotations

import json
from pathlib import Path

from . import v138_research_models as models
from . import v138_validation as validation

OUT=Path("data/v138_validation.json")


def main() -> None:
    rows,labels=models.load_free_dataset();report=validation.full_report(rows,labels)
    OUT.parent.mkdir(parents=True,exist_ok=True);OUT.write_text(json.dumps(report,ensure_ascii=False,indent=2,sort_keys=True),encoding="utf-8")
    print(json.dumps({"schema":report.get("schema"),"games":report.get("games"),"folds":len((report.get("walk_forward") or {}).get("folds") or []),"ablation_available":bool((report.get("ablation") or {}).get("available"))},indent=2,sort_keys=True))


if __name__=="__main__":main()
