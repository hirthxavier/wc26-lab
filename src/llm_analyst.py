"""LLM analyst — the 4th contestant in the ablation.

Claude receives: the stats model's probabilities, the multilingual headline
panel, lineup info (when available), and H2H/odds context. It returns
STRUCTURED JSON only: adjusted probabilities, key factors, and a rationale.

Guardrails:
- The LLM's probabilities are clamped to within MAX_LLM_SHIFT of the stats
  model per outcome, then renormalized. A hallucination cannot blow up a
  prediction.
- If the API call fails or returns unparseable output, we fall back to the
  stats-only probabilities and log the failure. The experiment never stalls.

Requires GitHub secret: ANTHROPIC_API_KEY
"""
from __future__ import annotations
import json
import os
import requests

API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
API_URL = "https://api.anthropic.com/v1/messages"
MODEL = "claude-sonnet-4-5"   # good cost/quality for this; haiku works too
MAX_LLM_SHIFT = 0.08          # max abs deviation from stats model per outcome

SYSTEM = """You are a quantitative football analyst. You will receive a stats
model's probabilities for a World Cup match plus recent multilingual news
headlines (Spanish, Italian, French, Portuguese, English) and, if available,
official lineups. Your job is to adjust the probabilities ONLY where the news
contains material information the stats model cannot know: confirmed injuries
or suspensions of key players, surprise lineup decisions, serious squad
turmoil. Ignore hype, opinion pieces, and vague speculation. Small adjustments
only; most matches warrant little or no change. Respond with ONLY valid JSON,
no markdown fences, in this exact schema:
{"home": float, "draw": float, "away": float,
 "confidence": "low"|"medium"|"high",
 "key_factors": [string, ...],
 "rationale": string}"""


def analyze(match: dict, stats_probs: dict, headlines: list[dict],
            lineups: str | None, market: dict | None) -> dict:
    """Returns dict with adjusted probs + analysis, or stats fallback."""
    fallback = {
        "home": stats_probs["home"], "draw": stats_probs["draw"],
        "away": stats_probs["away"], "confidence": "n/a",
        "key_factors": [], "rationale": "LLM unavailable; stats-only.",
        "llm_used": False,
    }
    if not API_KEY:
        return fallback

    headline_block = "\n".join(
        f"- [{h['source']}] {h['title']}" for h in headlines[:60])
    user_msg = f"""Match: {match['home']} vs {match['away']} ({match.get('stage','')})
Kickoff UTC: {match['utc_kickoff']}

Stats model (Elo+Poisson) probabilities:
home={stats_probs['home']:.3f} draw={stats_probs['draw']:.3f} away={stats_probs['away']:.3f}
Elo: {stats_probs.get('elo_home')} vs {stats_probs.get('elo_away')}

Market implied probabilities (margin removed): {json.dumps(market) if market else 'unavailable'}

Official lineups: {lineups or 'not yet published'}

Recent headlines (multilingual panel):
{headline_block or '(none found)'}

Return the JSON now."""

    try:
        r = requests.post(
            API_URL,
            headers={
                "x-api-key": API_KEY,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": MODEL,
                "max_tokens": 800,
                "system": SYSTEM,
                "messages": [{"role": "user", "content": user_msg}],
            },
            timeout=60,
        )
        r.raise_for_status()
        text = "".join(b.get("text", "") for b in r.json()["content"]
                       if b.get("type") == "text")
        text = text.replace("```json", "").replace("```", "").strip()
        out = json.loads(text)
        clamped = _clamp(out, stats_probs)
        clamped.update({
            "confidence": out.get("confidence", "low"),
            "key_factors": out.get("key_factors", [])[:5],
            "rationale": str(out.get("rationale", ""))[:600],
            "llm_used": True,
        })
        return clamped
    except Exception as e:  # noqa: BLE001 — any failure -> safe fallback
        fallback["rationale"] = f"LLM call failed ({type(e).__name__}); stats-only."
        return fallback


def _clamp(llm: dict, stats: dict) -> dict:
    """Clamp each outcome within MAX_LLM_SHIFT of stats model, renormalize."""
    p = {}
    for k in ("home", "draw", "away"):
        v = float(llm.get(k, stats[k]))
        lo, hi = stats[k] - MAX_LLM_SHIFT, stats[k] + MAX_LLM_SHIFT
        p[k] = max(0.01, min(max(lo, min(v, hi)), 0.97))
    total = sum(p.values())
    return {k: v / total for k, v in p.items()}
