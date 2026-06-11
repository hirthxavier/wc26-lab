"""Build the pre-match briefing email and send it. Entry point `run_hourly()`
is what GitHub Actions calls every hour: it finds matches kicking off within
the window, freezes predictions, and emails the briefing."""
from __future__ import annotations
import json
import smtplib
from email.mime.text import MIMEText
from config import (SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASS, EMAIL_TO,
                    BRIEFING_WINDOW_MIN, BRIEFING_WINDOW_MIN_LOW, SENT_DIR, DATA)
from datetime import datetime, timedelta, time as dtime, timezone
from zoneinfo import ZoneInfo
from fixtures import matches_in_window, get_matches

PARIS = ZoneInfo("Europe/Paris")


def paris(dt_iso: str) -> datetime:
    return datetime.fromisoformat(dt_iso.replace("Z", "+00:00")).astimezone(PARIS)


def fmt_cet(dt_iso: str) -> str:
    return paris(dt_iso).strftime("%d/%m %H:%M") + " (heure de Paris)"


def is_night_match(dt_iso: str) -> bool:
    """Kickoff between 21:00 and 08:00 Paris time."""
    h = paris(dt_iso).hour
    return h >= 21 or h < 8


def freeze_due(m: dict) -> bool:
    """Standard matches: freeze 0-60 min before kickoff.
    Night matches (21:00-08:00 Paris): freeze from 20:30 Paris the evening
    before kickoff, so the pronostic is ready before bedtime. Trade-off
    (documented): official lineups are usually NOT out yet at 20:30."""
    now = datetime.now(timezone.utc)
    ko = datetime.fromisoformat(m["utc_kickoff"].replace("Z", "+00:00"))
    if ko <= now:
        return False
    if is_night_match(m["utc_kickoff"]):
        ko_p = ko.astimezone(PARIS)
        anchor_date = ko_p.date() if ko_p.hour >= 21 else (ko_p - timedelta(days=1)).date()
        anchor = datetime.combine(anchor_date, dtime(20, 30), tzinfo=PARIS)
        return now >= anchor
    return (ko - now) <= timedelta(minutes=BRIEFING_WINDOW_MIN)
from sources import fetch_panel
from lineups import get_lineups
import llm_analyst
import bets
import players
from odds import snapshot, line_movement, consensus_probs
from news import team_news
import model


def build_briefing(match, stats_probs, final_probs, market, nh, na, movement,
                   llm=None, lineups=None, panel=None, markets=None, ev=None,
                   player_form=None) -> str:
    def pct(x): return f"{x*100:.1f}%"
    lines = [
        f"⚽ {match['home']} vs {match['away']} — {match['stage']}",
        f"Coup d'envoi : {fmt_cet(match['utc_kickoff'])}",
        "",
        "— MODEL (Elo+Poisson) —",
        f"  {match['home']}: {pct(stats_probs['home'])}  Draw: {pct(stats_probs['draw'])}  {match['away']}: {pct(stats_probs['away'])}",
        f"  With news adjustment: {pct(final_probs['home'])} / {pct(final_probs['draw'])} / {pct(final_probs['away'])}",
        f"  Elo: {stats_probs['elo_home']} vs {stats_probs['elo_away']}",
    ]
    if market:
        ip = market["implied_probs"]
        lines += ["", "— MARKET (consensus, margin removed) —"]
        lines += [f"  {k}: {pct(v)}" for k, v in ip.items()]
        lines.append(f"  Overround: {market['overround']*100:.1f}%  Books: {market['n_books']}")
    if len(movement) >= 2:
        first, last = movement[0]["implied_probs"], movement[-1]["implied_probs"]
        lines += ["", "— LINE MOVEMENT (where money went) —"]
        for k in first:
            delta = (last[k] - first[k]) * 100
            arrow = "↑" if delta > 0.5 else "↓" if delta < -0.5 else "→"
            lines.append(f"  {k}: {first[k]*100:.1f}% {arrow} {last[k]*100:.1f}%")
    for label, n in ((match['home'], nh), (match['away'], na)):
        lines += ["", f"— NEWS: {label} (sentiment {n['sentiment']:+.2f}) —"]
        for h in n["injury_flags"]:
            lines.append(f"  🏥 {h}")
        for h in n["turmoil_flags"]:
            lines.append(f"  ⚠️ {h}")
        if not n["injury_flags"] and not n["turmoil_flags"]:
            lines.append("  No injury/turmoil flags detected.")
    if is_night_match(match["utc_kickoff"]) and not lineups:
        lines += ["", "ℹ Pronostic gelé à 20h30 (match de nuit) — compos "
                      "officielles pas encore publiées."]
    if player_form:
        lines += ["", "— FORME JOUEURS (ratings récents) —", player_form]
    if lineups:
        lines += ["", "— OFFICIAL LINEUPS —", lineups]
    else:
        lines += ["", "— LINEUPS — not yet published at send time."]
    if llm and llm.get("llm_used"):
        def pct2(x): return f"{x*100:.1f}%"
        lines += ["", f"— LLM ANALYST (confidence: {llm['confidence']}) —",
                  f"  {pct2(llm['home'])} / {pct2(llm['draw'])} / {pct2(llm['away'])}"]
        for kf in llm.get("key_factors", []):
            lines.append(f"  • {kf}")
        if llm.get("rationale"):
            lines.append(f"  {llm['rationale']}")
    if panel:
        lines += ["", f"— PANEL — {len(panel)} headlines from ES/IT/FR/AR/UK/BR sources —"]
        for h in panel[:8]:
            lines.append(f"  [{h['source']}] {h['title']}")
    if markets:
        def pc(x): return f"{x*100:.1f}%"
        fav = max(markets["1x2"], key=markets["1x2"].get)
        fav_name = {"home": match["home"], "draw": "Draw",
                    "away": match["away"]}[fav]
        lines += ["", "— MOST LIKELY OUTCOME —",
                  f"  {fav_name} ({pc(markets['1x2'][fav])})",
                  f"  Tentative exact scores: " + ", ".join(
                      f"{s['score']} ({pc(s['prob'])})"
                      for s in markets["top_scorelines"][:3]),
                  f"  xG: {markets['expected_goals']['home']} - "
                  f"{markets['expected_goals']['away']}   "
                  f"O2.5: {pc(markets['over_under']['over_2.5'])}   "
                  f"BTTS: {pc(markets['btts_yes'])}"]
    if ev:
        if ev["flagged"]:
            top = ev["flagged"][0]
            lines += ["", "★ THE PICK ★",
                      f"  {top['market']} — model {top['model_prob']*100:.0f}% "
                      f"vs odds {top['odds']} (fair: {top['fair_odds']}) "
                      f"-> EV {top['ev']*100:+.1f}%",
                      f"  Mise suggérée: {top.get('stake_pct',0)*100:.1f}% de la "
                      f"bankroll (¼ Kelly, plafond 5%)"]
        else:
            lines += ["", "★ THE PICK: NO BET ★"]
            if ev["best"]:
                bb = ev["best"]
                lines.append(f"  Nothing clears +5%. Closest: {bb['market']} "
                             f"EV {bb['ev']*100:+.1f}%")
        lines.append(f"  ⚠ {ev['caveat']}")
    lines += ["", "Prediction frozen and committed. Scoring after full time.",
              "(Experiment, not betting advice — see README.)"]
    return "\n".join(lines)


def send_email(subject: str, body: str):
    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = subject
    msg["From"] = SMTP_USER
    msg["To"] = EMAIL_TO
    with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as s:
        s.starttls()
        s.login(SMTP_USER, SMTP_PASS)
        s.send_message(msg)


def run_hourly():
    """Runs every 15 min via Actions. Fires once per match when kickoff is
    45-60 min away (lineups published by then). Dedupe via sent markers."""
    upcoming = [m for m in get_matches(days_ahead=2)
                if m["status"] in ("TIMED", "SCHEDULED") and freeze_due(m)]
    if not upcoming:
        print("No matches in window.")
        return
    odds_events = {(e["home"], e["away"]): e for e in _current_odds_events()}
    for match in upcoming:
        if _already_sent(match):
            continue
        lineup_probe = get_lineups(match["match_id"])
        ko = datetime.fromisoformat(match["utc_kickoff"].replace("Z", "+00:00"))
        mins_to_ko = (ko - datetime.now(timezone.utc)).total_seconds() / 60
        if (lineup_probe is None and not is_night_match(match["utc_kickoff"])
                and mins_to_ko > 25):
            print(f"{match['home']}-{match['away']}: compos pas sorties, "
                  f"retry au prochain run ({mins_to_ko:.0f} min avant KO)")
            continue
        nh, na = team_news(match["home"]), team_news(match["away"])
        panel = fetch_panel([match["home"], match["away"]])
        lineup_text = lineup_probe
        stats = model.elo_to_probs(match["home"], match["away"])
        final = model.apply_news(stats, nh, na)
        event = odds_events.get((match["home"], match["away"]))
        market = consensus_probs(event) if event else None
        pform_text, pform_diff = players.player_form_summary(
            match["home"], match["away"], lineup_text)
        llm = llm_analyst.analyze(
            match, stats, panel,
            lineup_text, market.get("implied_probs") if market else None,
            player_form=pform_text or None)
        players_probs = model.apply_players(stats, pform_diff)
        markets = bets.price_markets(match["home"], match["away"])
        # build offered odds dict from consensus avg odds if available
        offered = {}
        if market and event:
            names = {match["home"]: "1x2.home", match["away"]: "1x2.away",
                     "Draw": "1x2.draw"}
            for nm, o in market["avg_odds"].items():
                if nm in names:
                    offered[names[nm]] = o
        ev = bets.ev_analysis(markets, offered) if offered else None
        extra = {"model_players": ({k: round(v, 4) for k, v in
                                    players_probs.items()}
                                   if players_probs else None),
                 "player_form_text": pform_text or None,
                 "top_scorelines": markets["top_scorelines"],
                 "ev_summary": ({"verdict": ev["verdict"],
                                 "top": (ev["flagged"][0] if ev["flagged"]
                                         else None)} if ev else None)}
        model.freeze_prediction(match, stats, final, market or {}, nh, na,
                                llm_result=llm, lineups=lineup_text, extra=extra)
        movement = line_movement(match["home"], match["away"])
        body = build_briefing(match, stats, final, market, nh, na, movement,
                              llm=llm, lineups=lineup_text, panel=panel,
                              markets=markets, ev=ev,
                              player_form=pform_text or None)
        (DATA / "briefings").mkdir(parents=True, exist_ok=True)
        (DATA / "briefings" / f"{match['match_id']}.txt").write_text(body)
        if SMTP_USER and EMAIL_TO:
            send_email(f"WC26 briefing: {match['home']} vs {match['away']}", body)
        else:
            print("Email secrets not set — briefing saved to dashboard only.")
        _mark_sent(match)
        print(f"Sent briefing for {match['home']} vs {match['away']}")


def run_lineup_updates():
    """For matches frozen WITHOUT lineups (night matches): once the official
    XI is published, send a timestamped UPDATE. The original frozen
    prediction is never modified — this is an amendment, not a revision."""
    from config import PREDICTIONS_DIR
    import players
    now = datetime.now(timezone.utc)
    for f in PREDICTIONS_DIR.glob("*.json"):
        if f.name.endswith("_update.json"):
            continue
        try:
            pred = json.loads(f.read_text())
        except json.JSONDecodeError:
            continue
        m = pred.get("match", {})
        ko = datetime.fromisoformat(m["utc_kickoff"].replace("Z", "+00:00"))
        upd_marker = SENT_DIR / f"{m['match_id']}.updated"
        if (pred.get("lineups_available") or upd_marker.exists()
                or ko <= now or ko - now > timedelta(hours=14)):
            continue
        lineup_text = get_lineups(m["match_id"])
        if lineup_text is None:
            continue  # retry next run (every 15 min)
        names = [n.strip() for part in lineup_text.split("XI:")[1:]
                 for n in part.split("\n")[0].split(",")]
        deltas = []
        for team in (m["home"], m["away"]):
            d = players.lineup_delta(team, names)
            if d.get("delta") is not None:
                deltas.append(f"{team}: delta forme du 11 {d['delta']:+.2f}"
                              + (f" — habituels absents: {', '.join(d['missing_regulars'])}"
                                 if d['missing_regulars'] else ""))
        body = "\n".join([
            f"⚽ UPDATE COMPOS — {m['home']} vs {m['away']}",
            f"Coup d'envoi : {fmt_cet(m['utc_kickoff'])}",
            "",
            "Le pronostic gelé reste inchangé (intégrité de l'expérience).",
            "Compos officielles désormais publiées :",
            "", lineup_text, ""] + deltas)
        upd = {"published_at_utc": now.isoformat(), "lineups": lineup_text,
               "lineup_deltas": deltas}
        (PREDICTIONS_DIR / f"{m['match_id']}_update.json").write_text(
            json.dumps(upd, indent=2))
        if SMTP_USER and EMAIL_TO:
            send_email(f"UPDATE compos: {m['home']} vs {m['away']}", body)
        SENT_DIR.mkdir(parents=True, exist_ok=True)
        upd_marker.write_text("1")
        print(f"Lineup update envoyé: {m['home']} vs {m['away']}")


def _already_sent(match) -> bool:
    return (SENT_DIR / f"{match['match_id']}.sent").exists()


def _mark_sent(match):
    SENT_DIR.mkdir(parents=True, exist_ok=True)
    (SENT_DIR / f"{match['match_id']}.sent").write_text("1")


def _current_odds_events():
    try:
        return snapshot() and __import__("json").loads(
            (__import__("config").DATA / "odds_snapshots.json").read_text())[-50:]
    except Exception as e:
        print(f"Odds fetch failed: {e}")
        return []


if __name__ == "__main__":
    run_hourly()
    run_lineup_updates()
