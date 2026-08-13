import json
from pathlib import Path
from collections import defaultdict
rows=[json.loads(x) for x in Path('data/mlb_backtest_2026.jsonl').read_text(encoding='utf-8').splitlines() if x.strip()]
rows.sort(key=lambda r:r['game_date'])

def fit_bins(xs,edges=(.50,.55,.60,.65,.70,.75,.80,1.001),prior_n=40):
    pts=[]
    for lo,hi in zip(edges[:-1],edges[1:]):
        z=[(p,y) for p,y in xs if lo<=p<hi]
        if not z:continue
        n=len(z);w=sum(y for _,y in z);rate=(w+.5*prior_n)/(n+prior_n)
        pts.append(((lo+min(hi,1.0))/2,rate,n))
    blocks=[]
    for x,rate,n in pts:
        weight=n+prior_n;win=rate*weight;blocks.append([x,x,win,weight,n])
        while len(blocks)>=2 and blocks[-2][2]/blocks[-2][3] > blocks[-1][2]/blocks[-1][3]:
            b=blocks.pop();a=blocks.pop();blocks.append([a[0],b[1],a[2]+b[2],a[3]+b[3],a[4]+b[4]])
    anchors=[(.50,.50)]
    for lo,hi,w,n,realn in blocks:anchors.append(((lo+hi)/2,w/n))
    return anchors

def interp(p,a):
    p=max(.5,min(.999,p));a=sorted(a)
    if p<=a[0][0]:return a[0][1]
    for (x0,y0),(x1,y1) in zip(a[:-1],a[1:]):
        if p<=x1:
            t=(p-x0)/(x1-x0) if x1>x0 else 0;return y0+t*(y1-y0)
    return a[-1][1]

def obs(r,market):
    if market=='ML':
        ph=float(r['v10']['p_home_raw']);p=max(ph,1-ph);home_pick=ph>=.5;y=int((r['home_score']>r['away_score'])==home_pick);return p,y
    rr=r['rl_proxy'];return float(rr['p']),1 if rr['result']=='W' else 0

def brier(xs,fn):return sum((fn(p)-y)**2 for p,y in xs)/len(xs)
def acc(xs,fn,thr):
    z=[(p,y) for p,y in xs if fn(p)>=thr]
    return len(z),sum(y for p,y in z),sum(y for p,y in z)/len(z) if z else None

n=len(rows);c1=int(n*.60);c2=int(n*.80);parts={'train':rows[:c1],'tune':rows[c1:c2],'test':rows[c2:]}
anchors={}
for m in ('ML','RL'):
    train=[obs(r,m) for r in parts['train']];anchors[m]=fit_bins(train)
    print('ANCHORS',m,anchors[m])
    for part,rs in parts.items():
        xs=[obs(r,m) for r in rs]
        if m=='ML':
            A=((.500,.500),(.524,.507),(.574,.523),(.623,.554),(.669,.592),(.718,.648),(.750,.660));old=lambda p,A=A:interp(p,A)
        else:old=lambda p:.5+(p-.5)*.82
        new=lambda p,m=m:interp(p,anchors[m])
        print('EVAL',m,part,'n',len(xs),'raw_brier',round(brier(xs,lambda p:p),5),'old_brier',round(brier(xs,old),5),'new_brier',round(brier(xs,new),5),'old_sel',acc(xs,old,.60 if m=='ML' else .59),'new_sel',acc(xs,new,.60 if m=='ML' else .59))

def datekey(r):return r['game_date'][:10]
def uncertainty(r,pen_warm=.010,pen_sp=.010,pen_res=.015):
    warm=min(int(r.get('pregame_games_home',0)),int(r.get('pregame_games_away',0)));pw=pen_warm*max(0,5-warm)/5
    sp=min(float(r['starters'].get('home_prior_ip',0)),float(r['starters'].get('away_prior_ip',0)));ps=pen_sp*max(0,20-sp)/20
    v=r['v10'];ds=float(v['home_struct'])-float(v['away_struct']);df=float(v['home_mu'])-float(v['away_mu']);pr=pen_res*min(1,abs(df-ds)/.75)
    return pw+ps+pr

def candidates(rs,which='old',weights=(.01,.01,.015)):
    out=[]
    for r in rs:
        for m in ('ML','RL'):
            p,y=obs(r,m)
            if which=='old':
                q=interp(p,((.500,.500),(.524,.507),(.574,.523),(.623,.554),(.669,.592),(.718,.648),(.750,.660))) if m=='ML' else .5+(p-.5)*.82;safe=q
            else:q=interp(p,anchors[m]);safe=max(.5,q-uncertainty(r,*weights))
            thr=.60 if m=='ML' else .59
            if q<thr:continue
            out.append({'date':datekey(r),'game':r['game_pk'],'m':m,'q':q,'safe':safe,'y':y})
    return out

def daily_eval(rs,which,weights=(.01,.01,.015)):
    cs=candidates(rs,which,weights);d=defaultdict(list)
    for c in cs:d[c['date']].append(c)
    picks=[]
    for day,z in d.items():
        z.sort(key=lambda c:(c['safe'],c['q']),reverse=True);used=set()
        for c in z:
            if c['game'] in used:continue
            picks.append(c);used.add(c['game'])
            if len(used)>=3:break
    return len(picks),sum(x['y'] for x in picks),sum(x['y'] for x in picks)/len(picks) if picks else None,sum((x['q']-x['y'])**2 for x in picks)/len(picks) if picks else None

print('DAILY_OLD')
for part in ('train','tune','test'):print(part,daily_eval(parts[part],'old'))
opts=[]
for pw in (0,.005,.01,.015,.02):
 for ps in (0,.005,.01,.015,.02):
  for pr in (0,.005,.01,.015,.02):
   met=daily_eval(parts['tune'],'new',(pw,ps,pr));opts.append((met[2] or 0,-(met[3] or 9),met[0],(pw,ps,pr),met))
opts.sort(reverse=True);best=opts[0]
print('BEST_TUNE',best)
for part in ('train','tune','test'):print('NEW',part,best[3],daily_eval(parts[part],'new',best[3]))
