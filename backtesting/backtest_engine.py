"""
Pandas-based backtester — single-ticker and portfolio modes.

Single-ticker strategy (long-only):
  - Enter long at next day's OPEN on BUY signal
  - Exit long  at next day's OPEN on SELL signal
  - Stop-loss: exit intraday at stop price when today's LOW ≤ stop

Portfolio strategy:
  - Equal capital allocation across all tickers
  - Each ticker runs its own independent signal and position
  - Combined equity curve = sum of per-ticker sub-portfolios

Execution lag: signals generated from today's close, executed at
tomorrow's open — no lookahead bias.

Reported metrics:
  total_return_pct, cagr_pct, sharpe_ratio, max_drawdown_pct,
  num_trades, num_stop_losses, win_rate_pct, avg_return_per_trade_pct,
  + buy-and-hold benchmark
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

import config
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
    exit_type: str   # "SIGNAL" | "STOP_LOSS" | "END_OF_DATA"


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
    num_stop_losses: int
    win_rate_pct: float
    avg_return_per_trade_pct: float
    bnh_return_pct: float
    bnh_cagr_pct: float
    trades: list[Trade] = field(default_factory=list)
    portfolio_values: pd.Series = field(default_factory=pd.Series)


@dataclass
class PortfolioBacktestResult:
    tickers: list[str]
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
    total_trades: int
    total_stop_losses: int
    win_rate_pct: float
    bnh_return_pct: float
    bnh_cagr_pct: float
    per_ticker: dict[str, BacktestResult] = field(default_factory=dict)
    portfolio_values: pd.Series = field(default_factory=pd.Series)


# ── Public API ────────────────────────────────────────────────────────────────

def run_backtest(
    ticker: str,
    max_years: int = 15,
    initial_capital: float = 10_000.0,
    stop_loss: bool = True,
) -> BacktestResult:
    """
    Load stored OHLCV, score every bar, simulate the strategy, return metrics.
    Raises ValueError if no data is stored for ticker.
    """
    df = _load_scored(ticker, max_years)
    vol_class = config.ASSETS_BY_TICKER.get(ticker, {}).get("volatility", "medium")
    sl_pct = config.STOP_LOSS_PCT[vol_class] if stop_loss else None
    return _simulate(ticker, df, initial_capital, sl_pct)


def run_portfolio_backtest(
    tickers: list[str] = None,
    max_years: int = 15,
    initial_capital: float = 60_000.0,
    stop_loss: bool = True,
) -> PortfolioBacktestResult:
    """
    Run independent per-ticker backtests, then combine into a portfolio equity curve.
    Capital is allocated equally across all requested tickers.
    """
    tickers = tickers or [a["ticker"] for a in config.PREDEFINED_ASSETS]
    alloc = initial_capital / len(tickers)

    per_ticker: dict[str, BacktestResult] = {}
    failed: list[str] = []

    for ticker in tickers:
        try:
            per_ticker[ticker] = run_backtest(ticker, max_years, alloc, stop_loss)
        except Exception as exc:
            log.error("  %s skipped: %s", ticker, exc)
            failed.append(ticker)

    if not per_ticker:
        raise ValueError("All tickers failed; no portfolio to construct.")

    # Combine equity curves on common dates (outer join, forward-fill gaps)
    combined = pd.concat(
        {t: r.portfolio_values for t, r in per_ticker.items()}, axis=1
    ).ffill().bfill()
    port = combined.sum(axis=1)

    # ── Portfolio metrics ────────────────────────────────────────────────────
    final_value = float(port.iloc[-1])
    total_ret   = (final_value / initial_capital - 1) * 100
    trading_days = len(port)
    years        = trading_days / 252
    cagr = ((final_value / initial_capital) ** (1 / years) - 1) * 100 if years > 0 else 0.0

    daily_ret = port.pct_change().dropna()
    sharpe = (
        float(daily_ret.mean() / daily_ret.std() * np.sqrt(252))
        if daily_ret.std() > 0 else 0.0
    )
    rolling_peak = port.cummax()
    max_dd = float(((port - rolling_peak) / rolling_peak).min() * 100)

    all_trades = [t for r in per_ticker.values() for t in r.trades]
    total_sl   = sum(r.num_stop_losses for r in per_ticker.values())
    completed  = [t for t in all_trades if t.return_pct is not None]
    win_rate   = (sum(1 for t in completed if t.return_pct > 0) / len(completed) * 100) if completed else 0.0

    # Equal-weight BnH benchmark
    bnh_ret  = sum(r.bnh_return_pct  for r in per_ticker.values()) / len(per_ticker)
    bnh_cagr = sum(r.bnh_cagr_pct    for r in per_ticker.values()) / len(per_ticker)

    return PortfolioBacktestResult(
        tickers=list(per_ticker.keys()),
        start_date=str(port.index.min().date()),
        end_date=str(port.index.max().date()),
        trading_days=trading_days,
        years=round(years, 1),
        initial_capital=initial_capital,
        final_value=round(final_value, 2),
        total_return_pct=round(total_ret, 2),
        cagr_pct=round(cagr, 2),
        sharpe_ratio=round(sharpe, 3),
        max_drawdown_pct=round(max_dd, 2),
        total_trades=len(all_trades),
        total_stop_losses=total_sl,
        win_rate_pct=round(win_rate, 2),
        bnh_return_pct=round(bnh_ret, 2),
        bnh_cagr_pct=round(bnh_cagr, 2),
        per_ticker=per_ticker,
        portfolio_values=port,
    )


# ── Simulation ────────────────────────────────────────────────────────────────

def _load_scored(ticker: str, max_years: int) -> pd.DataFrame:
    df = get_ohlcv(ticker)
    if df.empty:
        raise ValueError(
            f"No data for {ticker}. Run 'python main.py fetch --tickers {ticker}' first."
        )
    cutoff = df.index.max() - pd.DateOffset(years=max_years)
    df = df[df.index >= cutoff].copy()
    if len(df) < 250:
        raise ValueError(f"{ticker}: only {len(df)} rows after trim — need at least 250.")
    df = calculate_all(df)
    return score_series(ticker, df)


def _simulate(
    ticker: str,
    df: pd.DataFrame,
    initial_capital: float,
    stop_loss_pct: float | None,
) -> BacktestResult:
    """Event-driven simulation with 1-bar lag and optional stop-loss."""
    df = df.dropna(subset=["sma200", "rsi"]).copy().reset_index()

    vol_class = config.ASSETS_BY_TICKER.get(ticker, {}).get("volatility", "medium")

    cash = initial_capital
    shares = 0.0
    in_position = False
    entry_price = 0.0
    entry_date  = None
    trades: list[Trade] = []
    port_dates:  list[pd.Timestamp] = []
    port_values: list[float] = []
    n = len(df)

    for i in range(n - 1):
        row      = df.iloc[i]
        next_row = df.iloc[i + 1]
        signal   = row["signal"]
        low      = float(row["low"])
        cur_close = float(row["adj_close"])

        # ── Stop-loss check (intraday, before executing next signal) ─────────
        if in_position and stop_loss_pct is not None:
            stop_price = entry_price * (1.0 - stop_loss_pct)
            if low <= stop_price:
                # Assume execution at stop price (worst-case gap: open could be lower,
                # but we cap at stop for simplicity)
                exec_p = min(float(row["open"]), stop_price)
                cash   = shares * exec_p
                ret    = (exec_p - entry_price) / entry_price * 100
                trades.append(Trade(
                    ticker=ticker,
                    entry_date=entry_date,
                    entry_price=entry_price,
                    exit_date=row["date"],
                    exit_price=exec_p,
                    return_pct=round(ret, 3),
                    holding_days=(row["date"] - entry_date).days,
                    exit_type="STOP_LOSS",
                ))
                shares      = 0.0
                in_position = False

        # ── Signal execution (at next day's open) ────────────────────────────
        exec_price = float(next_row["open"])
        if exec_price <= 0:
            pass
        elif not in_position and signal == "BUY":
            shares      = cash / exec_price
            cash        = 0.0
            in_position = True
            entry_price = exec_price
            entry_date  = next_row["date"]
        elif in_position and signal == "SELL":
            cash = shares * exec_price
            ret  = (exec_price - entry_price) / entry_price * 100
            trades.append(Trade(
                ticker=ticker,
                entry_date=entry_date,
                entry_price=entry_price,
                exit_date=next_row["date"],
                exit_price=exec_price,
                return_pct=round(ret, 3),
                holding_days=(next_row["date"] - entry_date).days,
                exit_type="SIGNAL",
            ))
            shares      = 0.0
            in_position = False

        port_dates.append(row["date"])
        port_values.append(cash + shares * cur_close)

    # Close open position at last price
    if in_position and n > 0:
        last       = df.iloc[-1]
        last_price = float(last["adj_close"])
        cash       = shares * last_price
        ret        = (last_price - entry_price) / entry_price * 100
        trades.append(Trade(
            ticker=ticker,
            entry_date=entry_date,
            entry_price=entry_price,
            exit_date=last["date"],
            exit_price=last_price,
            return_pct=round(ret, 3),
            holding_days=(last["date"] - entry_date).days,
            exit_type="END_OF_DATA",
        ))
        if port_values:
            port_values[-1] = cash

    port = pd.Series(port_values, index=port_dates, dtype=float)

    # ── Metrics ──────────────────────────────────────────────────────────────
    final_value  = float(port.iloc[-1]) if not port.empty else initial_capital
    total_ret    = (final_value / initial_capital - 1) * 100
    trading_days = len(port)
    years        = trading_days / 252
    cagr = ((final_value / initial_capital) ** (1 / years) - 1) * 100 if years > 0 else 0.0

    daily_ret = port.pct_change().dropna()
    sharpe = (
        float(daily_ret.mean() / daily_ret.std() * np.sqrt(252))
        if daily_ret.std() > 0 else 0.0
    )
    rolling_peak = port.cummax()
    max_dd = float(((port - rolling_peak) / rolling_peak).min() * 100)

    completed = [t for t in trades if t.return_pct is not None]
    stop_losses = [t for t in completed if t.exit_type == "STOP_LOSS"]
    win_rate = (sum(1 for t in completed if t.return_pct > 0) / len(completed) * 100) if completed else 0.0
    avg_ret  = sum(t.return_pct for t in completed) / len(completed) if completed else 0.0

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
        num_stop_losses=len(stop_losses),
        win_rate_pct=round(win_rate, 2),
        avg_return_per_trade_pct=round(avg_ret, 2),
        bnh_return_pct=round(bnh_ret, 2),
        bnh_cagr_pct=round(bnh_cagr, 2),
        trades=trades,
        portfolio_values=port,
    )
