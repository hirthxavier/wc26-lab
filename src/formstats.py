"""Forme récente et confrontations directes, calculées depuis le dataset
historique (49k matchs) déjà présent dans le repo. Zéro requête API.

- last5(team): 5 derniers résultats (V/N/D) avec scores et adversaires
- h2h(a, b): bilan complet des confrontations directes + dernières rencontres
- form_summary(home, away): bloc texte pour l'analyste IA + dict pour le
  dashboard, gelé dans chaque prédiction.
"""
from __future__ import annotations
import csv
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw_results.csv"

_matches_cache: list[dict] | None = None


def _load() -> list[dict]:
    global _matches_cache
    if _matches_cache is not None:
        return _matches_cache
    out = []
    with open(RAW, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row["home_score"] in ("NA", "", None):
                continue
            out.append({"date": row["date"], "home": row["home_team"],
                        "away": row["away_team"],
                        "hg": int(row["home_score"]),
                        "ag": int(row["away_score"]),
                        "tournament": row["tournament"]})
    out.sort(key=lambda m: m["date"])
    _matches_cache = out
    return out


def last5(team: str) -> list[dict]:
    res = []
    for m in reversed(_load()):
        if m["home"] == team or m["away"] == team:
            mine = m["hg"] if m["home"] == team else m["ag"]
            theirs = m["ag"] if m["home"] == team else m["hg"]
            opp = m["away"] if m["home"] == team else m["home"]
            res.append({"date": m["date"], "opp": opp,
                        "score": f"{mine}-{theirs}",
                        "r": "V" if mine > theirs else "D" if mine < theirs else "N"})
            if len(res) == 5:
                break
    return res


def h2h(a: str, b: str) -> dict:
    wins_a = wins_b = draws = 0
    goals_a = goals_b = 0
    meetings = []
    for m in _load():
        pair = {m["home"], m["away"]}
        if pair != {a, b}:
            continue
        ga = m["hg"] if m["home"] == a else m["ag"]
        gb = m["ag"] if m["home"] == a else m["hg"]
        goals_a += ga; goals_b += gb
        if ga > gb:
            wins_a += 1
        elif ga < gb:
            wins_b += 1
        else:
            draws += 1
        meetings.append({"date": m["date"][:4], "score": f"{ga}-{gb}",
                         "tournament": m["tournament"]})
    return {"played": wins_a + wins_b + draws,
            "wins_a": wins_a, "draws": draws, "wins_b": wins_b,
            "goals_a": goals_a, "goals_b": goals_b,
            "last_meetings": meetings[-5:][::-1]}


def form_summary(home: str, away: str) -> tuple[str, dict]:
    """(bloc texte pour le prompt LLM, dict gelé pour le dashboard)."""
    fh, fa = last5(home), last5(away)
    head = h2h(home, away)
    lines = [f"Forme {home} (5 derniers): " + " ".join(
                 f"{r['r']}({r['score']} vs {r['opp']})" for r in fh),
             f"Forme {away} (5 derniers): " + " ".join(
                 f"{r['r']}({r['score']} vs {r['opp']})" for r in fa)]
    if head["played"]:
        lines.append(
            f"Confrontations directes ({head['played']} matchs): "
            f"{home} {head['wins_a']}V, {head['draws']}N, "
            f"{away} {head['wins_b']}V — buts {head['goals_a']}-{head['goals_b']}. "
            f"Dernières: " + ", ".join(
                f"{m['date']} {m['score']}" for m in head["last_meetings"]))
    else:
        lines.append(f"Première confrontation officielle entre {home} et {away}.")
    data = {"form_home": [r["r"] for r in fh], "form_away": [r["r"] for r in fa],
            "form_home_detail": fh, "form_away_detail": fa, "h2h": head}
    return "\n".join(lines), data
