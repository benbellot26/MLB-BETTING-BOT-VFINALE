from pathlib import Path
p=Path('bot.py')
s=p.read_text(encoding='utf-8')
old='_V1010_BUILD_SNAPSHOT_011=build_snapshot\n\nVERSION="10.0.11"'
new='_V1010_BUILD_SNAPSHOT_011=build_snapshot\n_V1010_ALLOCATE_011=allocate_portfolio\n\nVERSION="10.0.11"'
if old not in s and '_V1010_ALLOCATE_011=allocate_portfolio' not in s:
    raise SystemExit('capture anchor not found')
s=s.replace(old,new,1)
old2='def allocate_portfolio(results):\n    global _V10_LAST_PORTFOLIO,_V1007_LAST_SLATE\n    for r in results:'
new2='def allocate_portfolio(results):\n    global _V10_LAST_PORTFOLIO,_V1007_LAST_SLATE\n    if not results or not all(("option_recs" in r or "model_recs" in r) for r in results):\n        return _V1010_ALLOCATE_011(results)\n    for r in results:'
if old2 not in s:
    raise SystemExit('allocate anchor not found')
s=s.replace(old2,new2,1)
p.write_text(s,encoding='utf-8')
print('Applied V10.0.11 compatibility fix')
