"""Small runtime hook for the V11.3 live runner only.

Python imports ``sitecustomize`` automatically when it is available on sys.path.
This hook is deliberately inert for every command except a real
``python v11_3_live.py`` execution.  It lets the existing GitHub Actions
workflow stay untouched while adding the requested post-settlement Discord
summary.
"""
from __future__ import annotations

import atexit
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path


_START_NS = time.time_ns()


def _is_live_v113_run() -> bool:
    try:
        return Path(sys.argv[0]).name == "v11_3_live.py" and "--self-test" not in sys.argv
    except Exception:
        return False


def _pct(value):
    if value is None:
        return "—"
    try:
        return f"{100*float(value):.1f}%"
    except Exception:
        return "—"


def _num(value, digits=4):
    if value is None:
        return "—"
    try:
        return f"{float(value):.{digits}f}"
    except Exception:
        return "—"


def _post_summary() -> None:
    webhook = os.getenv("DISCORD_WEBHOOK_URL", "").strip()
    if not webhook:
        return

    report_path = Path(os.getenv("V11_3_LIVE_REPORT", "data/v11_3_live_report.json"))
    try:
        if not report_path.exists() or report_path.stat().st_mtime_ns < _START_NS:
            return
        report = json.loads(report_path.read_text(encoding="utf-8"))
    except Exception:
        return

    # A summary is useful only when this execution actually settled new rows.
    settled_now = int(report.get("settled_comparison_rows_this_run") or 0)
    if settled_now <= 0:
        return

    c = report.get("comparison") or {}
    n = int(c.get("settled_games") or 0)
    v10w = int(c.get("v10_wins") or 0)
    v11w = int(c.get("v11_3_wins") or 0)
    changed = int(c.get("changed_direction_games") or 0)
    corrections = int(c.get("v11_corrections") or 0)
    regressions = int(c.get("v11_regressions") or 0)
    net = int(c.get("v11_net_corrections") or 0)

    grades = c.get("by_grade") or {}
    grade_lines = []
    for grade in ("FORT", "BON", "PRUDENCE", "FAIBLE"):
        g = grades.get(grade)
        if not g:
            continue
        grade_lines.append(
            f"**{grade}** : {int(g.get('wins') or 0)}/{int(g.get('n') or 0)} "
            f"({_pct(g.get('accuracy'))})"
        )
    if not grade_lines:
        grade_lines.append("Pas encore assez de matchs réglés par grade.")

    official = c.get("official_ml") or {}
    off_n = int(official.get("n") or 0)
    off_w = int(official.get("wins") or 0)
    official_text = (
        f"ML officiels : **{off_w}/{off_n} ({_pct(official.get('accuracy'))})**"
        if off_n else
        "Aucun ML officiel réglé dans l'échantillon comparatif."
    )

    if net > 0:
        verdict = f"🟢 V11.3 apporte **+{net} bonne prédiction nette** par rapport à V10."
        color = 5763719
    elif net < 0:
        verdict = f"🔴 V11.3 est à **{net} prédiction nette** par rapport à V10."
        color = 15548997
    else:
        verdict = "🟡 V11.3 et V10 sont actuellement à égalité en corrections nettes."
        color = 16766720

    fields = [
        {
            "name": "🏆 Direction — cumulé live",
            "value": (
                f"V10 : **{v10w}/{n} ({_pct(c.get('v10_accuracy'))})**\n"
                f"V11.3 : **{v11w}/{n} ({_pct(c.get('v11_3_accuracy'))})**\n"
                f"Directions différentes : **{changed}**\n"
                f"Corrections V11 : **{corrections}** • régressions : **{regressions}** • net : **{net:+d}**"
            ),
            "inline": False,
        },
        {
            "name": "🎯 Calibration ML",
            "value": (
                f"Brier V10 **{_num(c.get('v10_brier'))}** → V11.2 **{_num(c.get('v11_2_brier'))}**\n"
                f"LogLoss V10 **{_num(c.get('v10_logloss'))}** → V11.2 **{_num(c.get('v11_2_logloss'))}**\n"
                "*(plus bas = meilleur)*"
            ),
            "inline": False,
        },
        {
            "name": "⭐ V11.3 par grade",
            "value": "\n".join(grade_lines),
            "inline": False,
        },
        {
            "name": "🎟️ Picks officiels ML",
            "value": official_text,
            "inline": False,
        },
        {
            "name": "📌 Verdict provisoire",
            "value": verdict + "\nÉchantillon live encore limité : aucune modification automatique du modèle.",
            "inline": False,
        },
    ]

    payload = {
        "embeds": [{
            "title": "📊 BILAN LIVE — V10 vs V11.3",
            "description": f"**{settled_now}** nouvelle(s) ligne(s) réglée(s) sur ce run • **{n}** match(s) uniques cumulés.",
            "color": color,
            "fields": fields,
            "footer": {"text": "V11.3 live comparison • résultats officiels MLB"},
        }]
    }

    try:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(
            webhook,
            data=data,
            headers={"Content-Type": "application/json", "User-Agent": "MLB-Betting-Bot-V11.3"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=15) as response:
            response.read()
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError):
        # The report is observability only: a Discord failure must never make the
        # betting run fail or alter predictions/data persistence.
        return


if _is_live_v113_run():
    atexit.register(_post_summary)
