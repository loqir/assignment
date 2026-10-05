import os
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

from src.data import download_prices, load_portfolio, load_prices
from src.pnl import build_report

START_DATE = "2026-01-01"
GREEN = "#3cba6f"
RED = "#ff6b6b"
COLORS = {
    "USD": "#e6e6e6",
    "JPY": "#ee6677",
    "EUR": "#4477aa",
    "SGD": "#2f9e44",
    "INR": "#ee7733",
    "KRW": "#66ccee",
    "CNY": "#aa3377",
    "AUD": "#8da0cb",
    "Foreign": "#fee440",
}
TOTALS = ["usd_notional", "day_pnl_usd", "window_pnl_usd", "inception_pnl_usd", "component_var_usd", "worst_day_pnl_usd"]
PNL_COLUMNS = ["day_pnl_usd", "window_pnl_usd", "inception_pnl_usd", "worst_day_pnl_usd"]


def _day(day):
    return pd.Timestamp(day).strftime("%Y-%m-%d")


def _ordinal(rank):
    rank = int(rank)
    if 10 <= rank % 100 <= 20:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(rank % 10, "th")
    return f"{rank}{suffix}"


def _tone(value):
    if pd.isna(value) or round(float(value)) == 0:
        return ""
    return GREEN if value > 0 else RED


def _money(value):
    return "" if pd.isna(value) else f"{value:,.0f}"


def _colored(name, amount):
    if pd.isna(amount):
        return name
    color = _tone(amount)
    style = f" style='color:{color}'" if color else ""
    return f"{name} <span{style}>{_money(amount)}</span>"


def _total_row(frame, label_column, label, sum_columns, source=None):
    rows = frame if source is None else source
    total = {}
    for column in frame.columns:
        if column == label_column:
            total[column] = label
        elif column in sum_columns:
            total[column] = float("nan") if rows.empty or rows[column].isna().any() else float(rows[column].sum())
        elif pd.api.types.is_numeric_dtype(frame[column]):
            total[column] = float("nan")
        else:
            total[column] = ""
    return total


def _show(frame):
    specs = {
        "entry_price": ",.5f",
        "live_spot": ",.5f",
        "usd_per_unit": ".6g",
        "marginal_var": ".2%",
        "day_usd_return": ".2%",
    }
    out = frame.copy()
    for column in out.columns:
        spec = specs.get(column)
        if spec is None and pd.api.types.is_numeric_dtype(out[column]):
            spec = ",.0f"
        if spec is None:
            continue
        shown = []
        for value in out[column]:
            shown.append("" if pd.isna(value) else format(value, spec))
        out[column] = shown
    return out


def _positions(frame):
    shown = _show(frame)
    total = _total_row(frame, "currency_pair", "Total", TOTALS)
    shown = pd.concat([shown, _show(pd.DataFrame([total]))], ignore_index=True)

    def paint(column):
        if column.name not in PNL_COLUMNS:
            return [""] * len(column)
        styles = []
        for value in list(frame[column.name]) + [total[column.name]]:
            color = _tone(value)
            styles.append(f"color: {color}" if color else "")
        return styles

    return shown.style.apply(paint, axis=0)


def _headline(report, requested):
    marked = _day(report["as_of"])
    shifted = pd.Timestamp(report["as_of"]).normalize() != pd.Timestamp(requested).normalize()
    line = f"Marked on {marked} (Everything in USD)."
    if shifted:
        st.error(line)
    else:
        st.caption(line)
    rank = report["day_pnl_rank"]
    if pd.isna(rank):
        day_note = ""
    elif int(rank) == 1:
        day_note = f"best of last {int(report['var_days'])} days"
    elif int(rank) > report["var_days"]:
        day_note = f"worse than the last {int(report['var_days'])} days"
    else:
        day_note = f"{_ordinal(rank)} best of last {int(report['var_days'])} days"
    tiles = [
        ("Day P&L", day_note, report["day_pnl_usd"], report["day_cross_pnl_usd"], report["day_dollar_pnl_usd"]),
        ("Window P&L", f"between {_day(report['start'])} and {marked}", report["window_pnl_usd"], report["window_cross_pnl_usd"], report["window_dollar_pnl_usd"]),
        ("Inception P&L", "since each trade was opened", report["inception_pnl_usd"], report["inception_cross_pnl_usd"], report["inception_dollar_pnl_usd"]),
        ("Portfolio exposure", "sum of all current position sizes", report["gross_usd"], None, None),
        ("Portfolio VaR", f"95%, {_ordinal(report['var_rank'])} worst of last {int(report['var_days'])} days ({_day(report['var_date'])})", report["portfolio_var_usd"], None, None),
    ]
    for column, (label, note, value, cross, dollar) in zip(st.columns(5), tiles):
        color = _tone(value) if cross is not None else ""
        style = f"color:{color};" if color else ""
        split = ""
        if cross is not None:
            split = f"<div>{_colored('Cross P&L', cross)}<br>{_colored('Dollar P&L', dollar)}</div>"
        column.markdown(
            f"<div style='font-size:1.35rem;font-weight:600;line-height:1.2'>{label}</div>"
            f"<div style='opacity:.6'>{note}</div>"
            f"<div style='font-size:2rem;font-weight:600;{style}'>{_money(value)}</div>{split}",
            unsafe_allow_html=True,
        )


def _rgba(hex_color, alpha):
    channel = hex_color.lstrip("#")
    red, green, blue = int(channel[0:2], 16), int(channel[2:4], 16), int(channel[4:6], 16)
    return f"rgba({red},{green},{blue},{alpha})"


def _exposure_chart(path):
    # Longs stack up, shorts stack down. USD stays in the positive stack.
    figure = go.Figure()
    foreign = [column for column in path.columns if column not in ("date", "USD", "Foreign")]
    names = ["USD"] + foreign
    groups = {
        "positive": ["USD"] + [column for column in foreign if float(path[column].min()) >= 0],
        "negative": [column for column in foreign if float(path[column].min()) < 0],
    }
    for group, group_names in groups.items():
        for column in group_names:
            color = COLORS.get(column, "#f2f2f2")
            figure.add_scatter(
                x=path["date"], y=path[column], name=column, mode="lines", stackgroup=group,
                line=dict(color=color, width=0.6), fillcolor=_rgba(color, 0.92),
            )
    figure.add_scatter(
        x=path["date"], y=path["Foreign"], name="Foreign", mode="lines",
        line=dict(color=COLORS["Foreign"], width=3),
    )
    figure.add_scatter(
        x=[path["date"].iloc[0], path["date"].iloc[-1]], y=[0, 0],
        mode="lines", showlegend=False, hoverinfo="skip",
        line=dict(color="#000000", width=2, dash="dot"),
    )
    low = min(float(path[names].clip(upper=0).sum(axis=1).min()), float(path["Foreign"].min()))
    high = max(float(path[names].clip(lower=0).sum(axis=1).max()), float(path["Foreign"].max()))
    pad = (high - low) * 0.08
    figure.update_layout(
        height=560, hovermode="x unified",
        margin=dict(l=16, r=16, t=12, b=96),
        legend=dict(orientation="h", yanchor="top", y=-0.16, x=0, xanchor="left"),
        yaxis=dict(title="USD value", range=[low - pad, high + pad]),
    )
    return figure


def _history_chart(history):
    figure = make_subplots(specs=[[{"secondary_y": True}]])
    figure.add_bar(x=history["date"], y=history["day_pnl_usd"], name="Day P&L", marker_color="#4c78a8")
    figure.add_scatter(
        x=history["date"], y=history["window_cumulative"], name="Window P&L", mode="lines",
        line=dict(color="#f58518", width=2), secondary_y=True,
    )
    figure.update_layout(height=420, margin=dict(l=20, r=20, t=20, b=20), legend=dict(orientation="h", y=1.02))
    figure.update_yaxes(title_text="Day P&L (USD)", secondary_y=False)
    figure.update_yaxes(title_text="Window P&L (USD)", secondary_y=True)
    return figure


def _ladder(exposure):
    foreign = exposure.loc[exposure["currency"] != "USD"]
    usd = exposure.loc[exposure["currency"] == "USD"]
    totals = pd.DataFrame([
        _total_row(exposure, "currency", "Foreign", ["usd_value"], foreign),
        _total_row(exposure, "currency", "Net", ["usd_value"]),
    ])
    return pd.concat([foreign, usd, totals], ignore_index=True)


def _cached_on_or_before(dates, day):
    # Returns the latest cached close on or before this calendar day.
    day = pd.Timestamp(day).normalize()
    found = None
    for cached in dates:
        if pd.Timestamp(cached) <= day:
            found = pd.Timestamp(cached)
        else:
            break
    if found is None:
        raise ValueError("start date is before the price cache")
    return found


def _should_refresh():
    # Local runs leave the cache file alone. Community Cloud, and REFRESH_PRICES=1, download once per wake.
    if os.environ.get("REFRESH_PRICES") == "1":
        return True
    return Path("/mount/src").exists()


@st.cache_resource
def _wake_prices():
    # Returns a short error, or a blank string when the saved cache is ready to read.
    if not _should_refresh():
        return ""
    try:
        download_prices(only_if_newer=True)
    except Exception as error:
        text = str(error).splitlines()
        return text[0] if text else "price download failed"
    return ""


st.set_page_config(page_title="FX spot book", layout="wide")
st.title("FX portfolio")
st.caption("Daily closes")
refresh_problem = _wake_prices()
if refresh_problem:
    st.caption(f"Price download failed. Showing the saved cache. {refresh_problem}")

prices = load_prices()
book = load_portfolio()
first_trade = pd.Timestamp(book["trade_date"].min()).normalize()
dates = list(prices.index[prices.index >= START_DATE])
first_close = pd.Timestamp(dates[0]).normalize()
last_close = pd.Timestamp(dates[-1]).normalize()
if "start_date" not in st.session_state:
    st.session_state.start_date = max(first_trade, first_close).date()
start_col, end_col = st.columns(2)
start_picked = start_col.date_input("Start", min_value=first_close.date(), max_value=last_close.date(), key="start_date")
start = _cached_on_or_before(dates, start_picked)
end_min = max(pd.Timestamp(start_picked).normalize(), first_trade)
if "end_date" not in st.session_state:
    st.session_state.end_date = last_close.date()
elif st.session_state.end_date < end_min.date():
    st.session_state.end_date = end_min.date()
as_of = end_col.date_input("End", min_value=end_min.date(), max_value=last_close.date(), key="end_date")

try:
    report = build_report(book, prices, as_of, start)
except ValueError as error:
    st.error(str(error))
    st.stop()

_headline(report, as_of)
st.markdown("<div style='height:1.75rem'></div>", unsafe_allow_html=True)
st.subheader("Positions")
st.caption(f"Component VaR is the {_day(report['var_date'])} loss. Worst day is {_day(report['stress_date'])}.")
st.dataframe(_positions(report["positions"]), hide_index=True)
st.markdown(
    f"<div style='font-weight:700'>Hedge benefit: {_money(report['hedge_benefit_usd'])}</div>",
    unsafe_allow_html=True,
)

st.subheader("Currency exposure")
exposure = report["exposure"]
bars = go.Figure(go.Bar(
    x=exposure["currency"],
    y=exposure["usd_value"],
    marker_color=["#b00020" if value < 0 else "#1b7f4a" for value in exposure["usd_value"]],
))
bars.update_layout(height=360, margin=dict(l=20, r=20, t=20, b=20), yaxis_title="USD value")
st.plotly_chart(bars, width="stretch")
st.dataframe(_show(_ladder(exposure)), hide_index=True)

st.subheader("Currency exposure over time")
path = report["exposure_path"]
if path.empty:
    st.write("No closes in the window.")
else:
    st.plotly_chart(_exposure_chart(path), width="stretch")

st.subheader("P&L history")
history = report["history"]
if history.empty:
    st.write("The window is a single close, so there is no path inside it.")
else:
    st.plotly_chart(_history_chart(history), width="stretch")
