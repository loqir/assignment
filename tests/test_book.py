"""Hand checks for quote direction and the dollar/cross split. No cache."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from src.data import PAIRS, download_prices
from src.pnl import (
    _balances,
    _day_changes,
    _dollar_cross,
    _position_values,
    _split_with_deals,
    build_report,
    position_value,
    usd_per_currency,
)


class QuoteDirection(unittest.TestCase):
    def test_long_eur_profits_when_eurusd_rises(self):
        # 1,000,000 * (1.12 - 1.10)
        self.assertAlmostEqual(position_value(1_000_000, 1.10, 1.12), 20_000)

    def test_short_eur_loses_when_eurusd_rises(self):
        self.assertAlmostEqual(position_value(-1_000_000, 1.10, 1.12), -20_000)

    def test_long_usd_profits_when_usdjpy_rises(self):
        # yen owed: -10,000,000 * 150. Each yen was 1/150 dollars, now 1/155.
        expected = -1_500_000_000 * (1 / 155 - 1 / 150)
        self.assertAlmostEqual(position_value(-1_500_000_000, 1 / 150, 1 / 155), expected)
        self.assertEqual(f"{expected:,.0f}", "322,581")

    def test_short_usd_loses_when_usdjpy_rises(self):
        expected = -(-1_500_000_000 * (1 / 155 - 1 / 150))
        self.assertAlmostEqual(position_value(1_500_000_000, 1 / 150, 1 / 155), expected)
        self.assertLess(expected, 0)

    def test_value_is_zero_when_the_mark_equals_the_entry(self):
        self.assertAlmostEqual(position_value(1_000_000, 1.10, 1.10), 0)
        self.assertAlmostEqual(position_value(-1_500_000_000, 1 / 150, 1 / 150), 0)


class DollarAndCross(unittest.TestCase):
    def test_fill_at_the_close_adds_nothing_that_day(self):
        # dealt at 1.12, the same close. Day P&L, Dollar, and Cross are 0.
        prices = pd.DataFrame({"EURUSD": [1.12, 1.15]}, index=pd.to_datetime(["2026-01-02", "2026-01-05"]))
        book = pd.DataFrame(
            {
                "trade_id": ["T1"],
                "trade_date": pd.to_datetime(["2026-01-02"]),
                "currency_pair": ["EURUSD"],
                "notional_base": [1_000_000.0],
                "entry_price": [1.12],
            }
        )
        rates = usd_per_currency(prices)
        day = _day_changes(_position_values(book, rates))
        split = _dollar_cross(_balances(book, prices.index), rates)
        opened = pd.Timestamp("2026-01-02")
        opened_pnl = day.loc[(day["date"] == opened) & (day["currency_pair"] == "EURUSD"), "day_pnl"].iloc[0]
        self.assertAlmostEqual(opened_pnl, 0)
        self.assertAlmostEqual(split.at[opened, "dollar_pnl_usd"], 0)
        self.assertAlmostEqual(split.at[opened, "cross_pnl_usd"], 0)

    def test_two_currencies_match_the_hand_weights(self):
        # both dealt at the first close. long 10m USDJPY 150 to 155, short 1m EURUSD 1.10 to 1.12.
        prices = pd.DataFrame(
            {"USDJPY": [150.0, 155.0], "EURUSD": [1.10, 1.12]},
            index=pd.to_datetime(["2026-01-02", "2026-01-05"]),
        )
        book = pd.DataFrame(
            {
                "trade_id": ["T1", "T2"],
                "trade_date": pd.to_datetime(["2026-01-02", "2026-01-02"]),
                "currency_pair": ["USDJPY", "EURUSD"],
                "notional_base": [10_000_000.0, -1_000_000.0],
                "entry_price": [150.0, 1.10],
            }
        )
        split = _dollar_cross(_balances(book, prices.index), usd_per_currency(prices))
        day = pd.Timestamp("2026-01-05")
        r_jpy = 150 / 155 - 1
        r_eur = 1.12 / 1.10 - 1
        basket = (r_jpy + r_eur) / 2
        w_jpy = -10_000_000.0
        w_eur = -1_100_000.0
        dollar = (w_jpy + w_eur) * basket
        cross = w_jpy * (r_jpy - basket) + w_eur * (r_eur - basket)
        jpy_pnl = 10_000_000 - 1_500_000_000 / 155
        self.assertAlmostEqual(split.at[day, "dollar_pnl_usd"], dollar)
        self.assertAlmostEqual(split.at[day, "cross_pnl_usd"], cross)
        self.assertAlmostEqual(dollar + cross, jpy_pnl - 20_000)

    def test_a_fill_off_the_close_is_added_to_cross(self):
        # long 10m USDJPY dealt at 140, marked at 150 then 155. The 140-to-150 gap is Cross.
        prices = pd.DataFrame(
            {"USDJPY": [150.0, 155.0]},
            index=pd.to_datetime(["2026-01-02", "2026-01-05"]),
        )
        book = pd.DataFrame(
            {
                "trade_id": ["T1"],
                "trade_date": pd.to_datetime(["2026-01-02"]),
                "currency_pair": ["USDJPY"],
                "notional_base": [10_000_000.0],
                "entry_price": [140.0],
            }
        )
        rates = usd_per_currency(prices)
        split = _split_with_deals(_balances(book, prices.index), rates, book)
        day = _day_changes(_position_values(book, rates))
        opened = pd.Timestamp("2026-01-02")
        opened_pnl = float(day.loc[day["date"] == opened, "day_pnl"].iloc[0])
        gap = position_value(-10_000_000.0 * 140.0, 1 / 140, 1 / 150)
        self.assertAlmostEqual(opened_pnl, gap)
        self.assertAlmostEqual(split.at[opened, "dollar_pnl_usd"], 0)
        self.assertAlmostEqual(split.at[opened, "cross_pnl_usd"], gap)
        later = pd.Timestamp("2026-01-05")
        later_pnl = float(day.loc[day["date"] == later, "day_pnl"].iloc[0])
        self.assertAlmostEqual(split.at[later, "dollar_pnl_usd"] + split.at[later, "cross_pnl_usd"], later_pnl)


class DayRankLeavesOutToday(unittest.TestCase):
    def test_the_marked_day_is_not_counted_against_itself(self):
        # Flat at 1.10, then 1.12. Booked day P&L is 20,000. The replay of today is larger.
        dates = pd.bdate_range("2025-01-02", periods=260)
        prices = pd.DataFrame({"EURUSD": 1.10}, index=dates)
        prices.iloc[-1, 0] = 1.12
        book = pd.DataFrame(
            {
                "trade_id": ["T1"],
                "trade_date": [dates[0]],
                "currency_pair": ["EURUSD"],
                "notional_base": [1_000_000.0],
                "entry_price": [1.00],
            }
        )
        report = build_report(book, prices, dates[-1], dates[0])
        self.assertAlmostEqual(report["day_pnl_usd"], 20_000)
        self.assertEqual(report["day_pnl_rank"], 1)
        self.assertAlmostEqual(report["inception_pnl_usd"], 120_000)
        self.assertAlmostEqual(report["inception_cross_pnl_usd"] + report["inception_dollar_pnl_usd"], 120_000)


class SameDateKeepsTheFile(unittest.TestCase):
    def test_a_reprint_of_the_last_date_is_not_written(self):
        dates = pd.to_datetime(["2026-10-02", "2026-10-05"])
        saved = pd.DataFrame(1.0, index=dates, columns=list(PAIRS))
        saved["EURUSD"] = [1.10, 1.12]
        reprint = saved.copy()
        reprint["EURUSD"] = [1.10, 1.20]
        newer = pd.DataFrame(1.0, index=list(dates) + [pd.Timestamp("2026-10-06")], columns=list(PAIRS))
        newer["EURUSD"] = [1.10, 1.20, 1.21]
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "fx_closes.csv"
            saved.to_csv(path, index_label="date")
            before = path.read_bytes()
            with patch("src.data._fetch_closes", return_value=reprint):
                kept = download_prices(path, only_if_newer=True)
            self.assertEqual(path.read_bytes(), before)
            self.assertAlmostEqual(float(kept.iloc[-1, 0]), 1.12)
            with patch("src.data._fetch_closes", return_value=newer):
                written = download_prices(path, only_if_newer=True)
            self.assertEqual(pd.Timestamp(written.index[-1]), pd.Timestamp("2026-10-06"))
            self.assertAlmostEqual(float(written.iloc[-1, 0]), 1.21)
