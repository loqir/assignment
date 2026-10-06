"""Pair map, portfolio file, and the daily close cache."""

from pathlib import Path

import pandas as pd
import yfinance as yf

# pair -> (base, quote). Price is quote currency per 1 base.
PAIRS = {
    "EURUSD": ("EUR", "USD"),
    "AUDUSD": ("AUD", "USD"),
    "USDJPY": ("USD", "JPY"),
    "USDSGD": ("USD", "SGD"),
    "USDCNY": ("USD", "CNY"),
    "USDINR": ("USD", "INR"),
    "USDKRW": ("USD", "KRW"),
}

ROOT = Path(__file__).resolve().parent.parent
PORTFOLIO_PATH = ROOT / "data" / "portfolio.csv"
CACHE_PATH = ROOT / "cache" / "fx_closes.csv"


def load_portfolio(path=PORTFOLIO_PATH):
    book = pd.read_csv(path, parse_dates=["trade_date"])
    book["trade_date"] = book["trade_date"].dt.normalize()
    book["currency_pair"] = book["currency_pair"].str.upper()
    for row in book.itertuples(index=False):
        if row.currency_pair not in PAIRS:
            raise ValueError(f"Unknown pair: {row.currency_pair}")
        if row.notional_base == 0 or row.entry_price <= 0:
            raise ValueError("notional_base must be non-zero and entry_price must be positive")
    return book


def load_prices(path=CACHE_PATH):
    prices = pd.read_csv(path, parse_dates=["date"], index_col="date")
    prices = prices.sort_index()
    prices.index = prices.index.normalize()
    prices = prices[list(PAIRS)]
    for pair in prices.columns:
        prices[pair] = prices[pair].where(prices[pair] > 0)
    return prices


# Yahoo's name for each pair. Used by download_prices.
YAHOO = {
    "EURUSD": "EURUSD=X",
    "AUDUSD": "AUDUSD=X",
    "USDJPY": "JPY=X",
    "USDSGD": "SGD=X",
    "USDCNY": "CNY=X",
    "USDINR": "INR=X",
    "USDKRW": "KRW=X",
}

def download_prices(path=CACHE_PATH, only_if_newer=False):
    # Overwrites the cache. only_if_newer keeps the file when Yahoo's last date is already in it.
    close = _fetch_closes()
    if only_if_newer and not _has_newer_date(close, path):
        return load_prices(path)
    _check_against_cache(close, path)
    path.parent.mkdir(parents=True, exist_ok=True)
    close.to_csv(path, index_label="date")
    return close


def _fetch_closes():
    # Yahoo's daily closes. Does not write the file.
    tickers = []
    yahoo_to_pair = {}
    for pair in PAIRS:
        ticker = YAHOO[pair]
        tickers.append(ticker)
        yahoo_to_pair[ticker] = pair
    raw = yf.download(
        tickers,
        start="2024-01-01",
        interval="1d",
        auto_adjust=False,
        progress=False,
        threads=False,
    )
    close = raw["Close"].rename(columns=yahoo_to_pair)[list(PAIRS)]
    close.index = _plain_dates(close.index)
    close = close.sort_index()
    close = close.reset_index()
    date_column = close.columns[0]
    close = close.drop_duplicates(date_column, keep="last")
    close = close.set_index(date_column)
    for pair in close.columns:
        close[pair] = close[pair].where(close[pair] > 0)
    return close


def _has_newer_date(close, path):
    # True when Yahoo's last date is after the cache, or the cache is missing.
    if not path.exists() or len(close) == 0:
        return True
    saved = pd.read_csv(path, parse_dates=["date"], index_col="date")
    if len(saved) == 0:
        return True
    return pd.Timestamp(close.index[-1]) > pd.Timestamp(saved.index[-1])


def _check_against_cache(close, path):
    if not path.exists():
        return
    saved = pd.read_csv(path, parse_dates=["date"], index_col="date")
    for pair in close.columns:
        if pair not in saved.columns:
            continue
        old_prices = saved[pair].dropna()
        new_prices = close[pair].dropna()
        if len(old_prices) == 0 or len(new_prices) == 0:
            continue
        old_close = float(old_prices.iloc[-1])
        new_close = float(new_prices.iloc[-1])
        if old_close <= 0:
            continue
        ratio = new_close / old_close
        if ratio < 0.5 or ratio > 2:
            raise RuntimeError(
                f"{pair} last close {new_close:.4f} vs cached {old_close:.4f}. File not written."
            )


def _plain_dates(index):
    dates = pd.to_datetime(index)
    if dates.tz is not None:
        dates = dates.tz_convert("UTC").tz_localize(None)
    return dates.normalize()
