# ============================================================
# PlanC — System Configuration
# ============================================================

# ── Asset Universe ──────────────────────────────────────────
#
# USE_PREDEFINED_ASSETS: When True, the system tracks only the
# tickers listed in PREDEFINED_ASSETS. Set to False to switch
# to a dynamically-built universe (future implementation).
#
USE_PREDEFINED_ASSETS = True

# Predefined asset list, grouped by volatility profile.
# Each entry carries metadata that the analysis engine can use
# to calibrate thresholds and expectations per asset.
#
# Volatility categories:
#   "slow"   — Defensive / low-beta. Gradual, predictable moves.
#   "medium" — Moderate swings. Responds to macro & earnings.
#   "high"   — Fast, large moves in both directions. News-driven.
#
PREDEFINED_ASSETS = [
    # ── Slow / Stable ───────────────────────────────────────
    {
        "ticker":      "JNJ",
        "name":        "Johnson & Johnson",
        "sector":      "Healthcare",
        "volatility":  "slow",
        "notes":       "Defensive blue-chip, consistent dividend grower, beta ~0.6",
    },
    {
        "ticker":      "PG",
        "name":        "Procter & Gamble",
        "sector":      "Consumer Staples",
        "volatility":  "slow",
        "notes":       "Recession-resistant consumer staples giant, low drawdowns",
    },

    # ── Medium Volatility ────────────────────────────────────
    {
        "ticker":      "AAPL",
        "name":        "Apple Inc.",
        "sector":      "Technology",
        "volatility":  "medium",
        "notes":       "Mega-cap with meaningful but orderly swings, beta ~1.2",
    },
    {
        "ticker":      "MSFT",
        "name":        "Microsoft Corporation",
        "sector":      "Technology",
        "volatility":  "medium",
        "notes":       "Steady compounder, cloud + AI tailwinds, manageable swings",
    },

    # ── Highly Volatile ──────────────────────────────────────
    {
        "ticker":      "TSLA",
        "name":        "Tesla Inc.",
        "sector":      "Consumer Discretionary",
        "volatility":  "high",
        "notes":       "News-driven, earnings-surprise-sensitive, beta ~2.0+",
    },
    {
        "ticker":      "MSTR",
        "name":        "MicroStrategy Inc.",
        "sector":      "Technology",
        "volatility":  "high",
        "notes":       "Leveraged Bitcoin proxy; extreme intraday and daily swings",
    },
]

# Convenience lookup: ticker → asset config dict
ASSETS_BY_TICKER = {a["ticker"]: a for a in PREDEFINED_ASSETS}

# Convenience lookup: volatility category → list of tickers
ASSETS_BY_VOLATILITY = {}
for _asset in PREDEFINED_ASSETS:
    ASSETS_BY_VOLATILITY.setdefault(_asset["volatility"], []).append(_asset["ticker"])


# ── Data Source API Keys ─────────────────────────────────────
# Store actual keys in a .env file — never commit them.
# Load with: from dotenv import load_dotenv; load_dotenv()
import os

ALPHA_VANTAGE_API_KEY  = os.getenv("ALPHA_VANTAGE_API_KEY",  "")
FMP_API_KEY            = os.getenv("FMP_API_KEY",            "")
FINNHUB_API_KEY        = os.getenv("FINNHUB_API_KEY",        "")
TWELVE_DATA_API_KEY    = os.getenv("TWELVE_DATA_API_KEY",    "")
POLYGON_API_KEY        = os.getenv("POLYGON_API_KEY",        "")


# ── Analysis Thresholds ──────────────────────────────────────
# Per-volatility RSI and signal sensitivity overrides.
# These give the scoring engine room to treat a slow stock
# differently from a high-volatility one.
#
VOLATILITY_THRESHOLDS = {
    "slow": {
        "rsi_oversold":       35,
        "rsi_overbought":     65,
        "min_signal_score":   0.60,   # higher bar — fewer but cleaner signals
    },
    "medium": {
        "rsi_oversold":       30,
        "rsi_overbought":     70,
        "min_signal_score":   0.55,
    },
    "high": {
        "rsi_oversold":       25,
        "rsi_overbought":     75,
        "min_signal_score":   0.50,   # lower bar — these move fast, act sooner
    },
}


# ── Scheduling ───────────────────────────────────────────────
# How often (in minutes) each data-collection pillar runs.
#
FETCH_INTERVAL_MINUTES = {
    "technical":    15,
    "fundamental":  60 * 24,   # daily
    "institutional": 60 * 24 * 7,  # weekly (13F cadence)
    "sentiment":    30,
}
