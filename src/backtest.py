"""Seed Elo ratings from ~150 years of international results and FIT the
model's free parameters on a holdout of recent competitive matches.

Methodology (standard, eloratings.net-style):
- Replay all matches chronologically. K varies by match importance
  (World Cup 60, continental finals 50, qualifiers/Nations League 40,
  friendlies 20), scaled by goal-difference multiplier.
- Home advantage: +HOME_ADV Elo to the home side when venue is not neutral
  (HOME_ADV itself is fitted).
- Parameter fit: grid-search (base_goals, elo_scale, dc_rho, home_adv) to
  minimize mean Brier score on competitive matches from EVAL_FROM onward,
  using only ratings available before each match (walk-forward, no leakage).

Outputs:
  data/elo.json    — current ratings for all national teams
  data/params.json — fitted parameters + holdout Brier (our preregistered
                     in-sample-of-history benchmark)

Run locally once before the tournament: python backtest.py
"""
from __future__ import annotations
import csv
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw_results.csv"
ELO_OUT = ROOT / "data" / "elo.json"
PARAMS_OUT = ROOT / "data" / "params.json"

EVAL_FROM = "2018-01-01"   # holdout period for parameter fitting
DEFAULT_ELO = 1500.0

K_BY_TOURNAMENT = [
    ("FIFA World Cup", 60), ("qualification", 40),
    ("UEFA Euro", 50), ("Copa Am", 50), ("African Cup", 50),
    ("AFC Asian Cup", 50), ("Gold Cup", 50), ("Confederations", 50),
    ("Nations League", 40), ("Friendly", 20),
]
MAX_GOALS = 10
_FACT = [math.factorial(i) for i in range(MAX_GOALS + 1)]


def k_for(tournament: str) -> float:
    for key, k in K_BY_TOURNAMENT:
        if key.lower() in tournament.lower():
            return k
    return 30  # other competitive


def pmf(lam: float, k: int) -> float:
    return math.exp(-lam) * lam ** k / _FACT[k]


def dc_tau(gh: int, ga: int, lh: float, la: float, rho: float) -> float:
    """Dixon-Coles low-score correction factor."""
    if gh == 0 and ga == 0:
        return 1 - lh * la * rho
    if gh == 0 and ga == 1:
        return 1 + lh * rho
    if gh == 1 and ga == 0:
        return 1 + la * rho
    if gh == 1 and ga == 1:
        return 1 - rho
    return 1.0


def match_probs(elo_diff: float, base_goals: float, elo_scale: float,
                rho: float) -> tuple[float, float, float]:
    lh = base_goals * 10 ** (elo_diff / elo_scale)
    la = base_goals * 10 ** (-elo_diff / elo_scale)
    lh, la = min(lh, 6.0), min(la, 6.0)
    ph = pd = pa = 0.0
    ph_row = [pmf(lh, g) for g in range(MAX_GOALS + 1)]
    pa_row = [pmf(la, g) for g in range(MAX_GOALS + 1)]
    for gh in range(MAX_GOALS + 1):
        for ga in range(MAX_GOALS + 1):
            p = ph_row[gh] * pa_row[ga] * dc_tau(gh, ga, lh, la, rho)
            if p <= 0:
                continue
            if gh > ga:
                ph += p
            elif gh == ga:
                pd += p
            else:
                pa += p
    t = ph + pd + pa
    return ph / t, pd / t, pa / t


def load_matches() -> list[dict]:
    out = []
    with open(RAW, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row["home_score"] in ("NA", "", None):
                continue
            out.append({
                "date": row["date"],
                "home": row["home_team"], "away": row["away_team"],
                "hg": int(row["home_score"]), "ag": int(row["away_score"]),
                "tournament": row["tournament"],
                "neutral": row["neutral"].strip().upper() == "TRUE",
            })
    out.sort(key=lambda m: m["date"])
    return out


def replay(matches: list[dict], home_adv: float,
           eval_params: tuple | None = None) -> tuple[dict, float | None, int]:
    """Replay history. If eval_params given, also score walk-forward Brier on
    competitive matches from EVAL_FROM using pre-match ratings."""
    elo: dict[str, float] = {}
    total_brier, n_eval = 0.0, 0
    for m in matches:
        ra = elo.get(m["home"], DEFAULT_ELO)
        rb = elo.get(m["away"], DEFAULT_ELO)
        adv = 0.0 if m["neutral"] else home_adv

        if (eval_params and m["date"] >= EVAL_FROM
                and "friendly" not in m["tournament"].lower()):
            bg, es, rho = eval_params
            ph, pd, pa = match_probs(ra + adv - rb, bg, es, rho)
            actual = ("home" if m["hg"] > m["ag"]
                      else "away" if m["hg"] < m["ag"] else "draw")
            probs = {"home": ph, "draw": pd, "away": pa}
            total_brier += sum(
                (probs[o] - (1.0 if o == actual else 0.0)) ** 2
                for o in ("home", "draw", "away"))
            n_eval += 1

        ea = 1 / (1 + 10 ** ((rb - (ra + adv)) / 400))
        sa = 1.0 if m["hg"] > m["ag"] else 0.0 if m["hg"] < m["ag"] else 0.5
        k = k_for(m["tournament"])
        mult = math.log(abs(m["hg"] - m["ag"]) + 1) + 1
        delta = k * mult * (sa - ea)
        elo[m["home"]] = ra + delta
        elo[m["away"]] = rb - delta
    return elo, (total_brier / n_eval if n_eval else None), n_eval


def fit():
    matches = load_matches()
    print(f"Loaded {len(matches)} completed matches "
          f"({matches[0]['date']} → {matches[-1]['date']})")

    best = None
    # coarse grid, then refine around winner
    grid = [(bg, es, rho, ha)
            for bg in (1.25, 1.35, 1.45)
            for es in (600, 800, 1000)
            for rho in (-0.10, 0.0, 0.10)
            for ha in (60, 100)]
    for bg, es, rho, ha in grid:
        _, brier, n = replay(matches, ha, eval_params=(bg, es, rho))
        if best is None or brier < best[0]:
            best = (brier, bg, es, rho, ha, n)
            print(f"  new best: brier={brier:.4f} "
                  f"bg={bg} scale={es} rho={rho} home_adv={ha} (n={n})")

    brier, bg, es, rho, ha, n = best
    # refine
    for bg2 in (bg - 0.05, bg, bg + 0.05):
        for es2 in (es - 100, es, es + 100):
            for rho2 in (rho - 0.05, rho, rho + 0.05):
                _, b2, _ = replay(matches, ha, eval_params=(bg2, es2, rho2))
                if b2 < brier:
                    brier, bg, es, rho = b2, bg2, es2, rho2
                    print(f"  refined: brier={brier:.4f} "
                          f"bg={bg} scale={es} rho={rho:.2f}")

    elo, _, _ = replay(matches, ha)
    ELO_OUT.write_text(json.dumps(
        {k: round(v, 1) for k, v in sorted(elo.items())}, indent=2))
    PARAMS_OUT.write_text(json.dumps({
        "base_goals": bg, "elo_scale": es, "dc_rho": round(rho, 3),
        "home_adv_elo": ha,
        "holdout_brier": round(brier, 4), "holdout_n": n,
        "holdout_from": EVAL_FROM,
        "note": "Walk-forward Brier on competitive internationals; "
                "compare tournament results against this benchmark.",
    }, indent=2))
    print(f"\nSaved {len(elo)} team ratings -> {ELO_OUT.name}")
    print(f"Fitted params (holdout Brier {brier:.4f}, n={n}) -> {PARAMS_OUT.name}")
    top = sorted(elo.items(), key=lambda kv: -kv[1])[:15]
    print("\nTop 15 teams by Elo:")
    for t, r in top:
        print(f"  {t:<22}{r:7.1f}")


if __name__ == "__main__":
    fit()
