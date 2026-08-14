from __future__ import annotations
import copy, gzip, hashlib, json, logging, math, os, time, urllib.error, urllib.parse, urllib.request
from datetime import datetime, timezone, timedelta
from statistics import mean
from zoneinfo import ZoneInfo

PARIS = ZoneInfo("Europe/Paris")
NOW = datetime.now(timezone.utc)
LOCAL_NOW = datetime.now(PARIS)
DEFAULT_DATE = (LOCAL_NOW.date()-timedelta(days=1)).isoformat() if LOCAL_NOW.hour < 6 else LOCAL_NOW.date().isoformat()
TARGET_DATE = os.getenv("MLB_DATE", DEFAULT_DATE)
SEASON = int(os.getenv("MLB_SEASON", TARGET_DATE[:4]))
ODDS_KEY = os.getenv("ODDS_API_KEY", "").strip()
DISCORD_URL = os.getenv("DISCORD_WEBHOOK_URL", "").strip()
UNIT = float(os.getenv("UNIT", "0.5") or 0.5)
BANKROLL = float(os.getenv("BANKROLL", "10") or 10)
TIMEOUT = int(os.getenv("HTTP_TIMEOUT", "25") or 25)
DISCORD_MIN_INTERVAL = float(os.getenv("DISCORD_MIN_INTERVAL", "0.75") or .75)
BOOKMAKERS = [x.strip() for x in os.getenv(
    "ODDS_BOOKMAKERS",
    "winamax_fr,pinnacle,betfair_ex_eu,matchbook,betonlineag,betclic_fr,unibet_fr,pmu_fr,netbet_fr"
).split(",") if x.strip()]
SHARP_BOOKS = {"pinnacle", "betfair_ex_eu", "matchbook", "betonlineag"}
WINAMAX_KEY = "winamax_fr"
logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO").upper(), format="%(asctime)s | %(levelname)s | %(message)s")

PARK = {"Arizona Diamondbacks":1.04,"Athletics":1.05,"Atlanta Braves":1.01,"Baltimore Orioles":1.01,"Boston Red Sox":1.03,"Chicago White Sox":1.00,"Chicago Cubs":1.02,"Cincinnati Reds":1.05,"Cleveland Guardians":0.98,"Colorado Rockies":1.14,"Detroit Tigers":0.98,"Houston Astros":1.00,"Kansas City Royals":0.99,"Los Angeles Angels":1.01,"Los Angeles Dodgers":0.98,"Miami Marlins":0.96,"Milwaukee Brewers":1.00,"Minnesota Twins":0.99,"New York Mets":0.98,"New York Yankees":1.03,"Philadelphia Phillies":1.02,"Pittsburgh Pirates":0.97,"San Diego Padres":0.97,"San Francisco Giants":0.94,"Seattle Mariners":0.96,"St. Louis Cardinals":1.00,"Tampa Bay Rays":0.98,"Texas Rangers":1.02,"Toronto Blue Jays":1.01,"Washington Nationals":1.00}
COORD = {"Arizona Diamondbacks":(33.4453,-112.0667),"Athletics":(38.5806,-121.5130),"Atlanta Braves":(33.8907,-84.4677),"Baltimore Orioles":(39.2839,-76.6217),"Boston Red Sox":(42.3467,-71.0972),"Chicago White Sox":(41.8301,-87.6338),"Chicago Cubs":(41.9484,-87.6553),"Cincinnati Reds":(39.0975,-84.5069),"Cleveland Guardians":(41.4962,-81.6852),"Colorado Rockies":(39.7559,-104.9942),"Detroit Tigers":(42.3390,-83.0485),"Houston Astros":(29.7573,-95.3555),"Kansas City Royals":(39.0517,-94.4803),"Los Angeles Angels":(33.8003,-117.8827),"Los Angeles Dodgers":(34.0739,-118.2400),"Miami Marlins":(25.7781,-80.2197),"Milwaukee Brewers":(43.0280,-87.9712),"Minnesota Twins":(44.9817,-93.2776),"New York Mets":(40.7571,-73.8458),"New York Yankees":(40.8296,-73.9262),"Philadelphia Phillies":(39.9061,-75.1665),"Pittsburgh Pirates":(40.4469,-80.0057),"San Diego Padres":(32.7076,-117.1570),"San Francisco Giants":(37.7786,-122.3893),"Seattle Mariners":(47.5914,-122.3325),"St. Louis Cardinals":(38.6226,-90.1928),"Tampa Bay Rays":(27.7683,-82.6534),"Texas Rangers":(32.7473,-97.0832),"Toronto Blue Jays":(43.6414,-79.3894),"Washington Nationals":(38.8730,-77.0074)}
_CACHE = {}
_LAST_DISCORD_SEND = 0.0
_HTTP_RECORDING = None
_HTTP_REPLAY = None


def num(x, d=0.0):
    try:
        y = float(x)
        return y if math.isfinite(y) else d
    except Exception:
        return d


def clamp(x, a=.001, b=.999):
    return max(a, min(b, num(x, .5)))


def pct(x):
    return "—" if x is None else f"{100*num(x):.1f}%"


def parse_dt(s):
    return datetime.fromisoformat(str(s).replace("Z", "+00:00"))


def norm_name(s):
    return "".join(c.lower() for c in str(s or "") if c.isalnum())


def _scrub_url(url):
    p = urllib.parse.urlsplit(url)
    q = urllib.parse.parse_qsl(p.query, keep_blank_values=True)
    safe = []
    for k, v in q:
        safe.append((k, "***" if k.lower() in {"apikey", "api_key", "key", "token"} else v))
    return urllib.parse.urlunsplit((p.scheme, p.netloc, p.path, urllib.parse.urlencode(sorted(safe), doseq=True), ""))


def _request_key(url, method="GET", payload=None):
    raw = json.dumps({"url": _scrub_url(url), "method": method, "payload": payload}, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(raw.encode()).hexdigest()


def start_http_recording(path, run_id, analyzed_at, target_date):
    global _HTTP_RECORDING
    _HTTP_RECORDING = {
        "path": str(path),
        "payload": {
            "schema": "v12-source-replay-v1", "run_id": run_id, "analyzed_at": analyzed_at,
            "target_date": target_date, "calls": [],
        },
    }


def stop_http_recording():
    global _HTTP_RECORDING
    rec = _HTTP_RECORDING
    _HTTP_RECORDING = None
    if not rec:
        return None
    path = rec["path"]
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with gzip.open(path, "wt", encoding="utf-8", compresslevel=9) as f:
        json.dump(rec["payload"], f, ensure_ascii=False, separators=(",", ":"))
    return path


def load_http_replay(path):
    global _HTTP_REPLAY
    with gzip.open(path, "rt", encoding="utf-8") as f:
        payload = json.load(f)
    index = {}
    for call in payload.get("calls") or []:
        index.setdefault(call.get("request_key"), []).append(call)
    _HTTP_REPLAY = {"payload": payload, "index": index, "positions": {}}
    return payload


def clear_http_replay():
    global _HTTP_REPLAY
    _HTTP_REPLAY = None


def replay_as_of():
    if not _HTTP_REPLAY:
        return None
    return _HTTP_REPLAY.get("payload", {}).get("analyzed_at")


def http_json(url, params=None, method="GET", payload=None, timeout=TIMEOUT, retries=2):
    if params:
        url += ("&" if "?" in url else "?") + urllib.parse.urlencode(params, safe=",")
    request_key = _request_key(url, method, payload)
    if _HTTP_REPLAY is not None:
        calls = _HTTP_REPLAY["index"].get(request_key) or []
        pos = _HTTP_REPLAY["positions"].get(request_key, 0)
        if pos >= len(calls):
            raise RuntimeError(f"Replay source manquant pour {_scrub_url(url)}")
        _HTTP_REPLAY["positions"][request_key] = pos+1
        call = calls[pos]
        if call.get("error"):
            raise RuntimeError(f"Replay source enregistrée en erreur: {call['error']}")
        return copy.deepcopy(call.get("response"))

    data = None
    headers = {"User-Agent": "MLB-Betting-Bot-V12.2", "Accept": "application/json"}
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode()
        headers["Content-Type"] = "application/json"
    last = None
    for attempt in range(retries+1):
        try:
            req = urllib.request.Request(url, data=data, headers=headers, method=method)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                body = r.read().decode("utf-8", "replace")
                response = json.loads(body) if body else None
            if _HTTP_RECORDING is not None:
                _HTTP_RECORDING["payload"]["calls"].append({
                    "request_key": request_key, "url": _scrub_url(url), "method": method,
                    "payload": payload, "response": response, "recorded_at": datetime.now(timezone.utc).isoformat(),
                })
            return response
        except urllib.error.HTTPError as e:
            last = e
            if e.code not in (429, 500, 502, 503, 504) or attempt >= retries:
                if _HTTP_RECORDING is not None:
                    _HTTP_RECORDING["payload"]["calls"].append({
                        "request_key": request_key, "url": _scrub_url(url), "method": method,
                        "payload": payload, "response": None, "error": f"HTTP {e.code}",
                        "recorded_at": datetime.now(timezone.utc).isoformat(),
                    })
                raise
            time.sleep(1.2*(attempt+1))
        except Exception as e:
            last = e
            if attempt >= retries:
                if _HTTP_RECORDING is not None:
                    _HTTP_RECORDING["payload"]["calls"].append({
                        "request_key": request_key, "url": _scrub_url(url), "method": method,
                        "payload": payload, "response": None, "error": f"{type(e).__name__}:{e}",
                        "recorded_at": datetime.now(timezone.utc).isoformat(),
                    })
                raise
            time.sleep(1+attempt)
    raise last


def mlb(path, params=None):
    return http_json("https://statsapi.mlb.com/api/"+path.lstrip("/"), params)


def mlb_schedule(day, team_id=None, hydrate="probablePitcher,linescore"):
    p = {"sportId": 1, "date": day, "hydrate": hydrate}
    if team_id:
        p["teamId"] = team_id
    d = mlb("v1/schedule", p) or {}
    return [g for block in d.get("dates", []) for g in block.get("games", [])]


def _stat_split(d):
    try:
        s = (d.get("stats") or [{}])[0].get("splits") or []
        return s[0].get("stat", {}) if s else {}
    except Exception:
        return {}


def season_stats(team_id, group):
    key = ("team", team_id, group, SEASON)
    if key in _CACHE:
        return _CACHE[key]
    try:
        out = _stat_split(mlb(f"v1/teams/{team_id}/stats", {"stats": "season", "group": group, "season": SEASON}))
    except Exception as e:
        logging.warning("Stats %s/%s indisponibles: %s", team_id, group, e)
        out = {}
    _CACHE[key] = out
    return out


def player_stats(pid, group="pitching"):
    if not pid:
        return {}
    key = ("player", pid, group, SEASON)
    if key in _CACHE:
        return _CACHE[key]
    try:
        out = _stat_split(mlb(f"v1/people/{pid}/stats", {"stats": "season", "group": group, "season": SEASON}))
    except Exception:
        out = {}
    _CACHE[key] = out
    return out


def league_baselines():
    key = ("league", SEASON)
    if key in _CACHE:
        return _CACHE[key]
    vals = {"rpg": 4.45, "era": 4.35, "ops": .710, "whip": 1.32}
    try:
        dh = mlb("v1/teams/stats", {"stats": "season", "group": "hitting", "season": SEASON, "sportIds": 1}) or {}
        dp = mlb("v1/teams/stats", {"stats": "season", "group": "pitching", "season": SEASON, "sportIds": 1}) or {}
        hs = (dh.get("stats") or [{}])[0].get("splits") or []
        ps = (dp.get("stats") or [{}])[0].get("splits") or []
        if hs:
            vals["rpg"] = mean(num(x.get("stat", {}).get("runsPerGame"), 4.45) for x in hs)
            vals["ops"] = mean(num(x.get("stat", {}).get("ops"), .710) for x in hs)
        if ps:
            vals["era"] = mean(num(x.get("stat", {}).get("era"), 4.35) for x in ps)
            vals["whip"] = mean(num(x.get("stat", {}).get("whip"), 1.32) for x in ps)
    except Exception as e:
        logging.warning("Baselines MLB fallback: %s", e)
    _CACHE[key] = vals
    return vals


def odds_api():
    if not ODDS_KEY and _HTTP_REPLAY is None:
        raise RuntimeError("ODDS_API_KEY absente")
    params = {"apiKey": ODDS_KEY or "replay", "regions": "eu", "markets": "h2h,spreads,totals", "oddsFormat": "decimal", "dateFormat": "iso", "bookmakers": ",".join(BOOKMAKERS)}
    return http_json("https://api.the-odds-api.com/v4/sports/baseball_mlb/odds", params) or []


def match_odds_events(games, events):
    index = {}
    for e in events:
        index[(norm_name(e.get("home_team")), norm_name(e.get("away_team")))] = e
    out = {}
    for g in games:
        teams = g.get("teams") or {}
        h = ((teams.get("home") or {}).get("team") or {}).get("name", "")
        a = ((teams.get("away") or {}).get("team") or {}).get("name", "")
        e = index.get((norm_name(h), norm_name(a)))
        if e:
            out[str(g.get("gamePk"))] = e
    return out


def _market(book, key):
    return next((m for m in book.get("markets") or [] if m.get("key") == key), None)


def _outcome_price(market, name, point=None):
    if not market:
        return None
    for o in market.get("outcomes") or []:
        if norm_name(o.get("name")) != norm_name(name):
            continue
        if point is not None and abs(num(o.get("point"), 999)-num(point)) > 1e-6:
            continue
        p = num(o.get("price"), 0)
        if p > 1:
            return p
    return None


def winamax_price(event, market, name, point=None):
    for b in event.get("bookmakers") or []:
        if b.get("key") != WINAMAX_KEY:
            continue
        return _outcome_price(_market(b, {"ML": "h2h", "RUNLINE": "spreads", "TOTAL": "totals"}[market]), name, point)
    return None


def phase_for_game(game, as_of=None):
    try:
        ref = parse_dt(as_of) if isinstance(as_of, str) else as_of
        ref = ref or (parse_dt(replay_as_of()) if replay_as_of() else datetime.now(timezone.utc))
        sec = (parse_dt(game.get("gameDate"))-ref).total_seconds()
    except Exception:
        return "EARLY"
    if sec <= 90*60:
        return "FINAL"
    if sec <= 5*3600:
        return "LATE"
    return "EARLY"


def _discord_retry_after(error):
    wait = 1.5
    try:
        raw = error.read().decode("utf-8", "replace")
        body = json.loads(raw) if raw else {}
        wait = max(wait, float(body.get("retry_after", wait)))
    except Exception:
        pass
    try:
        hdr = error.headers.get("Retry-After")
        if hdr is not None:
            wait = max(wait, float(hdr))
    except Exception:
        pass
    return min(max(wait, .5), 15.0)


def send_embed(title, fields, color=5763719, description=None):
    global _LAST_DISCORD_SEND
    if not DISCORD_URL:
        return False
    payload = {"embeds": [{"title": title, "color": color, "fields": [{"name": n, "value": v, "inline": False} for n, v in fields]}]}
    if description:
        payload["embeds"][0]["description"] = description
    data = json.dumps(payload, ensure_ascii=False).encode()
    for attempt in range(4):
        elapsed = time.monotonic()-_LAST_DISCORD_SEND
        if elapsed < DISCORD_MIN_INTERVAL:
            time.sleep(DISCORD_MIN_INTERVAL-elapsed)
        try:
            req = urllib.request.Request(DISCORD_URL, data=data, headers={"Content-Type": "application/json", "User-Agent": "MLB-Betting-Bot-V12.2"}, method="POST")
            with urllib.request.urlopen(req, timeout=15) as r:
                r.read()
            _LAST_DISCORD_SEND = time.monotonic()
            return True
        except urllib.error.HTTPError as e:
            _LAST_DISCORD_SEND = time.monotonic()
            if e.code == 429 and attempt < 3:
                wait = _discord_retry_after(e)
                logging.info("Discord rate limit: nouvelle tentative dans %.2fs", wait)
                time.sleep(wait)
                continue
            logging.warning("Discord impossible: HTTP %s", e.code)
            return False
        except Exception as e:
            _LAST_DISCORD_SEND = time.monotonic()
            logging.warning("Discord impossible: %s", e)
            return False
    return False


def discord_test():
    if not DISCORD_URL:
        logging.warning("DISCORD_WEBHOOK_URL absente")
        return False
    return True


def lineup_text(lineup):
    if not lineup:
        return "lineup non confirmée"
    n = int(num(lineup.get("count"), 0))
    usable = int(num(lineup.get("usable_ops_count"), 0))
    return f"{n}/9 joueurs ({usable} stats utilisables)" if n else "lineup détectée"


def market_label(rec):
    if rec.get("market") == "ML":
        return f"{rec.get('name')} ML"
    if rec.get("market") == "RUNLINE":
        return f"{rec.get('name')} {num(rec.get('point')):+g}"
    return f"{str(rec.get('name')).title()} {num(rec.get('point')):g}"
