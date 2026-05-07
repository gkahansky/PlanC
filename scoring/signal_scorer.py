"""
Signal scoring engine.

Each ticker's latest indicators are mapped to a composite score
on a 0.0 – 1.0 scale (0.5 = neutral). Config thresholds per volatility
class determine where BUY / SELL boundaries sit.

Score components (each –2 … +2):
  rsi_score   — oversold/overbought position
  macd_score  — crossover + trend direction
  trend_score — price vs SMA50 vs SMA200

Raw total: –6 … +6  →  normalized: (raw + 6) / 12  →  0.0 … 1.0
"""

from dataclasses import dataclass
from datetime import datetime

import pandas as pd

import config


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
    rsi_score: int       # –2 … +2
    macd_score: int      # –2 … +2
    trend_score: int     # –2 … +2
    raw_score: int       # –6 … +6
    norm_score: float    # 0.0 … 1.0
    action: str          # BUY | SELL | HOLD
    volatility_class: str
    buy_threshold: float
    sell_threshold: float


def score_latest(ticker: str, df: pd.DataFrame) -> SignalResult:
    """Score the most recent row of an indicator-enriched DataFrame."""
    if len(df) < 2:
        raise ValueError(f"{ticker}: need at least 2 rows to detect crossovers")

    vol, thresholds = _get_thresholds(ticker)
    buy_th = thresholds["min_signal_score"]
    sell_th = 1.0 - buy_th

    last = df.iloc[-1]
    prev = df.iloc[-2]

    rsi_sc    = _score_rsi(last["rsi"], thresholds["rsi_oversold"], thresholds["rsi_overbought"])
    macd_sc   = _score_macd(last["macd"], last["macd_signal"], prev["macd"], prev["macd_signal"])
    trend_sc  = _score_trend(last["adj_close"], last["sma50"], last["sma200"])

    raw  = rsi_sc + macd_sc + trend_sc
    norm = (raw + 6) / 12

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
        norm_score=round(norm, 4),
        action=action,
        volatility_class=vol,
        buy_threshold=buy_th,
        sell_threshold=sell_th,
    )


def score_series(ticker: str, df: pd.DataFrame) -> pd.DataFrame:
    """
    Vectorised scoring for the full DataFrame (used in backtesting).
    Returns df with columns: rsi_score, macd_score, trend_score,
    raw_score, norm_score, signal (BUY/SELL/HOLD).
    No lookahead: each row uses only data available at that bar's close.
    """
    _, thresholds = _get_thresholds(ticker)
    buy_th  = thresholds["min_signal_score"]
    sell_th = 1.0 - buy_th
    oversold   = thresholds["rsi_oversold"]
    overbought = thresholds["rsi_overbought"]

    df = df.copy()

    # RSI score (vectorised)
    df["rsi_score"] = 0
    df.loc[df["rsi"] <= oversold,          "rsi_score"] =  2
    df.loc[(df["rsi"] > oversold) & (df["rsi"] <= oversold + 10),  "rsi_score"] =  1
    df.loc[df["rsi"] >= overbought,        "rsi_score"] = -2
    df.loc[(df["rsi"] < overbought) & (df["rsi"] >= overbought - 10), "rsi_score"] = -1

    # MACD score (vectorised crossover detection)
    prev_macd = df["macd"].shift(1)
    prev_sig  = df["macd_signal"].shift(1)
    bull_x = (prev_macd <= prev_sig) & (df["macd"] > df["macd_signal"])
    bear_x = (prev_macd >= prev_sig) & (df["macd"] < df["macd_signal"])
    above  = df["macd"] > df["macd_signal"]
    pos    = df["macd"] > 0

    df["macd_score"] = 0
    df.loc[bull_x,                         "macd_score"] =  2
    df.loc[bear_x,                         "macd_score"] = -2
    df.loc[~bull_x & ~bear_x & above & pos, "macd_score"] =  1
    df.loc[~bull_x & ~bear_x & ~above & ~pos, "macd_score"] = -1

    # Trend score (vectorised)
    p, s50, s200 = df["adj_close"], df["sma50"], df["sma200"]
    df["trend_score"] = 0
    df.loc[(p > s50) & (s50 > s200),  "trend_score"] =  2
    df.loc[(p > s50) & (s50 <= s200), "trend_score"] =  1
    df.loc[(p < s50) & (s50 < s200),  "trend_score"] = -2
    df.loc[(p < s50) & (s50 >= s200), "trend_score"] = -1

    df["raw_score"]  = df["rsi_score"] + df["macd_score"] + df["trend_score"]
    df["norm_score"] = (df["raw_score"] + 6) / 12

    df["signal"] = "HOLD"
    df.loc[df["norm_score"] >= buy_th,  "signal"] = "BUY"
    df.loc[df["norm_score"] <= sell_th, "signal"] = "SELL"

    return df


# ── Helpers ───────────────────────────────────────────────────────────────────

def _get_thresholds(ticker: str):
    asset      = config.ASSETS_BY_TICKER.get(ticker, {})
    vol_class  = asset.get("volatility", "medium")
    thresholds = config.VOLATILITY_THRESHOLDS[vol_class]
    return vol_class, thresholds


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
