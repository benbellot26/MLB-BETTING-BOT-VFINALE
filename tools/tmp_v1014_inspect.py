import json
from pathlib import Path
from collections import defaultdict
rows=[json.loads(x) for x in Path('data/mlb_backtest_2026.jsonl').read_text(encoding='utf-8').splitlines() if x.strip()]
rows.sort(key=lambda r:r['game_date'])
A=((.500,.500),(.524,.507),(.574,.523),(.623,.554),(.669,.592),(.718,.648),(.750,.660))

def interp(p,a=A):
    p=max(.5,min(.999,p));a=sorted(a)
    if p<=a[0][0]:return a[0][1]
    for (x0,y0),(x1,y1) in zip(a[:-1],a[1:]):
        if p<=x1:
            t=(p-x0)/(x1-x0) if x1>x0 else 0;return y0+t*(y1-y0)
    return a[-1][1]

def obs(r,m):
    if m=='ML':
        ph=float(r['v10']['p_home_raw']);p=max(ph,1-ph);home_pick=ph>=.5;y=int((r['home_score']>r['away_score'])==home_pick);return p,y
    rr=r['rl_proxy'];return float(rr['p']),1 if rr['result']=='W' else 0

def current_q(p,m):return interp(p) if m=='ML' else .5+(p-.5)*.82

def uncertainty(r,pen_warm=.010,pen_sp=.010,pen_res=.015):
    warm=min(int(r.get('pregame_games_home',0)),int(r.get('pregame_games_away',0)));pw=pen_warm*max(0,5-warm)/5
    sp=min(float(r['starters'].get('home_prior_ip',0)),float(r['starters'].get('away_prior_ip',0)));ps=pen_sp*max(0,20-sp)/20
    v=r['v10'];ds=float(v['home_struct'])-float(v['away_struct']);df=float(v['home_mu'])-float(v['away_mu']);pr=pen_res*min(1,abs(df-ds)/.75)
    return pw+ps+pr

def candidates(rs,weights=None):
    out=[]
    for r in rs:
        for m in ('ML','RL'):
            p,y=obs(r,m);q=current_q(p,m);thr=.60 if m=='ML' else .59
            if q<thr:continue
            safe=q if weights is None else max(.5,q-uncertainty(r,*weights))
            out.append({'date':r['game_date'][:10],'game':r['game_pk'],'m':m,'q':q,'safe':safe,'y':y})
    return out

def daily_eval(rs,weights=None):
    d=defaultdict(list)
    for c in candidates(rs,weights):d[c['date']].append(c)
    picks=[]
    for z in d.values():
        z.sort(key=lambda c:(c['safe'],c['q']),reverse=True);used=set()
        for c in z:
            if c['game'] in used:continue
            picks.append(c);used.add(c['game'])
            if len(used)>=3:break
    n=len(picks);w=sum(x['y'] for x in picks);b=sum((x['q']-x['y'])**2 for x in picks)/n if n else None
    return n,w,w/n if n else None,b

n=len(rows);c1=int(n*.60);c2=int(n*.80);parts={'train':rows[:c1],'tune':rows[c1:c2],'test':rows[c2:]}
print('BASELINE')
for part in parts:print(part,daily_eval(parts[part],None))
opts=[]
for pw in (0,.005,.01,.015,.02,.025):
 for ps in (0,.005,.01,.015,.02):
  for pr in (0,.005,.01,.015,.02):
   met=daily_eval(parts['tune'],(pw,ps,pr));opts.append((met[2] or 0,-(met[3] or 9),(pw,ps,pr),met))
opts.sort(reverse=True);best=opts[0]
print('BEST_TUNE',best)
for part in parts:print('ROBUST',part,best[2],daily_eval(parts[part],best[2]))
# fixed conservative candidate for easier interpretation
fixed=(.02,.005,.005)
for part in parts:print('FIXED',part,fixed,daily_eval(parts[part],fixed))
