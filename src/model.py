"""Model v0: Elo ratings -> expected goals -> Poisson match simulation,
with a small, capped adjustment from news features. Every prediction is
frozen to data/predictions/ BEFORE kickoff with full provenance.

The model intentionally also records the market's implied probabilities at
prediction time, so evaluate.py can compare:
  model_stats_only   vs  model_with_news   vs  market
(that's our ablation: do news features add signal?)
"""
from __future__ import annotations
import json
import math
from datetime import datetime, timezone
from config import PREDICTIONS_DIR, MODEL_VERSION, DATA

ELO_FILE = DATA / "elo.json"
PARAMS_FILE = DATA / "params.json"
DEFAULT_ELO = 1500.0
K_FACTOR = 32.0

# WC2026 host nations get the fitted home-advantage Elo bonus when they are
# the designated home team (approximation: hosts play their group matches at
# home venues). Documented limitation: we don't check venue city.
HOSTS = {"United States", "Canada", "Mexico"}

# football-data.org names -> historical dataset names
ALIASES = {
    "USA": "United States", "Korea Republic": "South Korea",
    "IR Iran": "Iran", "Côte d'Ivoire": "Ivory Coast",
    "Cabo Verde": "Cape Verde", "Czechia": "Czech Republic",
    "Türkiye": "Turkey", "Bosnia & Herzegovina": "Bosnia and Herzegovina",
}


def canon(team: str) -> str:
    return ALIASES.get(team, team)


def load_params() -> dict:
    if PARAMS_FILE.exists():
        return json.loads(PARAMS_FILE.read_text())
    return {"base_goals": 1.3, "elo_scale": 1300, "dc_rho": -0.15,
            "home_adv_elo": 100}


def _dc_tau(gh, ga, lh, la, rho):
    if gh == 0 and ga == 0:
        return 1 - lh * la * rho
    if gh == 0 and ga == 1:
        return 1 + lh * rho
    if gh == 1 and ga == 0:
        return 1 + la * rho
    if gh == 1 and ga == 1:
        return 1 - rho
    return 1.0
# Max absolute shift news can apply to win prob (kept tiny on purpose)
NEWS_MAX_SHIFT = 0.03
# Max shift from player form differential (rating points -> probability)
PLAYERS_MAX_SHIFT = 0.05
PLAYERS_SCALE = 0.10  # 1.0 rating point of form diff -> 10pp shift (capped)


def apply_players(probs: dict, form_diff: float | None) -> dict | None:
    """6th contestant: stats model shifted by quantified player form.
    Returns None when no player data (contestant skips the match)."""
    if form_diff is None:
        return None
    shift = max(-PLAYERS_MAX_SHIFT, min(form_diff * PLAYERS_SCALE,
                                        PLAYERS_MAX_SHIFT))
    p = dict(probs)
    p["home"] = max(0.01, probs["home"] + shift)
    p["away"] = max(0.01, probs["away"] - shift)
    total = p["home"] + p["draw"] + p["away"]
    return {k: p[k] / total for k in ("home", "draw", "away")}


def load_elo() -> dict:
    if ELO_FILE.exists():
        return json.loads(ELO_FILE.read_text())
    return {}


def save_elo(elo: dict):
    ELO_FILE.write_text(json.dumps(elo, indent=2))


def update_elo(home: str, away: str, home_goals: int, away_goals: int):
    elo = load_elo()
    home, away = canon(home), canon(away)
    ra, rb = elo.get(home, DEFAULT_ELO), elo.get(away, DEFAULT_ELO)
    ea = 1 / (1 + 10 ** ((rb - ra) / 400))
    sa = 1.0 if home_goals > away_goals else 0.0 if home_goals < away_goals else 0.5
    margin_mult = math.log(abs(home_goals - away_goals) + 1) + 1
    elo[home] = ra + K_FACTOR * margin_mult * (sa - ea)
    elo[away] = rb + K_FACTOR * margin_mult * ((1 - sa) - (1 - ea))
    save_elo(elo)


def _poisson_pmf(lam: float, k: int) -> float:
    return math.exp(-lam) * lam ** k / math.factorial(k)


def elo_to_probs(home: str, away: str) -> dict:
    """Elo gap (+ host advantage) -> expected goals -> Poisson with
    Dixon-Coles low-score correction -> 1X2 probs. All parameters fitted
    by backtest.py on held-out competitive internationals."""
    params = load_params()
    elo = load_elo()
    home_c, away_c = canon(home), canon(away)
    ra, rb = elo.get(home_c, DEFAULT_ELO), elo.get(away_c, DEFAULT_ELO)
    adv = params["home_adv_elo"] if home_c in HOSTS else 0.0
    diff = (ra + adv) - rb
    base_goals = params["base_goals"]
    scale = params["elo_scale"]
    rho = params["dc_rho"]
    lam_home = min(base_goals * 10 ** (diff / scale), 6.0)
    lam_away = min(base_goals * 10 ** (-diff / scale), 6.0)

    p_home = p_draw = p_away = 0.0
    for gh in range(11):
        for ga in range(11):
            p = (_poisson_pmf(lam_home, gh) * _poisson_pmf(lam_away, ga)
                 * _dc_tau(gh, ga, lam_home, lam_away, rho))
            if p <= 0:
                continue
            if gh > ga:
                p_home += p
            elif gh == ga:
                p_draw += p
            else:
                p_away += p
    total = p_home + p_draw + p_away
    return {"home": p_home / total, "draw": p_draw / total, "away": p_away / total,
            "lam_home": round(lam_home, 3), "lam_away": round(lam_away, 3),
            "elo_home": round(ra, 1), "elo_away": round(rb, 1),
            "host_adv_applied": adv}


def apply_news(probs: dict, news_home: dict, news_away: dict) -> dict:
    """Tiny, capped, transparent adjustment. Injury flags and negative
    sentiment shift probability away from a team; renormalize after."""
    def signal(n):
        s = n.get("sentiment", 0.0)
        s -= 0.02 * len(n.get("injury_flags", []))
        s -= 0.01 * len(n.get("turmoil_flags", []))
        return max(-1.0, min(1.0, s))

    shift = (signal(news_home) - signal(news_away)) * NEWS_MAX_SHIFT
    p = dict(probs)
    p["home"] = max(0.01, probs["home"] + shift)
    p["away"] = max(0.01, probs["away"] - shift)
    total = p["home"] + p["draw"] + p["away"]
    for k in ("home", "draw", "away"):
        p[k] /= total
    p["news_shift_applied"] = round(shift, 4)
    return p


def freeze_prediction(match: dict, stats_probs: dict, final_probs: dict,
                      market: dict | None, news_home: dict, news_away: dict,
                      llm_result: dict | None = None, lineups: str | None = None,
                      extra: dict | None = None):
    """Write the prediction to disk BEFORE kickoff. Committing this file is
    the experiment's integrity guarantee."""
    record = {
        "frozen_at_utc": datetime.now(timezone.utc).isoformat(),
        "model_version": MODEL_VERSION,
        "match": match,
        "model_stats_only": {k: round(stats_probs[k], 4) for k in ("home", "draw", "away")},
        "model_with_news": {k: round(final_probs[k], 4) for k in ("home", "draw", "away")},
        "model_llm": ({k: round(llm_result[k], 4) for k in ("home", "draw", "away")}
                      if llm_result else None),
        "llm_analysis": ({k: llm_result.get(k) for k in
                          ("confidence", "key_factors", "rationale", "llm_used")}
                         if llm_result else None),
        "lineups_available": lineups is not None,
        "market_implied": market.get("implied_probs") if market else None,
        "market_overround": market.get("overround") if market else None,
        "news_home": {k: news_home[k] for k in ("sentiment", "injury_flags", "turmoil_flags")},
        "news_away": {k: news_away[k] for k in ("sentiment", "injury_flags", "turmoil_flags")},
        "diagnostics": {k: stats_probs[k] for k in ("lam_home", "lam_away", "elo_home", "elo_away")},
    }
    if extra:
        record.update(extra)
    PREDICTIONS_DIR.mkdir(parents=True, exist_ok=True)
    path = PREDICTIONS_DIR / f"{match['match_id']}.json"
    path.write_text(json.dumps(record, indent=2))
    return path
