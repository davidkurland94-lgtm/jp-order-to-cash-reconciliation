"""AR aging page — what's owed, how late it is, and who owes it. Source: mart_ar_aging."""

import altair as alt
import pandas as pd
import streamlit as st

from common import YEN_AXIS, query, theme_colors, yen, yen_short

# Aging buckets in order, from mart_ar_aging's column names to display labels
BUCKETS = {
    "current_jpy": "Current",
    "days_1_30_jpy": "1–30 days",
    "days_31_60_jpy": "31–60 days",
    "days_61_90_jpy": "61–90 days",
    "days_over_90_jpy": "90+ days",
}

colors = theme_colors()

aging = query("select * from main.mart_ar_aging")
open_invoices = query("""
    select invoice_id, customer_name, open_amount_jpy, due_date, days_past_due
    from main.fct_invoice_reconciliation
    where open_amount_jpy > 0
""")

as_of_date = pd.to_datetime(aging["as_of_date"].iloc[0]).date()
aging["overdue_jpy"] = aging["total_open_jpy"] - aging["current_jpy"]
worst = aging.sort_values("overdue_jpy", ascending=False).iloc[0]

# Several invoices can tie for oldest (same due date), so keep all of them
max_days_late = open_invoices["days_past_due"].max()
oldest = open_invoices[open_invoices["days_past_due"] == max_days_late]

st.title("Accounts receivable aging")
st.markdown("How much customers still owe, and how late it is.")
st.caption(
    f"As of {as_of_date:%Y-%m-%d} · {len(aging)} customers with open invoices · "
    "source: `mart_ar_aging` (dbt)"
)

# --- KPI cards -------------------------------------------------------------

total_open = aging["total_open_jpy"].sum()
total_overdue = aging["overdue_jpy"].sum()

card1, card2, card3, card4 = st.columns(4)
card1.metric(
    "Total still owed",
    yen_short(total_open),
    help=f"{yen(total_open)} across {aging['open_invoice_count'].sum()} open invoices, "
         "including ones not yet due",
    border=True,
)
card2.metric(
    "Overdue",
    yen_short(total_overdue),
    help=f"{yen(total_overdue)} past its due date",
    border=True,
)
card2.caption(f"{total_overdue / total_open:.0%} of everything owed")
card3.metric(
    "Most overdue customer",
    yen_short(worst["overdue_jpy"]),
    help=f"The customer with the largest past-due balance ({yen(worst['overdue_jpy'])})",
    border=True,
)
card3.caption(f"{worst['customer_name']} · {worst['overdue_jpy'] / total_overdue:.0%} of all overdue")
card4.metric(
    "Oldest open invoice",
    f"{max_days_late:.0f} days",
    help="Open invoice(s) furthest past their due date: "
         + ", ".join(f"{r.invoice_id} ({r.customer_name})" for r in oldest.itertuples()),
    border=True,
)
if len(oldest) == 1:
    card4.caption(f"{oldest.iloc[0]['invoice_id']} · {oldest.iloc[0]['customer_name']} · "
                  f"{yen(oldest.iloc[0]['open_amount_jpy'])}")
else:
    card4.caption(f"{len(oldest)} invoices tied, due {oldest['due_date'].iloc[0]:%Y-%m-%d} · "
                  f"{yen(oldest['open_amount_jpy'].sum())} total")

# --- Long format for charts: one row per customer per bucket ----------------

long = aging.melt(
    id_vars=["customer_name"],
    value_vars=list(BUCKETS),
    var_name="bucket_column",
    value_name="open_jpy",
)
long["bucket"] = long["bucket_column"].map(BUCKETS)
long["bucket_order"] = long["bucket_column"].map({c: i for i, c in enumerate(BUCKETS)})

bucket_scale = alt.Scale(domain=list(BUCKETS.values()), range=colors["buckets"])

left, right = st.columns([2, 3])

# --- Chart 1: how much is owed at each level of lateness --------------------

with left:
    st.subheader("By days past due")
    by_bucket = long.groupby(["bucket", "bucket_order"], as_index=False)["open_jpy"].sum()
    by_bucket["label"] = by_bucket["open_jpy"].map(yen_short)

    bars = alt.Chart(by_bucket).mark_bar(cornerRadiusEnd=4, width={"band": 0.8}).encode(
        x=alt.X("bucket:N", sort=list(BUCKETS.values()), title=None, axis=alt.Axis(labelAngle=0)),
        y=alt.Y("open_jpy:Q", axis=YEN_AXIS),
        color=alt.Color("bucket:N", scale=bucket_scale, legend=None),
        tooltip=[
            alt.Tooltip("bucket:N", title="Days past due"),
            alt.Tooltip("open_jpy:Q", title="Open (¥)", format=","),
        ],
    )
    # Text uses the page's text color, not the bar color
    labels = alt.Chart(by_bucket).mark_text(dy=-8, fontSize=12, color=colors["text"]).encode(
        x=alt.X("bucket:N", sort=list(BUCKETS.values())),
        y="open_jpy:Q",
        text="label:N",
    )
    st.altair_chart((bars + labels).properties(height=360), width="stretch")

# --- Chart 2: who owes it -----------------------------------------------------

with right:
    st.subheader("By customer")
    customer_order = aging.sort_values("total_open_jpy", ascending=False)["customer_name"].tolist()

    # A 2px outline in the page's background color draws a thin gap between segments
    stacked = alt.Chart(long[long["open_jpy"] > 0]).mark_bar(
        stroke=colors["background"], strokeWidth=2, height={"band": 0.7}
    ).encode(
        y=alt.Y("customer_name:N", sort=customer_order, title=None,
                axis=alt.Axis(labelLimit=240)),   # wide enough for full company names
        x=alt.X("open_jpy:Q", stack="zero", axis=YEN_AXIS),
        color=alt.Color(
            "bucket:N", scale=bucket_scale, title="Days past due",
            # columns=3 wraps the legend onto two rows instead of cutting it off
            legend=alt.Legend(orient="top", direction="horizontal", columns=3),
        ),
        order=alt.Order("bucket_order:Q"),
        tooltip=[
            alt.Tooltip("customer_name:N", title="Customer"),
            alt.Tooltip("bucket:N", title="Days past due"),
            alt.Tooltip("open_jpy:Q", title="Open (¥)", format=","),
        ],
    )
    st.altair_chart(stacked.properties(height=360), width="stretch")

# --- Table view --------------------------------------------------------------

with st.expander("Table view"):
    table = aging[["customer_name", *BUCKETS, "total_open_jpy", "open_invoice_count", "max_days_past_due"]]
    table = table.sort_values("total_open_jpy", ascending=False).rename(
        columns={"customer_name": "Customer", **BUCKETS, "total_open_jpy": "Total open",
                 "open_invoice_count": "Open invoices", "max_days_past_due": "Oldest (days late)"}
    )
    st.dataframe(
        table,
        hide_index=True,
        width="stretch",
        column_config={
            label: st.column_config.NumberColumn(format="¥%,d")
            for label in [*BUCKETS.values(), "Total open"]
        },
    )
