import logging
import time
from datetime import date

import pandas as pd
import requests
from dotenv import load_dotenv

load_dotenv()
import config

log = logging.getLogger(__name__)

_BASE = "https://www.alphavantage.co/query"
_MIN_INTERVAL_SEC = 12  # 5 req/min — safe for free tier (25/day, 500/month)


class AlphaVantageClient:

    def __init__(self, api_key: str = None):
        self.api_key = api_key or config.ALPHA_VANTAGE_API_KEY
        if not self.api_key:
            raise ValueError(
                "ALPHA_VANTAGE_API_KEY not set. Copy .env.example → .env and add your key."
            )
        self._last_req: float = 0.0
        self._day_count: int = 0
        self._day_reset: date = date.today()

    # ── Public ──────────────────────────────────────────────────────────────

    def fetch_daily_full(self, ticker: str) -> pd.DataFrame:
        """Download full daily adjusted history (~20 years) for ticker."""
        data = self._get({
            "function": "TIME_SERIES_DAILY_ADJUSTED",
            "symbol": ticker,
            "outputsize": "full",
            "apikey": self.api_key,
        })
        ts = data.get("Time Series (Daily)")
        if not ts:
            _raise_api_error(ticker, data)
        return _parse_daily(ts)

    def fetch_quote(self, ticker: str) -> dict:
        """Fetch current quote (latest trading day OHLCV + live price)."""
        data = self._get({
            "function": "GLOBAL_QUOTE",
            "symbol": ticker,
            "apikey": self.api_key,
        })
        q = data.get("Global Quote", {})
        if not q or not q.get("05. price"):
            _raise_api_error(ticker, data)
        return {
            "ticker":         ticker,
            "date":           q.get("07. latest trading day", ""),
            "open":           float(q.get("02. open", 0)),
            "high":           float(q.get("03. high", 0)),
            "low":            float(q.get("04. low", 0)),
            "close":          float(q.get("05. price", 0)),
            "adj_close":      float(q.get("05. price", 0)),
            "volume":         float(q.get("06. volume", 0)),
            "previous_close": float(q.get("08. previous close", 0)),
            "change_pct":     q.get("10. change percent", "0%").rstrip("%"),
        }

    # ── Internal ─────────────────────────────────────────────────────────────

    def _get(self, params: dict) -> dict:
        self._throttle()
        resp = requests.get(_BASE, params=params, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        if "Note" in data:
            log.warning("Alpha Vantage rate-limit note: %s", data["Note"])
        if "Information" in data:
            log.warning("Alpha Vantage info: %s", data["Information"])
        self._day_count += 1
        if self._day_count >= 20:
            log.warning("Approaching Alpha Vantage daily limit (%d requests today)", self._day_count)
        return data

    def _throttle(self):
        today = date.today()
        if today != self._day_reset:
            self._day_count = 0
            self._day_reset = today
        wait = _MIN_INTERVAL_SEC - (time.time() - self._last_req)
        if wait > 0:
            time.sleep(wait)
        self._last_req = time.time()


# ── Helpers ───────────────────────────────────────────────────────────────────

def _parse_daily(ts: dict) -> pd.DataFrame:
    rows = [
        {
            "date":      d,
            "open":      float(v["1. open"]),
            "high":      float(v["2. high"]),
            "low":       float(v["3. low"]),
            "close":     float(v["4. close"]),
            "adj_close": float(v["5. adjusted close"]),
            "volume":    float(v["6. volume"]),
        }
        for d, v in ts.items()
    ]
    df = pd.DataFrame(rows)
    df["date"] = pd.to_datetime(df["date"])
    return df.sort_values("date").reset_index(drop=True)


def _raise_api_error(ticker: str, data: dict):
    msg = data.get("Note") or data.get("Information") or str(data)
    raise ValueError(f"Alpha Vantage returned no data for {ticker}: {msg}")
