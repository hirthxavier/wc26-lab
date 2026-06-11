"""Player-level data from API-Football (api-sports.io) — the L'Équipe-style
post-match ratings, as structured data.

Provides:
  - squad_form(team): minutes-weighted average match rating per player over
    the team's recent fixtures (the "forme du match n-1", smoothed over 3-5)
  - team_form_index(team): single number = mean rating of the likely XI
  - lineup_delta(team, starting_names): how the announced XI compares to the
    team's strongest recent XI (rotation / surprise starters, quantified)
  - injuries(team): structured injury list
  - fetch_top_scorers(): live Golden Boot standings -> data/top_scorers.json

Request budget: the free plan allows 100 req/day. Everything is cached to
data/players_cache.json with a per-day key; a hard counter stops at
MAX_REQUESTS_PER_RUN so a bug can never burn the quota.

Requires GitHub secret: APIFOOTBALL_KEY
"""
from __future__ import annotations
import json
import os
from datetime import date
from pathlib import Path
import requests

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
CACHE_FILE = DATA / "players_cache.json"
TOP_SCORERS_FILE = DATA / "top_scorers.json"

API_KEY = os.environ.get("APIFOOTBALL_KEY", "")
BASE = "https://v3.football.api-sports.io"
WC_LEAGUE = 1
SEASON = 2026

MAX_REQUESTS_PER_RUN = 40
_requests_made = 0

# football-data.org / dataset names -> API-Football names (extend as needed)
NAME_MAP = {"United States": "USA", "South Korea": "South Korea",
            "Ivory Coast": "Ivory Coast"}


class BudgetExceeded(RuntimeError):
    pass


def _get(endpoint: str, params: dict) -> dict | None:
    global _requests_made
    if not API_KEY:
        return None
    if _requests_made >= MAX_REQUESTS_PER_RUN:
        raise BudgetExceeded(f"player API budget ({MAX_REQUESTS_PER_RUN}) hit")
    _requests_made += 1
    try:
        r = requests.get(f"{BASE}/{endpoint}", params=params,
                         headers={"x-apisports-key": API_KEY}, timeout=30)
        r.raise_for_status()
        return r.json()
    except requests.RequestException as e:
        print(f"players API error on {endpoint}: {e}")
        return None


def _cache() -> dict:
    if CACHE_FILE.exists():
        return json.loads(CACHE_FILE.read_text())
    return {}


def _save_cache(c: dict):
    CACHE_FILE.write_text(json.dumps(c, indent=2))


def _cached(key: str, fetch, ttl_today: bool = True):
    """Day-scoped cache: one fetch per key per day max."""
    c = _cache()
    full_key = f"{date.today().isoformat()}:{key}" if ttl_today else key
    if full_key in c:
        return c[full_key]
    val = fetch()
    if val is not None:
        c[full_key] = val
        _save_cache(c)
    return val


def team_id(team_name: str) -> int | None:
    name = NAME_MAP.get(team_name, team_name)

    def fetch():
        res = _get("teams", {"league": WC_LEAGUE, "season": SEASON,
                             "search": name})
        if res and res.get("response"):
            return res["response"][0]["team"]["id"]
        return None
    return _cached(f"teamid:{name}", fetch, ttl_today=False)


def squad_form(team_name: str, last_n: int = 4) -> dict:
    """Per-player average rating + minutes over the last N fixtures.
    Returns {"players": {name: {"rating": x, "minutes": m, "games": g}},
             "team_avg": y} — cached per day."""
    def fetch():
        tid = team_id(team_name)
        if not tid:
            return {"players": {}, "team_avg": None}
        fx = _get("fixtures", {"team": tid, "last": last_n})
        if not fx or not fx.get("response"):
            return {"players": {}, "team_avg": None}
        agg: dict[str, dict] = {}
        for f in fx["response"]:
            stats = _get("fixtures/players", {"fixture": f["fixture"]["id"]})
            if not stats or not stats.get("response"):
                continue
            for side in stats["response"]:
                if side["team"]["id"] != tid:
                    continue
                for p in side["players"]:
                    st = p["statistics"][0]
                    rating = st["games"].get("rating")
                    minutes = st["games"].get("minutes") or 0
                    if rating is None:
                        continue
                    a = agg.setdefault(p["player"]["name"],
                                       {"rsum": 0.0, "msum": 0, "games": 0})
                    a["rsum"] += float(rating) * minutes
                    a["msum"] += minutes
                    a["games"] += 1
        players = {n: {"rating": round(a["rsum"] / a["msum"], 2),
                       "minutes": a["msum"], "games": a["games"]}
                   for n, a in agg.items() if a["msum"] > 0}
        regulars = sorted(players.values(), key=lambda v: -v["minutes"])[:11]
        team_avg = (round(sum(p["rating"] for p in regulars) / len(regulars), 3)
                    if regulars else None)
        return {"players": players, "team_avg": team_avg}
    return _cached(f"form:{team_name}", fetch) or {"players": {}, "team_avg": None}


def team_form_index(team_name: str) -> float | None:
    return squad_form(team_name).get("team_avg")


def lineup_delta(team_name: str, starting_names: list[str]) -> dict:
    """Announced XI vs the team's strongest recent XI. Negative delta =
    weaker-than-usual lineup (rotation, surprise absences)."""
    form = squad_form(team_name)
    players = form.get("players", {})
    if not players or not starting_names:
        return {"delta": None, "missing_regulars": []}

    def find(name):  # tolerant matching (accents/short names differ)
        for k, v in players.items():
            if name.lower() in k.lower() or k.lower() in name.lower():
                return v
        return None
    xi = [find(n) for n in starting_names]
    xi_ratings = [p["rating"] for p in xi if p]
    best11 = sorted((p["rating"] for p in players.values()), reverse=True)[:11]
    if not xi_ratings or not best11:
        return {"delta": None, "missing_regulars": []}
    delta = round(sum(xi_ratings) / len(xi_ratings)
                  - sum(best11) / len(best11), 3)
    regulars = {k for k, v in sorted(players.items(),
                key=lambda kv: -kv[1]["minutes"])[:11]}
    started = {k for k in players if find(k) and any(
        k.lower() in s.lower() or s.lower() in k.lower()
        for s in starting_names)}
    missing = sorted(regulars - started)[:4]
    return {"delta": delta, "missing_regulars": missing}


def injuries(team_name: str) -> list[dict]:
    def fetch():
        tid = team_id(team_name)
        if not tid:
            return []
        res = _get("injuries", {"league": WC_LEAGUE, "season": SEASON,
                                "team": tid})
        if not res:
            return []
        return [{"player": i["player"]["name"],
                 "reason": i["player"].get("reason", "?")}
                for i in res.get("response", [])][:8]
    return _cached(f"injuries:{team_name}", fetch) or []


def fetch_top_scorers() -> list[dict]:
    """Live Golden Boot standings, saved for the dashboard."""
    res = _get("players/topscorers", {"league": WC_LEAGUE, "season": SEASON})
    if not res or not res.get("response"):
        return []
    out = [{"player": p["player"]["name"],
            "team": p["statistics"][0]["team"]["name"],
            "goals": p["statistics"][0]["goals"]["total"] or 0,
            "assists": p["statistics"][0]["goals"]["assists"] or 0}
           for p in res["response"][:12]]
    TOP_SCORERS_FILE.write_text(json.dumps(out, indent=2))
    return out


def player_form_summary(home: str, away: str,
                        lineups_text: str | None) -> tuple[str, float | None]:
    """Builds the text block for the LLM analyst + a quantitative form
    differential (home minus away, in rating points) for the 6th contestant.
    Never raises: returns ('', None) on any failure."""
    try:
        fh, fa = team_form_index(home), team_form_index(away)
        ih, ia = injuries(home), injuries(away)
        lines = []
        if fh is not None and fa is not None:
            lines.append(f"Form index (avg match rating, recent): "
                         f"{home} {fh} vs {away} {fa}")
        for team, inj in ((home, ih), (away, ia)):
            if inj:
                lines.append(f"Injuries {team}: " + ", ".join(
                    f"{i['player']} ({i['reason']})" for i in inj))
        diff = (fh - fa) if (fh is not None and fa is not None) else None
        return "\n".join(lines), diff
    except BudgetExceeded as e:
        print(e)
        return "", None
    except Exception as e:  # noqa: BLE001
        print(f"player_form_summary failed: {e}")
        return "", None


if __name__ == "__main__":
    print(json.dumps(squad_form("France"), indent=2)[:800])
    print(player_form_summary("France", "Senegal", None))
