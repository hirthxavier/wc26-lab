"""Fetch odds from The Odds API, compute consensus, de-margined implied
probabilities, and track line movement over time (line movement is itself a
feature: it shows where informed money is going)."""
from __future__ import annotations
import json
from datetime import datetime, timezone
import requests
from config import ODDS_BASE, ODDS_API_KEY, ODDS_SPORT_KEY, ODDS_REGIONS, ODDS_MARKETS, DATA

SNAPSHOT_FILE = DATA / "odds_snapshots.json"


def fetch_odds(markets: str | None = None) -> list[dict]:
    """markets: comma list. Each extra market costs API credits — the rich
    call (h2h,totals,btts) is made only at freeze time, not every snapshot."""
    r = requests.get(
        f"{ODDS_BASE}/sports/{ODDS_SPORT_KEY}/odds",
        params={
            "apiKey": ODDS_API_KEY,
            "regions": ODDS_REGIONS,
            "markets": markets or ODDS_MARKETS,
            "oddsFormat": "decimal",
        },
        timeout=30,
    )
    r.raise_for_status()
    return r.json()


def extract_offered(event: dict, home: str, away: str) -> dict[str, float]:
    """Average offered odds per market, keyed for bets.ev_analysis:
    1x2.*, over_under.over_2.5, btts_yes."""
    sums: dict[str, float] = {}
    counts: dict[str, int] = {}

    def add(key, price):
        if price and price > 1.0:
            sums[key] = sums.get(key, 0.0) + price
            counts[key] = counts.get(key, 0) + 1

    for book in event.get("bookmakers", []):
        for mk in book.get("markets", []):
            if mk["key"] == "h2h":
                for out in mk["outcomes"]:
                    if out["name"] == home:
                        add("1x2.home", out["price"])
                    elif out["name"] == away:
                        add("1x2.away", out["price"])
                    elif out["name"].lower() == "draw":
                        add("1x2.draw", out["price"])
            elif mk["key"] == "totals":
                for out in mk["outcomes"]:
                    if out.get("point") == 2.5 and out["name"] == "Over":
                        add("over_under.over_2.5", out["price"])
            elif mk["key"] == "btts":
                for out in mk["outcomes"]:
                    if out["name"].lower() == "yes":
                        add("btts_yes", out["price"])
    return {k: round(sums[k] / counts[k], 3) for k in sums}


def consensus_probs(event: dict) -> dict | None:
    """Average decimal odds across books, then remove the margin
    (basic normalization) -> implied P(home), P(draw), P(away)."""
    sums = {}
    counts = {}
    for book in event.get("bookmakers", []):
        for market in book.get("markets", []):
            if market["key"] != "h2h":
                continue
            for outcome in market["outcomes"]:
                sums[outcome["name"]] = sums.get(outcome["name"], 0.0) + outcome["price"]
                counts[outcome["name"]] = counts.get(outcome["name"], 0) + 1
    if not sums:
        return None
    avg_odds = {k: sums[k] / counts[k] for k in sums}
    raw = {k: 1.0 / v for k, v in avg_odds.items()}
    total = sum(raw.values())  # >1 because of the margin
    probs = {k: v / total for k, v in raw.items()}
    return {
        "avg_odds": avg_odds,
        "implied_probs": probs,
        "overround": round(total - 1, 4),
        "n_books": max(counts.values()),
    }


def snapshot():
    """Append a timestamped snapshot of all current odds. Run periodically;
    the time series gives us line movement and the final pre-kickoff snapshot
    approximates the closing line."""
    events = fetch_odds()
    now = datetime.now(timezone.utc).isoformat()
    record = []
    for e in events:
        c = consensus_probs(e)
        if c:
            record.append({
                "ts": now,
                "home": e["home_team"],
                "away": e["away_team"],
                "commence": e["commence_time"],
                **c,
            })
    existing = json.loads(SNAPSHOT_FILE.read_text()) if SNAPSHOT_FILE.exists() else []
    existing.extend(record)
    SNAPSHOT_FILE.write_text(json.dumps(existing, indent=2))
    return record


def line_movement(home: str, away: str) -> list[dict]:
    if not SNAPSHOT_FILE.exists():
        return []
    snaps = json.loads(SNAPSHOT_FILE.read_text())
    return [s for s in snaps if s["home"] == home and s["away"] == away]


if __name__ == "__main__":
    print(json.dumps(snapshot(), indent=2))
