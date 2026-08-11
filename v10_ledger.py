#!/usr/bin/env python3
"""V10 prediction ledger, settlement and performance metrics."""
import hashlib,math
MARKETS=("ML","RUNLINE","TOTAL")
PHASES=("EARLY","LATE","FINAL")
def num(x,d=0.0):
    try:
        y=float(x);return y if math.isfinite(y) else d
    except Exception:return d
def norm(s):return "".join(c.lower() for c in str(s) if c.isalnum())
def prediction_id(game_pk,snapshot_id,market,name,point):return hashlib.sha1(f"{game_pk}|{snapshot_id}|{market}|{norm(name)}|{point}".encode()).hexdigest()[:20]
def prediction_payload(result,snapshot_id,rec):
    e=rec.get("winamax_eval") or {}
    return {"prediction_id":prediction_id(result.get("game_pk"),snapshot_id,rec.get("market"),rec.get("name"),rec.get("point")),"snapshot_id":snapshot_id,"game_pk":result.get("game_pk"),"analyzed_at":result.get("analyzed_at"),"phase":result.get("phase"),"market":rec.get("market"),"name":rec.get("name"),"point":rec.get("point"),"p_model_raw":rec.get("p_model_raw",rec.get("p_model")),"p_model":rec.get("p_model"),"p_win":rec.get("p_win"),"p_push":rec.get("p_push",0),"p_loss":rec.get("p_loss"),"p_market":rec.get("p_market"),"refs":rec.get("refs",0),"confidence":rec.get("confidence"),"fair":rec.get("fair"),"min_price":rec.get("min_price"),"quality":result.get("quality"),"winamax_price":e.get("price"),"winamax_qualified":bool(e.get("qualified")),"winamax_selected":bool(e.get("selected")),"result":None}
def predictions_for_snapshot(result,snapshot_id):
    return [prediction_payload(result,snapshot_id,rec) for market in MARKETS for rec in [(result.get("model_recs") or {}).get(market)] if rec]
def settle_market(market,name,point,home,away,home_score,away_score):
    hs,as_=num(home_score),num(away_score)
    if market=="ML":
        picked_home=norm(name)==norm(home);won=(hs>as_) if picked_home else (as_>hs);return "W" if won else "L"
    if market=="RUNLINE":
        picked_home=norm(name)==norm(home);score=(hs if picked_home else as_)+num(point);opp=(as_ if picked_home else hs);return "W" if score>opp else "L" if score<opp else "P"
    if market=="TOTAL":
        total=hs+as_;line=num(point)
        if abs(total-line)<1e-9:return "P"
        over=str(name).lower()=="over";return "W" if ((total>line)==over) else "L"
    return None
def settle_record_predictions(record):
    final=record.get("final") or record.get("final_score") or record.get("result") or {};hs=final.get("home_score",final.get("home"));as_=final.get("away_score",final.get("away"))
    if hs is None or as_ is None:return 0
    home=record.get("home") or final.get("home_name") or "";away=record.get("away") or final.get("away_name") or "";changed=0
    for p in record.get("predictions",[]) or []:
        if p.get("result") in ("W","L","P"):continue
        r=settle_market(p.get("market"),p.get("name"),p.get("point"),home,away,hs,as_)
        if r:p["result"]=r;changed+=1
    return changed
def brier(probs,ys):return sum((p-y)**2 for p,y in zip(probs,ys))/len(probs) if probs else None
def logloss(probs,ys):
    if not probs:return None
    out=0
    for p,y in zip(probs,ys):
        p=max(.001,min(.999,num(p,.5)));out+=-(y*math.log(p)+(1-y)*math.log(1-p))
    return out/len(probs)
def prediction_metrics(preds):
    settled=[p for p in preds if p.get("result") in ("W","L","P")];wl=[p for p in settled if p["result"] in ("W","L")];probs=[num(p.get("p_model"),.5) for p in wl];ys=[1 if p["result"]=="W" else 0 for p in wl]
    return {"n":len(settled),"n_wl":len(wl),"pushes":len(settled)-len(wl),"wins":sum(ys),"accuracy":sum(ys)/len(ys) if ys else None,"brier":brier(probs,ys),"logloss":logloss(probs,ys)}
def performance_report(hist):
    preds=[]
    for r in (hist or {}).values():preds.extend(r.get("predictions",[]) or [])
    return {"overall":prediction_metrics(preds),"by_market":{m:prediction_metrics([p for p in preds if p.get("market")==m]) for m in MARKETS},"by_phase":{ph:prediction_metrics([p for p in preds if p.get("phase")==ph]) for ph in PHASES},"by_confidence":{f"{lo}-{lo+1}":prediction_metrics([p for p in preds if lo<=num(p.get("confidence"))<lo+1]) for lo in (4,5,6,7,8,9)}}
def self_test():
    assert settle_market("ML","Home",None,"Home","Away",5,3)=="W" and settle_market("RUNLINE","Away",1.0,"Home","Away",5,4)=="P" and settle_market("TOTAL","Over",9,"Home","Away",5,4)=="P" and settle_market("TOTAL","Under",9.5,"Home","Away",5,4)=="W"
    preds=[{"result":"W","p_model":.7,"market":"ML","phase":"FINAL","confidence":7.2},{"result":"L","p_model":.6,"market":"ML","phase":"FINAL","confidence":7.1},{"result":"P","p_model":.55,"market":"RUNLINE","phase":"LATE","confidence":6.4}];r=performance_report({"g":{"predictions":preds}});assert r["overall"]["n"]==3 and r["overall"]["n_wl"]==2 and r["overall"]["logloss"] is not None
    print("SELF-TEST V10 LEDGER/METRICS OK",r["overall"])
if __name__=="__main__":self_test()
