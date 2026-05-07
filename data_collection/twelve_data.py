import logging

import pandas as pd
import requests
from dotenv import load_dotenv

load_dotenv()
import config

log = logging.getLogger(__name__)

_BASE = "https://api.twelvedata.com"


class TwelveDataClient:
    """
    Twelve Data API client.
    Free tier: 800 credits/day, real-time quotes, up to 5000 bars per request.
    Preferred over Alpha Vantage for live monitoring due to higher rate limits.
    """

    def __init__(self, api_key: str = None):
        self.api_key = api_key or config.TWELVE_DATA_API_KEY
        if not self.api_key:
            raise ValueError(
                "TWELVE_DATA_API_KEY not set. Copy .env.example → .env and add your key."
            )

    def fetch_daily_full(self, ticker: str, years: int = 15) -> pd.DataFrame:
        """Fetch daily history for ticker. outputsize capped at 5000 bars (~20y)."""
        outputsize = min(years * 252, 5000)
        resp = requests.get(
            f"{_BASE}/time_series",
            params={
                "symbol":     ticker,
                "interval":   "1day",
                "outputsize": outputsize,
                "apikey":     self.api_key,
            },
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        if data.get("status") == "error":
            raise ValueError(f"Twelve Data error for {ticker}: {data.get('message')}")
        values = data.get("values")
        if not values:
            raise ValueError(f"No time series data returned for {ticker}")
        return _parse_series(values)

    def fetch_quote(self, ticker: str) -> dict:
        """Fetch real-time quote for ticker (1 API credit)."""
        resp = requests.get(
            f"{_BASE}/quote",
            params={"symbol": ticker, "apikey": self.api_key},
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
        if data.get("status") == "error":
            raise ValueError(f"Twelve Data error for {ticker}: {data.get('message')}")
        return {
            "ticker":         ticker,
            "date":           str(data.get("datetime", ""))[:10],
            "open":           float(data.get("open") or 0),
            "high":           float(data.get("high") or 0),
            "low":            float(data.get("low") or 0),
            "close":          float(data.get("close") or 0),
            "adj_close":      float(data.get("close") or 0),
            "volume":         float(data.get("volume") or 0),
            "previous_close": float(data.get("previous_close") or 0),
            "change_pct":     str(data.get("percent_change", "0")),
        }


def _parse_series(values: list) -> pd.DataFrame:
    rows = [
        {
            "date":      v["datetime"],
            "open":      float(v["open"]),
            "high":      float(v["high"]),
            "low":       float(v["low"]),
            "close":     float(v["close"]),
            "adj_close": float(v.get("adjusted_close") or v["close"]),
            "volume":    float(v.get("volume") or 0),
        }
        for v in values
    ]
    df = pd.DataFrame(rows)
    df["date"] = pd.to_datetime(df["date"])
    return df.sort_values("date").reset_index(drop=True)
