# inception = foreign amount * (dollars now - dollars then)
# day pnl = change in that value. On a pair's first row the previous value is 0.
# var = today's foreign-leg usd value times the last 252 daily moves.

import math

import pandas as pd

from src.data import PAIRS

VAR_LOOKBACK = 252
VAR_MIN_DAYS = 240


def usd_per_currency(prices):
    # Returns dollars for one unit of each currency. USD is 1.
    # EURUSD and AUDUSD are already dollars. The Asian pairs are 1/price.
    rates = pd.DataFrame({"USD": 1.0}, index=prices.index)
    for pair in prices.columns:
        base, quote = PAIRS[pair]
        if quote == "USD":
            rates[base] = prices[pair]
        else:
            rates[quote] = 1.0 / prices[pair]
    return rates


def position_value(foreign_amount, usd_then, usd_now):
    # Returns the profit. usd_then is one dealt price. A price column comes back as one profit per date.
    return foreign_amount * (usd_now - usd_then)


def _one_pair(frame, pair, column):
    # Returns one pair's dates as a series, taken from the long table.
    rows = frame.loc[frame["currency_pair"] == pair]
    return rows.set_index("date")[column].sort_index()


def _position_values(book, rates):
    # Returns inception P&L, one row per date per pair.
    # Fills in the same pair are added. Dates before a fill are left out.
    # A missing close on any open fill blanks that pair.
    frames = []
    for trade in book.itertuples(index=False):
        base, quote = PAIRS[trade.currency_pair]
        if quote == "USD":
            # EURUSD: foreign amount is the euros. The dealt price is already dollars per euro.
            foreign_amount = trade.notional_base
            usd_then = trade.entry_price
            usd_now = rates[base]
        else:
            # USDJPY: foreign amount is the yen owed. Dollars per yen is 1/price.
            foreign_amount = -trade.notional_base * trade.entry_price
            usd_then = 1.0 / trade.entry_price
            usd_now = rates[quote]
        column = position_value(foreign_amount, usd_then, usd_now)
        kept = column.loc[column.index >= trade.trade_date]
        frames.append(pd.DataFrame({
            "date": kept.index,
            "currency_pair": trade.currency_pair,
            "value": kept.to_numpy(),
        }))
    if not frames:
        return pd.DataFrame(columns=["date", "currency_pair", "value"])
    fills = pd.concat(frames, ignore_index=True)

    #Sums up to one row of pnl per currency pair per date. 
    rows = []
    for pair in fills["currency_pair"].drop_duplicates():
        this_pair = fills.loc[fills["currency_pair"] == pair]
        for date in this_pair["date"].drop_duplicates():
            values = this_pair.loc[this_pair["date"] == date, "value"]
            if values.isna().any():
                total = float("nan")
            else:
                total = float(values.sum())
            rows.append({"date": date, "currency_pair": pair, "value": total})
    return pd.DataFrame(rows)


def _day_changes(values):
    # Returns day P&L, one row per date per pair: today's value minus yesterday's.
    # The pair's first row has no previous close, so that day's P&L is the value itself.
    # A blank first row stays blank. Do not fill it from a later close.
    frames = []
    for pair in values["currency_pair"].drop_duplicates():
        series = _one_pair(values, pair, "value")
        day = series - series.shift(1)
        if pd.notna(series.iloc[0]):
            day.iloc[0] = series.iloc[0]
        frames.append(pd.DataFrame({
            "date": day.index,
            "currency_pair": pair,
            "day_pnl": day.to_numpy(),
        }))
    if not frames:
        return pd.DataFrame(columns=["date", "currency_pair", "day_pnl"])
    return pd.concat(frames, ignore_index=True)


def _window_pnl(value, start, as_of):
    # value is a series of inception pnl values for a single currency pair.
    # Returns window P&L: end value minus the start value. A pair whose first row is after the start contributes its end value.
    value = value.sort_index()
    end = value.at[as_of]
    if value.index[0] > start:
        return end
    if start not in value.index or pd.isna(value.at[start]) or pd.isna(end):
        return float("nan")
    return end - value.at[start]


def _book_history(values, day):
    # Returns one row per date. Day P&L and inception P&L are the sums of the pairs with a row that day.
    # A blank pair on that date blanks the total.
    if values.empty:
        return pd.DataFrame(columns=["date", "day_pnl_usd", "cumulative_pnl_usd"])
    rows = []
    for date in values["date"].drop_duplicates():
        value_now = values.loc[values["date"] == date, "value"]
        day_now = day.loc[day["date"] == date, "day_pnl"]
        missing = value_now.isna().any() or day_now.isna().any() or len(day_now) != len(value_now)
        rows.append({
            "date": date,
            "day_pnl_usd": float("nan") if missing else float(day_now.sum()),
            "cumulative_pnl_usd": float("nan") if missing else float(value_now.sum()),
        })
    return pd.DataFrame(rows)


def _dealt_pnl(book, rates):
    # Returns entry-to-close P&L on the first close on or after each trade date.
    # Zero when the entry is that close. A weekend trade lands on the next close.
    total = pd.Series(0.0, index=rates.index)
    for trade in book.itertuples(index=False):
        trade_date = pd.Timestamp(trade.trade_date).normalize()
        later = rates.index[rates.index >= trade_date]
        if len(later) == 0:
            continue
        mark = later[0]
        base, quote = PAIRS[trade.currency_pair]
        if quote == "USD":
            foreign_amount = trade.notional_base
            usd_then = trade.entry_price
            usd_now = rates.at[mark, base]
        else:
            foreign_amount = -trade.notional_base * trade.entry_price
            usd_then = 1.0 / trade.entry_price
            usd_now = rates.at[mark, quote]
        total.at[mark] = total.at[mark] + position_value(foreign_amount, usd_then, usd_now)
    return total


def _dollar_cross(quantities, rates):
    # Returns Dollar and Cross per date for balances already open yesterday.
    # One vote per foreign currency held yesterday.
    # Dollar = yesterday's foreign net times that average.
    # Cross = each currency's move minus that average, times yesterday's USD value.
    # A fill's entry-to-close P&L is not in here. _split_with_deals adds it to Cross.
    foreign = quantities.drop(columns="USD", errors="ignore")
    fx = rates.reindex(index=quantities.index, columns=foreign.columns)
    prev_qty = foreign.shift(1)
    prev_fx = fx.shift(1)
    move = fx / prev_fx - 1
    dollar_rows = []
    cross_rows = []
    for date in quantities.index:
        held = []
        for currency in foreign.columns:
            qty = prev_qty.at[date, currency]
            if pd.notna(qty) and abs(qty) > 0:
                held.append(currency)
        changes = [move.at[date, currency] for currency in held]
        missing = any(pd.isna(change) for change in changes)
        if not held:
            dollar, cross = 0.0, 0.0
        elif missing:
            dollar, cross = float("nan"), float("nan")
        else:
            basket = sum(changes) / len(changes)
            foreign_net = 0.0
            cross = 0.0
            for currency, change in zip(held, changes):
                weight = prev_qty.at[date, currency] * prev_fx.at[date, currency]
                foreign_net = foreign_net + weight
                cross = cross + weight * (change - basket)
            dollar = foreign_net * basket
        dollar_rows.append(dollar)
        cross_rows.append(cross)
    return pd.DataFrame({"dollar_pnl_usd": dollar_rows, "cross_pnl_usd": cross_rows}, index=quantities.index)


def _split_with_deals(quantities, rates, book):
    # Dollar stays yesterday's book. A fill dealt off the close is added to Cross on its first mark.
    split = _dollar_cross(quantities, rates)
    dealt = _dealt_pnl(book, rates).reindex(split.index)
    split = split.copy()
    split["cross_pnl_usd"] = split["cross_pnl_usd"] + dealt
    return split


def _ranked_day(pnl, rank):
    # Returns the date and the P&L at that rank. Rank 1 is the worst profit. A tie keeps the later date.
    if rank < 1 or rank > len(pnl):
        raise ValueError(f"rank {rank} is outside the {len(pnl)} returns")
    frame = pnl.rename("pnl").rename_axis("date").reset_index()
    frame = frame.sort_values(["pnl", "date"], ascending=[True, False], kind="mergesort")
    row = frame.iloc[rank - 1]
    return pd.Timestamp(row["date"]), float(row["pnl"])


def _dollar_results(quantities, rates, as_of):
    # Returns one column per pair: today's foreign-currency dollars times each past daily move, and those dollar amounts.
    as_of = pd.Timestamp(as_of).normalize()
    rates = rates.loc[:as_of]
    if as_of not in rates.index:
        raise ValueError("end date is not in the price cache")
    if len(rates) < 2 or as_of == rates.index[0]:
        raise ValueError("the end date has no previous close")
    if as_of not in quantities.index:
        raise ValueError("end date is not in the balances")
    pair_of = {}
    for pair, (base, quote) in PAIRS.items():
        pair_of[base if quote == "USD" else quote] = pair
    signed = {}
    columns = {}
    for currency in quantities.columns:
        if currency == "USD":
            continue
        usd_per_unit = rates.at[as_of, currency] if currency in rates.columns else float("nan")
        amount = float(quantities.at[as_of, currency]) * usd_per_unit
        pair = pair_of[currency]
        if pd.isna(amount):
            raise ValueError(f"{pair} has no USD value on the end date")
        signed[pair] = amount
        columns[pair] = amount * (rates[currency] / rates[currency].shift(1) - 1)
    if not signed:
        raise ValueError("VaR needs an open trade")
    return pd.DataFrame(columns, index=rates.index).iloc[1:], signed


def _usable_var_window(results):
    # Returns the last 252 results that can be used. A day with any blank return is dropped and is not replaced.
    if len(results) < VAR_LOOKBACK:
        raise ValueError(f"need {VAR_LOOKBACK} USD returns ending on the end date, found {len(results)}")
    usable = results.iloc[-VAR_LOOKBACK:].dropna(how="any")
    if len(usable) < VAR_MIN_DAYS:
        raise ValueError(f"{len(usable)} of the last {VAR_LOOKBACK} USD returns can be computed; need {VAR_MIN_DAYS}")
    return usable


def historical_var(quantities, rates, as_of):
    # Returns 95% one-day VaR, the ranked day, and one VaR row per pair. The rank is 5% of the usable days, 13th when all 252 are there.
    # Component VaR is that day's loss by pair, and the components sum to the portfolio VaR.
    results, signed = _dollar_results(quantities, rates, as_of)
    window = _usable_var_window(results)
    rank = math.ceil(0.05 * len(window))
    portfolio = window.sum(axis=1)
    var_date, portfolio_pnl = _ranked_day(portfolio, rank)
    components = -window.loc[var_date]
    portfolio_var = -portfolio_pnl
    if abs(float(components.sum()) - portfolio_var) > 1e-6:
        raise ValueError("component VaR does not sum to portfolio VaR")
    history = results.dropna(how="any").sum(axis=1)
    stress_date, stress_pnl = _ranked_day(history, 1)
    rows = []
    for pair in window.columns:
        _day, pair_pnl = _ranked_day(window[pair], rank)
        component = float(components[pair])
        size = abs(signed[pair])
        rows.append({
            "currency_pair": pair,
            "position_var_usd": -pair_pnl,
            "component_var_usd": component,
            "marginal_var": component / size if size else float("nan"),
            "worst_day_pnl_usd": float(results.loc[stress_date, pair]),
        })
    return {
        "portfolio_var_usd": portfolio_var,
        "var_date": var_date,
        "var_rank": rank,
        "var_days": len(window),
        "stress_date": stress_date,
        "stress_pnl_usd": stress_pnl,
        "scaled_pnl": portfolio,
        "by_pair": pd.DataFrame(rows),
    }


def _balances(book, index):
    # Returns currency amounts by date. Base is the notional. Quote is minus notional times the dealt price.
    currencies = []
    for trade in book.itertuples(index=False):
        for currency in PAIRS[trade.currency_pair]:
            if currency not in currencies:
                currencies.append(currency)
    quantities = pd.DataFrame(0.0, index=index, columns=currencies)
    for trade in book.itertuples(index=False):
        base, quote = PAIRS[trade.currency_pair]
        opened = index >= trade.trade_date
        quantities.loc[opened, base] = quantities.loc[opened, base] + trade.notional_base
        quantities.loc[opened, quote] = quantities.loc[opened, quote] - trade.notional_base * trade.entry_price
    return quantities


def _move(today, yesterday):
    # Returns the percent change in dollars per unit. Positive means that currency strengthened.
    if pd.isna(today) or pd.isna(yesterday):
        return float("nan")
    return today / yesterday - 1


def _exposure_table(quantities, rates, as_of):
    # Returns one row per currency on the end date: balance, dollars per unit, USD value, and the day's move.
    earlier = rates.index[rates.index < as_of]
    previous = earlier[-1] if len(earlier) else None
    rows = []
    for currency in quantities.columns:
        balance = float(quantities.at[as_of, currency])
        usd_per_unit = rates.at[as_of, currency] if currency in rates.columns else float("nan")
        usd_value = balance * usd_per_unit if pd.notna(usd_per_unit) else float("nan")
        if currency == "USD":
            day_return = 0.0
        elif previous is None or currency not in rates.columns:
            day_return = float("nan")
        else:
            day_return = _move(usd_per_unit, rates.at[previous, currency])
        rows.append({
            "currency": currency,
            "balance": balance,
            "usd_per_unit": usd_per_unit,
            "usd_value": usd_value,
            "day_usd_return": day_return,
        })
    exposure = pd.DataFrame(rows)
    exposure["_sort"] = exposure["usd_value"].abs()
    exposure = exposure.sort_values("_sort", ascending=False)
    return exposure.drop(columns="_sort")


def _exposure_path(quantities, rates, start, as_of):
    # Returns the USD value of each currency from the start date through the end date. Foreign is the non-dollar sum.
    window = quantities.loc[(quantities.index >= start) & (quantities.index <= as_of)]
    live = rates.reindex(index=window.index, columns=window.columns)
    values = (window * live).mask(window == 0, 0.0)
    foreign_names = [currency for currency in window.columns if currency != "USD"]
    if foreign_names:
        values["Foreign"] = values[foreign_names].sum(axis=1, min_count=len(foreign_names))
    else:
        values["Foreign"] = 0.0
    ordered = foreign_names + (["USD"] if "USD" in values.columns else []) + ["Foreign"]
    values = values[ordered].copy()
    values.insert(0, "date", values.index)
    return values.reset_index(drop=True)


def _window_history(history, start, as_of):
    # Returns book P&L after the start date. window_cumulative is the inception P&L since that date.
    if history.empty or start < history["date"].min():
        baseline = 0.0
    else:
        matched = history.loc[history["date"] == start, "cumulative_pnl_usd"]
        baseline = float(matched.iloc[0]) if not matched.empty else float("nan")
    window = history.loc[(history["date"] > start) & (history["date"] <= as_of)].copy()
    window["window_cumulative"] = window["cumulative_pnl_usd"] - baseline
    return window.reset_index(drop=True)


def _split_sum(split, dates):
    # Returns Dollar and Cross summed over these dates. One blank day blanks both totals.
    dates = [pd.Timestamp(date) for date in dates]
    if not dates:
        return float("nan"), float("nan")
    picked = split.reindex(dates)
    if picked.isna().to_numpy().any():
        return float("nan"), float("nan")
    return float(picked["dollar_pnl_usd"].sum()), float(picked["cross_pnl_usd"].sum())


def _same_pnl(total, dollar, cross):
    # Returns nothing (is a Check). Raises when Dollar plus Cross is more than 5 cents away from the P&L total.
    if pd.isna(total) or pd.isna(dollar) or pd.isna(cross):
        return
    if abs((dollar + cross) - total) > 0.05:
        raise ValueError(f"Dollar P&L {dollar} plus Cross P&L {cross} does not equal {total}")


def _last_complete_close(portfolio, prices, as_of):
    # Returns the latest date on or before the end date where every open pair has a close.
    as_of = pd.Timestamp(as_of).normalize()
    candidates = list(prices.index[prices.index <= as_of])
    if not candidates:
        raise ValueError("end date is before the price cache")
    for date in reversed(candidates):
        pairs = []
        for pair in portfolio.loc[portfolio["trade_date"] <= date, "currency_pair"]:
            if pair not in pairs:
                pairs.append(pair)
        if pairs and prices.loc[date, pairs].notna().all():
            return pd.Timestamp(date)
    raise ValueError("no close is available for every open pair")


def _position_rows(book, prices, rates, values, day, var, start, as_of):
    # Returns the position table, one row per pair: net size, P&L, VaR, and the live spot.
    # Fills in the pair are already netted. A flat pair keeps its locked-in P&L.
    live = rates.loc[as_of]
    by_pair = var["by_pair"].set_index("currency_pair")
    pairs = []
    for pair in book["currency_pair"]:
        if pair not in pairs:
            pairs.append(pair)
    rows = []
    for pair in pairs:
        base, _quote = PAIRS[pair]
        fills = book.loc[book["currency_pair"] == pair]
        notional = float(fills["notional_base"].sum())
        entry = float("nan") if notional == 0 else float((fills["notional_base"] * fills["entry_price"]).sum() / notional)
        series = _one_pair(values, pair, "value")
        day_series = _one_pair(day, pair, "day_pnl")
        pair_var = by_pair.loc[pair]
        if notional == 0:
            side = "Flat " + base
        elif notional > 0:
            side = "Long " + base
        else:
            side = "Short " + base
        rows.append({
            "currency_pair": pair,
            "side": side,
            "notional_base": notional,
            "usd_notional": abs(notional * live[base]),
            "entry_price": entry,
            "live_spot": prices.at[as_of, pair],
            "day_pnl_usd": day_series.at[as_of],
            "window_pnl_usd": _window_pnl(series, start, as_of),
            "inception_pnl_usd": series.at[as_of],
            "position_var_usd": float(pair_var["position_var_usd"]),
            "component_var_usd": float(pair_var["component_var_usd"]),
            "marginal_var": float(pair_var["marginal_var"]),
            "worst_day_pnl_usd": float(pair_var["worst_day_pnl_usd"]),
        })
    return pd.DataFrame(rows).sort_values("component_var_usd", ascending=False)


def build_report(portfolio, prices, as_of, start):
    # Returns the headline numbers and the tables, marked on the last complete close.
    requested = pd.Timestamp(as_of).normalize()
    start = pd.Timestamp(start).normalize()
    as_of = _last_complete_close(portfolio, prices, requested)
    if start > as_of:
        if as_of != requested:
            raise ValueError(f"start date is after the last complete close on {as_of:%Y-%m-%d}")
        raise ValueError("start date is after the end date")
    prices = prices.loc[:as_of]
    rates = usd_per_currency(prices)
    book = portfolio.loc[portfolio["trade_date"] <= as_of]
    values = _position_values(book, rates)
    day = _day_changes(values)
    history = _book_history(values, day)
    quantities = _balances(book, rates.index)
    var = historical_var(quantities, rates, as_of)
    positions = _position_rows(book, prices, rates, values, day, var, start, as_of)
    exposure = _exposure_table(quantities, rates, as_of)
    window_history = _window_history(history, start, as_of)
    split = _split_with_deals(quantities, rates, book)
    today = history.loc[history["date"] == as_of].iloc[0]
    day_pnl = float(today["day_pnl_usd"])
    # The as-of replay is sized on today's dollar price. Day P&L is sized on the previous close.
    # Leave that replay out so the day is not counted against a different copy of itself.
    replay = var["scaled_pnl"]
    replay = replay[replay.index != as_of]
    day_pnl_rank = float("nan") if pd.isna(day_pnl) else 1 + int((replay > day_pnl).sum())
    window_pnl = positions["window_pnl_usd"]
    window_total = float("nan") if window_pnl.isna().any() else float(window_pnl.sum())
    inception_pnl = float(today["cumulative_pnl_usd"])
    spans = (
        (day_pnl, [as_of]),
        (window_total, list(window_history["date"])),
        (inception_pnl, list(history["date"])),
    )
    parts = []
    for total, dates in spans:
        dollar, cross = _split_sum(split, dates)
        _same_pnl(total, dollar, cross)
        parts.append((cross, dollar))
    (day_cross, day_dollar), (window_cross, window_dollar), (inception_cross, inception_dollar) = parts
    
    return {
        "as_of": as_of,
        "start": start,
        "day_pnl_usd": day_pnl,
        "day_cross_pnl_usd": day_cross,
        "day_dollar_pnl_usd": day_dollar,
        "day_pnl_rank": day_pnl_rank,
        "window_pnl_usd": window_total,
        "window_cross_pnl_usd": window_cross,
        "window_dollar_pnl_usd": window_dollar,
        "inception_pnl_usd": inception_pnl,
        "inception_cross_pnl_usd": inception_cross,
        "inception_dollar_pnl_usd": inception_dollar,
        "gross_usd": float(positions["usd_notional"].sum()),
        "portfolio_var_usd": var["portfolio_var_usd"],
        "var_date": var["var_date"],
        "var_rank": var["var_rank"],
        "var_days": var["var_days"],
        "hedge_benefit_usd": float(positions["position_var_usd"].sum() - var["portfolio_var_usd"]),
        "stress_date": var["stress_date"],
        "stress_pnl_usd": var["stress_pnl_usd"],
        "positions": positions,
        "exposure": exposure,
        "exposure_path": _exposure_path(quantities, rates, start, as_of),
        "history": window_history,
    }
