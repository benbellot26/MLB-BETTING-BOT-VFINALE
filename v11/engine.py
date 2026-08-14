from __future__ import annotations
import math
from collections import Counter
from . import core, market

def _poisson_pmf(mu,k):return math.exp(-mu)*(mu**k)/math.factorial(k)
def score_matrix(home_mu,away_mu,max_runs=18):
    hp=[_poisson_pmf(home_mu,k) for k in range(max_runs+1)];ap=[_poisson_pmf(away_mu,k) for k in range(max_runs+1)];hs=sum(hp);aps=sum(ap)
    return [x/hs for x in hp],[x/aps for x in ap]
def prob_home_win(home_mu,away_mu):
    hp,ap=score_matrix(home_mu,away_mu);win=tie=0.0
    for h,ph in enumerate(hp):
        for a,pa in enumerate(ap):
            if h>a:win+=ph*pa
            elif h==a:tie+=ph*pa
    return core.clamp(win+.5*tie)
def prob_cover(home_mu,away_mu,side,point):
    hp,ap=score_matrix(home_mu,away_mu);w=p=0.0
    for h,ph in enumerate(hp):
        for a,pa in enumerate(ap):
            margin=(h-a+point) if side=="home" else (a-h+point)
            if margin>1e-9:w+=ph*pa
            elif abs(margin)<=1e-9:p+=ph*pa
    return core.clamp(w+.5*p)
def prob_total(home_mu,away_mu,side,point):
    hp,ap=score_matrix(home_mu,away_mu);w=p=0.0
    for h,ph in enumerate(hp):
        for a,pa in enumerate(ap):
            d=h+a-point
            if abs(d)<=1e-9:p+=ph*pa
            elif side=="over" and d>0:w+=ph*pa
            elif side=="under" and d<0:w+=ph*pa
    return core.clamp(w+.5*p)

def _lineup(game_pk):
    try:box=core.mlb(f"v1/game/{game_pk}/boxscore") or {}
    except Exception:return {"home":{"count":0},"away":{"count":0}}
    out={}
    for side in ("home","away"):
        team=(box.get("teams") or {}).get(side) or {};players=team.get("players") or {};hitters=[]
        for p in players.values():
            bo=p.get("battingOrder")
            if bo is None:continue
            pid=(p.get("person") or {}).get("id");st=core.player_stats(pid,"hitting") if pid else {};ops=core.num(st.get("ops"),0)
            hitters.append({"id":pid,"name":(p.get("person") or {}).get("fullName"),"batting_order":bo,"ops":ops if .3<=ops<=1.5 else None})
        hitters.sort(key=lambda x:str(x.get("batting_order")));vals=[x["ops"] for x in hitters if x.get("ops") is not None]
        out[side]={"count":len(hitters),"players":hitters,"weighted_ops":sum(vals)/len(vals) if len(vals)>=5 else None}
    return out

def _starter(game,side):
    pp=(((game.get("teams") or {}).get(side) or {}).get("probablePitcher") or {});pid=pp.get("id");st=core.player_stats(pid,"pitching") if pid else {}
    return {"id":pid,"name":pp.get("fullName"),"era":core.num(st.get("era"),0) or None,"whip":core.num(st.get("whip"),0) or None,"innings":core.num(st.get("inningsPitched"),0)}

def _project_runs(game):
    teams=game.get("teams") or {};home=((teams.get("home") or {}).get("team") or {});away=((teams.get("away") or {}).get("team") or {});hid,aid=home.get("id"),away.get("id");hn,an=home.get("name"),away.get("name")
    lg=core.league_baselines();rpg=core.num(lg.get("rpg"),4.45);lgops=core.num(lg.get("ops"),.710);lgera=core.num(lg.get("era"),4.35)
    hh=core.season_stats(hid,"hitting");ah=core.season_stats(aid,"hitting");hp=core.season_stats(hid,"pitching");ap=core.season_stats(aid,"pitching")
    h_ops=core.num(hh.get("ops"),lgops);a_ops=core.num(ah.get("ops"),lgops);h_rpg=core.num(hh.get("runsPerGame"),rpg);a_rpg=core.num(ah.get("runsPerGame"),rpg);h_era=core.num(hp.get("era"),lgera);a_era=core.num(ap.get("era"),lgera)
    hs=_starter(game,"home");ass=_starter(game,"away");lineups=_lineup(game.get("gamePk"));h_lu=core.num(lineups["home"].get("weighted_ops"),h_ops);a_lu=core.num(lineups["away"].get("weighted_ops"),a_ops)
    def ratio(x,b,lo=.75,hi=1.28):return max(lo,min(hi,x/max(1e-9,b)))
    h_off=.45*ratio(h_rpg,rpg)+.35*ratio(h_ops,lgops)+.20*ratio(h_lu,lgops);a_off=.45*ratio(a_rpg,rpg)+.35*ratio(a_ops,lgops)+.20*ratio(a_lu,lgops)
    away_sp_era=core.num(ass.get("era"),a_era) if ass.get("era") else a_era;home_sp_era=core.num(hs.get("era"),h_era) if hs.get("era") else h_era
    h_opp=.55*ratio(a_era,lgera)+.45*ratio(away_sp_era,lgera);a_opp=.55*ratio(h_era,lgera)+.45*ratio(home_sp_era,lgera);park=core.PARK.get(hn,1.0)
    home_mu=max(2.0,min(7.2,rpg*h_off*h_opp*park*1.025));away_mu=max(2.0,min(7.2,rpg*a_off*a_opp*park*.975))
    ctx={"home":hn,"away":an,"home_id":hid,"away_id":aid,"home_sp":hs.get("name"),"away_sp":ass.get("name"),"home_lineup":lineups["home"],"away_lineup":lineups["away"],"home_starter":hs,"away_starter":ass}
    return home_mu,away_mu,ctx,{"home_ops":h_ops,"away_ops":a_ops,"home_lineup_ops":h_lu,"away_lineup_ops":a_lu,"home_team_era":h_era,"away_team_era":a_era,"home_mu":home_mu,"away_mu":away_mu}

def _blend(structural,sharp):
    n=int(sharp.get("n") or 0);sp=sharp.get("p")
    if sp is None or n<=0:return structural,0.0
    w=.15 if n==1 else .24 if n==2 else .30
    return core.clamp((1-w)*structural+w*core.clamp(sp)),w
def _quality(phase,refs,lineup_count,starter_ok):
    q=.52+min(refs,4)*.06+(.10 if phase=="FINAL" else .05 if phase=="LATE" else 0)
    if lineup_count>=16:q+=.08
    if starter_ok:q+=.06
    return max(.35,min(.95,q))
def _effective(p,phase,quality):
    trust=(.64 if phase=="EARLY" else .76 if phase=="LATE" else .88)*(.75+.25*quality)
    return core.clamp(.5+(p-.5)*trust)
def _confidence(p,quality,refs):return max(0.0,min(10.0,3.0+abs(p-.5)*16+quality*2+min(refs,4)*.35))
def _most_common_spread(event,home_name):
    vals=[]
    for b in event.get("bookmakers") or []:
        for m in b.get("markets") or []:
            if m.get("key")!="spreads":continue
            for o in m.get("outcomes") or []:
                if core.norm_name(o.get("name"))==core.norm_name(home_name) and o.get("point") is not None:vals.append(round(core.num(o.get("point")),1))
    return Counter(vals).most_common(1)[0][0] if vals else -1.5
def _most_common_total(event):
    vals=[]
    for b in event.get("bookmakers") or []:
        for m in b.get("markets") or []:
            if m.get("key")!="totals":continue
            for o in m.get("outcomes") or []:
                if o.get("point") is not None:vals.append(round(core.num(o.get("point")),1))
    return Counter(vals).most_common(1)[0][0] if vals else None

def analyze(game,event):
    hmu,amu,ctx,features=_project_runs(game);phase=core.phase_for_game(game);structural_home=prob_home_win(hmu,amu);sharp_home=market.sharp_consensus(event,"ML",ctx["home"]);p_home,_=_blend(structural_home,sharp_home)
    lineup_count=int(core.num(ctx["home_lineup"].get("count"))+core.num(ctx["away_lineup"].get("count")));quality=_quality(phase,sharp_home.get("n",0),lineup_count,bool(ctx.get("home_sp") and ctx.get("away_sp")));options=[]
    def add(market_name,name,point,p_struct):
        sharp=market.sharp_consensus(event,market_name,name,point);p,sw=_blend(p_struct,sharp);pe=_effective(p,phase,quality);price=core.winamax_price(event,market_name,name,point)
        options.append({"market":market_name,"name":name,"point":point,"p_structural":round(p_struct,6),"p_model":round(p,6),"p_effective":round(pe,6),"p_market":round(sharp["p"],6) if sharp.get("p") is not None else None,"refs":sharp.get("n",0),"sharp_books":sharp.get("books",[]),"sharp_weight":sw,"confidence":round(_confidence(pe,quality,sharp.get("n",0)),3),"winamax_eval":{"price":price,"official_selected":False,"official_units":0}})
    add("ML",ctx["home"],None,structural_home);add("ML",ctx["away"],None,1-structural_home);hp=_most_common_spread(event,ctx["home"]);ap=-hp;add("RUNLINE",ctx["home"],hp,prob_cover(hmu,amu,"home",hp));add("RUNLINE",ctx["away"],ap,prob_cover(hmu,amu,"away",ap));total=_most_common_total(event)
    if total is not None:add("TOTAL","Over",total,prob_total(hmu,amu,"over",total));add("TOTAL","Under",total,prob_total(hmu,amu,"under",total))
    return {"game_pk":game.get("gamePk"),"game":game,"event":event,"ctx":ctx,"phase":phase,"hmu":hmu,"amu":amu,"p_home":p_home,"con":{"p":sharp_home.get("p"),"n":sharp_home.get("n",0),"books":sharp_home.get("books",[])},"quality":quality,"features":features,"options":options,"engine_version":"V11-standalone-all-markets"}
