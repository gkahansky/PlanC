import sqlite3
from datetime import datetime
from pathlib import Path

import pandas as pd

DB_PATH = Path(__file__).parent.parent / "data" / "planc.db"


def _conn():
    DB_PATH.parent.mkdir(exist_ok=True)
    c = sqlite3.connect(DB_PATH)
    c.execute("PRAGMA journal_mode=WAL")
    return c


def init_db():
    with _conn() as c:
        c.executescript("""
            CREATE TABLE IF NOT EXISTS ohlcv_daily (
                ticker    TEXT NOT NULL,
                date      TEXT NOT NULL,
                open      REAL,
                high      REAL,
                low       REAL,
                close     REAL,
                adj_close REAL,
                volume    REAL,
                PRIMARY KEY (ticker, date)
            );
            CREATE TABLE IF NOT EXISTS fetch_log (
                ticker     TEXT NOT NULL,
                source     TEXT NOT NULL,
                fetched_at TEXT NOT NULL,
                rows       INTEGER,
                PRIMARY KEY (ticker, source)
            );
            CREATE TABLE IF NOT EXISTS signals (
                ticker     TEXT NOT NULL,
                date       TEXT NOT NULL,
                action     TEXT NOT NULL,
                norm_score REAL,
                raw_score  INTEGER,
                price      REAL,
                rsi        REAL,
                macd       REAL,
                sma50      REAL,
                sma200     REAL,
                recorded_at TEXT NOT NULL,
                PRIMARY KEY (ticker, date)
            );
            CREATE TABLE IF NOT EXISTS fundamentals (
                ticker          TEXT NOT NULL,
                period          TEXT NOT NULL,
                period_type     TEXT NOT NULL,
                revenue         REAL,
                net_income      REAL,
                eps             REAL,
                eps_growth      REAL,
                revenue_growth  REAL,
                gross_margin    REAL,
                operating_margin REAL,
                pe_ratio        REAL,
                pb_ratio        REAL,
                debt_to_equity  REAL,
                free_cash_flow  REAL,
                fetched_at      TEXT NOT NULL,
                PRIMARY KEY (ticker, period, period_type)
            );
        """)


# ── OHLCV ─────────────────────────────────────────────────────────────────────

def save_ohlcv(ticker: str, df: pd.DataFrame, source: str = "alpha_vantage"):
    """Upsert OHLCV rows. df must have columns: date, open, high, low, close, adj_close, volume."""
    with _conn() as c:
        c.executemany(
            "INSERT OR REPLACE INTO ohlcv_daily "
            "(ticker, date, open, high, low, close, adj_close, volume) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (ticker, str(row.date)[:10], row.open, row.high, row.low,
                 row.close, row.adj_close, row.volume)
                for row in df.itertuples(index=False)
            ],
        )
        c.execute(
            "INSERT OR REPLACE INTO fetch_log (ticker, source, fetched_at, rows) VALUES (?, ?, ?, ?)",
            (ticker, source, datetime.utcnow().isoformat(), len(df)),
        )


def get_ohlcv(ticker: str, start_date: str = None, end_date: str = None) -> pd.DataFrame:
    """Load stored OHLCV for ticker, ascending by date. Returns DatetimeIndex DataFrame."""
    q = "SELECT date, open, high, low, close, adj_close, volume FROM ohlcv_daily WHERE ticker = ?"
    params: list = [ticker]
    if start_date:
        q += " AND date >= ?"
        params.append(start_date)
    if end_date:
        q += " AND date <= ?"
        params.append(end_date)
    q += " ORDER BY date ASC"
    with _conn() as c:
        df = pd.read_sql_query(q, c, params=params, parse_dates=["date"])
    return df.set_index("date")


def get_latest_date(ticker: str) -> str | None:
    with _conn() as c:
        row = c.execute("SELECT MAX(date) FROM ohlcv_daily WHERE ticker = ?", (ticker,)).fetchone()
    return row[0] if row and row[0] else None


def get_stored_tickers() -> list[str]:
    with _conn() as c:
        return [r[0] for r in c.execute("SELECT DISTINCT ticker FROM ohlcv_daily").fetchall()]


# ── Signal history ────────────────────────────────────────────────────────────

def save_signal(ticker: str, date: str, action: str, norm_score: float,
                raw_score: int, price: float, rsi: float, macd: float,
                sma50: float, sma200: float):
    """Upsert the latest signal for a ticker on a given date."""
    with _conn() as c:
        c.execute(
            "INSERT OR REPLACE INTO signals "
            "(ticker, date, action, norm_score, raw_score, price, rsi, macd, sma50, sma200, recorded_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (ticker, date[:10], action, norm_score, raw_score, price, rsi, macd,
             sma50, sma200, datetime.utcnow().isoformat()),
        )


def get_signals(ticker: str, start_date: str = None, end_date: str = None) -> pd.DataFrame:
    """Load signal history for ticker, ascending."""
    q = "SELECT * FROM signals WHERE ticker = ?"
    params: list = [ticker]
    if start_date:
        q += " AND date >= ?"
        params.append(start_date)
    if end_date:
        q += " AND date <= ?"
        params.append(end_date)
    q += " ORDER BY date ASC"
    with _conn() as c:
        return pd.read_sql_query(q, c, params=params, parse_dates=["date"])


def get_last_signal(ticker: str) -> dict | None:
    """Return the most recent signal row for ticker as a dict, or None."""
    with _conn() as c:
        row = c.execute(
            "SELECT * FROM signals WHERE ticker = ? ORDER BY date DESC LIMIT 1", (ticker,)
        ).fetchone()
        if not row:
            return None
        cols = [d[0] for d in c.execute("SELECT * FROM signals LIMIT 0").description]
    return dict(zip(cols, row))


# ── Fundamentals ──────────────────────────────────────────────────────────────

def save_fundamentals(ticker: str, df: pd.DataFrame):
    """Upsert fundamental records. df must have columns matching the fundamentals table."""
    now = datetime.utcnow().isoformat()
    with _conn() as c:
        for row in df.itertuples(index=False):
            c.execute(
                "INSERT OR REPLACE INTO fundamentals "
                "(ticker, period, period_type, revenue, net_income, eps, eps_growth, "
                "revenue_growth, gross_margin, operating_margin, pe_ratio, pb_ratio, "
                "debt_to_equity, free_cash_flow, fetched_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (ticker, row.period, row.period_type,
                 getattr(row, "revenue", None), getattr(row, "net_income", None),
                 getattr(row, "eps", None), getattr(row, "eps_growth", None),
                 getattr(row, "revenue_growth", None), getattr(row, "gross_margin", None),
                 getattr(row, "operating_margin", None), getattr(row, "pe_ratio", None),
                 getattr(row, "pb_ratio", None), getattr(row, "debt_to_equity", None),
                 getattr(row, "free_cash_flow", None), now),
            )


def get_latest_fundamentals(ticker: str) -> dict | None:
    """Return the most recent fundamental record for ticker as a dict, or None."""
    with _conn() as c:
        row = c.execute(
            "SELECT * FROM fundamentals WHERE ticker = ? ORDER BY period DESC LIMIT 1", (ticker,)
        ).fetchone()
        if not row:
            return None
        desc = c.execute("SELECT * FROM fundamentals LIMIT 0").description
        cols = [d[0] for d in desc]
    return dict(zip(cols, row))


def get_fundamentals(ticker: str, limit: int = 20) -> pd.DataFrame:
    """Load up to `limit` fundamental periods for ticker, descending."""
    with _conn() as c:
        return pd.read_sql_query(
            "SELECT * FROM fundamentals WHERE ticker = ? ORDER BY period DESC LIMIT ?",
            c, params=[ticker, limit],
        )
