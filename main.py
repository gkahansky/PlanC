#!/usr/bin/env python3
"""
PlanC — CLI entry point.

Commands
--------
  fetch     Download historical OHLCV data (run once, then incrementally)
  backtest  Run strategy backtest on stored data (up to 15y)
  monitor   Start 24/7 live monitoring with buy/sell alerts
  status    Print current signals from most-recent stored data

Examples
--------
  python main.py fetch
  python main.py fetch --tickers AAPL,MSFT --source twelve_data
  python main.py backtest --years 10 --trades
  python main.py backtest --tickers TSLA --capital 5000
  python main.py monitor --interval 15
  python main.py monitor --tickers AAPL,TSLA --interval 30
  python main.py status
"""

import argparse
import logging
import sys

from dotenv import load_dotenv

load_dotenv()

import config
from data_collection.data_store import get_ohlcv, init_db, save_ohlcv
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
    """Download and store historical OHLCV for all (or specified) tickers."""
    tickers = _tickers(args.tickers)
    client, source_name = _build_client(args.source)
    init_db()

    log.info("Fetching %d ticker(s) via %s …", len(tickers), args.source)
    for ticker in tickers:
        log.info("  → %s", ticker)
        try:
            df = client.fetch_daily_full(ticker)
            save_ohlcv(ticker, df, source=source_name)
            log.info(
                "     saved %d rows  (%s → %s)",
                len(df),
                str(df["date"].min().date()),
                str(df["date"].max().date()),
            )
        except Exception as exc:
            log.error("     FAILED: %s", exc)

    log.info("Fetch complete.")


def cmd_backtest(args):
    """Run backtest for all (or specified) tickers and print a summary table."""
    from backtesting.backtest_engine import run_backtest

    tickers = _tickers(args.tickers)
    init_db()

    results = []
    for ticker in tickers:
        log.info("Backtesting %s (max %dy, $%.0f) …", ticker, args.years, args.capital)
        try:
            r = run_backtest(ticker, max_years=args.years, initial_capital=args.capital)
            results.append(r)
        except Exception as exc:
            log.error("  FAILED %s: %s", ticker, exc)

    if not results:
        print("No results to show.")
        return

    # ── Summary table ─────────────────────────────────────────────────────────
    W = 100
    print()
    print("=" * W)
    print(f"{'BACKTEST RESULTS':^{W}}")
    print("=" * W)
    hdr = (
        f"{'Ticker':6}  {'Period':23}  {'Yrs':4}  "
        f"{'Ret%':>8}  {'CAGR%':>7}  {'Shrp':>6}  {'MaxDD%':>7}  "
        f"{'Trd':>4}  {'Win%':>6}  {'AvgTrd%':>8}  "
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
            f"{r.num_trades:4}  {r.win_rate_pct:6.1f}  "
            f"{r.avg_return_per_trade_pct:+8.2f}  "
            f"{r.bnh_return_pct:+9.1f}  {r.bnh_cagr_pct:+9.2f}"
        )
    print("=" * W)
    print(
        "  Columns: Ret%=total return | CAGR%=annualised | Shrp=Sharpe ratio | "
        "MaxDD%=max drawdown\n"
        "           Trd=trades | Win%=win rate | AvgTrd%=avg return/trade | "
        "BnH=buy-and-hold benchmark"
    )

    # ── Optional trade log ────────────────────────────────────────────────────
    if args.trades:
        for r in results:
            if not r.trades:
                continue
            print(f"\nTrade log — {r.ticker}:")
            print(f"  {'Entry':12}  {'Exit':12}  {'Entry $':>9}  {'Exit $':>9}  {'Ret%':>7}  {'Days':>5}")
            print(f"  {'-'*65}")
            for t in r.trades:
                print(
                    f"  {str(t.entry_date.date()):12}  {str(t.exit_date.date()):12}  "
                    f"{t.entry_price:>9.2f}  {t.exit_price:>9.2f}  "
                    f"{t.return_pct:>+7.2f}  {t.holding_days:>5}"
                )


def cmd_monitor(args):
    """Start 24/7 live monitoring. Blocks until Ctrl-C."""
    from monitoring.scheduler import LiveMonitor
    tickers = _tickers(args.tickers)
    monitor = LiveMonitor(tickers=tickers, interval_minutes=args.interval)
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
            action_fmt = f"\033[92m{r.action}\033[0m" if r.action == "BUY" else (
                         f"\033[91m{r.action}\033[0m" if r.action == "SELL" else r.action)
            print(
                f"{r.ticker:6}  {action_fmt:5}  {r.norm_score:6.2f}  {r.raw_score:+4}  "
                f"{r.rsi:6.1f}  {r.macd:9.3f}  "
                f"{r.sma50:9.2f}  {r.sma200:9.2f}  ${r.price:>9.2f}"
            )
        except Exception as exc:
            print(f"{ticker:6}  ERROR: {exc}")

    print("=" * W)
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
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging verbosity (default: INFO)",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # fetch
    p = sub.add_parser("fetch", help="Download historical OHLCV data")
    p.add_argument("--tickers", help="Comma-separated tickers (default: all predefined)")
    p.add_argument(
        "--source",
        choices=["alpha_vantage", "twelve_data"],
        default="alpha_vantage",
        help="Data source (default: alpha_vantage)",
    )
    p.set_defaults(func=cmd_fetch)

    # backtest
    p = sub.add_parser("backtest", help="Run strategy backtest on stored data")
    p.add_argument("--tickers", help="Comma-separated tickers (default: all predefined)")
    p.add_argument("--years",   type=int,   default=15,      help="Max years of history (default: 15)")
    p.add_argument("--capital", type=float, default=10_000., help="Starting capital (default: 10000)")
    p.add_argument("--trades",  action="store_true",         help="Print individual trade log")
    p.set_defaults(func=cmd_backtest)

    # monitor
    p = sub.add_parser("monitor", help="Start 24/7 live monitoring with buy/sell alerts")
    p.add_argument("--tickers",  help="Comma-separated tickers (default: all predefined)")
    p.add_argument("--interval", type=int, default=None,
                   help="Check interval in minutes (default: from config, typically 15)")
    p.set_defaults(func=cmd_monitor)

    # status
    p = sub.add_parser("status", help="Show current signals from stored data")
    p.add_argument("--tickers", help="Comma-separated tickers (default: all predefined)")
    p.set_defaults(func=cmd_status)

    args = parser.parse_args()
    logging.getLogger().setLevel(args.log_level)

    try:
        args.func(args)
    except KeyboardInterrupt:
        sys.exit(0)


if __name__ == "__main__":
    main()
