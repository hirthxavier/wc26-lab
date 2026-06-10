"""Score frozen predictions against actual results.

Three contestants per match:
  1. model_stats_only  (Elo+Poisson)
  2. model_with_news   (ablation: do news features help?)
  3. market_implied    (de-margined consensus odds — the benchmark to respect)

Metrics: multiclass Brier score and log loss, with bootstrap 95% CIs.
Lower is better for both. We also bin predictions for a calibration table.
"""
from __future__ import annotations
import json
import math
import random
import json as _json
from config import PREDICTIONS_DIR, RESULTS_DIR, DATA
from fixtures import get_finished_matches

SNAPSHOTS = DATA / "odds_snapshots.json"


def closing_probs(home: str, away: str, kickoff_iso: str) -> dict | None:
    """Implied probs from the LAST odds snapshot before kickoff (the closing
    line — the gold-standard benchmark)."""
    if not SNAPSHOTS.exists():
        return None
    best = None
    for s in _json.loads(SNAPSHOTS.read_text()):
        if s["home"] == home and s["away"] == away and s["ts"] <= kickoff_iso:
            if best is None or s["ts"] > best["ts"]:
                best = s
    return best["implied_probs"] if best else None

OUTCOMES = ("home", "draw", "away")


def outcome_of(score: dict) -> str | None:
    h, a = score.get("home"), score.get("away")
    if h is None or a is None:
        return None
    return "home" if h > a else "away" if h < a else "draw"


def brier(probs: dict, actual: str) -> float:
    return sum((probs[o] - (1.0 if o == actual else 0.0)) ** 2 for o in OUTCOMES)


def log_loss(probs: dict, actual: str) -> float:
    return -math.log(max(probs[actual], 1e-12))


def market_to_probs(market: dict, home: str, away: str) -> dict | None:
    """The Odds API names outcomes by team name + 'Draw'."""
    if not market:
        return None
    key_map = {}
    for name, p in market.items():
        if name.lower() == "draw":
            key_map["draw"] = p
        elif name == home:
            key_map["home"] = p
        elif name == away:
            key_map["away"] = p
    return key_map if len(key_map) == 3 else None


def evaluate() -> dict:
    finished = {m["match_id"]: m for m in get_finished_matches()}
    rows = []
    for f in sorted(PREDICTIONS_DIR.glob("*.json")):
        pred = json.loads(f.read_text())
        mid = pred["match"]["match_id"]
        result = finished.get(mid)
        if not result:
            continue
        actual = outcome_of(result["score"])
        if actual is None:
            continue
        market_probs = market_to_probs(
            pred.get("market_implied"), pred["match"]["home"], pred["match"]["away"])
        close_raw = closing_probs(pred["match"]["home"], pred["match"]["away"],
                                  pred["match"]["utc_kickoff"])
        close_probs = market_to_probs(close_raw, pred["match"]["home"],
                                      pred["match"]["away"]) if close_raw else None
        row = {"match_id": mid, "match": f'{pred["match"]["home"]} v {pred["match"]["away"]}',
               "actual": actual}
        for name, probs in (
            ("stats", pred["model_stats_only"]),
            ("news", pred["model_with_news"]),
            ("llm", pred.get("model_llm")),
            ("market", market_probs),
            ("close", close_probs),
        ):
            if probs:
                row[f"brier_{name}"] = round(brier(probs, actual), 4)
                row[f"logloss_{name}"] = round(log_loss(probs, actual), 4)
        rows.append(row)

    summary = {}
    for name in ("stats", "news", "llm", "market", "close"):
        vals = [r[f"brier_{name}"] for r in rows if f"brier_{name}" in r]
        if vals:
            summary[name] = {
                "n": len(vals),
                "mean_brier": round(sum(vals) / len(vals), 4),
                "brier_95ci": _bootstrap_ci(vals),
            }
    report = {"per_match": rows, "summary": summary}
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    (RESULTS_DIR / "evaluation.json").write_text(json.dumps(report, indent=2))
    return report


def _bootstrap_ci(vals: list[float], n_boot: int = 5000) -> list[float]:
    means = []
    for _ in range(n_boot):
        sample = [random.choice(vals) for _ in vals]
        means.append(sum(sample) / len(sample))
    means.sort()
    return [round(means[int(0.025 * n_boot)], 4), round(means[int(0.975 * n_boot)], 4)]


if __name__ == "__main__":
    rep = evaluate()
    print(json.dumps(rep["summary"], indent=2))
