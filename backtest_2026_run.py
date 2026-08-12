#!/usr/bin/env python3
import backtest_2026 as bt

_original_schedule = bt.schedule

def unique_schedule():
    games = _original_schedule()
    unique = {}
    for g in games:
        unique[g["game_pk"]] = g
    out = sorted(unique.values(), key=lambda x: (x["game_date"], x["game_pk"]))
    print(f"Schedule dedupe: {len(games)} rows -> {len(out)} unique gamePk", flush=True)
    return out

bt.schedule = unique_schedule
bt.main()
