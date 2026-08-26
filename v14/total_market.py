from __future__ import annotations

"""Generic Total market probabilities, including integer-line pushes.

The existing champion display contract remains half-run only.  This research/
execution utility extracts win/push/loss probabilities from the same score
model so integer totals can be evaluated without pretending a push is a loss.
"""

from typing import Any
from .distribution import joint_score_matrix, extra_innings_terminal_kernel
from .model import RunProjection


def total_probabilities(projection:RunProjection,line:float|None=None)->dict[str,Any]:
    p=projection.validated(); target=float(p.total_line if line is None else line)
    doubled=round(target*2)
    if abs(target*2-doubled)>1e-9: raise ValueError("total line must be integer or half-run")
    joint,tail=joint_score_matrix(p.home_mu,p.away_mu,dispersion=p.dispersion,environment_sigma=p.environment_sigma)
    kernel=extra_innings_terminal_kernel(p.home_mu,p.away_mu,p.extra_innings_home_probability); over=under=push=0.0
    def consume(total:int,mass:float)->None:
        nonlocal over,under,push
        if total>target: over+=mass
        elif total<target: under+=mass
        else: push+=mass
    for h,row in enumerate(joint):
        for a,mass in enumerate(row):
            if h!=a: consume(h+a,mass)
            else:
                for hadd,aadd,kp in kernel: consume(h+a+hadd+aadd,mass*kp)
    norm=over+under+push
    if norm<=0: raise ValueError("score distribution has no mass")
    over/=norm; under/=norm; push/=norm
    return {"schema":"pulsar-v14-total-market-v1","line":target,"line_type":"INTEGER" if doubled%2==0 else "HALF_RUN","over_win_probability":over,"under_win_probability":under,"push_probability":push,"over_loss_probability":under,"under_loss_probability":over,"tail_mass":tail,"complement_check":over+under+push}


def expected_value(*,win_probability:float,loss_probability:float,decimal_odds:float)->float:
    odds=float(decimal_odds)
    if odds<=1: raise ValueError("decimal_odds must be >1")
    return float(win_probability)*(odds-1.0)-float(loss_probability)
