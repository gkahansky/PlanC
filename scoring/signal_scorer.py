"""
Signal scoring engine.

Technical component (-6 … +6 raw, normalised 0-1):
  rsi_score   — oversold/overbought position (−2…+2)
  macd_score  — crossover + trend direction  (−2…+2)
  trend_score — price vs SMA50 vs SMA200     (−2…+2)

Fundamental component (−4 … +4 raw, normalised 0-1, optional):
  Requires stored FMP data. Disabled automatically when no FMP key / no data.
  eps_score     — EPS growth quality  (−2…+2)
  margin_score  — operating margin    (−1…+1)
  valuation_score — P/E + debt/equity (−1…+1)

Final score = weighted average of enabled components (weights from config).
BUY/SELL/HOLD threshold applies to the final 0-1 normalised score.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

import pandas as pd

import config


# ── Result type ───────────────────────────────────────────────────────────────

@dataclass
class SignalResult:
    ticker: str
    timestamp: datetime
    price: float
    rsi: float
    macd: float
    macd_signal: float
    sma50: float
    sma200: float
    # Technical sub-scores
    rsi_score: int       # −2 … +2
    macd_score: int      # −2 … +2
    trend_score: int     # −2 … +2
    raw_score: int       # −6 … +6
    tech_norm: float     # 0.0 … 1.0
    # Fundamental sub-score (0 when not available)
    fund_norm: float     # 0.0 … 1.0
    fund_available: bool
    # Combined
    norm_score: float    # 0.0 … 1.0  (weighted combo)
    action: str          # BUY | SELL | HOLD
    volatility_class: str
    buy_threshold: float
    sell_threshold: float
    components: list[str] = field(default_factory=list)


# ── Public API ────────────────────────────────────────────────────────────────

def score_latest(ticker: str, df: pd.DataFrame) -> SignalResult:
    """Score the most recent bar of an indicator-enriched DataFrame."""
    if len(df) < 2:
        raise ValueError(f"{ticker}: need at least 2 rows to detect crossovers")

    vol, thresholds = _get_thresholds(ticker)
    buy_th  = thresholds["min_signal_score"]
    sell_th = 1.0 - buy_th

    last = df.iloc[-1]
    prev = df.iloc[-2]

    rsi_sc   = _score_rsi(last["rsi"], thresholds["rsi_oversold"], thresholds["rsi_overbought"])
    macd_sc  = _score_macd(last["macd"], last["macd_signal"], prev["macd"], prev["macd_signal"])
    trend_sc = _score_trend(last["adj_close"], last["sma50"], last["sma200"])

    raw      = rsi_sc + macd_sc + trend_sc
    tech_norm = (raw + 6) / 12

    # Optional fundamental overlay
    fund_norm, fund_avail = _get_fund_norm(ticker)

    norm, components = _combine(tech_norm, fund_norm, fund_avail)

    action = "HOLD"
    if norm >= buy_th:
        action = "BUY"
    elif norm <= sell_th:
        action = "SELL"

    def _f(v):
        return float(v) if pd.notna(v) else float("nan")

    return SignalResult(
        ticker=ticker,
        timestamp=datetime.utcnow(),
        price=_f(last["adj_close"]),
        rsi=_f(last["rsi"]),
        macd=_f(last["macd"]),
        macd_signal=_f(last["macd_signal"]),
        sma50=_f(last["sma50"]),
        sma200=_f(last["sma200"]),
        rsi_score=rsi_sc,
        macd_score=macd_sc,
        trend_score=trend_sc,
        raw_score=raw,
        tech_norm=round(tech_norm, 4),
        fund_norm=round(fund_norm, 4),
        fund_available=fund_avail,
        norm_score=round(norm, 4),
        action=action,
        volatility_class=vol,
        buy_threshold=buy_th,
        sell_threshold=sell_th,
        components=components,
    )


def score_series(ticker: str, df: pd.DataFrame) -> pd.DataFrame:
    """
    Vectorised scoring of the full DataFrame (for backtesting).
    Returns df with rsi_score, macd_score, trend_score, raw_score,
    tech_norm, norm_score, signal columns.
    No lookahead: each row uses only data available at that bar's close.
    """
    _, thresholds = _get_thresholds(ticker)
    buy_th   = thresholds["min_signal_score"]
    sell_th  = 1.0 - buy_th
    oversold   = thresholds["rsi_oversold"]
    overbought = thresholds["rsi_overbought"]

    df = df.copy()

    # RSI score (vectorised)
    df["rsi_score"] = 0
    df.loc[df["rsi"] <= oversold,             "rsi_score"] =  2
    df.loc[(df["rsi"] > oversold) & (df["rsi"] <= oversold + 10),  "rsi_score"] =  1
    df.loc[df["rsi"] >= overbought,           "rsi_score"] = -2
    df.loc[(df["rsi"] < overbought) & (df["rsi"] >= overbought - 10), "rsi_score"] = -1

    # MACD score (vectorised, crossover detection)
    prev_macd = df["macd"].shift(1)
    prev_sig  = df["macd_signal"].shift(1)
    bull_x = (prev_macd <= prev_sig) & (df["macd"] > df["macd_signal"])
    bear_x = (prev_macd >= prev_sig) & (df["macd"] < df["macd_signal"])
    above  = df["macd"] > df["macd_signal"]
    pos    = df["macd"] > 0

    df["macd_score"] = 0
    df.loc[bull_x,                              "macd_score"] =  2
    df.loc[bear_x,                              "macd_score"] = -2
    df.loc[~bull_x & ~bear_x & above & pos,     "macd_score"] =  1
    df.loc[~bull_x & ~bear_x & ~above & ~pos,   "macd_score"] = -1

    # Trend score (vectorised)
    p, s50, s200 = df["adj_close"], df["sma50"], df["sma200"]
    df["trend_score"] = 0
    df.loc[(p > s50) & (s50 > s200),   "trend_score"] =  2
    df.loc[(p > s50) & (s50 <= s200),  "trend_score"] =  1
    df.loc[(p < s50) & (s50 < s200),   "trend_score"] = -2
    df.loc[(p < s50) & (s50 >= s200),  "trend_score"] = -1

    df["raw_score"]  = df["rsi_score"] + df["macd_score"] + df["trend_score"]
    df["tech_norm"]  = (df["raw_score"] + 6) / 12

    # Fundamental overlay (single value broadcast across all rows)
    fund_norm, fund_avail = _get_fund_norm(ticker)
    df["fund_norm"] = fund_norm

    if fund_avail:
        w_tech, w_fund = _weights()
        df["norm_score"] = w_tech * df["tech_norm"] + w_fund * fund_norm
    else:
        df["norm_score"] = df["tech_norm"]

    df["signal"] = "HOLD"
    df.loc[df["norm_score"] >= buy_th,  "signal"] = "BUY"
    df.loc[df["norm_score"] <= sell_th, "signal"] = "SELL"

    return df


def score_fundamentals_only(ticker: str) -> float:
    """
    Return the fundamental normalised score (0-1) for ticker from stored data.
    Returns 0.5 (neutral) if no fundamental data is available.
    """
    fund_norm, _ = _get_fund_norm(ticker)
    return fund_norm


# ── Helpers ───────────────────────────────────────────────────────────────────

def _get_thresholds(ticker: str):
    asset     = config.ASSETS_BY_TICKER.get(ticker, {})
    vol_class = asset.get("volatility", "medium")
    return vol_class, config.VOLATILITY_THRESHOLDS[vol_class]


def _weights() -> tuple[float, float]:
    w_tech = config.COMPONENT_WEIGHTS.get("technical", 1.0)
    w_fund = config.COMPONENT_WEIGHTS.get("fundamental", 0.0)
    total  = w_tech + w_fund or 1.0
    return w_tech / total, w_fund / total


def _combine(tech_norm: float, fund_norm: float, fund_avail: bool) -> tuple[float, list[str]]:
    if not fund_avail or config.COMPONENT_WEIGHTS.get("fundamental", 0.0) == 0.0:
        return tech_norm, ["technical"]
    w_tech, w_fund = _weights()
    return w_tech * tech_norm + w_fund * fund_norm, ["technical", "fundamental"]


def _get_fund_norm(ticker: str) -> tuple[float, bool]:
    """Load latest fundamentals from DB and score them. Returns (norm_score, available)."""
    if not config.FMP_API_KEY:
        return 0.5, False
    try:
        from data_collection.data_store import get_latest_fundamentals
        rec = get_latest_fundamentals(ticker)
        if not rec:
            return 0.5, False
        return _score_fundamentals_dict(rec), True
    except Exception:
        return 0.5, False


def _score_fundamentals_dict(rec: dict) -> float:
    """Score a fundamentals record dict → 0-1 normalised."""
    raw = 0

    # EPS growth: -2 … +2
    eps_g = rec.get("eps_growth")
    if eps_g is not None:
        if eps_g > 0.20:    raw += 2
        elif eps_g > 0.05:  raw += 1
        elif eps_g < -0.10: raw -= 2
        elif eps_g < 0:     raw -= 1

    # Operating margin: -1 … +1
    op_m = rec.get("operating_margin")
    if op_m is not None:
        if op_m > 0.20:    raw += 1
        elif op_m < 0.05:  raw -= 1

    # P/E ratio: -1 … +1 (lower P/E = better value)
    pe = rec.get("pe_ratio")
    if pe is not None and pe > 0:
        if pe < 15:    raw += 1
        elif pe > 40:  raw -= 1

    # Max raw = +4, min = -4
    return (raw + 4) / 8


def _score_rsi(rsi: float, oversold: int, overbought: int) -> int:
    if pd.isna(rsi):
        return 0
    if rsi <= oversold:
        return 2
    if rsi <= oversold + 10:
        return 1
    if rsi >= overbought:
        return -2
    if rsi >= overbought - 10:
        return -1
    return 0


def _score_macd(macd: float, sig: float, prev_macd: float, prev_sig: float) -> int:
    if any(pd.isna(v) for v in [macd, sig, prev_macd, prev_sig]):
        return 0
    if prev_macd <= prev_sig and macd > sig:
        return 2   # bullish crossover
    if prev_macd >= prev_sig and macd < sig:
        return -2  # bearish crossover
    if macd > sig and macd > 0:
        return 1
    if macd < sig and macd < 0:
        return -1
    return 0


def _score_trend(price: float, sma50: float, sma200: float) -> int:
    if any(pd.isna(v) for v in [price, sma50, sma200]):
        return 0
    if price > sma50 > sma200:
        return 2
    if price > sma50:
        return 1
    if price < sma50 < sma200:
        return -2
    if price < sma50:
        return -1
    return 0
