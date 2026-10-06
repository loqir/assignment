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

`src/data.py` reads the book and the close cache.

`build_report` keeps trades opened on or before the end date, then:

1. Turns each close into USD per currency. USD is 1. EUR and AUD use the price. JPY, SGD, CNY, INR, and KRW use 1/price.
2. Values the two fixed balances. That value is inception P&L. Day P&L is the change from the previous close. Window P&L is the end value minus the start value. Each of those three is split into Cross P&L and Dollar P&L.
3. Builds historical VaR from a different series. Today's foreign-currency exposure is scaled by the last 252 changes in USD per unit. A return that cannot be computed is left out. Portfolio VaR is the 5% worst loss of the days that remain, the 13th worst when all 252 are there. The day-P&L rank uses those same results.
4. Builds the currency balances once. The ladder is the end date. The exposure chart is the path from the start date.

`app.py` then draws, in order: the headline, the position table, currency exposure, currency exposure over time, and P&L history.

## How to read the code

Read these in order. Each step is one function and one number on the page. The drawing code in `app.py` can wait until the numbers are clear.

1. `app.py`, from `load_prices` to the end. It reads the two files, takes Start and End, calls `build_report`, and draws the report. There is no P&L formula in this file. A hosted run checks Yahoo when the server wakes and saves a new date only.
2. `load_portfolio` and `load_prices` in `src/data.py`. One row of the book, and one row of closes.
3. `build_report` in `src/pnl.py`. Read the calls in the body from top to bottom. That order is the order of the screen. Then read the functions below, one at a time.
4. `usd_per_currency`. USD is 1. EUR and AUD use the price. JPY, SGD, CNY, INR, and KRW use 1/price. Check USDJPY on 5 Oct: 1 / 157.675.
5. `position_value`, then `_position_values`, `_day_changes`, and `_window_pnl`. These are Inception, Day, and Window. `position_value` is the foreign amount times the change in its dollar price.
6. `_dollar_cross`. Cross plus Dollar equals the three P&L figures. The average gives each open foreign currency one vote.
7. `_dollar_results`, then `historical_var`. Portfolio VaR, the component column, marginal VaR, and the worst day. Marginal VaR divides by the foreign-currency leg.
8. `_balances`, `_exposure_table`, then `_exposure_path`. The currency table, the Net row, and the chart titled Currency exposure over time. `day_usd_return` is the percent move only.

`tests/test_book.py` checks steps 5 and 6 on made-up prices. It does not use the cache. From this folder:

```text
.venv\Scripts\python.exe -m unittest discover -s tests -t . -v
```

`walkthrough.ipynb` runs the same functions on Start 2026-01-02 and End 2026-10-05, and checks the page figures.

## Methodology

### Portfolio

The book is a CSV, `data/portfolio.csv`, not a database. Each row is one open spot trade:

| Field | Meaning |
| --- | --- |
| `trade_id` | Unique id |
| `trade_date` | Date the position was opened |
| `currency_pair` | Six letters, market convention. `USDJPY` means JPY per 1 USD |
| `notional_base` | Signed amount of **base** currency. Positive = long the base and short the quote |
| `entry_price` | Quote currency per 1 base, the price the trade was dealt |

The book is Asia-heavy spot versus USD (JPY, CNY, INR, KRW, SGD), plus EURUSD and AUDUSD so both quote directions are in the P&L check. In this sample file each entry price is the cached close on `trade_date`, so the deal price and the mark come from the same series.

The loader rejects an unknown pair, a zero notional, or a non-positive entry price. Two fills in one pair show one row. The entry on that row is the size-weighted average of the dealt prices. A net size of zero leaves the entry blank.

### Prices

Daily closes are in `cache/fx_closes.csv`. The page reads that file. `download_prices` rebuilds it from Yahoo Finance and overwrites the file. EURUSD and AUDUSD are dollars per unit. USDJPY, USDSGD, USDCNY, USDINR, and USDKRW are the foreign currency per dollar.

### USD P&L

Each fill adds two currency balances to its pair. Fills in the same pair are summed:

- base balance = `notional_base`
- quote balance = `-notional_base * entry_price`

Every pair in the book has USD on one side. A close becomes a USD-per-currency rate (USD itself is 1):

- `EURUSD` at 1.10 means 1 EUR = 1.10 USD
- `USDJPY` at 150 means 1 JPY = 1/150 USD

USD value = base balance × USD per base + quote balance × USD per quote.

At the entry price, that value is zero. Two checks, opposite quote directions:

- Long 1,000,000 EUR at 1.10, marked at 1.12. Value = `1,000,000 × 1.12 − 1,100,000 = +20,000` USD. EURUSD up, long EUR, profit.
- Long 10,000,000 USD at 150, marked at 155. Value = `10,000,000 − 1,500,000,000 / 155 ≈ +322,581` USD. USDJPY up, long USD, profit.

Inception P&L is the USD value of the two balances. It is zero when the market price equals the entry price, so it is P&L versus the dealt price. In the sample book the entry price is the trade-date close, so this is also the move since that close.

The balances do not earn interest. Carry, the rate differential for holding the currencies overnight, is part of what an FX position makes over months, especially in INR and KRW. The closes contain no interest rate, so day, window, and inception P&L are the spot move only. They are not the full FX result.

Day P&L is the change in that USD value from the previous cache close. The pair's first row has no previous close, so that day's P&L is the value itself. That row is the trade-date close when that date is in the cache, and the next close when it is not. A blank first row stays blank. In the sample book the entry price is the trade-date close, so that day's P&L is zero. Later days are close to close. Dates follow the cache calendar. A missing close is left blank. No price after the end date is used.

Window P&L is the USD value on the end date minus the USD value on the start date. A pair whose first row is after the start contributes its end value. Positions opened before the window stay on the book.

Day, window, and inception P&L are each split into Cross P&L and Dollar P&L. The two add back to the figure.

Dollar P&L is the part of the day that would have happened if every foreign currency already open had moved by the same percent against the dollar. That percent is a simple average. Each of those currencies has one vote, a large position and a small one alike. Dollar P&L is yesterday's unmatched foreign position times that average. On 5 Oct 2026 the average was about +0.21% and Dollar P&L is −19,019. Cross P&L is the rest of the day's 79,979, so +98,998. It is the P&L from the currencies moving by different amounts. KRW rose about 1.25% while the others were close to flat, and that difference is most of the Cross. Fills in this file are dealt at the close, so a new balance adds nothing that day. A fill dealt off the close puts that difference in Cross. With only one currency open there is no second move to compare, so Cross P&L is zero.

Giving larger positions a bigger vote would pull the average toward those positions. The gaps around the average would then cancel, Cross P&L would be zero every day, and the whole result would be labelled Dollar P&L. A currency with a zero balance the day before is left out of the average. A missing close on an open currency blanks that day. The window and inception split stay blank if any day inside them is blank, because the two parts would no longer add up.

### Historical VaR

95% one-day historical simulation. The window is the last 252 daily returns ending on the marked date. A missing close leaves that day and the next day with no one-day return. Those days are left out. The window does not start earlier to replace them. 5% of the days that remain is the VaR rank. A full window is 252 days, and 5% of 252 is 12.6, so the VaR day is the 13th worst. If fewer than 240 of the 252 returns can be computed, the report stops. A tied profit uses the later date.

The return is the percent change in dollars per one unit of the foreign currency. Long and short share that return. The sign is today's foreign-currency balance.

- `EURUSD` and `AUDUSD` are already dollars per unit, so the return is the pair's percent change.
- `USDJPY`, `USDSGD`, `USDCNY`, `USDINR`, and `USDKRW` use previous price / price − 1. That is the change in dollars per unit of the foreign currency, not the pair's own percent change.

The dollar result is today's signed USD value of the foreign-currency leg times that return. The USD cash leg earns nothing. This uses today's exposure on a past move. It is not a replay of that day's accounting P&L, and it does not use the day-P&L series, which only starts once the trade is open.

- **Portfolio VaR** is the portfolio loss on that ranked day. A loss is a positive number. The headline is the whole book. The grey line says 95%, the rank, the number of days used, and the date of that day.
- **Position VaR** is that same rank for the pair alone. The position VaRs do not sum to the portfolio VaR.
- **Component VaR** is the pair's contribution to the portfolio loss on the book's VaR day. The components sum to portfolio VaR. A pair that made money that day is negative. A pair whose foreign currency did not move is zero. The date under the position table is that day.
- **Marginal VaR** divides the component by the absolute USD value of the foreign-currency leg. The divisor is that leg, not the pair's base size.
- **Worst day** is the largest portfolio loss from the first cached close (2024-01-01) through the end date. The column is each pair's result on that one shared day, using today's foreign-currency exposure. It is a signed P&L, so a profit is positive. Each pair's own bad day is already the position VaR. The date under the position table is that day.
- **Hedge benefit** is the sum of the position VaRs minus the portfolio VaR. It is the loss the book avoids by holding the pairs together.

Day P&L is ranked against these same portfolio results, the days that remain after missing returns are left out. The marked day is left out of the count. Its replay is sized on today's dollar price, and day P&L is sized on the previous close. The rank is one plus the number of the other days with a larger result, so 1st is the best day. A tied result does not count as better.

### Screen

Streamlit draws the figures. The calculations live outside the UI.

- Strip: day P&L, window P&L, inception P&L, portfolio exposure, portfolio VaR. Under each of the three P&L figures: Cross P&L and Dollar P&L. The grey line under day P&L is its rank in the VaR days, for example "19th best of last 252 days". The grey line under portfolio VaR is "95%, 13th worst of last 252 days (2026-01-26)". If some returns were left out, both lines show that shorter count. The other three lines say which dates the number covers. The line above the strip is "Marked on {date} (Everything in USD)." That date is the close the book is marked on. The whole line is red when it is not the selected end date.
- Position table: one row per pair, not per fill. Side, net base, USD size, average entry, live spot, the three P&L columns, position VaR, component VaR, marginal VaR, and the worst-day P&L. Rows are sorted by component VaR, largest first. The Total row is always last. Above the table: the VaR-day and worst-day dates. Under it, in bold: Hedge benefit: and the number.
- Currency bars, above the ladder: every currency, including USD, sorted by absolute USD value, largest first. A short of 10 million comes before a long of 8 million. The dollar stays in that order.
- Currency ladder: the same absolute-size order, except USD is taken out and placed after the foreign currencies, then Foreign, then Net. Those three rows sit together so the foreign sum, the dollar cash, and their total can be read as one check. `day_usd_return` is that currency's move against the dollar since the previous close. Positive means it strengthened. USD is zero. Foreign and Net leave it blank.
- Currency exposure over time, under the ladder, from the chosen start date through the end date. This chart is not sorted by size. Positive balances stack up from zero and negative balances stack down, in the order the trades were opened. The dollar cash is the bottom positive band. Above it are the long foreign currencies. Below zero are the shorts, with the earliest short nearest the line. A dotted line at zero separates the longs from the shorts. Foreign is a line, the sum of the non-USD balances. It is not a band, because that would count those currencies twice. Net is not on that chart. The sum of every currency, including the dollar cash, is the cumulative P&L. The chart draws both legs, so the stack is larger than portfolio exposure. On 5 Oct 2026 the positive stack is about +27.4m and the negative stack is about −26.5m, including +9.9m of dollar cash. The foreign bars alone are about 44.0m, next to the 43.5m headline. USDJPY is 10,000,000 in the headline and −9,940,130 of yen on the chart: the headline uses the dollars traded, and the chart marks the yen at that day's rate.
- History between the two dates: daily P&L bars and the window P&L line.

Portfolio exposure is the sum of absolute trade sizes in USD (base notional times USD per base). It does not net longs against shorts, and it does not add both currency legs. On 5 Oct 2026 the seven pair sizes are USDJPY 10,000,000, USDSGD 8,000,000, USDINR 6,000,000, EURUSD 5,602,869, USDCNY 5,000,000, AUDUSD 4,869,565, and USDKRW 4,000,000, which sum to 43,472,434. Foreign is the sum of the non-USD rows. Net sums every currency, including the USD cash balances, and equals inception P&L.

## Major assumptions

- Spot FX only. Notional is in base currency. The sign is long or short the base.
- Prices are mid daily closes. They are not a bid/offer, and they are not a Tokyo or New York fix.
- P&L is unrealised USD mark-to-market of the two spot balances. The balances do not earn interest. No funding, no spot-next, no roll, no transaction costs. Inception P&L is the spot move, not the full FX result.
- The entry price uses the same quoting convention as the live series. In this file the entry is that day's close, so the fill date has no P&L. A fill dealt off the close puts that difference in Cross P&L. Dollar still uses only balances already open yesterday.
- USD is the only reporting currency.
- One leg of every pair is USD. Crosses such as EURJPY are not traded. Cross P&L is the relative-value result inside this USD book, not a separate cross price.
- Dollar P&L gives each foreign currency already open one equal vote. Cross P&L is the rest of the day's P&L. A size-weighted vote would make Cross P&L zero.
- Portfolio exposure is the sum of the absolute USD values of the base legs. It does not add the quote leg, and it does not net longs against shorts.
- Marginal VaR is the component divided by the absolute USD value of the foreign-currency leg.
- Hedge benefit is the sum of the position VaRs minus portfolio VaR. Each position VaR is that pair's own ranked day, so the position VaRs do not add up to portfolio VaR. Hedge benefit can be negative.
- The worst day is the largest loss in the whole cache back to 2024, using today's position size. It is not the worst day inside the 252 VaR days.
- VaR is 95%, one day, historical. The window is the last 252 returns ending on the marked date. Days with no return are left out, down to 240. A full window is ranked at the 13th worst. It scales today's foreign-currency USD value. The sample file is open trades only, so P&L and VaR are unrealised.
- A trade is in the book when its trade date is on or before the End date. Start does not add or remove trades. Day P&L, inception, exposure, and VaR are that whole book. Start only sets Window P&L, the P&L history, and the exposure path.
- The Start and End calendars run from the first cache date on or after 2026-01-01 through the last cached close. In this file the first of those is 2026-01-02. A day that is not a close uses the latest cached close on or before it. End still marks on the last complete close, and the marked line is red when that close is not the day picked. VaR and the worst day still use the cache back to 2024. A trade that was not open on the VaR day or the worst day is still included, at today's size.
- The day-P&L rank compares accounting day P&L with the replays of today's positions, leaving out the marked day. It is not today's place in the book's actual past P&L. Accounting day P&L and the replay of today are not the same number, so that replay is not in the count.

## Limitations and known issues

- Yahoo Finance is an unofficial source. It can gap, and it can revise history. The cache is what the app actually uses.
- The yuan leg is onshore USDCNY (`CNY=X`). Yahoo's CNH tickers returned a single print, so offshore CNH is not in the book. Onshore fixes are not used.
- Day P&L uses the previous row in the cache. On a Monday that previous close is Friday, so the figure includes the weekend.
- A missing close drops that point. It is not interpolated. That day and the next day are left out of VaR. The window is not extended earlier. Fewer than 240 usable days stops the report. A missing end-date close marks the book on the latest earlier complete close.
- The currency ladder is a spot delta in USD. It is not a rates, volatility, or cross-gamma report.
- Carry is excluded. Over the life of the trades it can be a material part of what the book made. There is no rate in the cache to calculate it.
- VaR applies today's foreign-currency exposure to a past return. It is not the P&L the book would have booked on that historical day.
- P&L and VaR are stored per pair, not as one column per fill. A long history adds one row per date per pair. Fills in one pair add. An opposite fill reduces the base, and a full close leaves the base at zero. The locked-in profit stays in that pair's quote balance. Exposure, Dollar, and Cross are one column per currency.

## If given more time

- A second price source, used only as a cross-check against the cache.
- A second VaR method beside the historical one, labelled so the two are not mixed.
- A parallel move of every foreign currency, beside the worst cached day.
- Strategy tags so a relative-value book is visible separately from outrights.
- Carry, once there is a rate for each currency that the P&L can point to.

## Run it locally

Run it from this folder:

```text
.venv\Scripts\python.exe -m streamlit run app.py
```

The page reads `cache/fx_closes.csv`. To rebuild that file from Yahoo:

```text
.venv\Scripts\python.exe -c "from src.data import download_prices; download_prices()"
```

That command overwrites the cache. Do not run it once this file is the audit trail.

## Deploy

Push the repository to GitHub, including `data/portfolio.csv` and `cache/fx_closes.csv`. On Streamlit Community Cloud, set the main file to `app.py` and the requirements file to `requirements.txt`.

The hosted app checks Yahoo once each time the server wakes. It saves the file only when Yahoo's last date is newer than the cache. A reprint of a date already in the file is ignored, so the page stays on the saved closes. A failed download leaves the saved cache in place, and the page says so. A local run does not download. Set `REFRESH_PRICES` to `1` in the environment when a host other than Community Cloud should download on wake. The portfolio and cache paths are anchored to this folder, so the page finds them when the server starts at the repository root.
