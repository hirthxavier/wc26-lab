"""Shared configuration. All secrets come from environment variables (GitHub Secrets)."""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
PREDICTIONS_DIR = DATA / "predictions"
RESULTS_DIR = DATA / "results"

FOOTBALL_DATA_KEY = os.environ.get("FOOTBALL_DATA_KEY", "")
ODDS_API_KEY = os.environ.get("ODDS_API_KEY", "")

SMTP_HOST = os.environ.get("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.environ.get("SMTP_PORT", "587"))
SMTP_USER = os.environ.get("SMTP_USER", "")
SMTP_PASS = os.environ.get("SMTP_PASS", "")
EMAIL_TO = os.environ.get("EMAIL_TO", "")

# football-data.org competition code for FIFA World Cup
FD_BASE = "https://api.football-data.org/v4"
WC_COMPETITION = "WC"

# The Odds API
ODDS_BASE = "https://api.the-odds-api.com/v4"
ODDS_SPORT_KEY = "soccer_fifa_world_cup"  # verify exact key at season start
ODDS_REGIONS = "eu"
ODDS_MARKETS = "h2h"

MODEL_VERSION = "0.1.0-elo-poisson"

# Briefing window: fire when kickoff is 45-60 min away (lineups are
# published ~60-75 min before kickoff at World Cups, so they're available).
BRIEFING_WINDOW_MIN = 60
BRIEFING_WINDOW_MIN_LOW = 45
SENT_DIR = DATA / "sent"
