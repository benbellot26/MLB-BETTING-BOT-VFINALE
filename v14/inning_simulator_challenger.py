from __future__ import annotations

"""Rules-aware inning / plate-appearance Monte Carlo challenger.

This is deliberately not the champion. It tests whether explicit MLB structure
(no bottom 9 when unnecessary, true walk-offs, base/out state transitions and
ghost-runner extras) improves score likelihood / RL / Total calibration over the
compact negative-binomial champion.

The fallback event model is deliberately low-dimensional, but unlike the first
prototype it is calibrated so nine full innings have the requested expected-run
mean. Explicit game rules may then move the realized final-game mean (notably by
skipping/walking off the home ninth); that movement is the structural effect the
challenger is intended to test.
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


def _pa_from_intensity(intensity:float)->TeamPA:
    """League-like PA mix at one scalar offensive intensity."""
    x=max(.25,min(2.0,float(intensity)))
    walk=.083*(x**.90); single=.145*(x**.90); double=.045*x; triple=.004*x; homer=.031*(x**1.15)
    non_out=walk+single+double+triple+homer
    out=max(.08,1.0-non_out)
    return TeamPA(walk,single,double,triple,homer,out).validated()


def _advance_transitions(event:str,bases:tuple[bool,bool,bool])->list[tuple[float,tuple[bool,bool,bool],int]]:
    """Exact base-state transition distribution for the simple event model.

    Probabilities are deliberately coarse league-level baserunning priors, but a
    runner can never disappear or occupy an impossible duplicate base.
    """
    first,second,third=bases
    if event=="HR": return [(1.0,(False,False,False),1+int(first)+int(second)+int(third))]
    if event=="3B": return [(1.0,(False,False,True),int(first)+int(second)+int(third))]
    if event=="2B":
        base_runs=int(second)+int(third)
        if not first: return [(1.0,(False,True,False),base_runs)]
        return [(.62,(False,True,False),base_runs+1),(.38,(False,True,True),base_runs)]
    if event=="1B":
        base_runs=int(third)
        rows: list[tuple[float,tuple[bool,bool,bool],int]]=[]
        # Runner from second scores 58%; otherwise occupies third.
        second_cases=[(.58,True),(.42,False)] if second else [(1.0,False)]
        for p_second,second_scores in second_cases:
            runs=base_runs+int(bool(second and second_scores))
            second_to_third=bool(second and not second_scores)
            if not first:
                rows.append((p_second,(True,False,second_to_third),runs)); continue
            # If third is free after the runner from second resolves, the runner
            # from first takes third 32%; otherwise he must take second.
            if not second_to_third:
                rows.append((p_second*.32,(True,False,True),runs))
                rows.append((p_second*.68,(True,True,False),runs))
            else:
                rows.append((p_second,(True,True,True),runs))
        return rows
    if event=="BB":
        runs=1 if first and second and third else 0
        return [(1.0,(True,second or first,third or (first and second)),runs)]
    return [(1.0,bases,0)]


def _advance(event:str,bases:tuple[bool,bool,bool],rng:random.Random)->tuple[tuple[bool,bool,bool],int]:
    rows=_advance_transitions(event,bases); u=rng.random(); cumulative=0.0
    for probability,next_bases,runs in rows:
        cumulative+=probability
        if u<=cumulative+1e-15: return next_bases,runs
    _probability,next_bases,runs=rows[-1]
    return next_bases,runs


def _event_probabilities(pa:TeamPA)->tuple[tuple[str,float],...]:
    p=pa.validated()
    return (("BB",p.walk),("1B",p.single),("2B",p.double),("3B",p.triple),("HR",p.homer),("OUT",p.out))


def expected_half_inning_runs(pa:TeamPA,*,ghost_runner:bool=False)->float:
    """Solve expected runs from the 24 base/out states by fixed-point iteration."""
    events=_event_probabilities(pa)
    base_states=[(bool(mask&1),bool(mask&2),bool(mask&4)) for mask in range(8)]
    next_out_values={bases:0.0 for bases in base_states}
    start_values={bases:0.0 for bases in base_states}
    for outs in (2,1,0):
        values={bases:0.0 for bases in base_states}
        for _ in range(200):
            updated={}
            max_delta=0.0
            for bases in base_states:
                expectation=0.0
                for event,event_p in events:
                    if event=="OUT":
                        future=0.0 if outs==2 else next_out_values[bases]
                        expectation+=event_p*future
                        continue
                    for transition_p,next_bases,runs in _advance_transitions(event,bases):
                        expectation+=event_p*transition_p*(runs+values[next_bases])
                updated[bases]=expectation; max_delta=max(max_delta,abs(expectation-values[bases]))
            values=updated
            if max_delta<1e-12: break
        next_out_values=values
        if outs==0: start_values=values
    return start_values[(False,bool(ghost_runner),False)]


def expected_nine_inning_runs(pa:TeamPA)->float:
    return 9.0*expected_half_inning_runs(pa)


def neutral_pa_from_runs(expected_runs:float)->TeamPA:
    """Calibrate league-like PA probabilities to the requested full-nine mean."""
    target=max(1.0,min(9.0,float(expected_runs)))
    lo,hi=.25,2.0
    for _ in range(55):
        mid=(lo+hi)/2.0; runs=expected_nine_inning_runs(_pa_from_intensity(mid))
        if runs<target: lo=mid
        else: hi=mid
    return _pa_from_intensity((lo+hi)/2.0)


def _half(pa:TeamPA,rng:random.Random,*,ghost_runner:bool=False,stop_after_runs:int|None=None,max_pa:int=100)->int:
    cuts=[]; running=0.0
    for name,p in _event_probabilities(pa): running+=p; cuts.append((running,name))
    outs=0; runs=0; bases=(False,bool(ghost_runner),False); appearances=0
    while outs<3 and appearances<max_pa:
        appearances+=1; u=rng.random(); event=next(name for cut,name in cuts if u<=cut+1e-15)
        if event=="OUT": outs+=1; continue
        bases,scored=_advance(event,bases,rng); runs+=scored
        if stop_after_runs is not None and runs>=int(stop_after_runs): break
    return runs


def simulate(*,home_mu:float,away_mu:float,n:int=20000,seed:int=14,max_extra_innings:int=8,total_line:float|None=None)->dict[str,Any]:
    if n<1000: raise ValueError("n must be >=1000")
    hp=neutral_pa_from_runs(home_mu); ap=neutral_pa_from_runs(away_mu); rng=random.Random(int(seed)); finals={}; home_wins=home_minus=away_minus=0; regulation_ties=0; total_runs=home_runs=away_runs=0.0; over=under=push=0
    for _ in range(int(n)):
        h=a=0
        for inning in range(1,10):
            a+=_half(ap,rng)
            if inning==9 and h>a: break
            needed=(a-h+1) if inning==9 else None
            h+=_half(hp,rng,stop_after_runs=needed)
        if h==a:
            regulation_ties+=1
            for _extra in range(max_extra_innings):
                a+=_half(ap,rng,ghost_runner=True)
                needed=a-h+1
                h+=_half(hp,rng,ghost_runner=True,stop_after_runs=needed)
                if h!=a: break
            if h==a:
                if rng.random()<.5: h+=1
                else: a+=1
        diff=h-a; total=h+a; home_wins+=int(diff>0); home_minus+=int(diff>=2); away_minus+=int(diff<=-2); total_runs+=total; home_runs+=h; away_runs+=a; finals[(h,a)]=finals.get((h,a),0)+1
        if total_line is not None:
            if total>float(total_line): over+=1
            elif total<float(total_line): under+=1
            else: push+=1
    ordered=sorted(finals.items(),key=lambda kv:kv[1],reverse=True)[:25]
    result={"schema":"pulsar-v14-inning-pa-simulator-challenger-v2","role":ROLE,"auto_activation":False,"status":"READY_SHADOW","simulations":int(n),"seed":int(seed),"home_ml":home_wins/n,"away_ml":1-home_wins/n,"home_minus_1_5":home_minus/n,"away_plus_1_5":1-home_minus/n,"away_minus_1_5":away_minus/n,"home_plus_1_5":1-away_minus/n,"mean_total_runs":total_runs/n,"mean_home_runs":home_runs/n,"mean_away_runs":away_runs/n,"regulation_tie_rate":regulation_ties/n,"top_final_scores":[{"home":h,"away":a,"probability":count/n} for (h,a),count in ordered],"pa_calibration":{"target_home_full_nine_runs":float(home_mu),"target_away_full_nine_runs":float(away_mu),"calibrated_home_full_nine_runs":expected_nine_inning_runs(hp),"calibrated_away_full_nine_runs":expected_nine_inning_runs(ap),"note":"realized home final-game mean may be lower because MLB rules can remove or truncate the bottom ninth"},"rules":{"skip_bottom_9_when_home_leads":True,"walkoff_resolution":True,"ghost_runner_extras":True,"batting_order_continuity":"not yet player-specific; team PA distribution only"},"event_model":"league-like PA mix calibrated exactly to each structural full-nine run mean","promotion_requirement":"must beat compact champion on frozen score NLL plus ML/RL/Total proper scores","market_probability_used_as_feature":False}
    if total_line is not None:
        result["total"]={"line":float(total_line),"over":over/n,"under":under/n,"push":push/n,"complement_check":over/n+under/n+push/n}
    return result
