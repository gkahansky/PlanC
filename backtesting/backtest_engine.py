"""
Pandas-based backtester.

Strategy (long-only, single ticker):
  - Enter long at next day's OPEN when signal == BUY
  - Exit long  at next day's OPEN when signal == SELL
  - Only one position at a time; no leverage; no fractional shares

Execution lag: signals are generated from today's close, executed at
tomorrow's open — no lookahead bias.

Metrics reported:
  total_return_pct, cagr_pct, sharpe_ratio, max_drawdown_pct,
  num_trades, win_rate_pct, avg_return_per_trade_pct
  + buy-and-hold benchmark for comparison
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from data_collection.data_store import get_ohlcv
from data_collection.indicators import calculate_all
from scoring.signal_scorer import score_series

log = logging.getLogger(__name__)


# ── Data classes ──────────────────────────────────────────────────────────────

@dataclass
class Trade:
    ticker: str
    entry_date: pd.Timestamp
    entry_price: float
    exit_date: pd.Timestamp
    exit_price: float
    return_pct: float
    holding_days: int


@dataclass
class BacktestResult:
    ticker: str
    start_date: str
    end_date: str
    trading_days: int
    years: float
    initial_capital: float
    final_value: float
    total_return_pct: float
    cagr_pct: float
    sharpe_ratio: float
    max_drawdown_pct: float
    num_trades: int
    win_rate_pct: float
    avg_return_per_trade_pct: float
    # Buy-and-hold benchmark
    bnh_return_pct: float
    bnh_cagr_pct: float
    trades: list[Trade] = field(default_factory=list)
    portfolio_values: pd.Series = field(default_factory=pd.Series)


# ── Public API ────────────────────────────────────────────────────────────────

def run_backtest(
    ticker: str,
    max_years: int = 15,
    initial_capital: float = 10_000.0,
) -> BacktestResult:
    """
    Load stored OHLCV, score every bar, simulate the strategy, return metrics.
    Raises ValueError if no data is stored for ticker.
    """
    df = get_ohlcv(ticker)
    if df.empty:
        raise ValueError(
            f"No data for {ticker}. Run 'python main.py fetch --tickers {ticker}' first."
        )

    # Trim to max_years
    cutoff = df.index.max() - pd.DateOffset(years=max_years)
    df = df[df.index >= cutoff].copy()
    if len(df) < 250:
        raise ValueError(f"{ticker}: only {len(df)} rows after trim — need at least 250.")

    df = calculate_all(df)
    df = score_series(ticker, df)

    return _simulate(ticker, df, initial_capital)


# ── Simulation ────────────────────────────────────────────────────────────────

def _simulate(ticker: str, df: pd.DataFrame, initial_capital: float) -> BacktestResult:
    """Event-driven simulation with 1-bar signal lag."""
    # Drop rows where SMA200 isn't ready yet (first ~200 bars)
    df = df.dropna(subset=["sma200", "rsi"]).copy()
    df = df.reset_index()  # date becomes a column so we can use integer indexing

    cash = initial_capital
    shares = 0.0
    in_position = False
    entry_price = 0.0
    entry_date = None
    trades: list[Trade] = []
    port_dates: list[pd.Timestamp] = []
    port_values: list[float] = []

    n = len(df)
    for i in range(n - 1):  # -1: need next bar for execution
        row = df.iloc[i]
        next_row = df.iloc[i + 1]
        signal = row["signal"]
        exec_price = float(next_row["open"])  # execute at next day's open

        if not in_position and signal == "BUY" and exec_price > 0:
            shares = cash / exec_price
            cash = 0.0
            in_position = True
            entry_price = exec_price
            entry_date = next_row["date"]

        elif in_position and signal == "SELL" and exec_price > 0:
            cash = shares * exec_price
            ret = (exec_price - entry_price) / entry_price * 100
            trades.append(Trade(
                ticker=ticker,
                entry_date=entry_date,
                entry_price=entry_price,
                exit_date=next_row["date"],
                exit_price=exec_price,
                return_pct=round(ret, 3),
                holding_days=(next_row["date"] - entry_date).days,
            ))
            shares = 0.0
            in_position = False

        pv = cash + shares * float(row["adj_close"])
        port_dates.append(row["date"])
        port_values.append(pv)

    # Close open position at last available price
    if in_position and n > 0:
        last = df.iloc[-1]
        last_price = float(last["adj_close"])
        cash = shares * last_price
        ret = (last_price - entry_price) / entry_price * 100
        trades.append(Trade(
            ticker=ticker,
            entry_date=entry_date,
            entry_price=entry_price,
            exit_date=last["date"],
            exit_price=last_price,
            return_pct=round(ret, 3),
            holding_days=(last["date"] - entry_date).days,
        ))
        port_values[-1] = cash

    port = pd.Series(port_values, index=port_dates, dtype=float)

    # ── Metrics ──────────────────────────────────────────────────────────────
    final_value = float(port.iloc[-1]) if not port.empty else initial_capital
    total_ret = (final_value / initial_capital - 1) * 100
    trading_days = len(port)
    years = trading_days / 252
    cagr = ((final_value / initial_capital) ** (1 / years) - 1) * 100 if years > 0 else 0.0

    daily_ret = port.pct_change().dropna()
    sharpe = (
        float(daily_ret.mean() / daily_ret.std() * np.sqrt(252))
        if daily_ret.std() > 0 else 0.0
    )

    rolling_peak = port.cummax()
    max_dd = float(((port - rolling_peak) / rolling_peak).min() * 100)

    completed = [t for t in trades if t.return_pct is not None]
    win_rate  = (sum(1 for t in completed if t.return_pct > 0) / len(completed) * 100) if completed else 0.0
    avg_ret   = sum(t.return_pct for t in completed) / len(completed) if completed else 0.0

    # ── Buy-and-hold benchmark ───────────────────────────────────────────────
    first_close = float(df.iloc[0]["adj_close"])
    last_close  = float(df.iloc[-1]["adj_close"])
    bnh_ret  = (last_close / first_close - 1) * 100
    bnh_cagr = ((last_close / first_close) ** (1 / years) - 1) * 100 if years > 0 else 0.0

    return BacktestResult(
        ticker=ticker,
        start_date=str(df.iloc[0]["date"].date()),
        end_date=str(df.iloc[-1]["date"].date()),
        trading_days=trading_days,
        years=round(years, 1),
        initial_capital=initial_capital,
        final_value=round(final_value, 2),
        total_return_pct=round(total_ret, 2),
        cagr_pct=round(cagr, 2),
        sharpe_ratio=round(sharpe, 3),
        max_drawdown_pct=round(max_dd, 2),
        num_trades=len(completed),
        win_rate_pct=round(win_rate, 2),
        avg_return_per_trade_pct=round(avg_ret, 2),
        bnh_return_pct=round(bnh_ret, 2),
        bnh_cagr_pct=round(bnh_cagr, 2),
        trades=trades,
        portfolio_values=port,
    )
