"""Generate the static dashboard (docs/index.html) for GitHub Pages.

v0.6 sections:
  - Upcoming fixtures (next 72h) with PREVIEW probabilities from the live
    Elo model (clearly marked not-frozen), replaced by the frozen card once
    the pre-kickoff freeze runs
  - Frozen predictions with THE PICK / NO BET verdicts
  - Group standings (live results when API key present, cached otherwise)
  - Champion race: evolution of P(champion) across nightly simulations
  - Model leaderboard (Brier scores, 5 contestants)

Pure stdlib, no build step. Mobile-first.
"""
from __future__ import annotations
import csv
import html
import json
import os
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

PARIS = ZoneInfo("Europe/Paris")


def cet(dt_iso: str) -> str:
    dt = datetime.fromisoformat(dt_iso.replace("Z", "+00:00")).astimezone(PARIS)
    return dt.strftime("%d/%m %H:%M") + " CET"
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent))
import model  # noqa: E402
from bets import market_label  # noqa: E402

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
.wx{background:#1e2638;color:#eef1f7;border:0;border-radius:12px;
padding:0;overflow:hidden}
.wx .top{display:flex;justify-content:space-between;align-items:center;
padding:10px 14px;background:#161d2c;font-size:11px;color:#8d97ad;
text-transform:uppercase;letter-spacing:.1em}
.wx .teams2{display:flex;justify-content:space-between;align-items:flex-start;
padding:14px 14px 4px;gap:10px}
.wx .tname{font-size:18px;font-weight:800;color:#fff}
.wx .tname.right{text-align:right}
.badges{display:flex;gap:4px;margin-top:6px}
.badges.right{justify-content:flex-end}
.bdg{width:18px;height:18px;border-radius:50%;font-size:10px;font-weight:800;
display:flex;align-items:center;justify-content:center;color:#fff}
.bdg.V{background:#2eb85c}.bdg.N{background:#7a8499}.bdg.D{background:#d9534f}
.wx .bar{margin:12px 14px 4px}
.wx .legend{padding:0 14px;color:#8d97ad}
.cotes{display:flex;gap:8px;padding:10px 14px}
.cote{flex:1;background:#fff;border-radius:8px;text-align:center;
padding:7px 4px;color:#1e2638}
.cote .c1{font-size:10px;font-weight:700;color:#7a8499;text-transform:uppercase}
.cote .c2{font-size:17px;font-weight:800;font-family:ui-monospace,Menlo,monospace}
.wxpick{background:#e2001a;color:#fff;padding:11px 14px;display:flex;
justify-content:space-between;align-items:center;gap:10px;flex-wrap:wrap}
.wxpick .what{font-size:16px;font-weight:800}
.wxpick .nums{font-size:13px;font-weight:700;text-align:right}
.wxpick.nobet{background:#39415a;color:#c9d0e0}
.anl{padding:12px 14px;font-size:14px;line-height:1.5;border-top:1px solid #2b3550}
.anl h4{font-size:10px;letter-spacing:.14em;text-transform:uppercase;
color:#e2001a;margin:10px 0 4px}
.anl h4:first-child{margin-top:0}
.anl ul{margin:0;padding-left:18px}
.anl .verdict{background:#161d2c;border-left:3px solid #e2001a;
padding:8px 10px;border-radius:0 6px 6px 0;margin-top:8px;font-weight:600}
.h2hline{display:flex;height:8px;border-radius:4px;overflow:hidden;margin:6px 0}
.h2hline div{height:100%}
.wx .meta,.wx .scores{color:#8d97ad;padding:0 14px}
.wx .stamp{margin:10px 14px 14px;border-color:#2eb85c;color:#2eb85c}
.wx .caveat{padding:0 14px 4px;color:#e8a33d}
.wx details{padding:0 14px 10px;color:#aab3c7}
.wx summary{color:#8d97ad}
.slip{border:2px solid var(--pitch);border-radius:10px;margin:12px 0;
overflow:hidden;background:#fff}
.slip .head{background:var(--pitch);color:#fff;padding:7px 12px;font-size:12px;
letter-spacing:.12em;text-transform:uppercase;font-weight:700}
.slip .bet{padding:12px;font-size:17px;font-weight:700}
.slip .grid{display:flex;border-top:1px solid var(--line);text-align:center}
.slip .grid>div{flex:1;padding:9px 4px;border-right:1px solid var(--line)}
.slip .grid>div:last-child{border-right:0}
.slip .lbl{font-size:10px;text-transform:uppercase;letter-spacing:.1em;
color:var(--muted)}
.slip .val{font-size:16px;font-weight:700;font-family:ui-monospace,Menlo,monospace}
.slip .gain .val{color:var(--pitch)}
.slip.nobet{border-color:var(--muted)}
.slip.nobet .head{background:var(--muted)}
.slip.nobet .bet{font-size:15px;color:var(--muted);font-weight:600}
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
            if f.name.endswith("_update.json"):
                continue
            try:
                out.append(json.loads(f.read_text()))
            except json.JSONDecodeError:
                continue
    return out


FIXTURES_CACHE = DATA / "fixtures_cache.json"


def load_upcoming_with_times(days: int = 3) -> list[dict]:
    """Exact kickoff times: live API in workflows (cached), CSV fallback."""
    if os.environ.get("FOOTBALL_DATA_KEY"):
        try:
            from fixtures import get_matches
            ms = get_matches(days_ahead=days)
            FIXTURES_CACHE.write_text(json.dumps(ms, indent=2))
            return ms
        except Exception:
            pass
    if FIXTURES_CACHE.exists():
        return json.loads(FIXTURES_CACHE.read_text())
    today = datetime.now(timezone.utc).date()
    horizon = today + timedelta(days=days)
    return [{"match_id": None, "utc_kickoff": f["date"] + "T00:00:00Z",
             "home": f["home"], "away": f["away"], "status": "TIMED",
             "date_only": True}
            for f in load_wc_schedule()
            if today.isoformat() <= f["date"] <= horizon.isoformat()]


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

def _badges(seq, right=False):
    cls = "badges right" if right else "badges"
    return ("<div class='" + cls + "'>" +
            "".join(f"<span class='bdg {r}'>{r}</span>" for r in (seq or [])[:5])
            + "</div>")


def frozen_card(pred: dict) -> str:
    m = pred["match"]
    upd_file = DATA / "predictions" / f"{m['match_id']}_update.json"
    upd_html = ""
    if upd_file.exists():
        try:
            upd = json.loads(upd_file.read_text())
            items = "".join(f"<li>{esc(x)}</li>" for x in upd.get("lineup_deltas", []))
            upd_html = ("<details><summary>Compos publiées après le gel</summary>"
                        f"<ul>{items}</ul>"
                        f"<p class='meta'>{esc(upd.get('lineups',''))[:400]}</p>"
                        "</details>")
        except json.JSONDecodeError:
            pass
    p = pred["model_with_news"]
    llm = pred.get("llm_analysis") or {}
    llm_probs = pred.get("model_llm")
    show = llm_probs if llm_probs and llm.get("llm_used") else p
    fs = pred.get("formstats") or {}

    # cotes 1/N/2
    oo = pred.get("offered_odds") or {}
    cotes_html = ""
    if oo.get("1x2.home"):
        cotes_html = ("<div class='cotes'>"
            f"<div class='cote'><div class='c1'>1 · {esc(m['home'][:12])}</div>"
            f"<div class='c2'>{oo['1x2.home']:.2f}</div></div>"
            f"<div class='cote'><div class='c1'>N · Nul</div>"
            f"<div class='c2'>{oo.get('1x2.draw',0):.2f}</div></div>"
            f"<div class='cote'><div class='c1'>2 · {esc(m['away'][:12])}</div>"
            f"<div class='c2'>{oo['1x2.away']:.2f}</div></div></div>")

    # bandeau pari
    ev = pred.get("ev_summary")
    pick_html = ""
    if ev:
        if ev.get("verdict") == "NO BET" or not ev.get("top"):
            pick_html = ("<div class='wxpick nobet'><span class='what'>"
                         "&#128683; AUCUN PARI &mdash; cotes justes, on passe"
                         "</span></div>")
        else:
            tt = ev["top"]
            stake = (tt.get("stake_pct", 0) or 0) * 100
            gain = stake * tt["odds"]
            label = market_label(tt["market"], m["home"], m["away"])
            pick_html = (
                f"<div class='wxpick'><span class='what'>&#127919; "
                f"{esc(label)}</span>"
                f"<span class='nums'>@ {tt['odds']} &middot; mise {stake:.1f}% "
                f"&middot; gain {gain:.0f}&euro;/100&euro;</span></div>"
                f"<div class='caveat'>Notre mod&egrave;le: {pct(tt['model_prob'])} "
                f"vs march&eacute; {100/tt['odds']:.0f}% &mdash; &eacute;cart "
                f"souvent d&ucirc; au mod&egrave;le. Exp&eacute;rience, pas conseil.</div>")

    # analyse experte visible
    anl = ""
    if llm.get("llm_used"):
        kf = "".join(f"<li>{esc(k)}</li>" for k in llm.get("key_factors", [])[:4])
        anl = ("<div class='anl'>"
               + (f"<h4>Lecture tactique</h4><div>{esc(llm.get('lecture_tactique',''))}</div>"
                  if llm.get("lecture_tactique") else "")
               + (f"<h4>Joueurs cl&eacute;s</h4><ul>{kf}</ul>" if kf else "")
               + (f"<h4>Facteur X</h4><div>{esc(llm.get('facteur_x',''))}</div>"
                  if llm.get("facteur_x") else "")
               + (("<h4>Trouv&eacute; en ligne</h4><ul>" + "".join(
                      f"<li>{esc(i)}</li>" for i in llm.get("infos_recherche", [])[:4])
                      + "</ul>") if llm.get("infos_recherche") else "")
               + (f"<h4>L'&oelig;il de l'expert (march&eacute;s)</h4>"
                  f"<div>{esc(llm.get('angle_pari',''))}</div>"
                  if llm.get("angle_pari") and llm.get("angle_pari") != "aucun" else "")
               + (f"<div class='verdict'>&#9889; {esc(llm.get('verdict',''))}</div>"
                  if llm.get("verdict") else "")
               + "</div>")

    # H2H
    h2h_html = ""
    head = fs.get("h2h") or {}
    if head.get("played"):
        tot = head["played"]
        h2h_html = (f"<div class='anl'><h4>Face &agrave; face &middot; "
            f"{tot} matchs</h4>"
            f"<div class='h2hline'>"
            f"<div style='width:{head['wins_a']/tot*100:.0f}%;background:#2eb85c'></div>"
            f"<div style='width:{head['draws']/tot*100:.0f}%;background:#7a8499'></div>"
            f"<div style='width:{head['wins_b']/tot*100:.0f}%;background:#d9534f'></div></div>"
            f"<div style='font-size:12px;color:#8d97ad'>{esc(m['home'])} "
            f"{head['wins_a']}V &middot; {head['draws']}N &middot; "
            f"{esc(m['away'])} {head['wins_b']}V &mdash; derniers: "
            + ", ".join(f"{x['date']} {x['score']}" for x in head.get('last_meetings', [])[:4])
            + "</div></div>")

    scorelines = pred.get("top_scorelines") or []
    score_html = ("<div class='scores'>Scores probables: " + ", ".join(
        f"{esc(s['score'])} ({pct(s['prob'])})" for s in scorelines[:3])
        + "</div>" if scorelines else "")

    return f"""<div class="card wx">
<div class="top"><span>{esc(m.get('stage','').replace('_',' '))}</span>
<span class="mono">{esc(cet(m['utc_kickoff']))}</span></div>
<div class="teams2"><div><div class="tname">{esc(m['home'])}</div>
{_badges(fs.get('form_home'))}</div>
<div style="text-align:right"><div class="tname right">{esc(m['away'])}</div>
{_badges(fs.get('form_away'), right=True)}</div></div>
{prob_bar(show, m['home'], m['away'])}
{cotes_html}
{pick_html}
{anl}
{h2h_html}
{score_html}{upd_html}
<div class="stamp mono">frozen {esc(pred['frozen_at_utc'][:16].replace('T',' '))}</div>
</div>"""


def prob_bar(p: dict, home: str, away: str) -> str:
    return f"""<div class="meta" style="margin-top:8px;font-size:11px;
text-transform:uppercase;letter-spacing:.08em">Probabilit&eacute;s du mod&egrave;le
&mdash; pas un conseil de pari</div><div class="bar">
<div class="h" style="flex:{p['home']:.3f}">{pct(p['home'])}</div>
<div class="d" style="flex:{p['draw']:.3f}">{pct(p['draw'])}</div>
<div class="a" style="flex:{p['away']:.3f}">{pct(p['away'])}</div></div>
<div class="legend"><span>{esc(home)}</span><span>draw</span><span>{esc(away)}</span></div>"""


def freeze_target_ms(utc_kickoff: str) -> int | None:
    """Epoch ms of the expected pick release: 20:30 Paris the evening before
    for night matches (KO 21:00-08:00 Paris), kickoff-60min otherwise."""
    try:
        ko = datetime.fromisoformat(utc_kickoff.replace("Z", "+00:00"))
        ko_p = ko.astimezone(PARIS)
        if ko_p.hour >= 21 or ko_p.hour < 8:
            anchor_date = (ko_p.date() if ko_p.hour >= 21
                           else (ko_p - timedelta(days=1)).date())
            from datetime import time as dtime
            target = datetime.combine(anchor_date, dtime(20, 30), tzinfo=PARIS)
        else:
            target = ko - timedelta(minutes=60)
        return int(target.timestamp() * 1000)
    except (ValueError, TypeError):
        return None


def preview_card(fx: dict) -> str:
    import formstats
    p = model.elo_to_probs(fx["home"], fx["away"])
    try:
        _, fdata = formstats.form_summary(fx["home"], fx["away"])
    except Exception:
        fdata = {}
    when = (fx["utc_kickoff"][:10] if fx.get("date_only")
            else cet(fx["utc_kickoff"]))
    ft = None if fx.get("date_only") else freeze_target_ms(fx["utc_kickoff"])
    if ft:
        countdown = (f'<div class="stamp preview mono">&#8987; LE PARI SERA '
                     f'DISPONIBLE DANS <span class="cd" data-freeze="{ft}">'
                     f'&hellip;</span></div>')
    else:
        countdown = ('<div class="stamp preview mono">&#8987; PARI DISPONIBLE '
                     '~1H AVANT LE MATCH</div>')
    return f"""<div class="card wx">
<div class="top"><span>{esc(fx.get('stage','match').replace('_',' '))}</span>
<span class="mono">{esc(when)}</span></div>
<div class="teams2"><div><div class="tname">{esc(fx['home'])}</div>
{_badges(fdata.get('form_home'))}</div>
<div style="text-align:right"><div class="tname right">{esc(fx['away'])}</div>
{_badges(fdata.get('form_away'), right=True)}</div></div>
{prob_bar(p, fx['home'], fx['away'])}
{countdown}</div>"""


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


def golden_boot_section() -> str:
    gb_file = DATA / "golden_boot.json"
    sim_file = DATA / "tournament_sim.json"
    if not (gb_file.exists() and sim_file.exists()):
        return ""
    gb = json.loads(gb_file.read_text())
    sim = json.loads(sim_file.read_text())
    live_file = DATA / "top_scorers.json"
    live_html = ""
    if live_file.exists():
        live = json.loads(live_file.read_text())
        if live:
            lr = "".join(f"<tr><td>{esc(p['player'])}</td>"
                         f"<td>{esc(p['team'])}</td>"
                         f"<td class='num'>{p['goals']}</td>"
                         f"<td class='num'>{p['assists']}</td></tr>"
                         for p in live[:8])
            live_html = ("<table><tr><th>Classement r&eacute;el</th><th>&Eacute;quipe</th>"
                         "<th>Buts</th><th>Passes</th></tr>" + lr +
                         "</table><div class='meta' style='margin-bottom:10px'>"
                         "Classement live des buteurs (API-Football).</div>")
    strikers = gb.get("strikers", {})
    rows = []
    for team, p in sim["probabilities"].items():
        if team in strikers:
            rows.append((strikers[team], team, p["semi"], p["final"]))
    rows.sort(key=lambda r: -r[2])
    body = "".join(
        f"<tr><td>{'&#11088; ' if name in gb.get('our_two', []) else ''}"
        f"{'&#128142; ' if name == gb.get('value_pick') else ''}{esc(name)}</td>"
        f"<td>{esc(team)}</td><td class='num'>{pct(semi)}</td>"
        f"<td class='num'>{pct(fin)}</td></tr>"
        for name, team, semi, fin in rows[:8])
    return ("<h2>Soulier d'or</h2>"
            "<div class='card'>" + live_html + "<table><tr><th>Joueur</th><th>&Eacute;quipe</th>"
            "<th>P(demi)</th><th>P(finale)</th></tr>" + body + "</table>"
            "<div class='meta'>&#11088; nos deux picks &middot; "
            "&#128142; value pick. Pas de mod&egrave;le joueur dans ce pipeline : "
            "le Soulier d'or va presque toujours &agrave; l'attaquant d'une "
            "&eacute;quipe demi-finaliste (6-7 matchs jou&eacute;s) &mdash; ce "
            "tableau croise nos simulations avec le buteur n&deg;1 de chaque "
            "pr&eacute;tendant (&eacute;ditable dans data/golden_boot.json). "
            f"{esc(gb.get('market_favorites_note',''))}</div></div>")


def leaderboard_section() -> str:
    ev_file = DATA / "results" / "evaluation.json"
    if not ev_file.exists():
        return ""
    rep = json.loads(ev_file.read_text())
    names = {"stats": "Elo+Poisson", "news": "+ keyword news",
             "llm": "+ LLM analyst", "players": "+ player form",
             "market": "Market T-60",
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

    schedule = [f for f in load_upcoming_with_times(3)
                if (model.canon(f["home"]), model.canon(f["away"]))
                not in frozen_pairs
                and f.get("status") in (None, "TIMED", "SCHEDULED")]
    schedule.sort(key=lambda f: f["utc_kickoff"])

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

    page = f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>WC26 Prediction Lab</title><style>{CSS}</style></head><body>
<div id="main">
<header><h1>WC26 <span>Prediction Lab</span></h1>
<div class="sub mono">predictions frozen pre-kickoff · updated
{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M')} UTC</div></header>
<details class="card" style="font-size:14px"><summary><b>&#10067; Comment lire cette page (important)</b></summary>
<p style="margin-top:8px"><b>La barre verte = des probabilit&eacute;s, PAS un conseil de pari.</b>
"87%" signifie que le mod&egrave;le estime 87 chances sur 100 que cette &eacute;quipe gagne
&mdash; il lui reste 13% de perdre, et surtout &ccedil;a ne dit rien de la rentabilit&eacute; :
si la cote ne paie que 1.10, parier sur un 87% <i>perd</i> de l'argent &agrave; long terme.</p>
<p style="margin-top:8px"><b>Le seul vrai signal de pari, c'est la ligne &laquo; The pick &raquo;</b>
qui appara&icirc;t au gel du pronostic (~1h avant le match), quand le mod&egrave;le compare
ses probabilit&eacute;s aux cotes r&eacute;elles. La plupart du temps le verdict est
<b>NO BET</b> &mdash; c'est normal et c'est le verdict qui fait &eacute;conomiser de l'argent.
Quand un pick sort, la mise sugg&eacute;r&eacute;e (% de bankroll, Kelly fractionn&eacute;)
est indiqu&eacute;e &mdash; et m&ecirc;me l&agrave;, l'explication la plus probable d'un
&eacute;cart avec les bookmakers reste une erreur de notre mod&egrave;le. Exp&eacute;rience
scientifique, pas conseil financier.</p></details>
<h2>Next matches</h2>{upcoming_html}
{race_section()}
{golden_boot_section()}
{standings_section(groups, finished)}
{track_html}
{past_html}
{leaderboard_section()}
<footer>A measurement experiment, not betting advice. The market is the
benchmark until the leaderboard says otherwise. Git history is the lab
notebook — every prediction's commit predates kickoff.</footer>
</div><script>
function tick(){{document.querySelectorAll(".cd").forEach(function(el){{
var t=parseInt(el.dataset.freeze),d=t-Date.now();
if(isNaN(t))return;
if(d<=0){{el.textContent="QUELQUES MINUTES — actualise la page";return}}
var h=Math.floor(d/36e5),m=Math.floor(d%36e5/6e4),s=Math.floor(d%6e4/1e3);
el.textContent=(h>0?h+"h ":"")+m+"m "+s+"s";}})}}
tick();setInterval(tick,1000);
</script></body></html>"""
    DOCS.mkdir(exist_ok=True)
    out = DOCS / "index.html"
    out.write_text(page)
    return out


if __name__ == "__main__":
    print(f"Dashboard written to {build()}")
