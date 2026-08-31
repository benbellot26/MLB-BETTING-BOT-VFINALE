from __future__ import annotations

"""Generation-bound source fingerprint for the active champion probability core.

The manifest is intentionally explicit. If any listed probability-bearing source
changes, CI fails until the change is reviewed, MODEL_GENERATION is bumped when
appropriate, and this manifest is deliberately refreshed. This prevents an
accidental champion mutation from silently inheriting old statistical evidence.
"""

from hashlib import sha1
from pathlib import Path
from typing import Any

from . import MODEL_GENERATION

MANIFEST_GENERATION="pulsar-v14-context-v4-all-stats"
CHAMPION_SOURCE_BLOBS={
    "v14/structural.py":"cc9842d06cfaac6300a3630aa1b9c883ed189ab1",
    "v14/run_stack.py":"abad3d32b6a9aee96dff6f896de851997475a500",
    "v14/context_overlay.py":"86e6f2127501015113088308d7f53cd150922640",
    "v14/all_stats_context.py":"8617352b85547ba052b9a4044977e876ca60008c",
    "v14/statcast_shadow.py":"3f1ab623c8c2ed27776b134e40d76b3e71bc53f3",
    "v14/pitch_matchup_challenger.py":"cb82f8753f247f194642c8206c8670ccf8ae23a5",
    "v14/starter_usage_challenger.py":"6e9443cd768df3071dfa445b9d3606ff9a0e1b28",
    "v14/defense_baserunning_challenger.py":"bc371cd26b2cfede7e92ea8da59e858487ba4f88",
    "v14/environment_physics_challenger.py":"96674fc0d5bfa75e9313549385371d80acbec131",
    "v14/distribution.py":"2308df0afece8f4f832a1df20438c7d4c2e06be4",
    "v14/champion_contract.py":"29fdcec466153161d8da266037f10fb7643a2861",
    "v14/pipeline.py":"3204e19f92209170b8c5441a81d286432d8f7376",
    "v14/model.py":"3fa53d6b7b6e57ba0c5683b2da9814c5405325e4",
}


def _git_blob_sha(path:Path)->str:
    data=path.read_bytes(); header=f"blob {len(data)}\0".encode("utf-8"); return sha1(header+data).hexdigest()


def validate(root:Path|str=".")->dict[str,Any]:
    base=Path(root); mismatches={}; missing=[]
    if MODEL_GENERATION!=MANIFEST_GENERATION:
        return {"valid":False,"generation_match":False,"model_generation":MODEL_GENERATION,"manifest_generation":MANIFEST_GENERATION,"missing":[],"mismatches":{},"reason":"MODEL_GENERATION changed; review and regenerate champion manifest"}
    for relative,expected in CHAMPION_SOURCE_BLOBS.items():
        path=base/relative
        if not path.exists(): missing.append(relative); continue
        actual=_git_blob_sha(path)
        if actual!=expected: mismatches[relative]={"expected":expected,"actual":actual}
    valid=not missing and not mismatches
    return {"valid":valid,"generation_match":True,"model_generation":MODEL_GENERATION,"manifest_generation":MANIFEST_GENERATION,"missing":missing,"mismatches":mismatches,"reason":None if valid else "champion probability source changed without an approved manifest/generation review"}


def assert_valid(root:Path|str=".")->None:
    result=validate(root)
    if not result["valid"]: raise RuntimeError(f"champion manifest mismatch: {result}")