"""Generate the static dashboard (docs/index.html) for GitHub Pages.

v0.6 sections:
  - Upcoming fixtures (next 72h) with PREVIEW probabilities from the live
    Elo model (clearly marked not-frozen), replaced by the frozen card once
    the pre-kickoff freeze runs
  - Frozen predictions with THE PICK / NO BET verdicts
  - Group standings (live results when API key present, cached otherwise)
  - Champion race: evolution of P(champion) across nightly simulations
  - Model leaderboard (Brier scores, 5 contestants)
  - Optional password gate: set env DASHBOARD_PASSWORD at build time
    (client-side SHA-256 gate — deters casual visitors; the public repo
    itself remains visible, so this is privacy theater, documented as such)

Pure stdlib, no build step. Mobile-first.
"""
from __future__ import annotations
import csv
import hashlib
import html
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent))
import model  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
DOCS = ROOT / "docs"
FINISHED_CACHE = DATA / "finished_cache.json"

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
.ko{color:var(--muted);font-size:12px;white-space:nowrap}
.bar{display:flex;height:22px;border-radius:6px;overflow:hidden;margin:12px 0 4px}
.bar div{display:flex;align-items:center;justify-content:center;
color:#fff;font-size:11px;min-width:34px}
.bar .h{background:var(--home)}.bar .d{background:var(--draw);color:var(--ink)}
.bar .a{background:var(--away)}
.legend{display:flex;justify-content:space-between;font-size:11px;
color:var(--muted);margin-bottom:6px}
.pick{border-left:4px solid var(--pitch);padding:8px 12px;background:#f2f7f0;
font-size:14px;border-radius:0 6px 6px 0;margin:10px 0}
.pick.no{border-left-color:var(--muted);background:#f5f4f0;color:var(--muted)}
.scores,.meta{font-size:13px;color:var(--muted)}
.stamp{display:inline-block;border:1.5px solid var(--pitch);color:var(--pitch);
font-size:10px;letter-spacing:.12em;padding:1px 7px;border-radius:4px;
transform:rotate(-2deg);text-transform:uppercase;margin-top:8px}
.stamp.preview{border-color:var(--muted);color:var(--muted);transform:none}
table{width:100%;border-collapse:collapse;font-size:14px}
td,th{padding:6px;border-bottom:1px solid var(--line);text-align:left}
th{font-size:11px;text-transform:uppercase;letter-spacing:.1em;color:var(--muted)}
td.num{text-align:right;font-family:ui-monospace,Menlo,monospace}
.caveat{font-size:12px;color:var(--warn);margin-top:8px}
footer{margin-top:40px;font-size:12px;color:var(--muted);
border-top:1px solid var(--line);padding-top:12px}
details{margin-top:8px;font-size:13px}summary{cursor:pointer;color:var(--pitch)}
.race{display:flex;align-items:center;gap:10px;padding:6px 0;
border-bottom:1px solid var(--line);font-size:14px}
.race .nm{flex:0 0 110px}.race .pc{flex:0 0 52px;text-align:right}
.race svg{flex:1;height:26px}
#gate{position:fixed;inset:0;background:var(--paper);display:flex;
flex-direction:column;align-items:center;justify-content:center;gap:12px;z-index:9}
#gate input{font-size:16px;padding:10px;border:1px solid var(--line);
border-radius:8px;width:220px;text-align:center}
#gate button{font-size:15px;padding:10px 22px;background:var(--pitch);
color:#fff;border:0;border-radius:8px;cursor:pointer}
#gate .err{color:var(--warn);font-size:13px;min-height:18px}
.hidden{display:none}
"""


def esc(s) -> str:
    return html.escape(str(s))


def pct(x: float) -> str:
    return f"{x*100:.0f}%"


# ---------- data loaders ----------

def load_predictions() -> list[dict]:
    out = []
    pdir = DATA / "predictions"
    if pdir.exists():
        for f in pdir.glob("*.json"):
            try:
                out.append(json.loads(f.read_text()))
            except json.JSONDecodeError:
                continue
    return out


def load_wc_schedule() -> list[dict]:
    """Full WC26 schedule from the bundled historical CSV (no API needed)."""
    raw = DATA / "raw_results.csv"
    out = []
    if not raw.exists():
        return out
    with open(raw, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row["tournament"] == "FIFA World Cup" and row["date"] >= "2026-06-01":
                out.append({"date": row["date"], "home": row["home_team"],
                            "away": row["away_team"]})
    return out


def load_finished() -> list[dict]:
    """Finished WC matches: live from API in workflows, cached for local."""
    if os.environ.get("FOOTBALL_DATA_KEY"):
        try:
            from fixtures import get_finished_matches
            fin = [m for m in get_finished_matches()
                   if m["utc_kickoff"] >= "2026-06-01"]
            FINISHED_CACHE.write_text(json.dumps(fin, indent=2))
            return fin
        except Exception:
            pass
    if FINISHED_CACHE.exists():
        return json.loads(FINISHED_CACHE.read_text())
    return []


# ---------- sections ----------

def frozen_card(pred: dict) -> str:
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
                         f'<div class="caveat">Model–market disagreement; most '
                         f'likely explanation is model error. Experiment, not advice.</div>')
    scorelines = pred.get("top_scorelines") or []
    score_html = ("<div class='scores'>Likely scores: " + ", ".join(
        f"{esc(s['score'])} ({pct(s['prob'])})" for s in scorelines[:3])
        + "</div>" if scorelines else "")
    factors = "".join(f"<li>{esc(k)}</li>" for k in llm.get("key_factors", [])[:4])
    llm_html = (f"<details><summary>Analyst notes ({esc(llm.get('confidence','-'))} "
                f"confidence)</summary><ul>{factors}</ul>"
                f"<p>{esc(llm.get('rationale',''))}</p></details>"
                if llm.get("llm_used") else "")
    return f"""<div class="card">
<div class="teams"><b>{esc(m['home'])} – {esc(m['away'])}</b>
<span class="ko mono">{esc(m['utc_kickoff'][:16].replace('T',' '))} UTC</span></div>
{prob_bar(show, m['home'], m['away'])}
{pick_html}{score_html}{llm_html}
<div class="stamp mono">frozen {esc(pred['frozen_at_utc'][:16].replace('T',' '))}</div>
</div>"""


def prob_bar(p: dict, home: str, away: str) -> str:
    return f"""<div class="bar">
<div class="h" style="flex:{p['home']:.3f}">{pct(p['home'])}</div>
<div class="d" style="flex:{p['draw']:.3f}">{pct(p['draw'])}</div>
<div class="a" style="flex:{p['away']:.3f}">{pct(p['away'])}</div></div>
<div class="legend"><span>{esc(home)}</span><span>draw</span><span>{esc(away)}</span></div>"""


def preview_card(fx: dict) -> str:
    p = model.elo_to_probs(fx["home"], fx["away"])
    return f"""<div class="card">
<div class="teams"><b>{esc(fx['home'])} – {esc(fx['away'])}</b>
<span class="ko mono">{esc(fx['date'])}</span></div>
{prob_bar(p, fx['home'], fx['away'])}
<div class="stamp preview mono">preview — freezes ~1h before kickoff with
odds, lineups &amp; news</div></div>"""


def standings_section(groups: dict, finished: list[dict]) -> str:
    if not groups:
        return ""
    stats = {t: [0, 0, 0, 0] for g in groups.values() for t in g}  # pts gd gf played
    for m in finished:
        h, a = model.canon(m["home"]), model.canon(m["away"])
        s = m.get("score", {})
        if h not in stats or a not in stats or s.get("home") is None:
            continue
        gh, ga = s["home"], s["away"]
        stats[h][1] += gh - ga; stats[h][2] += gh; stats[h][3] += 1
        stats[a][1] += ga - gh; stats[a][2] += ga; stats[a][3] += 1
        if gh > ga:
            stats[h][0] += 3
        elif gh < ga:
            stats[a][0] += 3
        else:
            stats[h][0] += 1; stats[a][0] += 1
    blocks = []
    for gname, teams in groups.items():
        order = sorted(teams, key=lambda t: (-stats[t][0], -stats[t][1], -stats[t][2]))
        rows = "".join(
            f"<tr><td>{esc(t)}</td><td class='num'>{stats[t][3]}</td>"
            f"<td class='num'>{stats[t][0]}</td><td class='num'>{stats[t][1]:+d}</td></tr>"
            for t in order)
        blocks.append(f"<details><summary>{esc(gname)}: "
                      f"{esc(' · '.join(order))}</summary>"
                      f"<table><tr><th>Team</th><th>P</th><th>Pts</th><th>GD</th></tr>"
                      f"{rows}</table></details>")
    played_any = any(v[3] for v in stats.values())
    note = "" if played_any else "<div class='meta'>No results yet — tables fill in as matches finish.</div>"
    return ("<h2>Group standings</h2><div class='card'>"
            + note + "".join(blocks) + "</div>")


def race_section() -> str:
    hist_file = DATA / "sim_history.json"
    sim_file = DATA / "tournament_sim.json"
    if not sim_file.exists():
        return ""
    sim = json.loads(sim_file.read_text())
    top = list(sim["probabilities"].items())[:8]
    hist = json.loads(hist_file.read_text()) if hist_file.exists() else []
    rows = []
    for team, p in top:
        series = [snap["champion"].get(team, 0.0) for snap in hist] or [p["champion"]]
        mx = max(max(series), 0.01)
        pts = " ".join(f"{i/(max(len(series)-1,1))*100:.1f},"
                       f"{26 - (v/mx)*22:.1f}" for i, v in enumerate(series))
        spark = (f"<svg viewBox='0 0 100 28' preserveAspectRatio='none'>"
                 f"<polyline points='{pts}' fill='none' stroke='#1a7a3c' "
                 f"stroke-width='2'/></svg>")
        rows.append(f"<div class='race'><span class='nm'>{esc(team)}</span>"
                    f"{spark}<span class='pc mono'>{pct(p['champion'])}</span></div>")
    n = len(hist)
    sub = (f"<div class='meta'>P(champion) across {n} nightly re-simulations — "
           f"Elo updates after every match, so this chart IS the evolution of "
           f"the cup.</div>" if n > 1 else
           "<div class='meta'>Line builds up as the tournament progresses — "
           "the sim re-runs every night with updated Elo.</div>")
    return ("<h2>Champion race · " + str(sim["n_sims"]) + " sims</h2>"
            "<div class='card'>" + "".join(rows) + sub + "</div>")


def leaderboard_section() -> str:
    ev_file = DATA / "results" / "evaluation.json"
    if not ev_file.exists():
        return ""
    rep = json.loads(ev_file.read_text())
    names = {"stats": "Elo+Poisson", "news": "+ keyword news",
             "llm": "+ LLM analyst", "market": "Market T-60",
             "close": "Closing line"}
    rows = "".join(
        f"<tr><td>{names.get(k,k)}</td><td class='num'>{v['mean_brier']:.4f}</td>"
        f"<td class='num'>{v['brier_95ci'][0]:.3f}–{v['brier_95ci'][1]:.3f}</td>"
        f"<td class='num'>{v['n']}</td></tr>"
        for k, v in sorted(rep.get("summary", {}).items(),
                           key=lambda kv: kv[1]["mean_brier"]))
    if not rows:
        return ""
    return ("<h2>Leaderboard · lower Brier = better</h2>"
            "<div class='card'><table><tr><th>Contestant</th><th>Brier</th>"
            "<th>95% CI</th><th>N</th></tr>" + rows + "</table>"
            "<div class='meta'>Backtest benchmark: 0.5020 "
            "(5,835 competitive internationals)</div></div>")


def track_record_section(preds: list[dict], finished: list[dict]) -> str:
    """Every frozen prediction vs the actual result: pick, score, hit/miss,
    plus running tally. The end-of-tournament accuracy report, live."""
    fin_by_id = {m["match_id"]: m for m in finished}
    rows, hits, total, prob_sum = [], 0, 0, 0.0
    for p in sorted(preds, key=lambda x: x["match"]["utc_kickoff"], reverse=True):
        res = fin_by_id.get(p["match"]["match_id"])
        if not res:
            continue
        s = res.get("score", {})
        if s.get("home") is None:
            continue
        actual = ("home" if s["home"] > s["away"]
                  else "away" if s["home"] < s["away"] else "draw")
        llm = p.get("llm_analysis") or {}
        probs = (p.get("model_llm") if p.get("model_llm") and llm.get("llm_used")
                 else p["model_with_news"])
        pick = max(("home", "draw", "away"), key=lambda o: probs[o])
        hit = pick == actual
        hits += hit; total += 1; prob_sum += probs[actual]
        names = {"home": p["match"]["home"], "away": p["match"]["away"],
                 "draw": "Draw"}
        rows.append(
            f"<tr><td>{esc(p['match']['home'])} {s['home']}-{s['away']} "
            f"{esc(p['match']['away'])}</td>"
            f"<td>{esc(names[pick])} ({pct(probs[pick])})</td>"
            f"<td class='num'>{pct(probs[actual])}</td>"
            f"<td class='num'>{'&#10003;' if hit else '&#10007;'}</td></tr>")
    if not total:
        return ""
    tally = (f"<div class='meta'>Top-pick hit rate: <b>{hits}/{total} "
             f"({hits/total*100:.0f}%)</b> &middot; avg probability assigned to "
             f"the actual outcome: <b>{prob_sum/total*100:.0f}%</b> "
             f"(random = 33%, higher = better calibrated). Hit rate alone is "
             f"a crude metric &mdash; favorites lose often in football; the "
             f"Brier leaderboard below is the scientific scoreboard.</div>")
    return ("<h2>Track record &middot; prediction vs reality</h2>"
            "<div class='card'><table><tr><th>Result</th><th>Our pick</th>"
            "<th>P(actual)</th><th></th></tr>" + "".join(rows[:30])
            + "</table>" + tally + "</div>")


def gate_snippet() -> tuple[str, str, str]:
    """Returns (gate_html, gate_js, content_class). Empty if no password set."""
    pw = os.environ.get("DASHBOARD_PASSWORD", "")
    if not pw:
        return "", "", ""
    digest = hashlib.sha256(pw.encode()).hexdigest()
    gate_html = """<div id="gate"><h1>WC26 <span style="color:#1a7a3c">Lab</span></h1>
<input id="pw" type="password" placeholder="Password" autofocus>
<button onclick="check()">Enter</button><div class="err" id="err"></div></div>"""
    gate_js = f"""<script>
const HASH="{digest}";
async function sha(s){{const b=await crypto.subtle.digest("SHA-256",
new TextEncoder().encode(s));return [...new Uint8Array(b)].map(
x=>x.toString(16).padStart(2,"0")).join("")}}
async function check(){{if(await sha(document.getElementById("pw").value)===HASH){{
sessionStorage.setItem("wc26","1");unlock()}}else{{
document.getElementById("err").textContent="Wrong password"}}}}
function unlock(){{document.getElementById("gate").remove();
document.getElementById("main").classList.remove("hidden")}}
if(sessionStorage.getItem("wc26")==="1")window.addEventListener(
"DOMContentLoaded",unlock);
document.addEventListener("keydown",e=>{{if(e.key==="Enter"&&
document.getElementById("gate"))check()}});
</script>"""
    return gate_html, gate_js, " hidden"


def build() -> Path:
    preds = load_predictions()
    now_iso = datetime.now(timezone.utc).isoformat()
    frozen_upcoming = sorted([p for p in preds
                              if p["match"]["utc_kickoff"] >= now_iso],
                             key=lambda p: p["match"]["utc_kickoff"])
    frozen_past = sorted([p for p in preds
                          if p["match"]["utc_kickoff"] < now_iso],
                         key=lambda p: p["match"]["utc_kickoff"], reverse=True)
    frozen_pairs = {(model.canon(p["match"]["home"]), model.canon(p["match"]["away"]))
                    for p in frozen_upcoming}

    today = datetime.now(timezone.utc).date()
    horizon = today + timedelta(days=3)
    schedule = [f for f in load_wc_schedule()
                if today.isoformat() <= f["date"] <= horizon.isoformat()
                and (model.canon(f["home"]), model.canon(f["away"]))
                not in frozen_pairs]
    schedule.sort(key=lambda f: f["date"])

    upcoming_html = ("".join(frozen_card(p) for p in frozen_upcoming)
                     + "".join(preview_card(f) for f in schedule[:12]))
    if not upcoming_html:
        upcoming_html = "<div class='card meta'>No upcoming matches in the next 3 days.</div>"

    finished = load_finished()
    track_html = track_record_section(frozen_past, finished)
    past_html = ""
    leftover = [p for p in frozen_past
                if p["match"]["match_id"] not in
                {m["match_id"] for m in finished}]
    if leftover:
        past_html = ("<h2>Awaiting result</h2>"
                     + "".join(frozen_card(p) for p in leftover[:4]))

    sim_file = DATA / "tournament_sim.json"
    groups = (json.loads(sim_file.read_text()).get("groups", {})
              if sim_file.exists() else {})

    gate_html, gate_js, content_class = gate_snippet()

    page = f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>WC26 Prediction Lab</title><style>{CSS}</style></head><body>
{gate_html}<div id="main" class="{content_class.strip()}">
<header><h1>WC26 <span>Prediction Lab</span></h1>
<div class="sub mono">predictions frozen pre-kickoff · updated
{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M')} UTC</div></header>
<h2>Next matches</h2>{upcoming_html}
{race_section()}
{standings_section(groups, finished)}
{track_html}
{past_html}
{leaderboard_section()}
<footer>A measurement experiment, not betting advice. The market is the
benchmark until the leaderboard says otherwise. Git history is the lab
notebook — every prediction's commit predates kickoff.</footer>
</div>{gate_js}</body></html>"""
    DOCS.mkdir(exist_ok=True)
    out = DOCS / "index.html"
    out.write_text(page)
    return out


if __name__ == "__main__":
    print(f"Dashboard written to {build()}")
