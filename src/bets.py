"""Price derivative markets from the model's Dixon-Coles score grid and
compare against bookmaker odds to compute expected value (EV).

Markets priced (all derivable from the score distribution — matching the
main markets on books like Winamax):
  1X2, double chance, over/under 1.5/2.5/3.5, BTTS, exact scores (top 5),
  European handicaps (-1/+1)

Verdict logic:
  EV(bet) = p_model * decimal_odds - 1
  A market is flagged only if EV > EV_THRESHOLD (default 5%).
  If nothing clears the bar -> verdict NO BET.

Epistemic honesty, printed in every briefing: when this flags 'value', the
most likely explanation is OUR model being wrong, not the bookmaker. The
market is the benchmark until evaluation data says otherwise. Treat flags
as 'model-market disagreements worth logging', not betting instructions.

Scorer markets are deliberately NOT priced: no player-level model yet.
"""
from __future__ import annotations
from model import load_elo, load_params, canon, HOSTS, DEFAULT_ELO, _dc_tau, _poisson_pmf

MAX_G = 8
EV_THRESHOLD = 0.05
# Staking: fractional Kelly with a hard cap. Full Kelly assumes our
# probability is exactly right — it never is. Fraction set to 0.15 per the
# 2026 empirical study on 17,403 top-5-league matches (Springer LNCS 16610:
# full Kelly suffered >80% drawdowns; 15%-Kelly gave the best ROI with
# contained drawdowns). Cap protects against model error.
# Match-day rule (not automated): with several simultaneous picks, total
# exposure should stay under ~10% of bankroll — scale stakes down pro rata.
KELLY_FRACTION = 0.15
KELLY_CAP = 0.05  # never suggest more than 5% of bankroll


def kelly_stake(p: float, odds: float,
                fraction: float = KELLY_FRACTION, cap: float = KELLY_CAP) -> float:
    """Suggested fraction of bankroll. 0 if no edge."""
    b_ = odds - 1
    if b_ <= 0:
        return 0.0
    full = (p * odds - 1) / b_
    return round(max(0.0, min(full * fraction, cap)), 4)


def score_matrix(home: str, away: str) -> tuple[list[list[float]], float, float]:
    p = load_params()
    elo = load_elo()
    adv = p["home_adv_elo"] if canon(home) in HOSTS else 0.0
    diff = (elo.get(canon(home), DEFAULT_ELO) + adv) - elo.get(canon(away), DEFAULT_ELO)
    lh = min(p["base_goals"] * 10 ** (diff / p["elo_scale"]), 6.0)
    la = min(p["base_goals"] * 10 ** (-diff / p["elo_scale"]), 6.0)
    mat = [[0.0] * (MAX_G + 1) for _ in range(MAX_G + 1)]
    total = 0.0
    for gh in range(MAX_G + 1):
        for ga in range(MAX_G + 1):
            pr = max(_poisson_pmf(lh, gh) * _poisson_pmf(la, ga)
                     * _dc_tau(gh, ga, lh, la, p["dc_rho"]), 0.0)
            mat[gh][ga] = pr
            total += pr
    for gh in range(MAX_G + 1):
        for ga in range(MAX_G + 1):
            mat[gh][ga] /= total
    return mat, lh, la


def price_markets(home: str, away: str) -> dict:
    mat, lh, la = score_matrix(home, away)
    ph = sum(mat[gh][ga] for gh in range(MAX_G + 1) for ga in range(MAX_G + 1) if gh > ga)
    pd = sum(mat[g][g] for g in range(MAX_G + 1))
    pa = 1 - ph - pd

    def p_over(line: float) -> float:
        return sum(mat[gh][ga] for gh in range(MAX_G + 1)
                   for ga in range(MAX_G + 1) if gh + ga > line)

    btts = sum(mat[gh][ga] for gh in range(1, MAX_G + 1) for ga in range(1, MAX_G + 1))
    # European handicap: home -1 wins if margin >= 2
    h_minus1 = sum(mat[gh][ga] for gh in range(MAX_G + 1)
                   for ga in range(MAX_G + 1) if gh - ga >= 2)
    a_plus1 = sum(mat[gh][ga] for gh in range(MAX_G + 1)
                  for ga in range(MAX_G + 1) if ga - gh >= 0)  # away +1: win or draw... 

    scores = sorted(((f"{gh}-{ga}", mat[gh][ga])
                     for gh in range(6) for ga in range(6)),
                    key=lambda kv: -kv[1])[:5]
    return {
        "1x2": {"home": ph, "draw": pd, "away": pa},
        "double_chance": {"1X": ph + pd, "X2": pd + pa, "12": ph + pa},
        "over_under": {f"over_{l}": p_over(l) for l in (1.5, 2.5, 3.5)},
        "btts_yes": btts,
        "handicap": {"home_-1": h_minus1, "away_+1_(X2_equiv)": a_plus1},
        "top_scorelines": [{"score": s, "prob": round(p, 4)} for s, p in scores],
        "expected_goals": {"home": round(lh, 2), "away": round(la, 2)},
    }


def ev_analysis(markets: dict, offered_odds: dict[str, float]) -> dict:
    """offered_odds maps market keys (e.g. '1x2.home', 'over_under.over_2.5',
    'btts_yes') to decimal odds. Returns EV per offered market + verdict."""
    flat = _flatten(markets)
    evals = []
    for key, odds in offered_odds.items():
        p = flat.get(key)
        if p is None:
            continue
        ev = p * odds - 1
        evals.append({"market": key, "model_prob": round(p, 4),
                      "odds": odds, "ev": round(ev, 4),
                      "stake_pct": kelly_stake(p, odds),
                      "fair_odds": round(1 / p, 2) if p > 0 else None})
    evals.sort(key=lambda e: -e["ev"])
    positive = [e for e in evals if e["ev"] > EV_THRESHOLD]
    return {
        "verdict": "NO BET" if not positive else "MODEL-MARKET DISAGREEMENT",
        "best": evals[0] if evals else None,
        "flagged": positive[:3],
        "all": evals,
        "caveat": ("Flags = model disagrees with market. The market is the "
                   "stronger predictor until our evaluation proves otherwise. "
                   "Most likely explanation for any flag: model error."),
    }


def market_label(key: str, home: str, away: str) -> str:
    """Market key -> libellé de pari en français, comme sur un site de paris."""
    labels = {
        "1x2.home": f"Victoire {home}",
        "1x2.draw": "Match nul",
        "1x2.away": f"Victoire {away}",
        "double_chance.1X": f"{home} ou match nul (double chance)",
        "double_chance.X2": f"Match nul ou {away} (double chance)",
        "double_chance.12": f"{home} ou {away} (pas de nul)",
        "over_under.over_1.5": "Plus de 1,5 buts dans le match",
        "over_under.over_2.5": "Plus de 2,5 buts dans le match",
        "over_under.over_3.5": "Plus de 3,5 buts dans le match",
        "btts_yes": "Les deux équipes marquent : OUI",
        "handicap.home_-1": f"{home} gagne par 2 buts ou plus (handicap -1)",
    }
    return labels.get(key, key)


def _flatten(d: dict, prefix: str = "") -> dict:
    out = {}
    for k, v in d.items():
        key = f"{prefix}{k}" if not prefix else f"{prefix}.{k}"
        if isinstance(v, dict):
            out.update(_flatten(v, key))
        elif isinstance(v, (int, float)):
            out[key] = float(v)
    return out


def no_bet_reasons(match: dict, ev: dict, lineups_out: bool,
                   llm_confidence: str) -> list[str]:
    reasons = []
    if ev["verdict"] == "NO BET":
        reasons.append("No market clears the +5% EV threshold vs our model.")
    if not lineups_out:
        reasons.append("Official lineups not yet published — key uncertainty.")
    if llm_confidence == "low":
        reasons.append("LLM analyst confidence is low (conflicting/thin news).")
    one_x_two = ev and max(
        (e for e in ev["all"] if e["market"].startswith("1x2")),
        key=lambda e: e["model_prob"], default=None)
    if one_x_two and one_x_two["model_prob"] < 0.45:
        reasons.append("No outcome above 45% — coin-flip territory, high variance.")
    return reasons


if __name__ == "__main__":
    import json
    m = price_markets("France", "Senegal")
    print(json.dumps(m, indent=2))
    demo_odds = {"1x2.home": 1.72, "1x2.draw": 3.6, "1x2.away": 5.2,
                 "over_under.over_2.5": 2.05, "btts_yes": 1.9}
    print(json.dumps(ev_analysis(m, demo_odds), indent=2))
