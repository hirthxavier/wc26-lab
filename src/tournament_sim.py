"""Monte Carlo simulation of the full WC2026 (pre-tournament predictions).

- Reads the 2026 fixtures already present in data/raw_results.csv
- Infers the 12 groups automatically (connected components of the
  group-stage 'played each other' graph)
- Simulates every group match score-by-score from the fitted
  Elo -> Dixon-Coles grid; applies points/GD/GF tiebreakers
- Qualifies 12 winners + 12 runners-up + 8 best thirds
- Knockout rounds R32..Final: P(win) = P(win in 90') + 0.5 * P(draw)
  (ET/pens approximated as a coin flip — documented simplification)
- Bracket approximation: R32 seeded 1v32, 2v31... by group-stage record
  (the real FIFA bracket is position-fixed; this shifts tails slightly)

Outputs data/tournament_sim.json: P(champion), P(final), P(semi) per team.
"""
from __future__ import annotations
import csv
import json
import math
import random
from collections import defaultdict
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent))
from model import load_elo, load_params, canon, HOSTS, DEFAULT_ELO, _dc_tau, _poisson_pmf

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw_results.csv"
OUT = ROOT / "data" / "tournament_sim.json"

GROUP_STAGE_END = "2026-06-28"
MAX_G = 8


def load_wc_fixtures() -> list[dict]:
    out = []
    with open(RAW, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if (row["tournament"] == "FIFA World Cup"
                    and row["date"] >= "2026-06-01"
                    and row["home_score"] in ("NA", "")):
                out.append({"date": row["date"], "home": row["home_team"],
                            "away": row["away_team"]})
    return out


def infer_groups(fixtures: list[dict]) -> list[list[str]]:
    gs = [f for f in fixtures if f["date"] <= GROUP_STAGE_END]
    adj = defaultdict(set)
    for f in gs:
        adj[f["home"]].add(f["away"])
        adj[f["away"]].add(f["home"])
    seen, groups = set(), []
    for team in adj:
        if team in seen:
            continue
        comp, stack = set(), [team]
        while stack:
            t = stack.pop()
            if t in comp:
                continue
            comp.add(t)
            stack.extend(adj[t] - comp)
        seen |= comp
        groups.append(sorted(comp))
    return [g for g in groups if len(g) == 4]


class Sim:
    def __init__(self):
        self.elo = load_elo()
        self.params = load_params()
        self._grid_cache: dict[tuple, tuple] = {}

    def rating(self, team: str) -> float:
        return self.elo.get(canon(team), DEFAULT_ELO)

    def score_grid(self, home: str, away: str) -> tuple:
        """Cumulative distribution over (gh, ga) for sampling, cached."""
        key = (home, away)
        if key in self._grid_cache:
            return self._grid_cache[key]
        p = self.params
        adv = p["home_adv_elo"] if canon(home) in HOSTS else 0.0
        diff = (self.rating(home) + adv) - self.rating(away)
        lh = min(p["base_goals"] * 10 ** (diff / p["elo_scale"]), 6.0)
        la = min(p["base_goals"] * 10 ** (-diff / p["elo_scale"]), 6.0)
        cells, cum, total = [], [], 0.0
        ph_row = [_poisson_pmf(lh, g) for g in range(MAX_G + 1)]
        pa_row = [_poisson_pmf(la, g) for g in range(MAX_G + 1)]
        for gh in range(MAX_G + 1):
            for ga in range(MAX_G + 1):
                pr = max(ph_row[gh] * pa_row[ga]
                         * _dc_tau(gh, ga, lh, la, p["dc_rho"]), 0.0)
                total += pr
                cells.append((gh, ga))
                cum.append(total)
        out = (cells, cum, total)
        self._grid_cache[key] = out
        return out

    def sample_score(self, home: str, away: str) -> tuple[int, int]:
        cells, cum, total = self.score_grid(home, away)
        r = random.random() * total
        lo, hi = 0, len(cum) - 1
        while lo < hi:
            mid = (lo + hi) // 2
            if cum[mid] < r:
                lo = mid + 1
            else:
                hi = mid
        return cells[lo]

    def win_prob_knockout(self, a: str, b: str) -> float:
        """P(a advances) = P(a wins 90') + 0.5 * P(draw)."""
        cells, cum, total = self.score_grid(a, b)
        pa = pd = 0.0
        prev = 0.0
        for (gh, ga), c in zip(cells, cum):
            pr = c - prev
            prev = c
            if gh > ga:
                pa += pr
            elif gh == ga:
                pd += pr
        return (pa + 0.5 * pd) / total


def simulate(n_sims: int = 10000, seed: int = 42) -> dict:
    random.seed(seed)
    fixtures = load_wc_fixtures()
    groups = infer_groups(fixtures)
    assert len(groups) == 12, f"expected 12 groups, inferred {len(groups)}"
    gs_fixtures = [f for f in fixtures if f["date"] <= GROUP_STAGE_END]

    counters = {k: defaultdict(int) for k in
                ("champion", "final", "semi", "quarter", "group_win")}

    sim = Sim()
    for _ in range(n_sims):
        # --- group stage ---
        stats = {t: [0, 0, 0] for g in groups for t in g}  # pts, gd, gf
        for f in gs_fixtures:
            gh, ga = sim.sample_score(f["home"], f["away"])
            h, a = f["home"], f["away"]
            stats[h][1] += gh - ga; stats[h][2] += gh
            stats[a][1] += ga - gh; stats[a][2] += ga
            if gh > ga:
                stats[h][0] += 3
            elif gh < ga:
                stats[a][0] += 3
            else:
                stats[h][0] += 1; stats[a][0] += 1

        winners, runners, thirds = [], [], []
        for g in groups:
            order = sorted(g, key=lambda t: (stats[t][0], stats[t][1],
                                             stats[t][2], random.random()),
                           reverse=True)
            winners.append(order[0]); runners.append(order[1])
            thirds.append(order[2])
            counters["group_win"][order[0]] += 1
        best_thirds = sorted(thirds, key=lambda t: (stats[t][0], stats[t][1],
                                                    stats[t][2], random.random()),
                             reverse=True)[:8]

        # --- bracket (seeded approximation) ---
        def rank_key(t):
            return (stats[t][0], stats[t][1], stats[t][2], random.random())
        field = (sorted(winners, key=rank_key, reverse=True)
                 + sorted(runners, key=rank_key, reverse=True)
                 + sorted(best_thirds, key=rank_key, reverse=True))
        rnd = field
        while len(rnd) > 1:
            if len(rnd) == 4:
                for t in rnd:
                    counters["semi"][t] += 1
            if len(rnd) == 8:
                for t in rnd:
                    counters["quarter"][t] += 1
            if len(rnd) == 2:
                for t in rnd:
                    counters["final"][t] += 1
            nxt = []
            n = len(rnd)
            for i in range(n // 2):
                a, b = rnd[i], rnd[n - 1 - i]
                nxt.append(a if random.random() < sim.win_prob_knockout(a, b) else b)
            rnd = nxt
        counters["champion"][rnd[0]] += 1

    result = {
        "n_sims": n_sims,
        "groups": {f"G{i+1}": g for i, g in enumerate(groups)},
        "probabilities": {},
        "method_notes": [
            "Knockout ET/pens approximated as 50/50 split of draw mass",
            "R32 bracket seeded by group record (approximation of FIFA bracket)",
            "Elo static within tournament",
        ],
    }
    teams = {t for g in groups for t in g}
    for t in sorted(teams, key=lambda t: -counters["champion"][t]):
        result["probabilities"][t] = {
            "champion": round(counters["champion"][t] / n_sims, 4),
            "final": round(counters["final"][t] / n_sims, 4),
            "semi": round(counters["semi"][t] / n_sims, 4),
            "win_group": round(counters["group_win"][t] / n_sims, 4),
        }
    OUT.write_text(json.dumps(result, indent=2))
    # append to history for the champion-race evolution chart
    hist_file = OUT.parent / "sim_history.json"
    hist = json.loads(hist_file.read_text()) if hist_file.exists() else []
    from datetime import date
    today = date.today().isoformat()
    hist = [h for h in hist if h["date"] != today]
    hist.append({"date": today,
                 "champion": {t: p["champion"] for t, p in
                              list(result["probabilities"].items())[:16]}})
    hist_file.write_text(json.dumps(hist, indent=2))
    return result


if __name__ == "__main__":
    res = simulate()
    print(f"Simulated {res['n_sims']} tournaments. Top 12:")
    for t, p in list(res["probabilities"].items())[:12]:
        print(f"  {t:<16} champion {p['champion']*100:5.1f}%   "
              f"final {p['final']*100:5.1f}%   semi {p['semi']*100:5.1f}%")
