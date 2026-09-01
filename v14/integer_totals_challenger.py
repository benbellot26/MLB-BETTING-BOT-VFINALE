from __future__ import annotations

"""Push-aware integer-total challenger for Pulsar V14.

The production display contract remains half-run totals only. This module exposes
P(Over), P(Push) and P(Under) for integer lines using the *same* champion score
distribution, so integer-market support can be validated prospectively before a
future generation changes executable behavior.
"""

import math
from typing import Any

from .distribution import extra_innings_terminal_kernel, joint_score_matrix


def _integer_line(value:Any)->int:
    try:x=float(value)
    except Exception as exc:raise ValueError("integer total line must be numeric") from exc
    if not math.isfinite(x) or x<=0 or abs(x-round(x))>1e-9:raise ValueError("challenger requires a positive integer total line")
    return int(round(x))


def probabilities(*,home_mu:float,away_mu:float,total_line:float,dispersion:float=7.5,environment_sigma:float=.08,extra_innings_home_probability:float=.5)->dict[str,Any]:
    line=_integer_line(total_line);joint,tail=joint_score_matrix(float(home_mu),float(away_mu),dispersion=float(dispersion),environment_sigma=float(environment_sigma));kernel=extra_innings_terminal_kernel(float(home_mu),float(away_mu),float(extra_innings_home_probability));over=push=under=0.0
    def consume(h:int,a:int,mass:float)->None:
        nonlocal over,push,under
        total=h+a
        if total>line:over+=mass
        elif total<line:under+=mass
        else:push+=mass
    for h,row in enumerate(joint):
        for a,mass in enumerate(row):
            if h!=a:consume(h,a,mass)
            else:
                for ha,aa,kp in kernel:consume(h+ha,a+aa,mass*kp)
    total=over+push+under
    if total<=0:raise RuntimeError("integer totals challenger produced zero probability mass")
    over,push,under=over/total,push/total,under/total;nonpush=max(1e-15,1-push)
    return {"schema":"pulsar-v14-integer-total-challenger-v1","role":"CHALLENGER_ONLY","champion_impact":False,"auto_activation":False,"market_probability_used_as_feature":False,"line":line,"over":over,"push":push,"under":under,"over_given_no_push":over/nonpush,"under_given_no_push":under/nonpush,"tail_mass_estimate":tail,"promotion_policy":"prospective validation required before any production total-line contract change"}
