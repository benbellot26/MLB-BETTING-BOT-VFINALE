from __future__ import annotations

"""Native Discord publication for Pulsar V14.

This module renders only the V14 production prediction surface. It deliberately
has no dependency on the legacy V11/V13 runtime or probability fields.
"""

import json
import os
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from . import MODEL_GENERATION, VERSION

_MATCH_COLORS = (
    0x5865F2,
    0x9B59B6,
    0x2ECC71,
    0xE67E22,
    0xE74C3C,
    0xF1C40F,
    0x1ABC9C,
    0xE91E63,
)


def _num(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return default


def _pct(value: Any) -> str:
    return f"**{100.0 * _num(value):.1f}%**"


def _team(result: dict[str, Any], side: str) -> str:
    ctx = result.get("ctx") or {}
    return str(ctx.get(side) or result.get(side) or "—")


def _lineup_status(lineup: Any) -> str:
    if not isinstance(lineup, dict):
        return "⚪ NON PUBLIÉE"
    count = int(_num(lineup.get("count"), len(lineup.get("players") or [])))
    confirmed = lineup.get("confirmed") is True
    if count >= 9 or (confirmed and len(lineup.get("players") or []) >= 9):
        return "✅ CONFIRMÉE 9/9"
    if count > 0:
        return f"🟡 PARTIELLE {count}/9"
    return "⚪ NON PUBLIÉE"


def _starter_name(ctx: dict[str, Any], side: str) -> str | None:
    for key in (f"{side}_sp", f"{side}_starter"):
        value = ctx.get(key)
        if isinstance(value, dict):
            name = value.get("name") or value.get("fullName")
            if name:
                return str(name)
        elif value:
            return str(value)
    return None


def _starter_status(name: str | None) -> str:
    return f"🟡 PROBABLE/ANNONCÉ — {name}" if name else "⚪ NON ANNONCÉ"


def build_game_embed(result: dict[str, Any]) -> dict[str, Any]:
    prediction = result.get("v14_prediction") or {}
    if prediction.get("model_generation") != MODEL_GENERATION or prediction.get("role") != "PRODUCTION":
        raise ValueError("result missing Pulsar V14 production prediction")
    probabilities = prediction.get("probabilities") or {}
    required = (
        "away_ml", "home_ml", "away_plus_1_5", "away_minus_1_5",
        "home_plus_1_5", "home_minus_1_5", "over", "under",
    )
    missing = [key for key in required if probabilities.get(key) is None]
    if missing:
        raise ValueError(f"incomplete V14 probability surface: {missing}")

    away, home = _team(result, "away"), _team(result, "home")
    line = _num(prediction.get("total_line") or (result.get("canonical_lines") or {}).get("TOTAL"))
    projection = prediction.get("run_projection") or {}
    ctx = result.get("ctx") or {}
    phase = str(result.get("phase") or prediction.get("phase") or "—").upper()
    gid = str(result.get("game_pk") or prediction.get("game_pk") or "0")
    try:
        color = _MATCH_COLORS[int(gid) % len(_MATCH_COLORS)]
    except Exception:
        color = _MATCH_COLORS[sum(ord(ch) for ch in gid) % len(_MATCH_COLORS)]

    context = prediction.get("context_adjustment") or {}
    context_label = "ACTIVE" if context.get("eligible") else "BASE"
    feature_as_of = context.get("feature_as_of") or "—"

    fields = [
        {
            "name": "🏆 MONEYLINE",
            "value": f"✈️ **{away}**  ·  {_pct(probabilities['away_ml'])}\n🏠 **{home}**  ·  {_pct(probabilities['home_ml'])}",
            "inline": False,
        },
        {
            "name": "⚾ RUN LINE ±1.5",
            "value": (
                f"✈️ **{away}**   `+1.5` {_pct(probabilities['away_plus_1_5'])}   │   `-1.5` {_pct(probabilities['away_minus_1_5'])}\n"
                f"🏠 **{home}**   `+1.5` {_pct(probabilities['home_plus_1_5'])}   │   `-1.5` {_pct(probabilities['home_minus_1_5'])}"
            ),
            "inline": False,
        },
        {
            "name": f"📊 TOTAL {line:g}",
            "value": f"📈 **OVER**  {_pct(probabilities['over'])}    │    📉 **UNDER**  {_pct(probabilities['under'])}",
            "inline": False,
        },
        {
            "name": "🧭 GAME SNAPSHOT",
            "value": (
                f"🎯 Projection  {away} **{_num(projection.get('away_mu')):.1f}**  —  **{_num(projection.get('home_mu')):.1f}** {home}\n"
                f"🧠 Phase **{phase}**  •  Context **{context_label}**  •  Model **{VERSION}**\n"
                f"🕒 PIT context **{feature_as_of}**"
            ),
            "inline": False,
        },
        {
            "name": "👥 Lineups & starters",
            "value": (
                f"✈️ {_lineup_status(ctx.get('away_lineup'))}  •  SP {_starter_status(_starter_name(ctx, 'away'))}\n"
                f"🏠 {_lineup_status(ctx.get('home_lineup'))}  •  SP {_starter_status(_starter_name(ctx, 'home'))}"
            ),
            "inline": False,
        },
    ]
    return {
        "title": f"⚾ {away} @ {home}  •  {phase}",
        "color": color,
        "fields": fields,
        "footer": {"text": f"Pulsar V14 • {MODEL_GENERATION}"},
    }


def _post_webhook(payload: dict[str, Any], webhook_url: str | None = None) -> bool:
    url = webhook_url or os.getenv("DISCORD_WEBHOOK_URL")
    if not url:
        raise RuntimeError("DISCORD_WEBHOOK_URL absent")
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = Request(url, data=body, headers={"Content-Type": "application/json", "User-Agent": "Pulsar-V14"}, method="POST")
    try:
        with urlopen(request, timeout=20) as response:
            return 200 <= int(response.status) < 300
    except (HTTPError, URLError, TimeoutError) as exc:
        raise RuntimeError(f"Discord webhook failed: {exc}") from exc


def send_game(result: dict[str, Any], webhook_url: str | None = None) -> bool:
    return _post_webhook({"username": "Pulsar V14", "embeds": [build_game_embed(result)]}, webhook_url=webhook_url)
