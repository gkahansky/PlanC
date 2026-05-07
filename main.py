#!/usr/bin/env python3
"""
PlanC — CLI entry point.

Commands
--------
  fetch             Download OHLCV data (--mode full | update)
  fetch-fundamentals Download FMP fundamental data
  backtest          Per-ticker strategy backtest (up to 15y, with stop-loss)
  portfolio         All-ticker portfolio backtest (equal allocation)
  monitor           Start 24/7 live monitoring with buy/sell alerts
  status            Print current signals from stored data
  signals           Print stored signal history for a ticker

Examples
--------
  python main.py fetch                              # full history, all tickers
  python main.py fetch --mode update                # incremental — last 100 bars only
  python main.py fetch --tickers AAPL,MSFT --source twelve_data
  python main.py fetch-fundamentals
  python main.py backtest --years 10 --trades
  python main.py backtest --no-stop-loss            # disable stop-loss
  python main.py portfolio --capital 60000
  python main.py monitor --interval 15
  python main.py monitor --tickers AAPL,TSLA --alerts-only
  python main.py status
  python main.py signals --tickers AAPL --days 30
"""

import argparse
import logging
import sys

from dotenv import load_dotenv

load_dotenv()

import config
from data_collection.data_store import (
    get_ohlcv, get_signals, init_db, save_ohlcv, get_latest_date
)
from data_collection.indicators import calculate_all
from scoring.signal_scorer import score_latest

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s — %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("planc")


# ── Helpers ───────────────────────────────────────────────────────────────────

def _tickers(arg: str | None) -> list[str]:
    if arg:
        return [t.strip().upper() for t in arg.split(",") if t.strip()]
    return [a["ticker"] for a in config.PREDEFINED_ASSETS]


def _build_client(source: str):
    if source == "twelve_data":
        from data_collection.twelve_data import TwelveDataClient
        return TwelveDataClient(), "twelve_data"
    from data_collection.alpha_vantage import AlphaVantageClient
    return AlphaVantageClient(), "alpha_vantage"


# ── Commands ──────────────────────────────────────────────────────────────────

def cmd_fetch(args):
    """Download and store OHLCV. --mode update fetches only the last ~100 bars."""
    tickers = _tickers(args.tickers)
    client, source_name = _build_client(args.source)
    init_db()

    mode = getattr(args, "mode", "full")
    log.info("Fetching %d ticker(s) via %s [mode=%s] …", len(tickers), args.source, mode)

    for ticker in tickers:
        latest = get_latest_date(ticker)
        if mode == "update" and latest:
            log.info("  → %s  (stored up to %s, fetching recent bars)", ticker, latest)
        else:
            log.info("  → %s  (full history)", ticker)

        try:
            if mode == "update" and latest:
                df = _fetch_compact(client, ticker)
            else:
                df = client.fetch_daily_full(ticker)

            save_ohlcv(ticker, df, source=source_name)
            log.info(
                "     saved %d rows  (%s → %s)",
                len(df),
                str(df["date"].min().date()),
                str(df["date"].max().date()),
            )
        except Exception as exc:
            log.error("     FAILED %s: %s", ticker, exc)

    log.info("Fetch complete.")


def _fetch_compact(client, ticker: str):
    """Fetch recent bars only. Falls back to full fetch for Twelve Data."""
    if hasattr(client, "api_key") and "alpha" in type(client).__module__:
        # Alpha Vantage supports compact outputsize natively
        import requests
        params = {
            "function": "TIME_SERIES_DAILY_ADJUSTED",
            "symbol":   ticker,
            "outputsize": "compact",  # last ~100 bars
            "apikey":   client.api_key,
        }
        client._throttle()
        resp = requests.get("https://www.alphavantage.co/query", params=params, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        ts = data.get("Time Series (Daily)")
        if not ts:
            raise ValueError(f"No compact data for {ticker}: {data}")
        from data_collection.alpha_vantage import _parse_daily
        return _parse_daily(ts)
    else:
        # Twelve Data: request last 100 bars via outputsize param
        return client.fetch_daily_full(ticker, years=1)


def cmd_fetch_fundamentals(args):
    """Download FMP fundamental data for all (or specified) tickers."""
    from data_collection.fundamental_analyzer import FMPClient
    from data_collection.data_store import save_fundamentals

    tickers = _tickers(args.tickers)
    init_db()

    try:
        client = FMPClient()
    except ValueError as e:
        log.error("%s", e)
        sys.exit(1)

    period = getattr(args, "period", "quarter")
    log.info("Fetching %s fundamentals for %d ticker(s) …", period, len(tickers))

    for ticker in tickers:
        log.info("  → %s", ticker)
        try:
            df = client.fetch_combined(ticker, period=period)
            save_fundamentals(ticker, df)
            log.info("     saved %d periods", len(df))
        except Exception as exc:
            log.error("     FAILED %s: %s", ticker, exc)


def cmd_backtest(args):
    """Per-ticker strategy backtest with stop-loss and buy-and-hold comparison."""
    from backtesting.backtest_engine import run_backtest

    tickers    = _tickers(args.tickers)
    use_sl     = not args.no_stop_loss
    init_db()

    results = []
    for ticker in tickers:
        log.info("Backtesting %s (max %dy, $%.0f, stop-loss=%s) …",
                 ticker, args.years, args.capital, "on" if use_sl else "off")
        try:
            r = run_backtest(ticker, max_years=args.years,
                             initial_capital=args.capital, stop_loss=use_sl)
            results.append(r)
        except Exception as exc:
            log.error("  FAILED %s: %s", ticker, exc)

    if not results:
        print("No results to show.")
        return

    W = 108
    print()
    print("=" * W)
    print(f"{'BACKTEST RESULTS  (stop-loss=' + ('on' if use_sl else 'off') + ')':^{W}}")
    print("=" * W)
    hdr = (
        f"{'Ticker':6}  {'Period':23}  {'Yrs':4}  "
        f"{'Ret%':>8}  {'CAGR%':>7}  {'Shrp':>6}  {'MaxDD%':>7}  "
        f"{'Trd':>4}  {'SL':>3}  {'Win%':>6}  {'AvgTrd%':>8}  "
        f"{'BnH Ret%':>9}  {'BnH CAGR':>9}"
    )
    print(hdr)
    print("-" * W)
    for r in results:
        period = f"{r.start_date} – {r.end_date}"
        print(
            f"{r.ticker:6}  {period:23}  {r.years:4.1f}  "
            f"{r.total_return_pct:+8.1f}  {r.cagr_pct:+7.2f}  "
            f"{r.sharpe_ratio:6.3f}  {r.max_drawdown_pct:7.1f}  "
            f"{r.num_trades:4}  {r.num_stop_losses:3}  {r.win_rate_pct:6.1f}  "
            f"{r.avg_return_per_trade_pct:+8.2f}  "
            f"{r.bnh_return_pct:+9.1f}  {r.bnh_cagr_pct:+9.2f}"
        )
    print("=" * W)
    print(
        "  SL=stop-loss exits | Ret%=total return | CAGR%=annualised | "
        "Shrp=Sharpe | MaxDD%=max drawdown | BnH=buy-and-hold"
    )

    if args.trades:
        for r in results:
            if not r.trades:
                continue
            print(f"\nTrade log — {r.ticker}:")
            print(f"  {'Entry':12}  {'Exit':12}  {'Entry $':>9}  {'Exit $':>9}  "
                  f"{'Ret%':>7}  {'Days':>5}  {'Type':10}")
            print(f"  {'-'*75}")
            for t in r.trades:
                print(
                    f"  {str(t.entry_date.date()):12}  {str(t.exit_date.date()):12}  "
                    f"{t.entry_price:>9.2f}  {t.exit_price:>9.2f}  "
                    f"{t.return_pct:>+7.2f}  {t.holding_days:>5}  {t.exit_type}"
                )

    if args.export:
        import csv, pathlib
        out = pathlib.Path(args.export)
        with out.open("w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["ticker", "entry_date", "exit_date", "entry_price", "exit_price",
                        "return_pct", "holding_days", "exit_type"])
            for r in results:
                for t in r.trades:
                    w.writerow([t.ticker, t.entry_date.date(), t.exit_date.date(),
                                 t.entry_price, t.exit_price, t.return_pct,
                                 t.holding_days, t.exit_type])
        log.info("Trade log exported → %s", out)


def cmd_portfolio(args):
    """Equal-allocation portfolio backtest across all (or specified) tickers."""
    from backtesting.backtest_engine import run_portfolio_backtest

    tickers = _tickers(args.tickers)
    use_sl  = not args.no_stop_loss
    init_db()

    log.info("Portfolio backtest — %d tickers, $%.0f total, stop-loss=%s",
             len(tickers), args.capital, "on" if use_sl else "off")
    try:
        r = run_portfolio_backtest(tickers, max_years=args.years,
                                   initial_capital=args.capital, stop_loss=use_sl)
    except Exception as exc:
        log.error("Portfolio backtest failed: %s", exc)
        return

    alloc = args.capital / len(r.tickers)
    W = 108
    print()
    print("=" * W)
    print(f"{'PORTFOLIO BACKTEST RESULTS':^{W}}")
    print("=" * W)
    print(f"  Period     : {r.start_date} → {r.end_date}  ({r.years}y)")
    print(f"  Capital    : ${r.initial_capital:,.0f} total  (${alloc:,.0f} per ticker)")
    print(f"  Tickers    : {', '.join(r.tickers)}")
    print(f"  Stop-loss  : {'enabled' if use_sl else 'disabled'}")
    print()
    print(f"  {'STRATEGY':30}  {'BUY-AND-HOLD BENCHMARK':30}")
    print(f"  {'─'*30}  {'─'*30}")
    print(f"  Total return  : {r.total_return_pct:+8.1f}%   Total return  : {r.bnh_return_pct:+8.1f}%")
    print(f"  CAGR          : {r.cagr_pct:+8.2f}%   CAGR          : {r.bnh_cagr_pct:+8.2f}%")
    print(f"  Sharpe ratio  : {r.sharpe_ratio:8.3f}    ")
    print(f"  Max drawdown  : {r.max_drawdown_pct:8.1f}%   ")
    print(f"  Trades        : {r.total_trades:8d}    (stop-losses: {r.total_stop_losses})")
    print(f"  Win rate      : {r.win_rate_pct:8.1f}%   ")
    print(f"  Final value   : ${r.final_value:>12,.2f}")
    print()
    print("  Per-ticker breakdown:")
    print(f"  {'Ticker':6}  {'Alloc $':>9}  {'Final $':>10}  {'Ret%':>8}  "
          f"{'CAGR%':>7}  {'Shrp':>6}  {'MaxDD%':>7}  {'Trd':>4}  {'SL':>3}  {'Win%':>6}")
    print(f"  {'-'*90}")
    for t, sub in r.per_ticker.items():
        print(
            f"  {t:6}  {alloc:>9,.0f}  {sub.final_value:>10,.2f}  "
            f"{sub.total_return_pct:>+8.1f}  {sub.cagr_pct:>+7.2f}  "
            f"{sub.sharpe_ratio:>6.3f}  {sub.max_drawdown_pct:>7.1f}  "
            f"{sub.num_trades:>4}  {sub.num_stop_losses:>3}  {sub.win_rate_pct:>6.1f}"
        )
    print("=" * W)


def cmd_monitor(args):
    """Start 24/7 live monitoring. Blocks until Ctrl-C."""
    from monitoring.scheduler import LiveMonitor
    tickers    = _tickers(args.tickers)
    alerts_only = getattr(args, "alerts_only", False)
    monitor    = LiveMonitor(tickers=tickers, interval_minutes=args.interval,
                             alerts_only=alerts_only)
    monitor.run()


def cmd_status(args):
    """Print current signals computed from the most-recent stored data."""
    tickers = _tickers(args.tickers)
    init_db()

    W = 90
    print()
    print("=" * W)
    print(f"{'CURRENT SIGNALS  (from stored data)':^{W}}")
    print("=" * W)
    hdr = (
        f"{'Ticker':6}  {'Action':5}  {'Score':6}  {'Raw':4}  "
        f"{'RSI':6}  {'MACD':9}  {'SMA50':9}  {'SMA200':9}  {'Price':>10}"
    )
    print(hdr)
    print("-" * W)

    for ticker in tickers:
        df = get_ohlcv(ticker)
        if df.empty:
            print(f"{ticker:6}  {'NO DATA':5}  — run 'python main.py fetch' first")
            continue
        df = calculate_all(df)
        try:
            r = score_latest(ticker, df)
            action_fmt = (
                f"\033[92m{r.action}\033[0m" if r.action == "BUY" else
                f"\033[91m{r.action}\033[0m" if r.action == "SELL" else r.action
            )
            print(
                f"{r.ticker:6}  {action_fmt:5}  {r.norm_score:6.2f}  {r.raw_score:+4}  "
                f"{r.rsi:6.1f}  {r.macd:9.3f}  "
                f"{r.sma50:9.2f}  {r.sma200:9.2f}  ${r.price:>9.2f}"
            )
        except Exception as exc:
            print(f"{ticker:6}  ERROR: {exc}")

    print("=" * W)
    print()


def cmd_signals(args):
    """Print stored signal history for one or more tickers."""
    from datetime import datetime, timedelta
    tickers = _tickers(args.tickers)
    init_db()

    days = getattr(args, "days", 30)
    since = (datetime.utcnow() - timedelta(days=days)).strftime("%Y-%m-%d")

    for ticker in tickers:
        df = get_signals(ticker, start_date=since)
        if df.empty:
            print(f"{ticker}: no signal history (run 'monitor' to start recording)")
            continue
        print(f"\nSignal history — {ticker} (last {days}d):")
        print(f"  {'Date':12}  {'Action':5}  {'Score':6}  {'Raw':4}  {'RSI':6}  {'Price':>10}")
        print(f"  {'-'*55}")
        for _, row in df.iterrows():
            c = "\033[92m" if row["action"] == "BUY" else ("\033[91m" if row["action"] == "SELL" else "")
            r = "\033[0m"
            print(
                f"  {str(row['date'].date()):12}  {c}{row['action']:5}{r}  "
                f"{row['norm_score']:6.2f}  {int(row['raw_score']):+4}  "
                f"{row['rsi']:6.1f}  ${row['price']:>9.2f}"
            )
    print()


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        prog="planc",
        description="PlanC — Automated investment signal analysis",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--log-level", default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # fetch
    p = sub.add_parser("fetch", help="Download OHLCV data")
    p.add_argument("--tickers")
    p.add_argument("--source", choices=["alpha_vantage", "twelve_data"], default="alpha_vantage")
    p.add_argument("--mode",   choices=["full", "update"], default="full",
                   help="full=entire history | update=last ~100 bars (incremental)")
    p.set_defaults(func=cmd_fetch)

    # fetch-fundamentals
    p = sub.add_parser("fetch-fundamentals", help="Download FMP fundamental data")
    p.add_argument("--tickers")
    p.add_argument("--period", choices=["quarter", "annual"], default="quarter")
    p.set_defaults(func=cmd_fetch_fundamentals)

    # backtest
    p = sub.add_parser("backtest", help="Per-ticker strategy backtest")
    p.add_argument("--tickers")
    p.add_argument("--years",         type=int,   default=15)
    p.add_argument("--capital",       type=float, default=10_000.)
    p.add_argument("--no-stop-loss",  action="store_true", help="Disable stop-loss exits")
    p.add_argument("--trades",        action="store_true", help="Print individual trade log")
    p.add_argument("--export",        metavar="FILE.csv",  help="Export trade log to CSV")
    p.set_defaults(func=cmd_backtest)

    # portfolio
    p = sub.add_parser("portfolio", help="Equal-allocation portfolio backtest")
    p.add_argument("--tickers")
    p.add_argument("--years",         type=int,   default=15)
    p.add_argument("--capital",       type=float, default=60_000.,
                   help="Total portfolio capital (split equally, default: 60000)")
    p.add_argument("--no-stop-loss",  action="store_true")
    p.set_defaults(func=cmd_portfolio)

    # monitor
    p = sub.add_parser("monitor", help="Start 24/7 live monitoring with alerts")
    p.add_argument("--tickers")
    p.add_argument("--interval",     type=int, default=None)
    p.add_argument("--alerts-only",  action="store_true",
                   help="Only print BUY/SELL alerts, suppress HOLD output")
    p.set_defaults(func=cmd_monitor)

    # status
    p = sub.add_parser("status", help="Show current signals from stored data")
    p.add_argument("--tickers")
    p.set_defaults(func=cmd_status)

    # signals
    p = sub.add_parser("signals", help="Show stored signal history")
    p.add_argument("--tickers")
    p.add_argument("--days", type=int, default=30, help="How many days back (default: 30)")
    p.set_defaults(func=cmd_signals)

    args = parser.parse_args()
    logging.getLogger().setLevel(args.log_level)

    try:
        args.func(args)
    except KeyboardInterrupt:
        sys.exit(0)


if __name__ == "__main__":
    main()
