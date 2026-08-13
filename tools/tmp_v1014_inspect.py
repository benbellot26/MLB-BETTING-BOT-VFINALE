import json
from pathlib import Path
from collections import Counter
p=Path('data/mlb_backtest_2026.jsonl')
rows=[json.loads(x) for x in p.read_text(encoding='utf-8').splitlines() if x.strip()]
print('ROWS',len(rows))
print('TOP_KEYS',sorted(rows[0].keys()))
for i,r in enumerate(rows[:3]):
    print('ROW',i,json.dumps(r,ensure_ascii=False,sort_keys=True))
for k in sorted(rows[0].keys()):
    vals=[r.get(k) for r in rows]
    typ=Counter(type(v).__name__ for v in vals)
    print('KEY',k,'types',dict(typ),'sample',repr(next((v for v in vals if v is not None),None))[:500])
