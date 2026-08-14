from __future__ import annotations
import math, random
from . import config

def brier(ps,ys): return sum((p-y)**2 for p,y in zip(ps,ys))/len(ps) if ps else None

def logloss(ps,ys):
    if not ps:return None
    out=[]
    for p,y in zip(ps,ys):
        p=max(1e-9,min(1-1e-9,float(p))); out.append(-(y*math.log(p)+(1-y)*math.log(1-p)))
    return sum(out)/len(out)

def paired_gain_probability(base_losses,challenger_losses,rounds=2000,seed=113):
    if not base_losses or len(base_losses)!=len(challenger_losses):return None
    rnd=random.Random(seed); n=len(base_losses); diffs=[b-c for b,c in zip(base_losses,challenger_losses)]; wins=0
    for _ in range(rounds): wins += (sum(diffs[rnd.randrange(n)] for _ in range(n))/n)>0
    return wins/rounds

def evaluate_probability_challenger(base_ps,challenger_ps,ys):
    n=len(ys)
    if not (n and len(base_ps)==n and len(challenger_ps)==n):return {"n":0,"passes":False,"reason":"invalid sample"}
    bb=brier(base_ps,ys); cb=brier(challenger_ps,ys); bl=logloss(base_ps,ys); cl=logloss(challenger_ps,ys); gp=paired_gain_probability([(p-y)**2 for p,y in zip(base_ps,ys)],[(p-y)**2 for p,y in zip(challenger_ps,ys)]); gain=bb-cb
    passes=(n>=config.MIN_HOLDOUT_N and gain>=config.MIN_BRIER_GAIN and gp is not None and gp>=config.MIN_GAIN_PROB and cl-bl<=config.MAX_LOGLOSS_DEGRADATION)
    return {"n":n,"base_brier":bb,"challenger_brier":cb,"brier_gain":gain,"base_logloss":bl,"challenger_logloss":cl,"logloss_delta":cl-bl,"paired_gain_probability":gp,"passes":passes,"gates":{"min_n":config.MIN_HOLDOUT_N,"min_brier_gain":config.MIN_BRIER_GAIN,"min_gain_probability":config.MIN_GAIN_PROB,"max_logloss_degradation":config.MAX_LOGLOSS_DEGRADATION}}

def production_gate(historical_report,live_n): return bool(historical_report.get("passes")) and int(live_n or 0)>=config.MIN_LIVE_N
