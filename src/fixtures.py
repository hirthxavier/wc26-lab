"""Fetch World Cup fixtures and results from football-data.org (free tier)."""
from __future__ import annotations
import json
from datetime import datetime, timedelta, timezone
import requests
from config import FD_BASE, FOOTBALL_DATA_KEY, WC_COMPETITION, DATA

HEADERS = {"X-Auth-Token": FOOTBALL_DATA_KEY}


def get_matches(days_ahead: int = 7) -> list[dict]:
    """Upcoming WC matches in the next `days_ahead` days."""
    now = datetime.now(timezone.utc)
    params = {
        "dateFrom": now.date().isoformat(),
        "dateTo": (now + timedelta(days=days_ahead)).date().isoformat(),
    }
    r = requests.get(
        f"{FD_BASE}/competitions/{WC_COMPETITION}/matches",
        headers=HEADERS, params=params, timeout=30,
    )
    r.raise_for_status()
    matches = r.json().get("matches", [])
    return [_normalize(m) for m in matches]


def get_finished_matches() -> list[dict]:
    r = requests.get(
        f"{FD_BASE}/competitions/{WC_COMPETITION}/matches",
        headers=HEADERS, params={"status": "FINISHED"}, timeout=30,
    )
    r.raise_for_status()
    return [_normalize(m) for m in r.json().get("matches", [])]


def _normalize(m: dict) -> dict:
    return {
        "match_id": m["id"],
        "utc_kickoff": m["utcDate"],
        "stage": m.get("stage"),
        "home": m["homeTeam"]["name"],
        "away": m["awayTeam"]["name"],
        "status": m["status"],
        "score": m.get("score", {}).get("fullTime", {}),
    }


def matches_in_window(min_minutes: int, max_minutes: int) -> list[dict]:
    """Matches kicking off between min_minutes and max_minutes from now."""
    now = datetime.now(timezone.utc)
    lo = now + timedelta(minutes=min_minutes)
    hi = now + timedelta(minutes=max_minutes)
    out = []
    for m in get_matches(days_ahead=2):
        ko = datetime.fromisoformat(m["utc_kickoff"].replace("Z", "+00:00"))
        if lo < ko <= hi and m["status"] in ("TIMED", "SCHEDULED"):
            out.append(m)
    return out


if __name__ == "__main__":
    ms = get_matches()
    print(json.dumps(ms, indent=2))
    (DATA / "fixtures.json").write_text(json.dumps(ms, indent=2))
