# ============================================================
# PlanC — System Configuration
# ============================================================

# ── Asset Universe ──────────────────────────────────────────
#
# USE_PREDEFINED_ASSETS: When True, the system tracks only the
# tickers listed in PREDEFINED_ASSETS. Set to False to switch
# to a dynamically-built universe (future implementation).
# Overridable via env: USE_PREDEFINED_ASSETS=true|false
#
import os

USE_PREDEFINED_ASSETS = os.getenv("USE_PREDEFINED_ASSETS", "true").lower() == "true"

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

ALPHA_VANTAGE_API_KEY  = os.getenv("ALPHA_VANTAGE_API_KEY",  "")
FMP_API_KEY            = os.getenv("FMP_API_KEY",            "")
FINNHUB_API_KEY        = os.getenv("FINNHUB_API_KEY",        "")
TWELVE_DATA_API_KEY    = os.getenv("TWELVE_DATA_API_KEY",    "")
POLYGON_API_KEY        = os.getenv("POLYGON_API_KEY",        "")


# ── Analysis Thresholds ──────────────────────────────────────
# Per-volatility RSI and signal sensitivity overrides.
# These give the scoring engine room to treat a slow stock
# differently from a high-volatility one.
# Edit directly in this file — nested structure is not suitable for env vars.
#
VOLATILITY_THRESHOLDS = {
    "slow": {
        "rsi_oversold":       int(os.getenv("RSI_OVERSOLD_SLOW",   "35")),
        "rsi_overbought":     int(os.getenv("RSI_OVERBOUGHT_SLOW",  "65")),
        "min_signal_score": float(os.getenv("MIN_SIGNAL_SLOW",     "0.60")),
    },
    "medium": {
        "rsi_oversold":       int(os.getenv("RSI_OVERSOLD_MEDIUM",  "30")),
        "rsi_overbought":     int(os.getenv("RSI_OVERBOUGHT_MEDIUM", "70")),
        "min_signal_score": float(os.getenv("MIN_SIGNAL_MEDIUM",   "0.55")),
    },
    "high": {
        "rsi_oversold":       int(os.getenv("RSI_OVERSOLD_HIGH",   "25")),
        "rsi_overbought":     int(os.getenv("RSI_OVERBOUGHT_HIGH",  "75")),
        "min_signal_score": float(os.getenv("MIN_SIGNAL_HIGH",     "0.50")),
    },
}


# ── Stop-Loss Percentages ────────────────────────────────────
# Maximum tolerated loss from entry before a position is closed
# regardless of the signal. Tighter for slow, wider for high-vol.
#
STOP_LOSS_PCT = {
    "slow":   float(os.getenv("STOP_LOSS_SLOW",   "0.05")),  # 5%
    "medium": float(os.getenv("STOP_LOSS_MEDIUM", "0.08")),  # 8%
    "high":   float(os.getenv("STOP_LOSS_HIGH",   "0.12")),  # 12%
}


# ── Signal Component Weights ─────────────────────────────────
# Weights applied when combining multiple scoring pillars.
# Weights are re-normalised at runtime so they do not have to
# sum to 1 — but it is clearer if they do.
# fundamental weight becomes non-zero once FMP_API_KEY is set.
#
COMPONENT_WEIGHTS = {
    "technical":   float(os.getenv("WEIGHT_TECHNICAL",   "1.0")),
    "fundamental": float(os.getenv("WEIGHT_FUNDAMENTAL", "0.0")),
}


# ── Scheduling ───────────────────────────────────────────────
# How often (in minutes) each data-collection pillar runs.
# Overridable individually via env vars.
#
FETCH_INTERVAL_MINUTES = {
    "technical":     int(os.getenv("FETCH_INTERVAL_TECHNICAL",     "15")),
    "fundamental":   int(os.getenv("FETCH_INTERVAL_FUNDAMENTAL",   str(60 * 24))),
    "institutional": int(os.getenv("FETCH_INTERVAL_INSTITUTIONAL", str(60 * 24 * 7))),
    "sentiment":     int(os.getenv("FETCH_INTERVAL_SENTIMENT",     "30")),
}
