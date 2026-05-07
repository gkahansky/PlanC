import pandas as pd


def calculate_all(df: pd.DataFrame) -> pd.DataFrame:
    """
    Add technical indicator columns to an OHLCV DataFrame.
    Requires columns: open, high, low, close, adj_close, volume.
    All calculations use only past data (no lookahead).
    """
    df = df.copy()
    price = df["adj_close"]

    df["rsi"] = _rsi(price, 14)
    df["ema20"] = price.ewm(span=20, adjust=False).mean()
    df["sma50"] = price.rolling(50).mean()
    df["sma200"] = price.rolling(200).mean()

    macd, macd_sig, macd_hist = _macd(price, 12, 26, 9)
    df["macd"] = macd
    df["macd_signal"] = macd_sig
    df["macd_hist"] = macd_hist

    vol_sma = df["volume"].rolling(20).mean()
    df["vol_ratio"] = df["volume"] / vol_sma

    return df


def _rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(com=period - 1, min_periods=period).mean()
    avg_loss = loss.ewm(com=period - 1, min_periods=period).mean()
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def _macd(series: pd.Series, fast: int, slow: int, signal: int):
    ema_fast = series.ewm(span=fast, adjust=False).mean()
    ema_slow = series.ewm(span=slow, adjust=False).mean()
    macd = ema_fast - ema_slow
    sig = macd.ewm(span=signal, adjust=False).mean()
    return macd, sig, macd - sig
