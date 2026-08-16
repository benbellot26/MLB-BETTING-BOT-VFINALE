from __future__ import annotations

import json
from pathlib import Path

from .v13_historical_prior import _joint_nll, _split_days
from .v13_reconstruct_1801 import build as reconstruct_build
from .distribution_learning_v13 import estimate_negative_binomial_dispersion, estimate_shared_environment_sigma
from .v13_distribution_transfer import _load_exact_latest

REPORT = Path("data/v13_distribution_ablation_report.json")
DEFAULT_D = 7.5
DEFAULT_S = .08


def _score(rows, d, s):
    return _joint_nll(rows, d, s)


def main():
    rows,_=reconstruct_build()
    warm=[r for r in rows if r.get("warm_sample")]
    train,val,test=_split_days(warm)
    d_train=estimate_negative_binomial_dispersion(train,DEFAULT_D)
    s_train=estimate_shared_environment_sigma(train,DEFAULT_S)
    train_val=train+val
    d=estimate_negative_binomial_dispersion(train_val,DEFAULT_D)
    s=estimate_shared_environment_sigma(train_val,DEFAULT_S)

    variants={
        "default":(DEFAULT_D,DEFAULT_S),
        "dispersion_only":(d,DEFAULT_S),
        "environment_only":(DEFAULT_D,s),
        "full":(d,s),
    }
    validation_variants={
        "default":(DEFAULT_D,DEFAULT_S),
        "dispersion_only":(d_train,DEFAULT_S),
        "environment_only":(DEFAULT_D,s_train),
        "full":(d_train,s_train),
    }
    vb=_score(val,DEFAULT_D,DEFAULT_S)
    tb=_score(test,DEFAULT_D,DEFAULT_S)
    exact=_load_exact_latest()
    eb=_score(exact,DEFAULT_D,DEFAULT_S)
    out={}
    for name,(d2,s2) in variants.items():
        vd,vs=validation_variants[name]
        vn=_score(val,vd,vs); tn=_score(test,d2,s2); en=_score(exact,d2,s2)
        out[name]={
            "dispersion":d2,"environment_sigma":s2,
            "validation_nll":vn,"validation_gain":vb-vn,
            "test_nll":tn,"test_gain":tb-tn,
            "exact_nll":en,"exact_gain":eb-en,
            "passes": name=="default" or ((vb-vn)>.0005 and (tb-tn)>.0005 and (eb-en)>=0),
        }
    eligible=[(0 if n=="dispersion_only" else 1 if n=="environment_only" else 2,n,v) for n,v in out.items() if n!="default" and v["passes"]]
    selected=min(eligible)[1] if eligible else "default"
    report={
        "schema":"v13-distribution-ablation-v1",
        "warm_games":len(warm),"validation_games":len(val),"test_games":len(test),"exact_replay_games":len(exact),
        "variants":out,"selected_variant":selected,
        "selection_rule":"Prefer the least-complexity variant that improves validation and untouched test NLL and does not regress exact replay NLL.",
        "production_activation_allowed":selected!="default",
    }
    REPORT.write_text(json.dumps(report,ensure_ascii=False,indent=2,sort_keys=True),encoding="utf-8")
    print(json.dumps(report,ensure_ascii=False,indent=2,sort_keys=True))


if __name__ == "__main__": main()
