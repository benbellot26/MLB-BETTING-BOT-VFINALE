#!/usr/bin/env python3
"""V10 market main-line selection.

The predictive model must choose a side on the market's primary line, not search
alternate lines for the easiest probability. One vote per fresh reference book
is used; within a book, the most balanced paired price is treated as its main
line.
"""
from collections import Counter
from datetime import datetime, timezone
from statistics import median


def num(x, d=0.0):
    try:
        y = float(x)
        return y if y == y else d
    except Exception:
        return d


def norm_name(s):
    return "".join(c.lower() for c in str(s) if c.isalnum())


def parse_dt(s):
    return datetime.fromisoformat(str(s).replace("Z", "+00:00"))


def _fresh(book, market, now, max_age_min=90):
    stamp = market.get("last_update") or book.get("last_update")
    if not stamp or now is None:
        return True
    try:
        age = max(0.0, (now - parse_dt(stamp)).total_seconds() / 60.0)
        return age <= max_age_min
    except Exception:
        return True


def _fair_two(price_a, price_b):
    if price_a <= 1 or price_b <= 1:
        return None
    a = 1.0 / price_a
    b = 1.0 / price_b
    return a / (a + b) if a + b else None


def _market_rows(event, market_key, ref_books, now=None):
    for book in event.get("bookmakers", []):
        if book.get("key") not in ref_books:
            continue
        for market in book.get("markets", []):
            if market.get("key") == market_key and _fresh(book, market, now):
                yield book, market


def _book_total_vote(market):
    by_point = {}
    for o in market.get("outcomes", []):
        name = str(o.get("name", "")).lower()
        if name not in ("over", "under") or o.get("point") is None:
            continue
        point = round(num(o.get("point")), 3)
        by_point.setdefault(point, {})[name] = num(o.get("price"))

    candidates = []
    for point, pair in by_point.items():
        if "over" not in pair or "under" not in pair:
            continue
        p_over = _fair_two(pair["over"], pair["under"])
        if p_over is None:
            continue
        candidates.append((abs(p_over - .5), point))
    return min(candidates)[1] if candidates else None


def main_total_line(event, ref_books, now=None):
    votes = []
    books = []
    for book, market in _market_rows(event, "totals", ref_books, now):
        point = _book_total_vote(market)
        if point is not None:
            votes.append(point)
            books.append(book.get("key"))
    if not votes:
        return None

    counts = Counter(votes)
    best_n = max(counts.values())
    tied = [p for p, n in counts.items() if n == best_n]
    center = median(votes)
    point = min(tied, key=lambda p: (abs(p - center), p))
    supporters = [b for b, p in zip(books, votes) if p == point]
    return {
        "point": point,
        "votes": counts[point],
        "books": supporters,
        "total_books": len(votes),
        "support_ratio": counts[point] / len(votes),
        "book_votes": dict(zip(books, votes)),
    }


def _book_spread_vote(market, home, away):
    hname = norm_name(home)
    aname = norm_name(away)
    homes = []
    aways = []
    for o in market.get("outcomes", []):
        if o.get("point") is None:
            continue
        row = (round(num(o.get("point")), 3), num(o.get("price")))
        n = norm_name(o.get("name"))
        if n == hname:
            homes.append(row)
        elif n == aname:
            aways.append(row)

    candidates = []
    for hp, hprice in homes:
        for ap, aprice in aways:
            if abs(hp + ap) > 1e-6:
                continue
            p_home = _fair_two(hprice, aprice)
            if p_home is None:
                continue
            candidates.append((abs(p_home - .5), abs(abs(hp) - 1.5), hp))
    return min(candidates)[2] if candidates else None


def main_spread_line(event, home, away, ref_books, now=None):
    votes = []
    books = []
    for book, market in _market_rows(event, "spreads", ref_books, now):
        home_point = _book_spread_vote(market, home, away)
        if home_point is not None:
            votes.append(home_point)
            books.append(book.get("key"))
    if not votes:
        return None

    counts = Counter(votes)
    best_n = max(counts.values())
    tied = [p for p, n in counts.items() if n == best_n]
    center = median(votes)
    home_point = min(tied, key=lambda p: (abs(abs(p) - 1.5), abs(p - center), p))
    supporters = [b for b, p in zip(books, votes) if p == home_point]
    return {
        "home_point": home_point,
        "away_point": -home_point,
        "votes": counts[home_point],
        "books": supporters,
        "total_books": len(votes),
        "support_ratio": counts[home_point] / len(votes),
        "book_votes": dict(zip(books, votes)),
    }


def _book(key, spreads=None, totals=None):
    markets = []
    if spreads is not None:
        markets.append({"key": "spreads", "outcomes": spreads})
    if totals is not None:
        markets.append({"key": "totals", "outcomes": totals})
    return {"key": key, "markets": markets}


def self_test():
    refs = {"pinnacle", "betfair_ex_eu", "betclic_fr", "unibet_fr"}
    event = {"bookmakers": [
        _book("pinnacle", totals=[
            {"name": "Over", "point": 8.5, "price": 1.91}, {"name": "Under", "point": 8.5, "price": 1.91},
            {"name": "Over", "point": 9.5, "price": 2.45}, {"name": "Under", "point": 9.5, "price": 1.55},
        ]),
        _book("betfair_ex_eu", totals=[
            {"name": "Over", "point": 8.5, "price": 1.94}, {"name": "Under", "point": 8.5, "price": 1.88},
        ]),
        _book("betclic_fr", totals=[
            {"name": "Over", "point": 8.5, "price": 1.90}, {"name": "Under", "point": 8.5, "price": 1.92},
        ]),
        _book("unibet_fr", totals=[
            {"name": "Over", "point": 9.0, "price": 1.91}, {"name": "Under", "point": 9.0, "price": 1.91},
        ]),
    ]}
    total = main_total_line(event, refs)
    assert total and total["point"] == 8.5 and total["votes"] == 3, total

    event2 = {"bookmakers": [
        _book("pinnacle", spreads=[
            {"name": "Home", "point": -1.5, "price": 1.91}, {"name": "Away", "point": 1.5, "price": 1.91},
            {"name": "Home", "point": -2.5, "price": 2.55}, {"name": "Away", "point": 2.5, "price": 1.50},
        ]),
        _book("betfair_ex_eu", spreads=[
            {"name": "Home", "point": -1.5, "price": 1.95}, {"name": "Away", "point": 1.5, "price": 1.87},
        ]),
        _book("betclic_fr", spreads=[
            {"name": "Home", "point": -1.5, "price": 1.90}, {"name": "Away", "point": 1.5, "price": 1.92},
        ]),
        _book("unibet_fr", spreads=[
            {"name": "Home", "point": -2.5, "price": 1.91}, {"name": "Away", "point": 2.5, "price": 1.91},
        ]),
    ]}
    spread = main_spread_line(event2, "Home", "Away", refs)
    assert spread and spread["home_point"] == -1.5 and spread["votes"] == 3, spread

    print("SELF-TEST V10 MAIN LINES OK", {"total": total, "spread": spread})


if __name__ == "__main__":
    self_test()
