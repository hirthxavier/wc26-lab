"""Fetch official lineups once published (~60-75 min before kickoff at WCs).
football-data.org exposes them on the match detail endpoint when available."""
from __future__ import annotations
import requests
from config import FD_BASE, FOOTBALL_DATA_KEY

HEADERS = {"X-Auth-Token": FOOTBALL_DATA_KEY}


def get_lineups(match_id: int) -> str | None:
    """Returns a compact text block of both lineups, or None if not yet out."""
    try:
        r = requests.get(f"{FD_BASE}/matches/{match_id}", headers=HEADERS, timeout=30)
        r.raise_for_status()
    except requests.RequestException:
        return None
    m = r.json().get("match", r.json())
    parts = []
    for side in ("homeTeam", "awayTeam"):
        team = m.get(side, {})
        lineup = team.get("lineup") or []
        bench = team.get("bench") or []
        if not lineup:
            return None  # not published yet
        names = ", ".join(p.get("name", "?") for p in lineup)
        parts.append(f"{team.get('name', side)} XI: {names}")
        if bench:
            parts.append(f"  Bench: {', '.join(p.get('name','?') for p in bench[:12])}")
        coach = team.get("coach", {}).get("name")
        if coach:
            parts.append(f"  Coach: {coach}")
    return "\n".join(parts)
