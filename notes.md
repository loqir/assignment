# Notes

## Flow

```text
data/portfolio.csv          cache/fx_closes.csv
        \                        /
         \                      /
          src/data.py  (load the two files)
                    |
            start date, end date
                    |
            src/pnl.py  build_report
                    |
                 app.py draws
```

`src/data.py` loads the book and the closes. `build_report` then:

1. Turns each close into USD per currency.
2. Values the two balances. Inception, day, window, Dollar and Cross are written up in the README.
3. VaR: today's foreign-currency dollars times the last 252 moves in USD per unit.
4. Currency balances, built once. The ladder is the end date. The exposure chart runs from the start date.

`app.py` only draws. Headline, position table, currency exposure, exposure over time, P&L history.

## How to read the code

1. `app.py`, from `load_prices` down. Start, End, `build_report`, then the charts.
2. `load_portfolio` and `load_prices` in `src/data.py`.
3. `build_report` in `src/pnl.py`. The calls in the body are the same order as the page.
4. `usd_per_currency`. USD is 1. EUR and AUD use the price. JPY, SGD, CNY, INR, KRW use 1/price. USDJPY on 5 Oct is 1 / 157.675.
5. `position_value`, `_position_values`, `_day_changes`, `_window_pnl`.
6. `_dollar_cross`, `_dealt_pnl`, `_split_with_deals`. Dollar is yesterday's book. If the fill is off the close, that gap goes into Cross.
7. `_dollar_results`, then `historical_var`.
8. `_balances`, `_exposure_table`, `_exposure_path`. `day_usd_return` is just the percent move.

Tests, from this folder. They use made-up prices, not the cache:

```text
.venv\Scripts\python.exe -m unittest discover -s tests -t . -v
```

`tests/test_book.py` covers quote direction, Dollar/Cross, a fill off the close, the day rank, and a same-date Yahoo reprint. `walkthrough.ipynb` runs the same functions on Start 2026-01-02 and End 2026-10-05.

## Book and prices

Book is `data/portfolio.csv`. One row, one open spot trade.

| Field | Meaning |
| --- | --- |
| `trade_id` | Id |
| `trade_date` | Date the position was opened |
| `currency_pair` | Six letters. `USDJPY` means JPY per 1 USD |
| `notional_base` | Signed **base** amount. Positive = long the base, short the quote |
| `entry_price` | Quote per 1 base, the price it was dealt at |

Asia spot vs USD (JPY, CNY, INR, KRW, SGD), plus EURUSD and AUDUSD so both quote directions get checked. In this file the entry is the cached close on `trade_date`.

Loader throws out an unknown pair, a zero notional, or an entry that is not positive. Two fills in one pair show as one row. Entry on that row is the size-weighted average. Net size of zero leaves the entry blank.

Closes live in `cache/fx_closes.csv`. The page reads that file. `download_prices` pulls Yahoo and overwrites it. In the file, EURUSD and AUDUSD are dollars per unit. USDJPY, USDSGD, USDCNY, USDINR, USDKRW are foreign currency per dollar.

## P&L

Each fill is two balances. Same pair, same date, they get added:

- base = `notional_base`
- quote = `-notional_base * entry_price`

USD value = base × USD per base + quote × USD per quote. That is 0 when the mark equals the entry. The 20,000 and 322,581 examples are in the README.

Day P&L is the change from the previous cache close. A pair's first row has no previous close, so that day's P&L is the value itself. If the trade date is in the cache, that row is the trade-date close. If it is not (weekend), it is the next close. A blank first row stays blank. A missing close stays blank. Nothing after the end date is used.

Window P&L is the end value minus the value on the start close. The start close is the baseline, so it is not one of the bars. If the pair's first row is after the start, the window is just the end value. Moving Start past an open date does not drop the trade.



## VaR

The 95% / 252 / 13th-worst setup is in the README.

EURUSD and AUDUSD are already dollars, so the VaR return is the pair's own percent change. USDJPY, USDSGD, USDCNY, USDINR, USDKRW use previous price / price − 1. That is dollars per unit of the foreign currency. It is not the USDJPY quote's own percent change. The USD cash leg is left out.

A missing close kills that day's return and the next day's. Those days are dropped. The window is not pulled earlier to fill the gap. A tie keeps the later date.

Day-P&L rank = 1 + how many of the other days beat it. 1st is the best day. The marked day is left out of that count.

Component VaR is 0 if that currency did not move. Worst-day P&L is signed (a profit is positive). Hedge benefit can come out negative.

## Screen

- Strip: day, window, inception, portfolio exposure, portfolio VaR. Cross and Dollar sit under the three P&L numbers. Grey line under day P&L is the rank, e.g. "19th best of last 252 days". Grey line under VaR is "95%, 13th worst of last 252 days (2026-01-26)". If some returns were dropped, both lines show the shorter count. The line above the strip is "Marked on {date} (Everything in USD)." It goes red when that close is not the End date you picked.
- Position table: one row per pair, not per fill. Side, net base, USD size, average entry, live spot, the three P&L columns, position VaR, component VaR, marginal VaR, worst-day P&L. Sorted by component VaR, largest first. Total row last. VaR date and worst-day date sit above the table. Hedge benefit is in bold under it.
- Currency bars: every currency including USD, sorted by absolute USD value. A short of 10m comes before a long of 8m.
- Currency ladder: same size order, except USD is pulled out and put after the foreign currencies, then Foreign, then Net. `day_usd_return` is the move vs the dollar since the previous close. Positive means it strengthened. USD is 0. Foreign and Net leave that cell blank.
- Exposure over time: start date through end date, not sorted by size. Longs stack up, shorts stack down, in the order the trades were opened. Dollar cash is the bottom of the positive stack. Long foreign currencies sit above it. Shorts are below zero, earliest short nearest the line. Dotted line at zero. Foreign is a line (sum of the non-USD balances), not another band, or those currencies would be counted twice. Net is not on this chart. The stack is both legs, so it is bigger than the gross exposure headline. On 5 Oct the positive stack is about +27.4m, and that includes about +9.9m of dollar cash. The negative stack is about −26.5m. Foreign bars alone are about 44.0m, next to the 43.5m headline. USDJPY shows as 10,000,000 in the headline and about −9,940,130 of yen on the chart, because the chart marks the yen at that day's rate.
- P&L history: day bars and the window P&L line, between the two dates.

Pair sizes on 5 Oct: USDJPY 10,000,000, USDSGD 8,000,000, USDINR 6,000,000, EURUSD 5,602,869, USDCNY 5,000,000, AUDUSD 4,869,565, USDKRW 4,000,000. Sum 43,472,434. Foreign is the non-USD rows added up. Net, including the USD cash, equals inception P&L.

## Other stuff

- Closes are mids.
- No crosses like EURJPY in the book. Cross P&L is the split inside this USD book, not a EURJPY price.
- A trade is in the book when its trade date is on or before the marked close. Start does not add or remove trades. Day, inception, exposure and VaR are the whole book. Start only moves window P&L, the P&L history, and the exposure path.
- Calendars run from the first cache date on or after 2026-01-01 through the last cached close. Here that first date is 2026-01-02. If a day that does not have a close is picked, the page uses the latest close on or before it. VaR and the worst day still look back to 2024. A pair that was not open on the VaR day is still in the VaR, at end date's size.
- Day P&L uses the previous cache row. On a Monday that is Friday, so the weekend is in the number.
- A missing close is not filled in. If the end date itself has no complete close, the book marks on the latest earlier one.

## Run it locally

From this folder:

```text
.venv\Scripts\python.exe -m streamlit run app.py
```

The page reads `cache/fx_closes.csv`. Rebuilding it from Yahoo overwrites the file, so don't run this once the cache is the one you want to keep:

```text
.venv\Scripts\python.exe -c "from src.data import download_prices; download_prices()"
```

## Deploy

Push the repo, including `data/portfolio.csv` and `cache/fx_closes.csv`. On Streamlit Community Cloud the main file is `app.py` and the requirements file is `requirements.txt`.

If the download fails, the page keeps the saved cache and says so. A bar dated today is left out, because that day is still trading. A local run does not download. Set `REFRESH_PRICES` to `1` if some other host should download when it wakes. Paths are relative to this folder, so the page still finds the files when the server starts at the repo root.
