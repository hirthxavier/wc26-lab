"""Curated source panel: top football outlets from ES/IT/FR/AR/UK/BR via RSS,
plus journalist-level Google News queries. All legitimate (RSS is made to be
read by machines), multilingual on purpose — the LLM analyst reads all of it.
"""
from __future__ import annotations
import xml.etree.ElementTree as ET
from urllib.parse import quote
import requests

# Outlet RSS feeds. URLs verified periodically; if one 404s the fetcher just
# skips it and logs.
OUTLET_FEEDS = {
    "ES": [
        ("Marca", "https://e00-marca.uecdn.es/rss/futbol/seleccion.xml"),
        ("AS", "https://as.com/rss/futbol/portada.xml"),
    ],
    "IT": [
        ("Gazzetta", "https://www.gazzetta.it/rss/calcio.xml"),
        ("Corriere dello Sport", "https://www.corrieredellosport.it/rss/calcio"),
    ],
    "FR": [
        ("L'Equipe", "https://dwh.lequipe.fr/api/edito/rss?path=/Football/"),
        ("Foot Mercato", "https://www.footmercato.net/rss"),
    ],
    "AR": [
        ("Ole", "https://www.ole.com.ar/rss/futbol-internacional/"),
        ("TyC Sports", "https://www.tycsports.com/rss.xml"),
    ],
    "UK": [
        ("BBC Sport", "https://feeds.bbci.co.uk/sport/football/rss.xml"),
        ("Guardian", "https://www.theguardian.com/football/rss"),
    ],
    "BR": [
        ("Globo Esporte", "https://ge.globo.com/rss/ge/"),
        ("UOL Esporte", "https://rss.uol.com.br/feed/esporte.xml"),
    ],
}

# Journalist-level signal via Google News byline queries (indexed in minutes).
JOURNALIST_QUERIES = [
    "Fabrizio Romano",          # transfers/squad news, IT/global
    '"Guillem Balagué"',        # ES national team insight
    'site:lequipe.fr équipe de France',
    '"Gianluca Di Marzio"',     # IT squad news
    'Olé selección argentina',
]


def _parse_rss(content: bytes, source: str, limit: int = 15) -> list[dict]:
    out = []
    try:
        root = ET.fromstring(content)
        for it in root.findall(".//item")[:limit]:
            out.append({
                "source": source,
                "title": (it.findtext("title") or "").strip(),
                "link": (it.findtext("link") or "").strip(),
                "published": (it.findtext("pubDate") or "").strip(),
            })
    except ET.ParseError:
        pass
    return out


def fetch_panel(team_names: list[str] | None = None, per_feed: int = 15) -> list[dict]:
    """Pull all panel feeds. If team_names given, also pull targeted Google
    News queries per team, and filter outlet items to those mentioning a team."""
    items: list[dict] = []
    for country, feeds in OUTLET_FEEDS.items():
        for name, url in feeds:
            try:
                r = requests.get(url, timeout=20,
                                 headers={"User-Agent": "wc26-lab/0.2 (research)"})
                if r.ok:
                    items.extend(_parse_rss(r.content, f"{name} ({country})", per_feed))
            except requests.RequestException:
                continue

    if team_names:
        lowered = [t.lower() for t in team_names]
        outlet_items = [i for i in items
                        if any(t in i["title"].lower() for t in lowered)]
        gn_items = []
        for team in team_names:
            for q in ([f'"{team}" world cup'] +
                      [f'{j} "{team}"' for j in JOURNALIST_QUERIES[:2]]):
                url = ("https://news.google.com/rss/search?q=" + quote(q)
                       + "&hl=en&gl=US&ceid=US:en")
                try:
                    r = requests.get(url, timeout=20)
                    if r.ok:
                        gn_items.extend(_parse_rss(r.content, f"GoogleNews:{q}", 10))
                except requests.RequestException:
                    continue
        # dedupe by title
        seen, deduped = set(), []
        for i in outlet_items + gn_items:
            key = i["title"][:80].lower()
            if key not in seen:
                seen.add(key)
                deduped.append(i)
        return deduped
    return items


if __name__ == "__main__":
    import json
    print(json.dumps(fetch_panel(["France", "Brazil"])[:20], indent=2))
