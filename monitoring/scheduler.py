"""
Live monitor: fetches the latest quote for each ticker on a fixed interval,
merges it into stored history, calculates indicators, scores, persists the
signal to DB, and dispatches alerts via AlertManager.

Data source priority:
  1. Twelve Data  — preferred (800 credits/day free tier)
  2. Alpha Vantage — fallback (25 req/day; set interval wide enough)

The monitor blocks until Ctrl-C.
"""

import logging
from datetime import datetime

import pandas as pd
from apscheduler.schedulers.blocking import BlockingScheduler
from dotenv import load_dotenv

load_dotenv()

import config
from data_collection.data_store import get_ohlcv, init_db, save_signal
from data_collection.indicators import calculate_all
from monitoring.alerter import Alert, AlertManager
from scoring.signal_scorer import score_latest

log = logging.getLogger(__name__)


class LiveMonitor:

    def __init__(
        self,
        tickers: list[str] = None,
        interval_minutes: int = None,
        alerts_only: bool = False,
    ):
        self.tickers      = tickers or [a["ticker"] for a in config.PREDEFINED_ASSETS]
        self.interval     = interval_minutes or config.FETCH_INTERVAL_MINUTES["technical"]
        self.alerts_only  = alerts_only   # suppress HOLD console output when True
        self.alert_mgr    = AlertManager()
        self._client      = None

    # ── Public ───────────────────────────────────────────────────────────────

    def run(self):
        """Block until interrupted. Fires the first tick immediately."""
        init_db()
        scheduler = BlockingScheduler(timezone="UTC")
        scheduler.add_job(
            self._tick,
            trigger="interval",
            minutes=self.interval,
            id="monitor",
            next_run_time=datetime.utcnow(),
        )
        log.info(
            "Live monitor started | tickers=%s | interval=%dm | alerts-only=%s",
            self.tickers, self.interval, self.alerts_only,
        )
        _print_rate_hint(self.interval, len(self.tickers))
        try:
            scheduler.start()
        except (KeyboardInterrupt, SystemExit):
            log.info("Live monitor stopped.")

    # ── Private ──────────────────────────────────────────────────────────────

    def _tick(self):
        now = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
        log.info("── tick %s ─────────────────────────────", now)
        client = self._get_client()
        for ticker in self.tickers:
            try:
                self._check(ticker, client)
            except Exception as exc:
                log.error("%s: %s", ticker, exc)

    def _check(self, ticker: str, client):
        hist = get_ohlcv(ticker)
        if hist.empty:
            log.warning("%s: no historical data — run 'python main.py fetch' first", ticker)
            return

        quote = client.fetch_quote(ticker)

        # Merge live quote as today's bar (update if date already stored)
        today = pd.Timestamp(quote["date"])
        live_row = pd.DataFrame(
            [{
                "open":      quote["open"],
                "high":      quote["high"],
                "low":       quote["low"],
                "close":     quote["close"],
                "adj_close": quote["adj_close"],
                "volume":    quote["volume"],
            }],
            index=[today],
        )
        live_row.index.name = "date"

        if today in hist.index:
            hist.loc[today] = live_row.iloc[0]
        else:
            hist = pd.concat([hist, live_row])

        df = calculate_all(hist)
        if df["rsi"].isna().all():
            log.warning("%s: indicators not ready (insufficient history)", ticker)
            return

        result = score_latest(ticker, df)

        # Persist signal to DB
        try:
            save_signal(
                ticker=ticker,
                date=quote["date"],
                action=result.action,
                norm_score=result.norm_score,
                raw_score=result.raw_score,
                price=result.price,
                rsi=result.rsi,
                macd=result.macd,
                sma50=result.sma50,
                sma200=result.sma200,
            )
        except Exception as exc:
            log.warning("%s: could not save signal: %s", ticker, exc)

        # Dispatch alert (suppress HOLD when alerts_only is set)
        if self.alerts_only and result.action == "HOLD":
            return

        self.alert_mgr.send(Alert(
            ticker=ticker,
            action=result.action,
            price=result.price,
            norm_score=result.norm_score,
            raw_score=result.raw_score,
            rsi=result.rsi,
            macd=result.macd,
            sma50=result.sma50,
            sma200=result.sma200,
            volatility_class=result.volatility_class,
        ))

    def _get_client(self):
        if self._client is None:
            if config.TWELVE_DATA_API_KEY:
                from data_collection.twelve_data import TwelveDataClient
                self._client = TwelveDataClient()
                log.info("Using Twelve Data for live quotes")
            elif config.ALPHA_VANTAGE_API_KEY:
                from data_collection.alpha_vantage import AlphaVantageClient
                self._client = AlphaVantageClient()
                log.info("Using Alpha Vantage for live quotes (free tier: 25 req/day)")
            else:
                raise ValueError(
                    "No API key found. Set TWELVE_DATA_API_KEY or ALPHA_VANTAGE_API_KEY in .env"
                )
        return self._client


def _print_rate_hint(interval_min: int, num_tickers: int):
    cycles    = 24 * 60 // interval_min
    req_day   = cycles * num_tickers
    td_ok     = req_day <= 800
    av_ok     = req_day <= 25
    print(
        f"\n  Rate estimate : {num_tickers} tickers × {cycles} cycles/day = ~{req_day} req/day\n"
        f"  Twelve Data   : 800/day free  → {'OK ✓' if td_ok  else f'OVER — raise --interval to >={num_tickers * 24 * 60 // 800 + 1}m'}\n"
        f"  Alpha Vantage : 25/day free   → {'OK ✓' if av_ok  else f'OVER — raise --interval to >={num_tickers * 24 * 60 // 25 + 1}m'}\n"
    )
