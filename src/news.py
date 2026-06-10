"""News signals per team via Google News RSS (legitimate, no auth, no ToS
violation). Extracts simple injury/suspension/turmoil flags and a crude
sentiment score. Deliberately simple v0 — the ablation in evaluate.py will
tell us whether these features add any signal at all."""
from __future__ import annotations
import re
import xml.etree.ElementTree as ET
from urllib.parse import quote
import requests

INJURY_TERMS = re.compile(
    r"\b(injur|blessure|out for|ruled out|doubt|fitness|hamstring|knee|ankle|"
    r"suspended|suspension|ban|forfait)\b", re.I)
TURMOIL_TERMS = re.compile(
    r"\b(crisis|row|dispute|conflict|locker room|vestiaire|polémique|scandal|"
    r"fallout|rift|unrest|strike)\b", re.I)
POSITIVE_TERMS = re.compile(
    r"\b(confident|in form|winning streak|boost|returns|fit again|morale high|"
    r"momentum|favourite|favorite)\b", re.I)
NEGATIVE_TERMS = re.compile(
    r"\b(struggl|poor form|losing streak|pressure|criticis|doubt|worry|concern|"
    r"blow|setback)\b", re.I)


def team_news(team: str, max_items: int = 25) -> dict:
    url = (
        "https://news.google.com/rss/search?q="
        + quote(f'"{team}" world cup 2026')
        + "&hl=en&gl=US&ceid=US:en"
    )
    r = requests.get(url, timeout=30)
    r.raise_for_status()
    root = ET.fromstring(r.content)
    items = root.findall(".//item")[:max_items]

    headlines, injury_flags, turmoil_flags = [], [], []
    pos = neg = 0
    for it in items:
        title = (it.findtext("title") or "").strip()
        headlines.append(title)
        if INJURY_TERMS.search(title):
            injury_flags.append(title)
        if TURMOIL_TERMS.search(title):
            turmoil_flags.append(title)
        pos += len(POSITIVE_TERMS.findall(title))
        neg += len(NEGATIVE_TERMS.findall(title))

    n = max(len(headlines), 1)
    return {
        "team": team,
        "n_headlines": len(headlines),
        "injury_flags": injury_flags[:5],
        "turmoil_flags": turmoil_flags[:5],
        "sentiment": round((pos - neg) / n, 3),  # in [-~1, ~1]
        "headlines": headlines[:10],
    }


if __name__ == "__main__":
    import json
    print(json.dumps(team_news("France"), indent=2))
