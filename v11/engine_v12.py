from __future__ import annotations
import math
from collections import Counter
from . import core, config, market, context, pro_model
from . import engine as legacy

_PRIOR = {}


def _n(x,d=0.0):
    try:
        y=float(x); return y if math.isfinite(y) else d
    except Exception:return d


def score_matrix(home_mu,away_mu,max_runs=None,dispersion=None):
    return legacy.score_matrix(home_mu,away_mu,max_runs)

def prob_home_win(home_mu,away_mu,dispersion=None):
    hp,ap=score_matrix(home_mu,away_mu); win=tie=0.0
    for h,ph in enumerate(hp):
        for a,pa in enumerate(ap):
            if h>a:win+=ph*pa
            elif h==a:tie+=ph*pa
    return core.clamp(win+tie*.52)

def prob_cover_parts(home_mu,away_mu,side,point,dispersion=None):
    return legacy.prob_cover_parts(home_mu,away_mu,side,point)

def prob_total_parts(home_mu,away_mu,side,point,dispersion=None):
    return legacy.prob_total_parts(home_mu,away_mu,side,point)


def _pitcher_prior(pid):
    if not pid:return {}
    key=(str(pid),core.SEASON)
    if key in _PRIOR:return _PRIOR[key]
    try:
        d=core.mlb(f"v1/people/{pid}/stats",{"stats":"yearByYear","group":"pitching"}) or {}
        splits=(d.get("stats") or [{}])[0].get("splits") or []
    except Exception:splits=[]
    by={int(_n(x.get("season"))):x.get("stat") or {} for x in splits if _n(x.get("season"))}
    rows=[]
    for back,w in ((1,.65),(2,.35)):
        st=by.get(core.SEASON-back) or {}; ip=_n(st.get("inningsPitched"))
        if ip>0:rows.append((st,w*min(1,ip/100)))
    if not rows:out={}
    else:
        sw=sum(w for _,w in rows)
        def avg(k,d):return sum(_n(st.get(k),d)*w for st,w in rows)/sw
        out={"era":avg("era",4.35),"whip":avg("whip",1.32),"k9":avg("strikeoutsPer9Inn",8.5),
             "bb9":avg("walksPer9Inn",3.2),"hr9":avg("homeRunsPer9",1.15)}
    _PRIOR[key]=out; return out


def _enhance_starter(st):
    st=dict(st or {}); prior=_pitcher_prior(st.get("id")); w=max(0,min(1,_n(st.get("innings"))/90))
    mapping=(("era","era",4.35),("whip","whip",1.32),("k9","k9",8.5),("bb9","bb9",3.2),("hr9","hr9",1.15))
    for dst,src,fallback in mapping:
        cur=_n(st.get(dst),fallback); old=_n(prior.get(src),fallback); st[dst]=w*cur+(1-w)*old
    st["sample_weight"]=w; st["prior_available"]=bool(prior); return st


def _starter_factor(st):
    era=_n(st.get("era"),4.35)/4.35; whip=_n(st.get("whip"),1.32)/1.32
    kbb=(_n(st.get("bb9"),3.2)+1)/(_n(st.get("k9"),8.5)+1) / ((3.2+1)/(8.5+1))
    hr=_n(st.get("hr9"),1.15)/1.15
    return max(.75,min(1.28,.38*era+.24*whip+.20*kbb+.18*hr))


def _winamax_points(event,key,home=None):
    for b in event.get("bookmakers") or []:
        if b.get("key")!=core.WINAMAX_KEY:continue
        m=next((x for x in b.get("markets") or [] if x.get("key")==key),None)
        if not m:return []
        if key=="spreads":
            return sorted({round(_n(o.get("point")),2) for o in m.get("outcomes") or [] if o.get("point") is not None and core.norm_name(o.get("name"))==core.norm_name(home)})
        return sorted({round(_n(o.get("point")),2) for o in m.get("outcomes") or [] if o.get("point") is not None})
    return []


def _modal(event,key,home=None):
    vals=[]
    for b in event.get("bookmakers") or []:
        for m in b.get("markets") or []:
            if m.get("key")!=key:continue
            for o in m.get("outcomes") or []:
                if o.get("point") is None:continue
                if key=="spreads" and core.norm_name(o.get("name"))!=core.norm_name(home):continue
                vals.append(round(_n(o.get("point")),2))
    return Counter(vals).most_common(1)[0][0] if vals else (-1.5 if key=="spreads" else None)


def _project(game):
    # Stable V11 structural baseline, then V12 adds priors, 3-day bullpen context and a validated residual layer.
    hmu,amu,ctx,features=legacy._project_runs(game)
    hs0,as0=ctx.get("home_starter") or {},ctx.get("away_starter") or {}
    hs,aws=_enhance_starter(hs0),_enhance_starter(as0)
    old_h=_starter_factor(as0); new_h=_starter_factor(aws); old_a=_starter_factor(hs0); new_a=_starter_factor(hs)
    hmu*=max(.92,min(1.08,new_h/max(.01,old_h))); amu*=max(.92,min(1.08,new_a/max(.01,old_a)))
    bph=context.bullpen_state(ctx.get("home_id"),core.TARGET_DATE); bpa=context.bullpen_state(ctx.get("away_id"),core.TARGET_DATE)
    hmu*=1+min(.035,.008*_n(bpa.get("taxed_relievers"))+.010*_n(bpa.get("likely_unavailable_relievers")))
    amu*=1+min(.035,.008*_n(bph.get("taxed_relievers"))+.010*_n(bph.get("likely_unavailable_relievers")))
    weather=context.weather_for_game(game,ctx.get("home"))
    ctx["home_starter"],ctx["away_starter"]=hs,aws
    features=dict(features or {}); features.update({"weather":weather,"bullpen":{"home":bph,"away":bpa,"coverage":min(_n(bph.get("coverage")),_n(bpa.get("coverage")))} ,"park_factor":core.PARK.get(ctx.get("home"),1.0)})
    result_like={"features":features,"ctx":ctx}; champ=pro_model.load_model()
    hmu,amu,learned=pro_model.apply_run_correction(hmu,amu,result_like,champ)
    dispersion=_n(champ.get("run_dispersion"),config.RUN_DISPERSION) if champ.get("active") else config.RUN_DISPERSION
    features.update({"home_mu":hmu,"away_mu":amu,"learned_run_adjustment":learned,"run_dispersion":dispersion,"distribution":"negative-binomial"})
    return hmu,amu,ctx,features,champ,dispersion


def _blend(p,sharp):
    if sharp.get("p") is None:return p,0.0
    w=market.blend_weight(sharp); return core.clamp((1-w)*p+w*core.clamp(sharp["p"])),w


def analyze(game,event):
    hmu,amu,ctx,features,champ,dispersion=_project(game); phase=core.phase_for_game(game)
    structural_home=prob_home_win(hmu,amu,dispersion); sharp_home=market.sharp_consensus(event,"ML",ctx["home"]); options=[]
    lineup_count=int(_n(ctx.get("home_lineup",{}).get("count"))+_n(ctx.get("away_lineup",{}).get("count")))
    starter_ok=bool(ctx.get("home_sp") and ctx.get("away_sp"))
    quality=max(.2,min(.95,.45+min(sharp_home.get("n",0),4)*.05+(.10 if phase=="FINAL" else .05 if phase=="LATE" else 0)+(.12 if lineup_count>=16 else 0)+(.08 if starter_ok else 0)))

    def add(mkt,name,point,pwin,ppush=0.0):
        nonpush=max(1e-9,1-ppush); ps=core.clamp(pwin/nonpush); sh=market.sharp_consensus(event,mkt,name,point); pb,sw=_blend(ps,sh)
        pe,unc,source=pro_model.calibrate(mkt,pb,champ); price=core.winamax_price(event,mkt,name,point)
        options.append({"market":mkt,"name":name,"point":point,"p_structural":round(ps,6),"p_model":round(pb,6),"p_effective":round(pe,6),
          "p_win":round(pe*nonpush,6),"p_push":round(ppush,6),"p_market":round(sh["p"],6) if sh.get("p") is not None else None,
          "refs":sh.get("n",0),"sharp_books":sh.get("books",[]),"sharp_weight":round(sw,6),"sharp_dispersion":sh.get("dispersion"),
          "sharp_robustness":sh.get("robustness"),"sharp_max_age_min":sh.get("max_age_min"),"sharp_effective_n":sh.get("effective_n"),
          "quality":quality,"confidence":round(max(0,min(10,3+1.4*abs(pe-.5)/max(.01,unc))),3),"model_uncertainty":round(unc,6),
          "calibration_source":source,"winamax_eval":{"price":price,"official_selected":False,"official_units":0}})

    add("ML",ctx["home"],None,structural_home); add("ML",ctx["away"],None,1-structural_home)
    points=_winamax_points(event,"spreads",ctx["home"]) or [_modal(event,"spreads",ctx["home"])]
    for hp in points:
        ap=-hp; hw,hpup=prob_cover_parts(hmu,amu,"home",hp,dispersion); aw,apup=prob_cover_parts(hmu,amu,"away",ap,dispersion)
        add("RUNLINE",ctx["home"],hp,hw,hpup); add("RUNLINE",ctx["away"],ap,aw,apup)
    totals=_winamax_points(event,"totals") or (lambda x:[x] if x is not None else [])(_modal(event,"totals"))
    for t in totals:
        ow,op=prob_total_parts(hmu,amu,"over",t,dispersion); uw,up=prob_total_parts(hmu,amu,"under",t,dispersion)
        add("TOTAL","Over",t,ow,op); add("TOTAL","Under",t,uw,up)
    hm=next(o for o in options if o["market"]=="ML" and core.norm_name(o["name"])==core.norm_name(ctx["home"]))
    return {"game_pk":game.get("gamePk"),"game":game,"event":event,"ctx":ctx,"phase":phase,"hmu":hmu,"amu":amu,"p_home":hm["p_effective"],
      "con":sharp_home,"quality":quality,"features":features,"options":options,
      "model":{"version":champ.get("version","structural-only"),"active":bool(champ.get("active")),"dispersion":dispersion},"engine_version":config.VERSION}
