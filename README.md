# WC26 Prediction Lab 🧪⚽

An honest, scientific experiment: can a model built on public data (stats, odds,
news sentiment) produce skillful probability estimates for World Cup 2026 matches —
and how does it compare to the betting market's closing line?

**This is a measurement project, not a betting tip service.** Predictions are
frozen pre-kickoff via git commits (tamper-proof lab notebook) and scored after
full time.

## Hypothesis

H1: Our model's probability estimates achieve a lower Brier score than naive baselines.
H0 (expected per the literature): The market's de-margined closing odds outperform our model.

## Pipeline (runs on GitHub Actions, no server needed)

1. **fixtures.py** — pull upcoming matches (football-data.org, free tier)
2. **odds.py** — pull consensus odds from multiple bookmakers (The Odds API, free tier)
3. **news.py** — pull recent headlines per team (RSS / NewsAPI), extract injury &
   sentiment signals
4. **model.py** — Elo + bivariate Poisson baseline, adjusted by news features →
   P(home win / draw / away win)
5. **briefing.py** — compile a pre-match briefing (form, H2H, odds + line movement,
   news flags, our probabilities vs market)
6. **send_email.py** — email the briefing ~1h before kickoff
7. **evaluate.py** — after each match: Brier score, log loss, calibration,
   closing-line comparison. Results accumulate in `data/results/`.

## Setup

1. Get free API keys:
   - https://www.football-data.org/ (fixtures, results, standings)
   - https://the-odds-api.com/ (odds; free tier = 500 req/month, enough if polled smartly)
   - Email: a Gmail app password (SMTP) or https://resend.com free tier
2. Add them as GitHub Secrets: `FOOTBALL_DATA_KEY`, `ODDS_API_KEY`,
   `SMTP_USER`, `SMTP_PASS`, `EMAIL_TO`
3. Enable the two workflows in `.github/workflows/`:
   - `hourly.yml` — checks for matches starting in the next ~75 min, sends briefings
   - `nightly.yml` — refreshes data, updates Elo, scores finished matches

## Scientific guardrails

- Predictions are committed BEFORE kickoff; the commit timestamp is the proof.
- We report Brier/log-loss with bootstrap confidence intervals (N=104 is small).
- We never report "profit" as the headline metric — variance over 104 matches
  dwarfs any plausible edge.
- All data sources and model versions are logged with each prediction.

## Research roadmap (in descending expected value)

Implemented in v0.3:
- ✅ Elo seeded from 49,400 real internationals (1872–present), importance-weighted K
- ✅ Parameters (base_goals, elo_scale, Dixon-Coles rho, home advantage) FITTED
  by walk-forward backtest on 5,835 held-out competitive matches (Brier 0.5020 —
  that number is the preregistered benchmark the tournament must be judged against)
- ✅ Dixon-Coles low-score correction (draws were mispriced under independent Poisson)
- ✅ Host advantage (+100 Elo, fitted) for USA/Canada/Mexico
- ✅ Closing-line contestant in evaluation (5 contestants total)

Not yet implemented — ordered by expected impact, for whoever works on v0.4:
1. **Player-level strength**: aggregate squad market values (Transfermarkt) or
   minutes-weighted club Elo of selected XI; react to LINEUPS quantitatively
   instead of via LLM prose. Biggest known gap vs professional models.
2. **Rest & travel covariates**: days since last match, time zones crossed,
   altitude (relevant: Mexico City). Cheap features, real WC literature behind them.
3. **Hierarchical Bayesian goals model** (PyMC/Stan, Dixon-Coles likelihood with
   time decay) replacing the Elo→goals heuristic; gives honest posterior intervals.
4. **Proper scoring of knockout matches**: current 1X2 refers to 90 minutes;
   model P(advance) separately via ET/penalty branch (~50/50 + slight Elo tilt).
5. **Ensemble & stacking**: logistic blend of stats model + market at T-60 —
   tests whether our signal adds anything ON TOP of the market (the only
   commercially meaningful question).
6. **CLV analysis**: did our T-60 disagreements with the market predict the
   direction of subsequent line movement? Sharper test than outcome Brier on N=104.
7. **Sentiment upgrade**: replace regex with multilingual transformer or LLM
   batch-scoring of full panel; current keyword matcher is English-biased.

## Honest expectations

The closing line is the strongest public predictor of match outcomes. Beating it
consistently is extraordinarily unlikely. The interesting science is in *where*
and *why* our model disagrees with the market, and whether news-derived features
add any measurable signal on top of a stats-only baseline (ablation built in).
