from __future__ import annotations
import math
from collections import Counter
from datetime import date, timedelta
from . import core, market, config

_PREV_CACHE={}
_BOX_CACHE={}

def _nb_pmf(mu,k,dispersion=None):
    r=max(.5,float(dispersion or config.RUN_DISPERSION));p=r/(r+max(.01,mu))
    return math.exp(math.lgamma(k+r)-math.lgamma(r)-math.lgamma(k+1)+r*math.log(p)+k*math.log1p(-p))
def score_matrix(home_mu,away_mu,max_runs=None):
    mx=int(max_runs or config.MAX_RUNS_MATRIX);hp=[_nb_pmf(home_mu,k) for k in range(mx+1)];ap=[_nb_pmf(away_mu,k) for k in range(mx+1)];hs=sum(hp);aps=sum(ap)
    return [x/hs for x in hp],[x/aps for x in ap]
def _home_extra_win(home_mu,away_mu):
    share=home_mu/max(.01,home_mu+away_mu);return max(.46,min(.59,.70*share+.30*.52))
def prob_home_win(home_mu,away_mu):
    hp,ap=score_matrix(home_mu,away_mu);win=tie=0.0
    for h,ph in enumerate(hp):
        for a,pa in enumerate(ap):
            if h>a:win+=ph*pa
            elif h==a:tie+=ph*pa
    return core.clamp(win+tie*_home_extra_win(home_mu,away_mu))
def prob_cover_parts(home_mu,away_mu,side,point):
    hp,ap=score_matrix(home_mu,away_mu);w=p=0.0
    for h,ph in enumerate(hp):
        for a,pa in enumerate(ap):
            margin=(h-a+point) if side=="home" else (a-h+point)
            if margin>1e-9:w+=ph*pa
            elif abs(margin)<=1e-9:p+=ph*pa
    return max(0.0,min(1.0,w)),max(0.0,min(1.0,p))
def prob_total_parts(home_mu,away_mu,side,point):
    hp,ap=score_matrix(home_mu,away_mu);w=p=0.0
    for h,ph in enumerate(hp):
        for a,pa in enumerate(ap):
            d=h+a-point
            if abs(d)<=1e-9:p+=ph*pa
            elif side=="over" and d>0:w+=ph*pa
            elif side=="under" and d<0:w+=ph*pa
    return max(0.0,min(1.0,w)),max(0.0,min(1.0,p))

def _lineup(game_pk):
    try:box=core.mlb(f"v1/game/{game_pk}/boxscore") or {}
    except Exception:return {"home":{"count":0},"away":{"count":0}}
    out={};weights=[1.04,1.05,1.08,1.10,1.06,1.00,.96,.93,.90]
    for side in ("home","away"):
        team=(box.get("teams") or {}).get(side) or {};players=team.get("players") or {};hitters=[]
        for p in players.values():
            bo=p.get("battingOrder")
            if bo is None:continue
            pid=(p.get("person") or {}).get("id");st=core.player_stats(pid,"hitting") if pid else {};ops=core.num(st.get("ops"),0)
            hitters.append({"id":pid,"name":(p.get("person") or {}).get("fullName"),"batting_order":bo,"ops":ops if .3<=ops<=1.5 else None})
        hitters.sort(key=lambda x:int(core.num(x.get("batting_order"),999)));weighted=[]
        for i,x in enumerate(hitters[:9]):
            if x.get("ops") is not None:weighted.append((x["ops"],weights[min(i,8)]))
        wops=sum(v*w for v,w in weighted)/sum(w for _,w in weighted) if len(weighted)>=5 else None
        out[side]={"count":len(hitters),"players":hitters,"weighted_ops":wops}
    return out

def _starter(game,side,league_era=4.35,league_whip=1.32):
    pp=(((game.get("teams") or {}).get(side) or {}).get("probablePitcher") or {});pid=pp.get("id");st=core.player_stats(pid,"pitching") if pid else {};ip=core.num(st.get("inningsPitched"),0);weight=max(0.0,min(1.0,ip/70.0));era=core.num(st.get("era"),league_era);whip=core.num(st.get("whip"),league_whip)
    era=weight*era+(1-weight)*league_era;whip=weight*whip+(1-weight)*league_whip
    return {"id":pid,"name":pp.get("fullName"),"era":era,"whip":whip,"innings":ip,"k9":core.num(st.get("strikeoutsPer9Inn"),None) if st.get("strikeoutsPer9Inn") is not None else None,"bb9":core.num(st.get("walksPer9Inn"),None) if st.get("walksPer9Inn") is not None else None,"hr9":core.num(st.get("homeRunsPer9"),None) if st.get("homeRunsPer9") is not None else None,"sample_weight":weight}

def _previous_game(team_id,target_date):
    key=(str(team_id),str(target_date))
    if key in _PREV_CACHE:return _PREV_CACHE[key]
    try:d=date.fromisoformat(str(target_date))
    except Exception:_PREV_CACHE[key]=None;return None
    for back in range(1,5):
        day=(d-timedelta(days=back)).isoformat()
        try:games=core.mlb_schedule(day,team_id=team_id,hydrate="linescore")
        except Exception:continue
        finals=[]
        for g in games:
            s=g.get("status") or {}
            if str(s.get("abstractGameState") or "").lower()=="final" or str(s.get("codedGameState") or "").upper()=="F":finals.append(g)
        if finals:
            g=finals[-1];teams=g.get("teams") or {};home_name=((teams.get("home") or {}).get("team") or {}).get("name");innings=int(core.num((g.get("linescore") or {}).get("currentInning"),9));out={"game_pk":g.get("gamePk"),"days_back":back,"venue_home_team":home_name,"extra_innings":innings>9,"doubleheader":str(g.get("doubleHeader") or "N")!="N"};_PREV_CACHE[key]=out;return out
    _PREV_CACHE[key]=None;return None

def _bullpen_usage(team_id,prev):
    if not prev or not prev.get("game_pk"):return {"relief_pitches":0,"heavy_relievers":0,"relievers_used":0}
    gid=str(prev["game_pk"])
    if gid not in _BOX_CACHE:
        try:_BOX_CACHE[gid]=core.mlb(f"v1/game/{gid}/boxscore") or {}
        except Exception:_BOX_CACHE[gid]={}
    box=_BOX_CACHE[gid];team=None
    for side in ("home","away"):
        t=(box.get("teams") or {}).get(side) or {}
        if str((t.get("team") or {}).get("id") or "")==str(team_id):team=t;break
    if not team:return {"relief_pitches":0,"heavy_relievers":0,"relievers_used":0}
    ids=list(team.get("pitchers") or []);rel=ids[1:] if len(ids)>1 else [];players=team.get("players") or {};counts=[]
    for pid in rel:
        st=(((players.get(f"ID{pid}") or {}).get("stats") or {}).get("pitching") or {});counts.append(int(core.num(st.get("pitchesThrown"),0)))
    return {"relief_pitches":sum(counts),"heavy_relievers":sum(x>=20 for x in counts),"relievers_used":len(counts)}
def _distance_km(a,b):
    if not a or not b:return None
    lat1,lon1,lat2,lon2=map(math.radians,(a[0],a[1],b[0],b[1]));h=math.sin((lat2-lat1)/2)**2+math.cos(lat1)*math.cos(lat2)*math.sin((lon2-lon1)/2)**2
    return 12742*math.asin(min(1,math.sqrt(h)))
def _operational(game,ctx):
    current=core.COORD.get(ctx.get("home"));out={"current_doubleheader":str(game.get("doubleHeader") or "N")!="N"}
    for side in ("home","away"):
        tid=ctx.get(f"{side}_id");prev=_previous_game(tid,core.TARGET_DATE);prev_coord=core.COORD.get(prev.get("venue_home_team")) if prev else None;dist=_distance_km(prev_coord,current);bull=_bullpen_usage(tid,prev)
        out[side]={"rest_days":max(0,int(prev.get("days_back",1))-1) if prev else None,"travel_km":round(dist,1) if dist is not None else None,"timezone_shift_hours_approx":round((current[1]-prev_coord[1])/15,2) if current and prev_coord else None,"previous_extra_innings":bool(prev.get("extra_innings")) if prev else None,"previous_doubleheader":bool(prev.get("doubleheader")) if prev else None,"bullpen_previous_game":bull}
    return out

def _project_runs(game):
    teams=game.get("teams") or {};home=((teams.get("home") or {}).get("team") or {});away=((teams.get("away") or {}).get("team") or {});hid,aid=home.get("id"),away.get("id");hn,an=home.get("name"),away.get("name")
    lg=core.league_baselines();rpg=core.num(lg.get("rpg"),4.45);lgops=core.num(lg.get("ops"),.710);lgera=core.num(lg.get("era"),4.35);lgwhip=core.num(lg.get("whip"),1.32)
    hh=core.season_stats(hid,"hitting");ah=core.season_stats(aid,"hitting");hp=core.season_stats(hid,"pitching");ap=core.season_stats(aid,"pitching")
    h_ops=core.num(hh.get("ops"),lgops);a_ops=core.num(ah.get("ops"),lgops);h_rpg=core.num(hh.get("runsPerGame"),rpg);a_rpg=core.num(ah.get("runsPerGame"),rpg);h_era=core.num(hp.get("era"),lgera);a_era=core.num(ap.get("era"),lgera)
    hs=_starter(game,"home",lgera,lgwhip);ass=_starter(game,"away",lgera,lgwhip);lineups=_lineup(game.get("gamePk"));h_lu=core.num(lineups["home"].get("weighted_ops"),h_ops);a_lu=core.num(lineups["away"].get("weighted_ops"),a_ops)
    def ratio(x,b,lo=.75,hi=1.28):return max(lo,min(hi,x/max(1e-9,b)))
    h_off=.42*ratio(h_rpg,rpg)+.33*ratio(h_ops,lgops)+.25*ratio(h_lu,lgops);a_off=.42*ratio(a_rpg,rpg)+.33*ratio(a_ops,lgops)+.25*ratio(a_lu,lgops)
    h_sp_quality=.68*ratio(ass.get("era",lgera),lgera)+.32*ratio(ass.get("whip",lgwhip),lgwhip);a_sp_quality=.68*ratio(hs.get("era",lgera),lgera)+.32*ratio(hs.get("whip",lgwhip),lgwhip)
    h_opp=.52*ratio(a_era,lgera)+.48*h_sp_quality;a_opp=.52*ratio(h_era,lgera)+.48*a_sp_quality;park=core.PARK.get(hn,1.0)
    home_mu=rpg*h_off*h_opp*park*1.025;away_mu=rpg*a_off*a_opp*park*.975
    ctx={"home":hn,"away":an,"home_id":hid,"away_id":aid,"home_sp":hs.get("name"),"away_sp":ass.get("name"),"home_lineup":lineups["home"],"away_lineup":lineups["away"],"home_starter":hs,"away_starter":ass};oper=_operational(game,ctx)
    def fatigue(side):
        x=oper.get(side) or {};adj=0.0;dist=core.num(x.get("travel_km"),0);tz=abs(core.num(x.get("timezone_shift_hours_approx"),0))
        if dist>=1500:adj-=.012
        if dist>=3000:adj-=.008
        if tz>=2:adj-=.008
        if x.get("previous_extra_innings"):adj-=.010
        if x.get("previous_doubleheader"):adj-=.008
        if x.get("rest_days") is not None and x.get("rest_days")>=1:adj+=.006
        return adj
    def bullpen_attack(opponent_side):
        b=((oper.get(opponent_side) or {}).get("bullpen_previous_game") or {});return min(.035,.00022*core.num(b.get("relief_pitches"),0)+.006*core.num(b.get("heavy_relievers"),0))
    hadj=max(-config.MAX_OPERATIONAL_RUN_ADJ,min(config.MAX_OPERATIONAL_RUN_ADJ,fatigue("home")+bullpen_attack("away")));aadj=max(-config.MAX_OPERATIONAL_RUN_ADJ,min(config.MAX_OPERATIONAL_RUN_ADJ,fatigue("away")+bullpen_attack("home")))
    if oper.get("current_doubleheader"):hadj-=.004;aadj-=.004
    home_mu=max(1.8,min(7.5,home_mu*(1+hadj)));away_mu=max(1.8,min(7.5,away_mu*(1+aadj)))
    features={"home_ops":h_ops,"away_ops":a_ops,"home_lineup_ops":h_lu,"away_lineup_ops":a_lu,"home_team_era":h_era,"away_team_era":a_era,"home_mu":home_mu,"away_mu":away_mu,"home_operational_adjustment":hadj,"away_operational_adjustment":aadj,"operational":oper,"distribution":"negative-binomial","run_dispersion":config.RUN_DISPERSION}
    return home_mu,away_mu,ctx,features

def _blend(structural,sharp):
    n=int(sharp.get("n") or 0);sp=sharp.get("p")
    if sp is None or n<=0:return structural,0.0
    base=config.SHARP_WEIGHT_1 if n==1 else config.SHARP_WEIGHT_2 if n==2 else config.SHARP_WEIGHT_3PLUS;w=base*max(.35,min(1.0,core.num(sharp.get("robustness"),1.0)))
    return core.clamp((1-w)*structural+w*core.clamp(sp)),w
def _quality(phase,refs,lineup_count,starter_ok):
    q=.50+min(refs,4)*.06+(.11 if phase=="FINAL" else .055 if phase=="LATE" else 0)
    if lineup_count>=16:q+=.08
    if starter_ok:q+=.07
    return max(.35,min(.95,q))
def _effective(p,phase,quality):
    trust=(.62 if phase=="EARLY" else .75 if phase=="LATE" else .88)*(.74+.26*quality)
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
    hmu,amu,ctx,features=_project_runs(game);phase=core.phase_for_game(game);structural_home=prob_home_win(hmu,amu);sharp_home=market.sharp_consensus(event,"ML",ctx["home"]);lineup_count=int(core.num(ctx["home_lineup"].get("count"))+core.num(ctx["away_lineup"].get("count")));starter_ok=bool(ctx.get("home_sp") and ctx.get("away_sp"));quality=_quality(phase,sharp_home.get("n",0),lineup_count,starter_ok);options=[]
    def add(market_name,name,point,p_win,p_push=0.0):
        nonpush=max(1e-9,1-p_push);struct_cond=core.clamp(p_win/nonpush);sharp=market.sharp_consensus(event,market_name,name,point);oq=_quality(phase,sharp.get("n",0),lineup_count,starter_ok);p,sw=_blend(struct_cond,sharp);pe=_effective(p,phase,oq);effective_win=pe*nonpush;price=core.winamax_price(event,market_name,name,point)
        options.append({"market":market_name,"name":name,"point":point,"p_structural":round(struct_cond,6),"p_model":round(p,6),"p_effective":round(pe,6),"p_win":round(effective_win,6),"p_push":round(p_push,6),"p_market":round(sharp["p"],6) if sharp.get("p") is not None else None,"refs":sharp.get("n",0),"sharp_books":sharp.get("books",[]),"sharp_weight":round(sw,6),"sharp_dispersion":round(core.num(sharp.get("dispersion")),6) if sharp.get("dispersion") is not None else None,"sharp_robustness":round(core.num(sharp.get("robustness")),6),"sharp_max_age_min":round(core.num(sharp.get("max_age_min")),2) if sharp.get("max_age_min") is not None else None,"quality":round(oq,4),"confidence":round(_confidence(pe,oq,sharp.get("n",0)),3),"winamax_eval":{"price":price,"official_selected":False,"official_units":0}})
    add("ML",ctx["home"],None,structural_home,0);add("ML",ctx["away"],None,1-structural_home,0);hp=_most_common_spread(event,ctx["home"]);ap=-hp;hw,hpush=prob_cover_parts(hmu,amu,"home",hp);aw,apush=prob_cover_parts(hmu,amu,"away",ap);add("RUNLINE",ctx["home"],hp,hw,hpush);add("RUNLINE",ctx["away"],ap,aw,apush);total=_most_common_total(event)
    if total is not None:
        ow,opush=prob_total_parts(hmu,amu,"over",total);uw,upush=prob_total_parts(hmu,amu,"under",total);add("TOTAL","Over",total,ow,opush);add("TOTAL","Under",total,uw,upush)
    home_ml=next(o for o in options if o["market"]=="ML" and core.norm_name(o["name"])==core.norm_name(ctx["home"]))
    return {"game_pk":game.get("gamePk"),"game":game,"event":event,"ctx":ctx,"phase":phase,"hmu":hmu,"amu":amu,"p_home":home_ml["p_effective"],"con":{"p":sharp_home.get("p"),"n":sharp_home.get("n",0),"books":sharp_home.get("books",[]),"dispersion":sharp_home.get("dispersion"),"robustness":sharp_home.get("robustness"),"max_age_min":sharp_home.get("max_age_min")},"quality":quality,"features":features,"options":options,"engine_version":"V11-standalone-all-markets-v3"}
