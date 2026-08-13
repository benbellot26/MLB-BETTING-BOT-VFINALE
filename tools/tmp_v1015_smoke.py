import bot

bot._V1015_CAL_CACHE={
    'ML':{'active':False,'factor':1.0,'n':0,'source':'test','reliability':.80},
    'RUNLINE':{'active':False,'factor':1.0,'n':0,'source':'test','reliability':.78},
    'TOTAL':{'active':False,'factor':1.0,'n':0,'source':'test','reliability':.64},
}
bot._V1014_PRIOR_INDEX={}

def make(gid,p):
    home=f'H{gid}';away=f'A{gid}'
    rec={'market':'ML','name':home,'point':None,'option_role':'ML_HOME','p_model':.75,'p_effective':p,'p_effective_static':p,
         'p_push':0,'confidence':8.0,'refs':4,'p_market':.59,'min_price_effective':1.65,'winamax_eval':{}}
    return {'game_pk':gid,'game':{'gameDate':'2026-08-13T20:00:00Z'},'phase':'FINAL','seconds':3600,'quality':.90,
            'stability_alert':'OK','stability_delta':.005,'ctx':{'home':home,'away':away,'home_sp':'Starter H','away_sp':'Starter A',
            'home_lineup':{'count':9,'confirmed':True},'away_lineup':{'count':9,'confirmed':True}},'option_recs':[rec],'evals':[]}

results=[make(2001,.632),make(2002,.630),make(2003,.628),make(2004,.625)]
portfolio=bot.allocate_portfolio(results)
selected=[]
for r in results:
    for rec in bot.v1011_iter_options(r):
        if (rec.get('winamax_eval') or {}).get('official_selected'):
            selected.append((r['game_pk'],rec['name'],rec['selection_official_score']))
assert len(selected)==3, selected
assert selected[0][2]>=selected[-1][2]
assert portfolio['official_count']==3
assert portfolio.get('combo_official') is True
assert abs(portfolio.get('combo_units',0)-.5)<1e-9
assert portfolio['allocated']<=portfolio['daily_cap']+1e-9
for r in results:
    for rec in bot.v1011_iter_options(r):
        sh=rec.get('selection_shadow') or {}
        assert 'v1013_probability' in sh and 'official_v2' in sh
print('V10.0.15 portfolio smoke OK',selected,'combo',portfolio.get('combo_official'),portfolio.get('allocated'))
