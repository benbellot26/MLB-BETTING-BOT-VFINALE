from __future__ import annotations

"""Generation-bound source fingerprint for the active probability chain.

V14.6 consumes advanced PIT data in production, so the manifest covers not only
the probability formulas but also the source builders/transforms that can change
those inputs. If any listed source changes, CI fails until the mutation is
reviewed and this generation-bound manifest is deliberately refreshed (or a new
MODEL_GENERATION is created when the statistical contract changes).
"""

from hashlib import sha1
from pathlib import Path
from typing import Any

from . import MODEL_GENERATION

MANIFEST_GENERATION="pulsar-v14-context-v4-all-stats"
CHAMPION_SOURCE_BLOBS={
    # Core run/probability surface.
    "v14/structural.py":"cc9842d06cfaac6300a3630aa1b9c883ed189ab1",
    "v14/run_stack.py":"abad3d32b6a9aee96dff6f896de851997475a500",
    "v14/context_overlay.py":"86e6f2127501015113088308d7f53cd150922640",
    "v14/all_stats_context.py":"ba4cfaf6b554ffebdfcd68a1713415cacde59177",
    "v14/distribution.py":"2308df0afece8f4f832a1df20438c7d4c2e06be4",
    "v14/champion_contract.py":"29fdcec466153161d8da266037f10fb7643a2861",
    "v14/pipeline.py":"3204e19f92209170b8c5441a81d286432d8f7376",
    "v14/model.py":"3fa53d6b7b6e57ba0c5683b2da9814c5405325e4",

    # Live feature construction that can alter probability-bearing inputs.
    "v14/mlb_inputs.py":"09214667b36d45ab7e84fb56dc8aea38ef7e53a4",
    "v14/feature_row.py":"b2c12de7bb777527e66dfd677a62e1e7a535265e",
    "v14/park.py":"c186af27876b39e4b053029282f8dd05d430bcec",
    "v14/native_candidate.py":"1f76758e570fbf561cb4bb05743730808b20f386",

    # Statcast production path and deterministic transforms.
    "v14/statcast_shadow.py":"3f1ab623c8c2ed27776b134e40d76b3e71bc53f3",
    "v14/statcast_daily.py":"f43d3d9a4bbb0cdc797a104a5010004ce3121d1f",
    "v14/statcast_pit_backfill.py":"edca8739820c1935c0b9dd163e49732edce5fdcb",
    "v14/statcast_base.py":"460ae5b2fbfb4510a3a6e7f30a2bcac2bb777af6",
    "v14/statcast_enrichment.py":"b2100fe50e4b744728212631b6da9833f1ebb483",
    "v14/pitch_matchup_challenger.py":"cb82f8753f247f194642c8206c8670ccf8ae23a5",
    "v14/starter_usage_challenger.py":"6e9443cd768df3071dfa445b9d3606ff9a0e1b28",

    # Defense/catcher/baserunning PIT production path.
    "v14/defense_baserunning_challenger.py":"15e30a3cbeda1572949d535cbf22798e886481e1",
    "v14/savant_run_value_builder.py":"c200db9e746a099bd678d7aff5caa232c84223d8",
    "v14/savant_run_value_pit.py":"61dd17fe8bdd69efdb58ee91a4f3d12a17eb78a0",

    # Venue-relative physical weather production path.
    "v14/weather_live_shadow.py":"7f85062bd1d7aa050cf5f244d831e01d11a30744",
    "v14/environment_physics_challenger.py":"96674fc0d5bfa75e9313549385371d80acbec131",
    "v14/venue_geometry.py":"fd3c5095666d947a728e1393b05dfa30ff78a9c1",
    "v14/weather_climatology.py":"6e734d122b28b8793d328f59c78566a6b2274efc",
    "v14/timezone_challenger.py":"8ca655e00915e245eee4e3bbd4b65b15750647e4",
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
