"""Generate the static dashboard (docs/index.html) for GitHub Pages.

Runs at the end of every workflow. Renders:
  - Upcoming matches with frozen predictions, THE PICK / NO BET verdict,
    segmented probability bars, top scorelines, LLM rationale
  - Tournament outlook (top champion probabilities from the last sim)
  - Model leaderboard (Brier scores of the 5 contestants)

Pure stdlib, no build step. Mobile-first.
"""
from __future__ import annotations
import html
import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
DOCS = ROOT / "docs"

CSS = """
:root{--paper:#fbfaf7;--ink:#13202e;--pitch:#1a7a3c;--muted:#6b7684;
--line:#e4e1d8;--home:#1a7a3c;--draw:#b9b3a4;--away:#13202e;--warn:#a85b00}
*{box-sizing:border-box;margin:0}
body{background:var(--paper);color:var(--ink);max-width:680px;margin:0 auto;
padding:20px 16px 60px;font:16px/1.55 system-ui,-apple-system,Segoe UI,sans-serif}
.mono{font-family:ui-monospace,SFMono-Regular,Menlo,monospace}
header{border-bottom:3px solid var(--ink);padding-bottom:12px;margin-bottom:24px}
h1{font-size:22px;letter-spacing:-.02em}
h1 span{color:var(--pitch)}
.sub{color:var(--muted);font-size:13px;margin-top:4px}
h2{font-size:12px;text-transform:uppercase;letter-spacing:.14em;
color:var(--muted);margin:32px 0 12px}
.card{border:1px solid var(--line);background:#fff;border-radius:10px;
padding:16px;margin-bottom:14px}
.teams{display:flex;justify-content:space-between;align-items:baseline;gap:8px}
.teams b{font-size:17px}
.ko{color:var(--muted);font-size:12px}
.bar{display:flex;height:22px;border-radius:6px;overflow:hidden;margin:12px 0 4px}
.bar div{display:flex;align-items:center;justify-content:center;
color:#fff;font-size:11px;min-width:34px}
.bar .h{background:var(--home)}.bar .d{background:var(--draw);color:var(--ink)}
.bar .a{background:var(--away)}
.legend{display:flex;justify-content:space-between;font-size:11px;
color:var(--muted);margin-bottom:10px}
.pick{border-left:4px solid var(--pitch);padding:8px 12px;background:#f2f7f0;
font-size:14px;border-radius:0 6px 6px 0;margin:10px 0}
.pick.no{border-left-color:var(--muted);background:#f5f4f0;color:var(--muted)}
.scores,.meta{font-size:13px;color:var(--muted)}
.stamp{display:inline-block;border:1.5px solid var(--pitch);color:var(--pitch);
font-size:10px;letter-spacing:.12em;padding:1px 7px;border-radius:4px;
transform:rotate(-2deg);text-transform:uppercase;margin-top:8px}
table{width:100%;border-collapse:collapse;font-size:14px}
td,th{padding:7px 6px;border-bottom:1px solid var(--line);text-align:left}
th{font-size:11px;text-transform:uppercase;letter-spacing:.1em;color:var(--muted)}
td.num{text-align:right;font-family:ui-monospace,Menlo,monospace}
.caveat{font-size:12px;color:var(--warn);margin-top:8px}
footer{margin-top:40px;font-size:12px;color:var(--muted);
border-top:1px solid var(--line);padding-top:12px}
details{margin-top:8px;font-size:13px}summary{cursor:pointer;color:var(--pitch)}
"""


def esc(s) -> str:
    return html.escape(str(s))


def pct(x: float) -> str:
    return f"{x*100:.0f}%"


def match_card(pred: dict) -> str:
    m = pred["match"]
    p = pred["model_with_news"]
    llm = pred.get("llm_analysis") or {}
    llm_probs = pred.get("model_llm")
    show = llm_probs if llm_probs and llm.get("llm_used") else p
    ev = pred.get("ev_summary")
    pick_html = ""
    if ev:
        if ev.get("verdict") == "NO BET":
            pick_html = '<div class="pick no">No bet — nothing clears the value bar.</div>'
        elif ev.get("top"):
            t = ev["top"]
            pick_html = (f'<div class="pick"><b>The pick:</b> {esc(t["market"])} — '
                         f'model {pct(t["model_prob"])} vs odds {t["odds"]} '
                         f'(EV {t["ev"]*100:+.1f}%)</div>'
                         f'<div class="caveat">Model–market disagreement; most likely '
                         f'explanation is model error. Experiment, not advice.</div>')
    scorelines = pred.get("top_scorelines") or []
    score_html = ("<div class='scores'>Likely scores: " + ", ".join(
        f"{esc(s['score'])} ({pct(s['prob'])})" for s in scorelines[:3]) + "</div>"
        if scorelines else "")
    factors = "".join(f"<li>{esc(k)}</li>" for k in llm.get("key_factors", [])[:4])
    llm_html = (f"<details><summary>Analyst notes ({esc(llm.get('confidence','-'))} "
                f"confidence)</summary><ul>{factors}</ul>"
                f"<p>{esc(llm.get('rationale',''))}</p></details>"
                if llm.get("llm_used") else "")
    return f"""<div class="card">
<div class="teams"><b>{esc(m['home'])} – {esc(m['away'])}</b>
<span class="ko mono">{esc(m['utc_kickoff'][:16].replace('T',' '))} UTC</span></div>
<div class="bar">
<div class="h" style="flex:{show['home']:.3f}">{pct(show['home'])}</div>
<div class="d" style="flex:{show['draw']:.3f}">{pct(show['draw'])}</div>
<div class="a" style="flex:{show['away']:.3f}">{pct(show['away'])}</div></div>
<div class="legend"><span>{esc(m['home'])}</span><span>draw</span>
<span>{esc(m['away'])}</span></div>
{pick_html}{score_html}{llm_html}
<div class="stamp mono">frozen {esc(pred['frozen_at_utc'][:16].replace('T',' '))}</div>
</div>"""


def build() -> Path:
    preds = []
    pdir = DATA / "predictions"
    if pdir.exists():
        for f in pdir.glob("*.json"):
            preds.append(json.loads(f.read_text()))
    preds.sort(key=lambda p: p["match"]["utc_kickoff"], reverse=True)
    upcoming, past = [], []
    now = datetime.now(timezone.utc).isoformat()
    for p in preds:
        (upcoming if p["match"]["utc_kickoff"] >= now else past).append(p)
    upcoming.sort(key=lambda p: p["match"]["utc_kickoff"])

    cards = "".join(match_card(p) for p in upcoming[:12])
    if not cards:
        cards = ('<div class="card meta">No frozen predictions yet. The next '
                 'briefing run (45–60 min before kickoff) will populate this.</div>')

    sim_html = ""
    sim_file = DATA / "tournament_sim.json"
    if sim_file.exists():
        sim = json.loads(sim_file.read_text())
        rows = "".join(
            f"<tr><td>{esc(t)}</td><td class='num'>{pct(v['champion'])}</td>"
            f"<td class='num'>{pct(v['final'])}</td>"
            f"<td class='num'>{pct(v['semi'])}</td></tr>"
            for t, v in list(sim["probabilities"].items())[:10])
        sim_html = (f"<h2>Tournament outlook · {sim['n_sims']} simulations</h2>"
                    f"<div class='card'><table><tr><th>Team</th><th>Champion</th>"
                    f"<th>Final</th><th>Semi</th></tr>{rows}</table></div>")

    eval_html = ""
    ev_file = DATA / "results" / "evaluation.json"
    if ev_file.exists():
        rep = json.loads(ev_file.read_text())
        names = {"stats": "Elo+Poisson", "news": "+ keyword news",
                 "llm": "+ LLM analyst", "market": "Market T-60",
                 "close": "Closing line"}
        rows = "".join(
            f"<tr><td>{names.get(k,k)}</td><td class='num'>{v['mean_brier']:.4f}</td>"
            f"<td class='num'>{v['brier_95ci'][0]:.3f}–{v['brier_95ci'][1]:.3f}</td>"
            f"<td class='num'>{v['n']}</td></tr>"
            for k, v in sorted(rep["summary"].items(),
                               key=lambda kv: kv[1]["mean_brier"]))
        if rows:
            eval_html = ("<h2>Leaderboard · lower Brier = better</h2>"
                         "<div class='card'><table><tr><th>Contestant</th>"
                         "<th>Brier</th><th>95% CI</th><th>N</th></tr>"
                         f"{rows}</table>"
                         "<div class='meta'>Benchmark from backtest: 0.5020 "
                         "(5,835 competitive internationals)</div></div>")

    page = f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>WC26 Prediction Lab</title><style>{CSS}</style></head><body>
<header><h1>WC26 <span>Prediction Lab</span></h1>
<div class="sub mono">predictions frozen pre-kickoff · updated
{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M')} UTC · refreshes every 15 min
on match days</div></header>
<h2>Next matches</h2>{cards}
{sim_html}{eval_html}
<footer>A measurement experiment, not betting advice. The market is the
benchmark until the leaderboard says otherwise. Git history is the lab
notebook — every prediction's commit predates kickoff.</footer>
</body></html>"""
    DOCS.mkdir(exist_ok=True)
    out = DOCS / "index.html"
    out.write_text(page)
    return out


if __name__ == "__main__":
    print(f"Dashboard written to {build()}")
