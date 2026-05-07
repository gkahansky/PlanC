"""
Financial Modeling Prep (FMP) fundamental data collector.

Fetches quarterly/annual key metrics, financial growth rates, and income
statement data. All results are stored in the `fundamentals` SQLite table.

Free tier: 250 requests/day, 5 years of historical data.
Sign up:   https://financialmodelingprep.com/developer/docs

Metrics collected per period:
  revenue, net_income, eps, eps_growth, revenue_growth,
  gross_margin, operating_margin, pe_ratio, pb_ratio,
  debt_to_equity, free_cash_flow

Usage:
  client = FMPClient()
  df = client.fetch_key_metrics("AAPL", period="quarter", limit=20)
  save_fundamentals("AAPL", df)
"""

import logging

import pandas as pd
import requests
from dotenv import load_dotenv

load_dotenv()
import config

log = logging.getLogger(__name__)

_BASE = "https://financialmodelingprep.com/api/v3"


class FMPClient:

    def __init__(self, api_key: str = None):
        self.api_key = api_key or config.FMP_API_KEY
        if not self.api_key:
            raise ValueError(
                "FMP_API_KEY not set. Copy .env.example → .env and add your key. "
                "Sign up free at financialmodelingprep.com"
            )

    # ── Public ───────────────────────────────────────────────────────────────

    def fetch_key_metrics(
        self, ticker: str, period: str = "quarter", limit: int = 20
    ) -> pd.DataFrame:
        """
        Fetch per-period key metrics (P/E, P/B, EPS, margins, debt/equity).
        period: "quarter" or "annual"
        """
        raw = self._get(f"/key-metrics/{ticker}", {"period": period, "limit": limit})
        if not raw:
            raise ValueError(f"No key-metrics data returned for {ticker}")
        return _parse_key_metrics(raw, period)

    def fetch_financial_growth(
        self, ticker: str, period: str = "quarter", limit: int = 20
    ) -> pd.DataFrame:
        """
        Fetch EPS and revenue growth rates per period.
        period: "quarter" or "annual"
        """
        raw = self._get(f"/financial-growth/{ticker}", {"period": period, "limit": limit})
        if not raw:
            raise ValueError(f"No financial-growth data returned for {ticker}")
        return _parse_growth(raw, period)

    def fetch_income_statement(
        self, ticker: str, period: str = "quarter", limit: int = 20
    ) -> pd.DataFrame:
        """Fetch raw income statement (revenue, net income, EPS, margins)."""
        raw = self._get(f"/income-statement/{ticker}", {"period": period, "limit": limit})
        if not raw:
            raise ValueError(f"No income-statement data returned for {ticker}")
        return _parse_income(raw, period)

    def fetch_combined(
        self, ticker: str, period: str = "quarter", limit: int = 20
    ) -> pd.DataFrame:
        """
        Merge key-metrics + financial-growth into one consolidated DataFrame
        ready for save_fundamentals(). Returns the merged set on common periods.
        """
        metrics = self.fetch_key_metrics(ticker, period, limit)
        growth  = self.fetch_financial_growth(ticker, period, limit)
        income  = self.fetch_income_statement(ticker, period, limit)

        df = metrics.merge(growth, on=["period", "period_type"], how="outer", suffixes=("", "_g"))
        df = df.merge(income,  on=["period", "period_type"], how="outer", suffixes=("", "_i"))

        # Keep only the canonical columns; drop duplicates from merge
        keep = [
            "period", "period_type", "revenue", "net_income", "eps",
            "eps_growth", "revenue_growth", "gross_margin", "operating_margin",
            "pe_ratio", "pb_ratio", "debt_to_equity", "free_cash_flow",
        ]
        existing = [c for c in keep if c in df.columns]
        return df[existing].sort_values("period", ascending=False).reset_index(drop=True)

    # ── Internal ─────────────────────────────────────────────────────────────

    def _get(self, path: str, params: dict = None) -> list:
        p = {"apikey": self.api_key, **(params or {})}
        resp = requests.get(f"{_BASE}{path}", params=p, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        if isinstance(data, dict) and "Error Message" in data:
            raise ValueError(f"FMP API error: {data['Error Message']}")
        return data if isinstance(data, list) else []


# ── Parsers ───────────────────────────────────────────────────────────────────

def _parse_key_metrics(raw: list, period_type: str) -> pd.DataFrame:
    rows = []
    for r in raw:
        rows.append({
            "period":          r.get("date", "")[:10],
            "period_type":     period_type,
            "pe_ratio":        _f(r.get("peRatio")),
            "pb_ratio":        _f(r.get("pbRatio")),
            "debt_to_equity":  _f(r.get("debtToEquity")),
            "free_cash_flow":  _f(r.get("freeCashFlowPerShare")),
            "operating_margin": _f(r.get("operatingProfitMargin")),
        })
    return pd.DataFrame(rows)


def _parse_growth(raw: list, period_type: str) -> pd.DataFrame:
    rows = []
    for r in raw:
        rows.append({
            "period":         r.get("date", "")[:10],
            "period_type":    period_type,
            "eps_growth":     _f(r.get("epsgrowth")),
            "revenue_growth": _f(r.get("revenueGrowth")),
        })
    return pd.DataFrame(rows)


def _parse_income(raw: list, period_type: str) -> pd.DataFrame:
    rows = []
    for r in raw:
        rows.append({
            "period":          r.get("date", "")[:10],
            "period_type":     period_type,
            "revenue":         _f(r.get("revenue")),
            "net_income":      _f(r.get("netIncome")),
            "eps":             _f(r.get("eps")),
            "gross_margin":    _f(r.get("grossProfitRatio")),
            "operating_margin": _f(r.get("operatingIncomeRatio")),
        })
    return pd.DataFrame(rows)


def _f(v) -> float | None:
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None
