from __future__ import annotations

"""Single production orchestration path for Pulsar V14."""

from typing import Any

from .champion_contract import CHAMPION_DISPERSION, CHAMPION_ENVIRONMENT_SIGMA, parameters_from_champion_result, validated_extra_innings_home_probability
from .context_overlay import context_overlay_from_feature_row
from .distribution import probability_surface
from .feature_row import feature_row_is_usable
from .model import RunProjection, prediction_payload
from .run_stack import StructuralRunInput, apply_current_champion, reproduce_from_champion_result


def _team_name(result:dict[str,Any],side:str)->str:
    direct=result.get(side)
    if direct:return str(direct)
    ctx=result.get("ctx") or {}
    if ctx.get(side):return str(ctx[side])
    game=result.get("game") or {}; teams=game.get("teams") or {}; team=((teams.get(side) or {}).get("team") or {}); name=team.get("name")
    if name:return str(name)
    raise ValueError(f"missing {side} team")


def _identity(result:dict[str,Any])->tuple[str,str,str]:
    game=result.get("game") or {}; game_pk=result.get("game_pk") or game.get("gamePk"); game_date=result.get("game_date") or game.get("gameDate"); analyzed_at=result.get("analyzed_at") or result.get("as_of")
    if not game_pk:raise ValueError("missing game_pk")
    if not game_date:raise ValueError("missing game_date")
    if not analyzed_at:raise ValueError("missing analyzed_at")
    return str(game_pk),str(game_date),str(analyzed_at)


def _selected_feature_row(feature_row:dict[str,Any]|None,*,game_pk:str,analyzed_at:str)->dict[str,Any]|None:
    return feature_row if feature_row_is_usable(feature_row,game_pk=game_pk,as_of=analyzed_at) else None


def _finish_prediction(*,structural_base:dict[str,Any],game_pk:str,game_date:str,analyzed_at:str,home:str,away:str,total_line:float,phase:str,feature_row:dict[str,Any]|None,dispersion:float,environment_sigma:float,extra_innings_home_probability:float,source_generation:str)->dict[str,Any]:
    selected=_selected_feature_row(feature_row,game_pk=game_pk,analyzed_at=analyzed_at); overlay=context_overlay_from_feature_row(selected,float(structural_base["home_mu"]),float(structural_base["away_mu"]))
    projection=RunProjection(game_pk=game_pk,game_date=game_date,analyzed_at=analyzed_at,home=home,away=away,home_mu=float(overlay["home_mu"]),away_mu=float(overlay["away_mu"]),total_line=float(total_line),phase=str(phase or "EARLY").upper(),dispersion=float(dispersion),environment_sigma=float(environment_sigma),extra_innings_home_probability=float(extra_innings_home_probability),source_generation=source_generation).validated()
    surface,tail_mass=probability_surface(projection); output=prediction_payload(projection,surface,tail_mass=tail_mass)
    output["base_run_projection"]={"home_mu":float(structural_base["home_mu"]),"away_mu":float(structural_base["away_mu"]),"active_layers":list(structural_base.get("active_layers") or [])}
    output["context_adjustment"]={"eligible":bool(overlay.get("eligible")),"home_delta":float(overlay.get("home_delta") or 0),"away_delta":float(overlay.get("away_delta") or 0),"feature_as_of":(feature_row or {}).get("as_of") if selected is not None else None,"components":overlay.get("components") or {}}
    return output


def predict_from_structural(structural:StructuralRunInput,*,analyzed_at:str,home:str,away:str,total_line:float,feature_row:dict[str,Any]|None=None,phase:str="EARLY",dispersion:float=CHAMPION_DISPERSION,environment_sigma:float=CHAMPION_ENVIRONMENT_SIGMA,extra_innings_home_probability:float|None=None)->dict[str,Any]:
    s=structural.validated(); extra=extra_innings_home_probability
    if extra is None: extra,_meta=validated_extra_innings_home_probability()
    return _finish_prediction(structural_base=apply_current_champion(s),game_pk=s.game_pk,game_date=s.game_date,analyzed_at=str(analyzed_at),home=str(home),away=str(away),total_line=float(total_line),phase=phase,feature_row=feature_row,dispersion=float(dispersion),environment_sigma=float(environment_sigma),extra_innings_home_probability=float(extra),source_generation="pulsar-v14-native-structural")


def predict_from_result(result:dict[str,Any],*,total_line:float,feature_row:dict[str,Any]|None=None)->dict[str,Any]:
    game_pk,game_date,analyzed_at=_identity(result); home,away=_team_name(result,"home"),_team_name(result,"away"); base=reproduce_from_champion_result(result); parameters=parameters_from_champion_result(result)
    return _finish_prediction(structural_base=base,game_pk=game_pk,game_date=game_date,analyzed_at=analyzed_at,home=home,away=away,total_line=float(total_line),phase=str(result.get("phase") or "EARLY"),feature_row=feature_row,dispersion=float(parameters["dispersion"]),environment_sigma=float(parameters["environment_sigma"]),extra_innings_home_probability=float(parameters["extra_innings_home_probability"]),source_generation=str(result.get("model_generation") or "legacy-input"))
