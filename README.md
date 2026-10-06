# FX Portfolio Management Dashboard

Monitoring of key metrics like PnL and risk

The page: https://assignment-xmpipukiyvlfadrrqvn4ns.streamlit.app/

More details on the project, including the code path, and how to run it are in [notes.md](notes.md).


## Methodology

### PnL

P&L is in US dollars. `usd_per_currency` turns each close price into per_usd. 
EURUSD and AUDUSD uses the price directly. USDJPY, USDSGD, USDCNY, USDINR, and USDKRW use 1/price.

`position_value` calculates P&L with  `foreign amount × (rate now − rate at point of trade)`

On EURUSD and AUDUSD the foreign amount is the base notional.  rate = price
        Long 1,000,000 EUR from 1.10 to 1.12 is `1,000,000 × (1.12 − 1.10) = 20,000`.

On USDJPY, USDSGD, USDCNY, USDINR, and USDKRW the foreign amount is the quote currency from the trade, `−notional × price`, and rate = 1/price. 
        Long 10,000,000 USD at USDJPY = 150 is short 1,500,000,000 yen. As USDJPY rises from 150 to 155 that is `−1,500,000,000 × (1/155 − 1/150) = 322,581`.

For each trade, P&L is calculated for all days that occur on/after the trade.

Inception P&L is that pair's value on the end date. P&L in the same pair on the same date are summed into that one row.

Day P&L (P&L from End date - 1 trading day to End date) is calculated by taking the row difference in Inception P&L

Window P&L (P&L from Start Date to End date). A start and end date is customisable so that users can see how P&L and other metrics changes with the window, eg. wanting to see what happens during a specific window. However, the positions are not affected by the window 

Each P&L is decomposed into Dollar P&L and Cross P&L, for an FX relative-value vs directional breakdown. 
Dollar P&L comes from the currencies moving together against the dollar. 
Cross P&L comes from currencies moving apart from each other. 
These 2 add up to each P&L.

EG.
On 5 Oct the positions are the 2 Oct balances. The move is the change in dollars per unit from 2 Oct to 5 Oct. Seven foreign currencies were open, so the average is the sum of the seven moves divided by 7: (A simple average was used, some investigation into weighting could be beneficial)

`(0.16 − 0.39 + 0.00 − 0.06 + 1.25 + 0.11 + 0.40) / 7 = 0.21%`

Dollar = yesterday's foreign currencies added up, times that average:

`−9,059,368 × 0.21% ~ −19,019`

Cross for one currency = its USD value on 2 Oct × (its move − 0.2099%).

| Currency | USD on 2 Oct | Move | Move − 0.2099% | Cross |
| --- | ---: | ---: | ---: | ---: |
| JPY | −9,924,269 | +0.16% | −0.05% | +4,974 |
| EUR | −5,624,930 | −0.39% | −0.60% | +33,870 |
| SGD | +8,060,178 | +0.00% | −0.21% | −16,795 |
| INR | −5,887,794 | −0.06% | −0.27% | +15,736 |
| KRW | +4,501,959 | +1.25% | +1.04% | +46,764 |
| CNY | −5,034,603 | +0.11% | −0.10% | +5,157 |
| AUD | +4,850,091 | +0.40% | +0.19% | +9,292 |
| Sum | −9,059,368 | | | +98,998 |

KRW position's Cross P&L showcases its relative outperformance : `4,501,959 × (1.2487% − 0.2099%) = 46,764`. 
The Cross column adds to +98,998. Day P&L is `−19,019 + 98,998 = 79,979`.


### VaR

I was considering between 2 methods for calculating VaR - parametric and historical. 
I decided with historical, especially in the context of Asian FX. Parametric method assumes normality of returns, which may not hold true for EM/Asian FX markets with fat tails, noisy estimations of the covariance matrix covariances. I felt that hsitorical simulation would better encapsulate the co-movement of the FX pairs.

VaR defined to be 95%, one day, historical.
The window is the last 252 returns ending on the marked date.  A full window is the 13th worst.


- **Position VaR** is for the pair alone. The position VaRs do not add up to portfolio VaR since the worst days do not occur on the same day.
- **Portfolio VaR** is calculated by taking the end date positions, and simulating with historical returns.
- **Component VaR** is that pair's result on the portfolio's VaR day. The components add up to portfolio VaR. 
- **Marginal VaR** is the component VaR divided by the absolute USD value of the foreign-currency leg.
- **Worst day** is the largest portfolio loss from the first cached close (2024-01-01) through the end date, using end date's sizes.
- **Hedge benefit** is the sum of the position VaRs minus portfolio VaR (Somewhat like a diversification effect)

The day-P&L rank compares end date's PnL to the past 252 returns, using end date's positions.

## Assumptions
There is no carry involved in the calculations, so all PnL are FROM spot move only.

## How to check the numbers

On the page, with Start 2026-01-02 and End 2026-10-05, six checks have to hold. If one fails, the book is wrong.

- Dollar P&L plus Cross P&L equals the Day, Window, and Inception figures above them.
- The position table Total for day, window, and inception equals those same headlines.
- The Net row in the Currency exposure table equals Inception P&L. Set End to 2026-01-02: Inception is 0, JPY is −10,000,000, USD is +10,000,000.
- Component VaR Total equals Portfolio VaR. Hedge benefit equals the seven position VaRs added up, minus Portfolio VaR.
- On 5 Oct, USDKRW is short USD. Its day move is positive, and its day P&L is positive.
- The grey VaR line says 95%, 13th worst of 252 days (2026-01-26), and the date under the position table is the same day.

A short calculator test of those two lines and the two-currency split is in `tests/test_book.py`. It does not use the cache.
