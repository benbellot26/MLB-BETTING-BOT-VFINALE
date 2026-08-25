from __future__ import annotations

import math

from .champion_contract import MAX_RUNS_HARD, MAX_RUNS_MATRIX, SCORE_TAIL_TOLERANCE
from .model import DEFAULT_MAX_RUNS, DEFAULT_TAIL_TOLERANCE, ProbabilitySurface, RunProjection

EXTRA_INNING_RUN_MULTIPLIER = 1.75
MAX_EXTRA_INNINGS_MODELED = 6
MAX_EXTRA_HALF_INNING_RUNS = 6


def _nb_mass(mu: float, runs: int, dispersion: float) -> float:
    r=max(.5,float(dispersion)); mean=max(.01,float(mu)); p=r/(r+mean)
    return math.exp(math.lgamma(runs+r)-math.lgamma(r)-math.lgamma(runs+1)+r*math.log(p)+runs*math.log1p(-p))


def negative_binomial_pmf(mu: float, dispersion: float, *, max_runs: int=DEFAULT_MAX_RUNS, tail_tolerance: float=DEFAULT_TAIL_TOLERANCE) -> tuple[list[float],float]:
    mu=float(mu); dispersion=float(dispersion)
    if not math.isfinite(mu) or mu<=0 or not math.isfinite(dispersion) or dispersion<=0: raise ValueError("mu and dispersion must be finite and > 0")
    if max_runs<10: raise ValueError("max_runs must be >= 10")
    if not 0<tail_tolerance<.01: raise ValueError("tail_tolerance must be between 0 and 0.01")
    probs=[]; cumulative=0.0
    for runs in range(max_runs+1):
        value=_nb_mass(mu,runs,dispersion); probs.append(value); cumulative+=value
        if runs>=10 and 1-cumulative<=tail_tolerance: break
    tail=max(0.0,1-cumulative); probs=[v/max(1e-15,cumulative) for v in probs]
    return probs,tail


def _required_max_runs(mu: float, dispersion: float, minimum: int|None=None) -> int:
    minimum=int(minimum or MAX_RUNS_MATRIX); cumulative=0.0
    for runs in range(MAX_RUNS_HARD+1):
        cumulative+=_nb_mass(mu,runs,dispersion)
        if runs>=minimum and 1-cumulative<=SCORE_TAIL_TOLERANCE: return runs
    return MAX_RUNS_HARD


def _environment_nodes(sigma: float) -> list[tuple[float,float]]:
    sigma=max(0.0,min(.30,float(sigma)))
    if sigma<=1e-9: return [(1.0,1.0)]
    delta=math.sqrt(3.0)*sigma
    return [(max(.45,1-delta),1/6),(1.0,2/3),(1+delta,1/6)]


def joint_score_matrix(home_mu: float, away_mu: float, *, dispersion: float, environment_sigma: float, minimum_runs: int|None=None) -> tuple[list[list[float]],float]:
    nodes=_environment_nodes(environment_sigma); max_factor=max(f for f,_ in nodes)
    max_runs=max(_required_max_runs(home_mu*max_factor,dispersion,minimum_runs),_required_max_runs(away_mu*max_factor,dispersion,minimum_runs))
    joint=[[0.0]*(max_runs+1) for _ in range(max_runs+1)]; estimated_tail=0.0
    for factor,weight in nodes:
        hr=[_nb_mass(home_mu*factor,r,dispersion) for r in range(max_runs+1)]; ar=[_nb_mass(away_mu*factor,r,dispersion) for r in range(max_runs+1)]
        hs=sum(hr); ass=sum(ar); hp=[v/max(1e-15,hs) for v in hr]; ap=[v/max(1e-15,ass) for v in ar]
        estimated_tail+=weight*min(1.0,max(0.0,(1-hs)+(1-ass)))
        for h,ph in enumerate(hp):
            for a,pa in enumerate(ap): joint[h][a]+=weight*ph*pa
    total=sum(sum(row) for row in joint)
    return [[v/max(1e-15,total) for v in row] for row in joint],max(0.0,min(1.0,estimated_tail))


def _poisson_probs(mean: float, max_runs: int=MAX_EXTRA_HALF_INNING_RUNS) -> list[float]:
    mean=max(.01,float(mean)); vals=[math.exp(-mean)*mean**k/math.factorial(k) for k in range(max_runs+1)]; s=sum(vals)
    return [v/max(1e-15,s) for v in vals]


def extra_innings_terminal_kernel(home_mu: float, away_mu: float, target_home_win: float) -> list[tuple[int,int,float]]:
    """Approximate final added runs after a regulation tie, with no terminal ties.

    The ghost-runner era is represented by elevated half-inning scoring means.
    Terminal home/away masses are reweighted to the validated historical home
    extra-inning win prior, while preserving the simulated margin/run shape.
    """
    hmean=max(.12,min(1.50,float(home_mu)/9.0*EXTRA_INNING_RUN_MULTIPLIER)); amean=max(.12,min(1.50,float(away_mu)/9.0*EXTRA_INNING_RUN_MULTIPLIER))
    hp=_poisson_probs(hmean); ap=_poisson_probs(amean)
    states={(0,0):1.0}; terminal: dict[tuple[int,int],float]={}
    for _inning in range(MAX_EXTRA_INNINGS_MODELED):
        nxt: dict[tuple[int,int],float]={}
        for (ha,aa),state_p in states.items():
            for ar,pa in enumerate(ap):
                for hr,ph in enumerate(hp):
                    mass=state_p*pa*ph
                    nh,na=ha+hr,aa+ar
                    if nh!=na: terminal[(nh,na)]=terminal.get((nh,na),0.0)+mass
                    else: nxt[(nh,na)]=nxt.get((nh,na),0.0)+mass
        states=nxt
        if sum(states.values())<1e-7: break
    unresolved=sum(states.values())
    if unresolved>0:
        terminal[(1,0)]=terminal.get((1,0),0.0)+unresolved*.5
        terminal[(0,1)]=terminal.get((0,1),0.0)+unresolved*.5
    home_raw=sum(p for (h,a),p in terminal.items() if h>a); away_raw=sum(p for (h,a),p in terminal.items() if a>h)
    target=max(.45,min(.55,float(target_home_win))); out=[]
    for (h,a),p in terminal.items():
        if h>a: q=p/max(1e-15,home_raw)*target
        elif a>h: q=p/max(1e-15,away_raw)*(1-target)
        else: continue
        out.append((h,a,q))
    total=sum(p for _,_,p in out)
    return [(h,a,p/max(1e-15,total)) for h,a,p in out]


def probability_surface(projection: RunProjection, *, max_runs: int|None=None, tail_tolerance: float|None=None) -> tuple[ProbabilitySurface,float]:
    del tail_tolerance
    p=projection.validated(); joint,tail_mass=joint_score_matrix(p.home_mu,p.away_mu,dispersion=p.dispersion,environment_sigma=p.environment_sigma,minimum_runs=max_runs)
    kernel=extra_innings_terminal_kernel(p.home_mu,p.away_mu,p.extra_innings_home_probability)
    home_ml=home_minus=home_plus=over=0.0

    def consume(h: int,a: int,mass: float) -> None:
        nonlocal home_ml,home_minus,home_plus,over
        diff=h-a; total=h+a
        if diff>0: home_ml+=mass
        if diff>=2: home_minus+=mass
        if diff>=-1: home_plus+=mass
        if total>p.total_line: over+=mass

    for h,row in enumerate(joint):
        for a,mass in enumerate(row):
            if h!=a:
                consume(h,a,mass)
            else:
                for hadd,aadd,kp in kernel:
                    consume(h+hadd,a+aadd,mass*kp)

    home_ml=max(0.0,min(1.0,home_ml)); home_minus=max(0.0,min(1.0,home_minus)); home_plus=max(0.0,min(1.0,home_plus)); over=max(0.0,min(1.0,over))
    return ProbabilitySurface(
        away_ml=1-home_ml,home_ml=home_ml,
        away_plus_1_5=1-home_minus,away_minus_1_5=1-home_plus,
        home_plus_1_5=home_plus,home_minus_1_5=home_minus,
        over=over,under=1-over,
    ).validated(),tail_mass
