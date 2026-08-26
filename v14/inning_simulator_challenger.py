from __future__ import annotations

"""Rules-aware inning / plate-appearance Monte Carlo challenger.

This is deliberately not the champion.  It exists to test whether explicit MLB
structure (no bottom 9 when unnecessary, walk-offs, batting-order continuity and
ghost-runner extras) improves score likelihood / RL / Total calibration over the
current compact negative-binomial distribution.

The event model is intentionally transparent and low-dimensional.  Rich player
PA probabilities can be supplied later; until then it derives a neutral event
mix from expected team runs and therefore remains RESEARCH_ONLY.
"""

from dataclasses import dataclass
import math
import random
from typing import Any

ROLE="CHALLENGER_ONLY"

@dataclass(frozen=True)
class TeamPA:
    walk: float
    single: float
    double: float
    triple: float
    homer: float
    out: float

    def validated(self)->"TeamPA":
        vals=[self.walk,self.single,self.double,self.triple,self.homer,self.out]
        if any(not math.isfinite(float(v)) or float(v)<0 for v in vals): raise ValueError("invalid PA probabilities")
        total=sum(vals)
        if total<=0: raise ValueError("PA probabilities have no mass")
        return TeamPA(*(float(v)/total for v in vals))


def neutral_pa_from_runs(expected_runs:float)->TeamPA:
    """Conservative event mix scaled mildly by expected runs; research fallback."""
    mu=max(2.0,min(7.0,float(expected_runs))); delta=(mu-4.45)/4.45
    walk=.083*(1+.18*delta); single=.145*(1+.20*delta); double=.045*(1+.25*delta); triple=.004; homer=.031*(1+.38*delta)
    hit_event=walk+single+double+triple+homer; out=max(.45,1-hit_event)
    return TeamPA(walk,single,double,triple,homer,out).validated()


def _advance(event:str,bases:tuple[bool,bool,bool],rng:random.Random)->tuple[tuple[bool,bool,bool],int]:
    first,second,third=bases
    if event=="HR": return (False,False,False),1+int(first)+int(second)+int(third)
    if event=="3B": return (False,False,True),int(first)+int(second)+int(third)
    if event=="2B":
        runs=int(second)+int(third)+(int(first) if rng.random()<.62 else 0); new_third=bool(first and runs==int(second)+int(third)); return (False,True,new_third),runs
    if event=="1B":
        runs=int(third)+(int(second) if rng.random()<.58 else 0); new_third=bool(second and not (rng.random()<.58)); new_second=bool(first and rng.random()<.32); return (True,new_second,new_third),runs
    if event=="BB":
        runs=1 if first and second and third else 0
        return (True, second or first, third or (first and second)),runs
    return bases,0


def _half(pa:TeamPA,rng:random.Random,*,ghost_runner:bool=False,max_pa:int=30)->int:
    probs=pa.validated(); cuts=[]; running=0.0
    for name,p in (("BB",probs.walk),("1B",probs.single),("2B",probs.double),("3B",probs.triple),("HR",probs.homer),("OUT",probs.out)):
        running+=p; cuts.append((running,name))
    outs=0; runs=0; bases=(False,bool(ghost_runner),False); appearances=0
    while outs<3 and appearances<max_pa:
        appearances+=1; u=rng.random(); event=next(name for cut,name in cuts if u<=cut)
        if event=="OUT": outs+=1; continue
        bases,scored=_advance(event,bases,rng); runs+=scored
    return runs


def simulate(*,home_mu:float,away_mu:float,n:int=20000,seed:int=14,max_extra_innings:int=8)->dict[str,Any]:
    if n<1000: raise ValueError("n must be >=1000")
    hp=neutral_pa_from_runs(home_mu); ap=neutral_pa_from_runs(away_mu); rng=random.Random(int(seed)); finals={}; home_wins=0; regulation_ties=0; total_runs=0.0
    for _ in range(int(n)):
        h=a=0
        for inning in range(1,10):
            a+=_half(ap,rng)
            if inning==9 and h>a: break  # no bottom ninth when home already leads
            h+=_half(hp,rng)
            if inning==9 and h>a: break  # walk-off condition after bottom ninth PA block
        if h==a:
            regulation_ties+=1
            for _extra in range(max_extra_innings):
                a+=_half(ap,rng,ghost_runner=True)
                h+=_half(hp,rng,ghost_runner=True)
                if h!=a: break
            if h==a:
                # Tiny unresolved tail: neutral tie-break solely to ensure a final winner.
                if rng.random()<.5: h+=1
                else: a+=1
        home_wins+=int(h>a); total_runs+=h+a; finals[(h,a)]=finals.get((h,a),0)+1
    ordered=sorted(finals.items(),key=lambda kv:kv[1],reverse=True)[:25]
    return {"schema":"pulsar-v14-inning-pa-simulator-challenger-v1","role":ROLE,"auto_activation":False,"status":"READY_SHADOW","simulations":int(n),"seed":int(seed),"home_ml":home_wins/n,"away_ml":1-home_wins/n,"mean_total_runs":total_runs/n,"regulation_tie_rate":regulation_ties/n,"top_final_scores":[{"home":h,"away":a,"probability":count/n} for (h,a),count in ordered],"rules":{"skip_bottom_9_when_home_leads":True,"walkoff_resolution":True,"ghost_runner_extras":True,"batting_order_continuity":"not yet player-specific; team PA distribution only"},"event_model":"neutral PA mix mildly scaled by expected runs; replaceable by player-level probabilities","promotion_requirement":"must beat compact champion on frozen score NLL plus ML/RL/Total proper scores","market_probability_used_as_feature":False}
