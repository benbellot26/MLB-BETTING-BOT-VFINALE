from __future__ import annotations

"""Component-wise certified close capture for the modern V14 workflow.

A <=15 minute timestamp is not, by itself, complete betting evidence. Pulsar
needs two independent immutable close components:

* PRIMARY: Pinnacle sportsbook no-vig fair probability for information CLV.
* EXECUTION: fresh same-book executable close for tradable price CLV.

The first valid observation of each component is frozen independently. A later
snapshot may fill a still-missing component but can never replace one already
captured. Legacy ledger capture functions remain available for compatibility;
the scheduled production close workflow uses this module.
"""

from datetime import datetime, timezone
import math
from pathlib import Path
from typing import Any, Callable

from . import MODEL_GENERATION, PROBABILITY_POLICY_ID
from .acquisition import MATCH_TIME_TOLERANCE_MINUTES, parse_time
from .bet_ledger import LEDGER as BET_LEDGER, _read as read_bets, _write as write_bets
from .market_close_ledger import (
    CERTIFIED_CLOSE_MAX_MINUTES,
    LEDGER as MARKET_LEDGER,
    PRIMARY_SHARP_BENCHMARK,
    _execution_from_close as archive_execution_close,
    _read as read_market,
    _selection_from_close as archive_selection,
)
from .official_close import (
    _event_for_row as official_event_for_row,
    _pinnacle_probability as official_pinnacle_probability,
    _same_book_close as official_same_book_close,
)
from .paper_ledger import (
    LEDGER as PAPER_LEDGER,
    _certification_row as is_paper_certification_row,
    _event_for_row as paper_event_for_row,
    _execution_close as paper_execution_close,
    _pinnacle_probability as paper_pinnacle_probability,
    _read as read_paper,
    _write as write_paper,
)
from .sharp_market import sharp_consensus

PRIMARY="PRIMARY"
EXECUTION="EXECUTION"
COMPONENTS=(PRIMARY,EXECUTION)


def _num(value:Any)->float|None:
    try:out=float(value)
    except Exception:return None
    return out if math.isfinite(out) else None


def _valid_probability(value:Any)->bool:
    numeric=_num(value);return numeric is not None and 0<numeric<1


def _valid_odds(value:Any)->bool:
    numeric=_num(value);return numeric is not None and numeric>1


def paper_component_needs(row:dict[str,Any])->list[str]:
    primary_complete=(
        row.get("certification_clv_benchmark")==PRIMARY_SHARP_BENCHMARK
        and _valid_probability(row.get("closing_pinnacle_probability"))
        and _num(row.get("certification_clv_pp")) is not None
    )
    execution_complete=_valid_odds(row.get("execution_close_odds")) and _num(row.get("execution_price_clv_pp")) is not None
    return ([PRIMARY] if not primary_complete else [])+([EXECUTION] if not execution_complete else [])


def official_component_needs(row:dict[str,Any])->list[str]:
    primary_complete=(
        row.get("sharp_information_benchmark")==PRIMARY_SHARP_BENCHMARK
        and _valid_probability(row.get("sharp_fair_close_probability"))
        and _num(row.get("sharp_information_clv_pp")) is not None
    )
    execution_complete=_valid_odds(row.get("execution_close_odds")) and _num(row.get("execution_price_clv_pp")) is not None
    return ([PRIMARY] if not primary_complete else [])+([EXECUTION] if not execution_complete else [])


def _within_component_window(row:dict[str,Any],current:datetime)->float|None:
    try:mins=(parse_time(row.get("game_date"))-current).total_seconds()/60.0
    except Exception:return None
    return mins if 0<mins<=CERTIFIED_CLOSE_MAX_MINUTES else None


def _event_time_delta(event:dict[str,Any],row:dict[str,Any])->float|None:
    try:return abs((parse_time(event.get("commence_time"))-parse_time(row.get("game_date"))).total_seconds())/60.0
    except Exception:return None


def _entry_execution_probability(row:dict[str,Any],odds_field:str)->float|None:
    direct=_num(row.get("entry_execution_implied_probability"))
    if direct is not None and 0<direct<1:return direct
    odds=_num(row.get(odds_field));return 1/odds if odds is not None and odds>1 else None


def _append_component_history(row:dict[str,Any],marker:dict[str,Any])->None:
    history=row.get("close_history") if isinstance(row.get("close_history"),list) else []
    key=(marker.get("captured_at"),marker.get("odds_event_id"),tuple(marker.get("components_captured") or []),marker.get("source"))
    if not any(
        isinstance(item,dict)
        and (item.get("captured_at"),item.get("odds_event_id"),tuple(item.get("components_captured") or []),item.get("source"))==key
        for item in history
    ):history.append(marker)
    row["close_history"]=history


def _set_compatibility_close(row:dict[str,Any],*,captured:str,mins:float,primary:bool)->None:
    # Compatibility fields represent PRIMARY whenever it exists. An execution-
    # only observation may populate them temporarily, but a later first PRIMARY
    # observation is allowed to replace only these aliases, never component data.
    has_primary=not paper_component_needs(row) or row.get("certification_clv_benchmark")==PRIMARY_SHARP_BENCHMARK
    if primary or str(row.get("close_quality") or "")!="CERTIFIED_CLOSE" or not has_primary:
        row["close_captured_at"]=captured;row["close_minutes_to_game"]=mins;row["close_quality"]="CERTIFIED_CLOSE"


def capture_paper_components(path:Path|str=PAPER_LEDGER,*,api_key:str|None=None,events_loader:Callable[[],list[dict[str,Any]]]|None=None,now:datetime|None=None)->int:
    del api_key
    rows=read_paper(path);current=now or datetime.now(timezone.utc)
    if current.tzinfo is None:current=current.replace(tzinfo=timezone.utc)
    current=current.astimezone(timezone.utc);pending=[]
    for row in rows:
        if not is_paper_certification_row(row):continue
        needs=paper_component_needs(row);mins=_within_component_window(row,current)
        if needs and mins is not None:pending.append((row,mins,needs))
    if not pending:return 0
    events=(events_loader or (lambda:[]))();captured=current.isoformat();changed=0
    for row,mins,needs in pending:
        event=paper_event_for_row(row,events)
        if event is None:continue
        delta=_event_time_delta(event,row)
        if delta is None or delta>MATCH_TIME_TOLERANCE_MINUTES:continue
        selection=str(row.get("selection") or "");line=_num(row.get("total_line")) if selection in {"over","under"} else None
        if selection in {"over","under"} and line is None:continue
        entry_exec=_entry_execution_probability(row,"execution_odds")
        if entry_exec is None:continue
        captured_components=[];marker:dict[str,Any]={"captured_at":captured,"minutes_to_game":mins,"quality":"CERTIFIED_CLOSE","odds_event_id":event.get("id"),"event_time_delta_minutes":delta,"source":"COMPONENT_CLOSE_CAPTURE","components_captured":captured_components}

        if PRIMARY in needs:
            sharp=sharp_consensus(event,total_line=line,as_of=captured);sharp_row=((sharp.get("selections") or {}).get(selection) or {})
            consensus=_num(sharp_row.get("fair_probability"));pinnacle=paper_pinnacle_probability(sharp_row)
            if sharp.get("freshness_verified") is True and pinnacle is not None and 0<pinnacle<1:
                captured_components.append(PRIMARY);entry_sharp=_num(row.get("entry_sharp_probability"))
                row["primary_close_captured_at"]=captured;row["primary_close_minutes_to_game"]=mins;row["primary_close_quality"]="CERTIFIED_CLOSE";row["closing_pinnacle_probability"]=pinnacle;row["pinnacle_fair_close_odds"]=1/pinnacle;row["certification_clv_pp"]=(pinnacle-entry_exec)*100;row["certification_clv_benchmark"]=PRIMARY_SHARP_BENCHMARK
                if consensus is not None and 0<consensus<1:
                    row["closing_sharp_probability"]=consensus;row["sharp_fair_close_odds"]=1/consensus;row["sharp_clv_pp"]=(consensus-entry_sharp)*100 if entry_sharp is not None else None
                marker.update({"sharp_fair_probability":consensus,"pinnacle_no_vig_probability":pinnacle,"primary_benchmark":PRIMARY_SHARP_BENCHMARK,"sharp_dispersion_pp":_num(sharp_row.get("dispersion_pp"))})
                _set_compatibility_close(row,captured=captured,mins=mins,primary=True)

        if EXECUTION in needs:
            execution=paper_execution_close(event,row,as_of=captured)
            if execution is not None and execution>1:
                captured_components.append(EXECUTION);row["execution_close_captured_at"]=captured;row["execution_close_minutes_to_game"]=mins;row["execution_close_quality"]="CERTIFIED_CLOSE";row["execution_close_odds"]=execution;row["execution_price_clv_pp"]=(1/execution-entry_exec)*100;marker["execution_close_odds"]=execution
                if PRIMARY not in captured_components:_set_compatibility_close(row,captured=captured,mins=mins,primary=False)

        if captured_components:
            marker["components_captured"]=list(captured_components);_append_component_history(row,marker);changed+=1
    if changed:write_paper(rows,path)
    return changed


def capture_official_components(*,path:Path|str=BET_LEDGER,api_key:str|None=None,events_loader:Callable[[],list[dict[str,Any]]]|None=None,now:datetime|None=None)->int:
    del api_key
    rows=read_bets(path);current=now or datetime.now(timezone.utc)
    if current.tzinfo is None:current=current.replace(tzinfo=timezone.utc)
    current=current.astimezone(timezone.utc);pending=[]
    for row in rows:
        if row.get("result"):continue
        needs=official_component_needs(row);mins=_within_component_window(row,current)
        if needs and mins is not None:pending.append((row,mins,needs))
    if not pending:return 0
    events=(events_loader or (lambda:[]))();captured=current.isoformat();changed=0
    for row,mins,needs in pending:
        event=official_event_for_row(row,events)
        if event is None:continue
        delta=_event_time_delta(event,row)
        if delta is None or delta>60.0:continue
        selection=str(row.get("selection") or "");line=_num(row.get("line")) if selection in {"over","under"} else None
        if selection in {"over","under"} and line is None:continue
        entry_exec=_entry_execution_probability(row,"odds")
        if entry_exec is None:continue
        captured_components=[];marker:dict[str,Any]={"captured_at":captured,"minutes_to_game":mins,"quality":"CERTIFIED_CLOSE","odds_event_id":event.get("id"),"event_time_delta_minutes":delta,"source":"COMPONENT_CLOSE_CAPTURE","components_captured":captured_components}

        if PRIMARY in needs:
            sharp=sharp_consensus(event,total_line=line,as_of=captured);sharp_row=((sharp.get("selections") or {}).get(selection) or {});pinnacle=official_pinnacle_probability(sharp_row);consensus=_num(sharp_row.get("fair_probability"))
            if sharp.get("freshness_verified") is True and pinnacle is not None and 0<pinnacle<1:
                captured_components.append(PRIMARY);row["primary_close_captured_at"]=captured;row["primary_close_minutes_to_game"]=mins;row["primary_close_quality"]="CERTIFIED_CLOSE";row["closing_odds"]=1/pinnacle;row["closing_source"]="verified Pinnacle no-vig fair probability <=15m pregame (CERTIFIED_CLOSE)";row["clv_implied_probability_pp"]=(pinnacle-entry_exec)*100;row["sharp_fair_close_probability"]=pinnacle;row["sharp_fair_close_odds"]=1/pinnacle;row["sharp_information_clv_pp"]=(pinnacle-entry_exec)*100;row["sharp_information_benchmark"]=PRIMARY_SHARP_BENCHMARK;row["close_captured_at"]=captured;row["close_minutes_to_game"]=mins;row["close_quality"]="CERTIFIED_CLOSE";marker.update({"sharp_fair_probability":consensus,"pinnacle_no_vig_probability":pinnacle,"primary_benchmark":PRIMARY_SHARP_BENCHMARK})

        if EXECUTION in needs:
            execution=official_same_book_close(event,row,as_of=captured)
            if execution is not None and execution>1:
                captured_components.append(EXECUTION);row["execution_close_captured_at"]=captured;row["execution_close_minutes_to_game"]=mins;row["execution_close_quality"]="CERTIFIED_CLOSE";row["execution_close_odds"]=execution;row["execution_price_clv_pp"]=(1/execution-entry_exec)*100;marker["execution_close_odds"]=execution
                if str(row.get("close_quality") or "")!="CERTIFIED_CLOSE":row["close_captured_at"]=captured;row["close_minutes_to_game"]=mins;row["close_quality"]="CERTIFIED_CLOSE"

        if captured_components:
            marker["components_captured"]=list(captured_components);_append_component_history(row,marker);changed+=1
    if changed:write_bets(rows,path)
    return changed


def _eligible_archive_close(close:dict[str,Any],paper:dict[str,Any])->tuple[datetime,float]|None:
    if not isinstance(close,dict) or str(close.get("quality") or "")!="CERTIFIED_CLOSE":return None
    if str(close.get("odds_event_id") or "")!=str(paper.get("odds_event_id") or ""):return None
    try:captured=parse_time(close.get("captured_at"));analyzed=parse_time(paper.get("analyzed_at"));game=parse_time(paper.get("game_date"))
    except Exception:return None
    mins=_num(close.get("minutes_to_game"))
    if not (analyzed<=captured<game) or mins is None or not (0<mins<=CERTIFIED_CLOSE_MAX_MINUTES):return None
    return captured,mins


def hydrate_paper_components(market_path:Path|str=MARKET_LEDGER,paper_path:Path|str=PAPER_LEDGER)->int:
    """Fill each missing paper component from its earliest usable archive close."""
    archives={str(row.get("game_pk") or ""):row for row in read_market(market_path) if row.get("model_generation")==MODEL_GENERATION and row.get("probability_policy_id")==PROBABILITY_POLICY_ID and row.get("certification_eligible") is False};papers=read_paper(paper_path);changed=0
    for paper in papers:
        if paper.get("model_generation")!=MODEL_GENERATION or paper.get("probability_policy_id")!=PROBABILITY_POLICY_ID:continue
        needs=paper_component_needs(paper)
        if not needs:continue
        archive=archives.get(str(paper.get("game_pk") or ""));event_id=str(paper.get("odds_event_id") or "")
        if archive is None or not event_id or str(archive.get("odds_event_id") or "")!=event_id:continue
        entry_exec=_entry_execution_probability(paper,"execution_odds")
        if entry_exec is None:continue
        eligible=[]
        for close in archive.get("close_history") or []:
            timing=_eligible_archive_close(close,paper)
            if timing is not None:eligible.append((timing[0],timing[1],close))
        eligible.sort(key=lambda item:item[0]);row_changed=False

        if PRIMARY in needs:
            for _,mins,close in eligible:
                selection=archive_selection(close,paper) or {};consensus=_num(selection.get("fair_probability"));pinnacle=_num(selection.get("pinnacle_no_vig_probability"))
                if pinnacle is None or not 0<pinnacle<1:continue
                captured=str(close.get("captured_at"));entry_sharp=_num(paper.get("entry_sharp_probability"));paper["primary_close_captured_at"]=captured;paper["primary_close_minutes_to_game"]=mins;paper["primary_close_quality"]="CERTIFIED_CLOSE";paper["closing_pinnacle_probability"]=pinnacle;paper["pinnacle_fair_close_odds"]=1/pinnacle;paper["certification_clv_pp"]=(pinnacle-entry_exec)*100;paper["certification_clv_benchmark"]=PRIMARY_SHARP_BENCHMARK;paper["close_captured_at"]=captured;paper["close_minutes_to_game"]=mins;paper["close_quality"]="CERTIFIED_CLOSE"
                if consensus is not None and 0<consensus<1:paper["closing_sharp_probability"]=consensus;paper["sharp_fair_close_odds"]=1/consensus;paper["sharp_clv_pp"]=(consensus-entry_sharp)*100 if entry_sharp is not None else None
                _append_component_history(paper,{"captured_at":captured,"minutes_to_game":mins,"quality":"CERTIFIED_CLOSE","odds_event_id":close.get("odds_event_id"),"source":"RESEARCH_MARKET_CLOSE_ARCHIVE_COMPONENT","components_captured":[PRIMARY],"sharp_fair_probability":consensus,"pinnacle_no_vig_probability":pinnacle,"primary_benchmark":PRIMARY_SHARP_BENCHMARK});row_changed=True;break

        if EXECUTION in needs:
            for _,mins,close in eligible:
                execution=archive_execution_close(close,paper)
                if execution is None or execution<=1:continue
                captured=str(close.get("captured_at"));paper["execution_close_captured_at"]=captured;paper["execution_close_minutes_to_game"]=mins;paper["execution_close_quality"]="CERTIFIED_CLOSE";paper["execution_close_odds"]=execution;paper["execution_price_clv_pp"]=(1/execution-entry_exec)*100
                if str(paper.get("close_quality") or "")!="CERTIFIED_CLOSE":paper["close_captured_at"]=captured;paper["close_minutes_to_game"]=mins;paper["close_quality"]="CERTIFIED_CLOSE"
                _append_component_history(paper,{"captured_at":captured,"minutes_to_game":mins,"quality":"CERTIFIED_CLOSE","odds_event_id":close.get("odds_event_id"),"source":"RESEARCH_MARKET_CLOSE_ARCHIVE_COMPONENT","components_captured":[EXECUTION],"execution_close_odds":execution});row_changed=True;break
        if row_changed:changed+=1
    if changed:write_paper(papers,paper_path)
    return changed
