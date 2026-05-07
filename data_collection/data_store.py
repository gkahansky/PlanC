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
        """)


def save_ohlcv(ticker: str, df: pd.DataFrame, source: str = "alpha_vantage"):
    """Upsert OHLCV rows for ticker. df must have columns: date, open, high, low, close, adj_close, volume."""
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
    """Load stored OHLCV for ticker, sorted ascending. Returns DataFrame indexed by date."""
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
