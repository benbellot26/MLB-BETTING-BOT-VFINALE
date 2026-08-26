from __future__ import annotations

"""Historical point-in-time contract for Pulsar V14 research.

Live MLB `stats=season` responses are valid for a snapshot captured before a
future game, but they are NOT valid for reconstructing an old game at a later
date.  Historical training must therefore be built from immutable events whose
effective timestamp is strictly before the target cutoff.
"""

from datetime import datetime, timezone
import math
from typing import Any, Iterable

ROLE="DATA_CONTRACT"
UNSAFE_HISTORICAL_SOURCES={"mlb_stats_season_live","mlb_people_stats_season_live","mlb_teams_stats_season_live"}


def _dt(value:Any)->datetime:
    dt=datetime.fromisoformat(str(value).replace("Z","+00:00"))
    if dt.tzinfo is None: dt=dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def strictly_before(event_time:Any,cutoff:Any)->bool:
    try: return _dt(event_time)<_dt(cutoff)
    except Exception: return False


def filter_events(events:Iterable[dict[str,Any]],*,cutoff:Any,time_keys:tuple[str,...]=( "event_time","game_date","gameDate","date"))->list[dict[str,Any]]:
    out=[]
    for row in events:
        if not isinstance(row,dict): continue
        timestamp=next((row.get(k) for k in time_keys if row.get(k)),None)
        if timestamp is not None and strictly_before(timestamp,cutoff): out.append(row)
    return sorted(out,key=lambda r:_dt(next(r.get(k) for k in time_keys if r.get(k))))


def aggregate_counting_stats(rows:Iterable[dict[str,Any]],fields:Iterable[str])->dict[str,float]:
    out={str(field):0.0 for field in fields}
    for row in rows:
        for field in out:
            try: value=float(row.get(field) or 0.0)
            except Exception: value=0.0
            if math.isfinite(value): out[field]+=value
    return out


def hitting_rates(counts:dict[str,Any])->dict[str,float|None]:
    def n(k:str)->float:
        try: return float(counts.get(k) or 0.0)
        except Exception: return 0.0
    ab=n("atBats"); bb=n("baseOnBalls"); hbp=n("hitByPitch"); sf=n("sacFlies"); h=n("hits"); doubles=n("doubles"); triples=n("triples"); hr=n("homeRuns")
    singles=max(0.0,h-doubles-triples-hr); tb=singles+2*doubles+3*triples+4*hr; pa=ab+bb+hbp+sf
    obp=(h+bb+hbp)/pa if pa>0 else None; slg=tb/ab if ab>0 else None
    return {"pa":pa,"avg":h/ab if ab>0 else None,"obp":obp,"slg":slg,"ops":(obp+slg) if obp is not None and slg is not None else None}


def source_contract(*,captured_at:Any,effective_cutoff:Any,source_type:str,prospective:bool)->dict[str,Any]:
    historical_safe=source_type not in UNSAFE_HISTORICAL_SOURCES and strictly_before(effective_cutoff,captured_at) if not prospective else True
    return {"schema":"pulsar-v14-pit-source-contract-v1","role":ROLE,"captured_at":str(captured_at),"effective_cutoff":str(effective_cutoff),"source_type":str(source_type),"prospective":bool(prospective),"live_pregame_safe":bool(prospective),"historical_reconstruction_safe":bool(historical_safe),"rule":"historical features may only consume immutable events strictly before target game cutoff"}


def training_eligible(contract:dict[str,Any],*,historical:bool)->bool:
    if historical: return contract.get("historical_reconstruction_safe") is True
    return contract.get("live_pregame_safe") is True


def reject_live_season_backfill(*,target_game_date:Any,retrieved_at:Any,source_type:str)->None:
    """Hard guard used by future backfill builders before accepting live season endpoints."""
    if source_type in UNSAFE_HISTORICAL_SOURCES:
        try:
            if _dt(retrieved_at)>_dt(target_game_date):
                raise ValueError("historical leakage: live season endpoint retrieved after target game is not PIT-safe")
        except ValueError:
            raise
        except Exception:
            raise ValueError("historical PIT timestamps are invalid")
