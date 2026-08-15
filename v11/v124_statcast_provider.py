from __future__ import annotations

from html.parser import HTMLParser


class _TableParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.tables = []
        self._table = None
        self._row = None
        self._cell = None
        self._cell_tag = None

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        if tag == "table":
            self._table = []
        elif tag == "tr" and self._table is not None:
            self._row = []
        elif tag in {"th", "td"} and self._row is not None:
            self._cell = []
            self._cell_tag = tag

    def handle_data(self, data):
        if self._cell is not None:
            text = str(data or "").strip()
            if text:
                self._cell.append(text)

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag in {"th", "td"} and self._cell is not None and self._row is not None:
            self._row.append((self._cell_tag, " ".join(self._cell).strip()))
            self._cell = None
            self._cell_tag = None
        elif tag == "tr" and self._row is not None and self._table is not None:
            if self._row:
                self._table.append(self._row)
            self._row = None
        elif tag == "table" and self._table is not None:
            if self._table:
                self.tables.append(self._table)
            self._table = None


def _norm_header(value):
    return "".join(c.lower() for c in str(value or "") if c.isalnum())


def _canonical_player_names(name):
    text = str(name or "").replace("Image", "").strip()
    out = [text]
    if "," in text:
        last, first = [x.strip() for x in text.split(",", 1)]
        if first and last:
            out.append(f"{first} {last}")
    return out


def _parse_statcast_table(html, v124):
    parser = _TableParser()
    parser.feed(html or "")
    for table in parser.tables:
        if not table:
            continue
        header = [text for tag, text in table[0] if tag == "th"]
        if not header:
            header = [text for _, text in table[0]]
        normalized = [_norm_header(x) for x in header]
        if "player" not in normalized or "xwoba" not in normalized:
            continue
        pidx = normalized.index("player")
        rows = {}
        for raw in table[1:]:
            vals = [text for _, text in raw]
            if len(vals) < len(header) or pidx >= len(vals):
                continue
            item = {header[i]: vals[i] for i in range(min(len(header), len(vals)))}
            for name in _canonical_player_names(vals[pidx]):
                rows[("name", v124._norm(name))] = item
        if rows:
            return rows
    return {}


def install():
    from . import predictive_v124 as v124

    original = v124._savant_rows

    def safe_rows(player_type, cutoff):
        key = ("html-aggregate", str(player_type), str(cutoff), v124.core.SEASON)
        if key in v124._SAVANT_CACHE:
            return v124._SAVANT_CACHE[key]
        params = {
            "player_type": player_type,
            "game_date_gt": f"{v124.core.SEASON}-03-01",
            "game_date_lt": cutoff,
            "group_by": "name",
            "hfGT": "R|",
            "hfSea": f"{v124.core.SEASON}|",
            "min_pas": 0,
            "min_pitches": 0,
            "min_results": 0,
            "chk_stats_woba": "on",
            "chk_stats_xwoba": "on",
            "chk_stats_launch_speed": "on",
            "chk_stats_hardhit_percent": "on",
            "chk_stats_barrel_batted_rate": "on",
            "sort_col": "xwoba",
            "sort_order": "desc",
        }
        try:
            html = v124._http_text("https://baseballsavant.mlb.com/statcast_search", params, timeout=30)
            index = _parse_statcast_table(html, v124)
        except Exception:
            index = {}
        # Never fall back to the unbounded pitch-level CSV query in production.
        v124._SAVANT_CACHE[key] = index
        return index

    v124._savant_rows_unbounded = original
    v124._savant_rows = safe_rows
    v124.STATCAST_PROVIDER = "Baseball Savant aggregate HTML point-in-time"
    return True
