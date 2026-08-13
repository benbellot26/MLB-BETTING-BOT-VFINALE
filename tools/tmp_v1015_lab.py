import json, math
from pathlib import Path
from collections import defaultdict

rows=[json.loads(x) for x in Path('data/mlb_backtest_2026.jsonl').read_text(encoding='utf-8').splitlines() if x.strip()]
rows.sort(key=lambda r:r['game_date'])
ML_ANCH=((.500,.500),(.524,.507),(.574,.523),(.623,.554),(.669,.592),(.718,.648),(.750,.660))

def clamp(x,a,b): return max(a,min(b,x))
def interp(p,a=ML_ANCH):
    p=clamp(p,.5,.999);a=sorted(a)
    if p<=a[0][0]: return a[0][1]
    for (x0,y0),(x1,y1) in zip(a[:-1],a[1:]):
        if p<=x1:
            t=(p-x0)/(x1-x0) if x1>x0 else 0
            return y0+t*(y1-y0)
    return a[-1][1]

def obs(r,m):
    if m=='ML':
        ph=float(r['v10']['p_home_raw']);p=max(ph,1-ph);home=ph>=.5
        y=int((r['home_score']>r['away_score'])==home)
        return p,y
    rr=r['rl_proxy'];return float(rr['p']),1 if rr['result']=='W' else 0

def brier(xs,fn): return sum((fn(p)-y)**2 for p,y in xs)/len(xs)
def logloss(xs,fn):
    z=0
    for p,y in xs:
        q=clamp(fn(p),1e-6,1-1e-6);z+=-(y*math.log(q)+(1-y)*math.log(1-q))
    return z/len(xs)

n=len(rows);c1=int(n*.60);c2=int(n*.80)
parts={'train':rows[:c1],'tune':rows[c1:c2],'test':rows[c2:]}

def q_ml(p,f=1.0): return .5+(interp(p)-.5)*f
def q_rl(p,f=.82): return .5+(p-.5)*f
for market,grid,base in [('ML',[.70,.75,.80,.85,.90,.95,1.0,1.05],1.0),('RL',[.45,.50,.55,.60,.65,.70,.75,.80,.82,.85,.90,.95],.82)]:
    fn=lambda p,f=base,m=market: q_ml(p,f) if m=='ML' else q_rl(p,f)
    print('CAL_BASE',market,'tune',round(brier([obs(r,market) for r in parts['tune']],fn),6),'test',round(brier([obs(r,market) for r in parts['test']],fn),6))
    cand=[]
    for f in grid:
        fun=lambda p,f=f,m=market: q_ml(p,f) if m=='ML' else q_rl(p,f)
        cand.append((brier([obs(r,market) for r in parts['tune']],fun),logloss([obs(r,market) for r in parts['tune']],fun),f))
    cand.sort();f=cand[0][2];fun=lambda p,f=f,m=market: q_ml(p,f) if m=='ML' else q_rl(p,f)
    print('CAL_BEST',market,'factor',f,'train',round(brier([obs(r,market) for r in parts['train']],fun),6),'tune',round(brier([obs(r,market) for r in parts['tune']],fun),6),'test',round(brier([obs(r,market) for r in parts['test']],fun),6),'test_logloss',round(logloss([obs(r,market) for r in parts['test']],fun),6))

def data_quality(r):
    warm=min(int(r.get('pregame_games_home',0)),int(r.get('pregame_games_away',0)))
    warm_s=clamp(warm/12,0,1)
    sp=min(float(r['starters'].get('home_prior_ip',0)),float(r['starters'].get('away_prior_ip',0)))
    sp_s=clamp(sp/45,0,1)
    return .55*warm_s+.45*sp_s

def structural_stability(r):
    v=r['v10'];ds=float(v['home_struct'])-float(v['away_struct']);df=float(v['home_mu'])-float(v['away_mu'])
    return 1-clamp(abs(df-ds)/.75,0,1)

def uncertainty(r):
    warm=min(int(r.get('pregame_games_home',0)),int(r.get('pregame_games_away',0)))
    pw=.020*max(0,5-warm)/5
    sp=min(float(r['starters'].get('home_prior_ip',0)),float(r['starters'].get('away_prior_ip',0)))
    ps=.005*max(0,20-sp)/20
    v=r['v10'];ds=float(v['home_struct'])-float(v['away_struct']);df=float(v['home_mu'])-float(v['away_mu'])
    pr=.005*min(1,abs(df-ds)/.75)
    return min(.03,pw+ps+pr)

def market_rel(m): return .80 if m=='ML' else .76
def current_q(p,m): return q_ml(p,1.0) if m=='ML' else q_rl(p,.82)
def strength(q,m):
    thr=.60 if m=='ML' else .59
    return clamp((q-thr)/(.70-thr),0,1)

def candidate_rows(rs):
    out=[]
    for r in rs:
        for m in ('ML','RL'):
            p,y=obs(r,m);q=current_q(p,m);thr=.60 if m=='ML' else .59
            if q<thr: continue
            safe=max(.5,q-uncertainty(r));dq=data_quality(r);ss=structural_stability(r);cal=market_rel(m);depth=.70
            out.append({'date':r['game_date'][:10],'game':r['game_pk'],'m':m,'q':q,'safe':safe,'y':y,'strength':strength(q,m),'safe_strength':strength(safe,m),'data':dq,'stability':ss,'cal':cal,'depth':depth})
    return out

STRATEGIES={
 'probability_first': {'strength':.70,'stability':.10,'data':.05,'cal':.10,'depth':.05},
 'safe_only': {'safe_strength':1.0},
 'safe_hybrid_60': {'safe_strength':.60,'stability':.15,'data':.10,'cal':.10,'depth':.05},
 'safe_hybrid_50': {'safe_strength':.50,'stability':.20,'data':.10,'cal':.10,'depth':.10},
 'safe_hybrid_45': {'safe_strength':.45,'stability':.20,'data':.10,'cal':.15,'depth':.10},
 'quality_first': {'strength':.35,'stability':.20,'data':.30,'cal':.10,'depth':.05},
 'stability_first': {'strength':.25,'stability':.40,'data':.15,'cal':.15,'depth':.05},
 'balanced': {'strength':.30,'stability':.25,'data':.15,'cal':.15,'depth':.15},
}

def score(c,w): return 100*sum(c[k]*v for k,v in w.items())
def daily(rs,w):
    d=defaultdict(list)
    for c in candidate_rows(rs): d[c['date']].append(c)
    picks=[]
    for z in d.values():
        z.sort(key=lambda c:(score(c,w),c['safe'],c['q']),reverse=True);used=set()
        for c in z:
            if c['game'] in used: continue
            picks.append(c);used.add(c['game'])
            if len(used)>=3: break
    if not picks:return (0,0,None,None)
    hit=sum(x['y'] for x in picks)/len(picks);br=sum((x['q']-x['y'])**2 for x in picks)/len(picks)
    return len(picks),sum(x['y'] for x in picks),hit,br

basew={'strength':1.0}
print('SELECTOR baseline')
for part in parts: print('SEL','baseline',part,daily(parts[part],basew))
for name,w in STRATEGIES.items():
    print('SELECTOR',name,w)
    for part in parts: print('SEL',name,part,daily(parts[part],w))
