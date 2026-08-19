from __future__ import annotations

import html
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import v138_research_models as models
from . import v138_validation as validation

OUT=Path("data/v138_monitoring.json")
HISTORY=Path("data/v138_provider_health.jsonl")
DASHBOARD=Path("data/v138_dashboard.html")


def _load(path: str) -> dict[str,Any]:
    p=Path(path)
    if not p.exists():return {}
    try:return json.loads(p.read_text(encoding="utf-8"))
    except Exception:return {}


def _append(path: Path,row: dict[str,Any]) -> None:
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open("a",encoding="utf-8") as f:f.write(json.dumps(row,ensure_ascii=False,sort_keys=True,separators=(",",":"))+"\n")


def provider_snapshot() -> dict[str,Any]:
    free=_load("data/v137_free_data_health.json");state=_load("data/v137_mlb_state_report.json")
    stat=_load("data/v137_statcast_priors_report.json");weather=_load("data/v137_weather_backfill_report.json");park=_load("data/v137_park_factors_report.json")
    return {"observed_at":datetime.now(timezone.utc).isoformat(),
        "free_health_status":free.get("status"),"statcast_rows":stat.get("rows") or stat.get("accepted_pitch_rows"),
        "statcast_failures":stat.get("failed_chunks") or stat.get("failures"),"weather_available":weather.get("available_rows"),
        "weather_rows":weather.get("rows"),"park_rows":park.get("rows") or park.get("parsed_rows"),
        "rosters_ok":state.get("rosters_ok"),"transactions":state.get("transactions"),"il_signals":state.get("injured_list_transaction_signals")}


def _history(limit: int=90) -> list[dict[str,Any]]:
    if not HISTORY.exists():return []
    out=[]
    for line in HISTORY.read_text(encoding="utf-8").splitlines()[-limit:]:
        try:out.append(json.loads(line))
        except Exception:pass
    return out


def build() -> dict[str,Any]:
    snap=provider_snapshot();_append(HISTORY,snap);hist=_history()
    rows,labels=models.load_free_dataset();vectors=[models.vectorize(r) for r in rows]
    drift={"available":False}
    if len(vectors)>=200:
        split=max(100,len(vectors)-min(500,max(50,len(vectors)//5)))
        drift=validation.feature_drift(vectors[:split],vectors[split:])
    research=_load("data/v138_research_models.json");val=_load("data/v138_validation.json");manifest=_load("data/v138_dataset_manifest.json")
    alerts=[]
    if snap.get("rosters_ok") not in (None,30):alerts.append("roster_provider_incomplete")
    if snap.get("statcast_failures"):alerts.append("statcast_provider_failure")
    if snap.get("weather_rows") and not snap.get("weather_available"):alerts.append("weather_zero_coverage")
    for x in drift.get("alerts") or []:alerts.append(f"feature_drift:{x}")
    return {"schema":"v13-8-monitoring-v1","generated_at":datetime.now(timezone.utc).isoformat(),"provider_current":snap,
        "provider_history":hist,"feature_drift":drift,"research_model":{"status":research.get("status"),"games":research.get("games"),
        "holdout_metrics":research.get("holdout_metrics"),"ensemble_weights":research.get("ensemble_weights")},
        "validation":val,"dataset":{"feature_rows":manifest.get("feature_rows"),"label_rows":manifest.get("label_rows"),
        "dataset_version":manifest.get("dataset_version"),"feature_contract_sha256":manifest.get("feature_contract_sha256")},
        "alerts":sorted(set(alerts)),"claim":"observability only; no automatic model retuning"}


def render(report: dict[str,Any]) -> str:
    def esc(x: Any)->str:return html.escape(str(x if x is not None else "—"))
    current=report.get("provider_current") or {};research=report.get("research_model") or {};dataset=report.get("dataset") or {}
    drift=(report.get("feature_drift") or {}).get("features") or {}
    alert_html="".join(f"<li>{esc(x)}</li>" for x in report.get("alerts") or []) or "<li>None</li>"
    drift_rows="".join(f"<tr><td>{esc(k)}</td><td>{esc(round(float(v.get('standardized_shift') or 0),3))}</td><td>{'⚠️' if v.get('alert') else 'OK'}</td></tr>" for k,v in drift.items())
    return f'''<!doctype html><html><head><meta charset="utf-8"><title>MLB V13.8 Model Health</title><style>
body{{font-family:system-ui,Arial;margin:28px;background:#111;color:#eee}}.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:14px}}
.card{{background:#1c1c1c;border:1px solid #333;border-radius:10px;padding:14px}}table{{width:100%;border-collapse:collapse}}td,th{{border-bottom:1px solid #333;padding:7px;text-align:left}}code{{color:#9fe}}
</style></head><body><h1>MLB V13.8 — Model & Data Health</h1><p>Generated {esc(report.get('generated_at'))}</p><div class="grid">
<div class="card"><h3>Research challenger</h3><b>{esc(research.get('status'))}</b><p>Games: {esc(research.get('games'))}</p></div>
<div class="card"><h3>Dataset</h3><p>Features: {esc(dataset.get('feature_rows'))}<br>Labels: {esc(dataset.get('label_rows'))}</p></div>
<div class="card"><h3>MLB state</h3><p>Rosters: {esc(current.get('rosters_ok'))}/30<br>Transactions: {esc(current.get('transactions'))}</p></div>
<div class="card"><h3>Free providers</h3><p>Statcast: {esc(current.get('statcast_rows'))}<br>Weather: {esc(current.get('weather_available'))}/{esc(current.get('weather_rows'))}<br>Park: {esc(current.get('park_rows'))}</p></div>
</div><h2>Alerts</h2><ul>{alert_html}</ul><h2>Feature drift</h2><table><tr><th>Feature</th><th>Std shift</th><th>Status</th></tr>{drift_rows}</table>
<h2>Research metrics</h2><pre>{esc(json.dumps(research.get('holdout_metrics') or {{}},indent=2,sort_keys=True))}</pre>
<p><small>Monitoring/research artifact only. No automatic model promotion or betting action.</small></p></body></html>'''


def main() -> None:
    report=build();OUT.parent.mkdir(parents=True,exist_ok=True);OUT.write_text(json.dumps(report,ensure_ascii=False,indent=2,sort_keys=True),encoding="utf-8")
    DASHBOARD.write_text(render(report),encoding="utf-8");print(json.dumps({"schema":report["schema"],"alerts":report["alerts"],"dashboard":str(DASHBOARD)},indent=2))


if __name__=="__main__":main()
