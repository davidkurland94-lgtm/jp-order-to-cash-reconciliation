"""Invoice reconciliation page — how well are we collecting? Source: fct_invoice_reconciliation."""

import altair as alt
import pandas as pd
import streamlit as st

from common import YEN_AXIS, query, theme_colors, yen, yen_short

STATUS_LABELS = {
    "paid": "Paid",
    "paid_fee_deducted": "Paid (bank fee deducted)",
    "overpaid": "Overpaid",
    "partial": "Partially paid",
    "unpaid_overdue": "Unpaid, overdue",
    "not_yet_due": "Not yet due",
}
SETTLED = ["paid", "paid_fee_deducted"]

colors = theme_colors()

# The answer key is joined in so the page can show how often the model is right
invoices = query("""
    select f.*, e.expected_status
    from main.fct_invoice_reconciliation as f
    left join main.expected_invoice_status as e on e.invoice_id = f.invoice_id
""")
invoices["status"] = invoices["reconciliation_status"].map(STATUS_LABELS)
as_of_date = pd.to_datetime(invoices["as_of_date"].iloc[0]).date()

st.title("Invoice reconciliation")
st.caption(f"As of {as_of_date:%Y-%m-%d} · one row per invoice · source: `fct_invoice_reconciliation` (dbt)")

# --- Filter (applies to the whole page) --------------------------------------

customers = sorted(invoices["customer_name"].dropna().unique())
chosen = st.multiselect("Customers", customers, placeholder="All customers")
if chosen:
    invoices = invoices[invoices["customer_name"].isin(chosen)]

# --- KPI cards -------------------------------------------------------------

billed = invoices["invoice_amount_jpy"].sum()
collected = invoices["total_received_jpy"].sum()
settled = invoices["reconciliation_status"].isin(SETTLED)
fee_deducted = invoices["reconciliation_status"] == "paid_fee_deducted"
matches_key = invoices["reconciliation_status"] == invoices["expected_status"]

card1, card2, card3, card4 = st.columns(4)
card1.metric("Billed", yen_short(billed), help=yen(billed), border=True)
card1.caption(f"{len(invoices)} invoices")
card2.metric("Collected", yen_short(collected), help=yen(collected), border=True)
card2.caption(f"{collected / billed:.0%} of billed")
card3.metric("Invoices settled", f"{settled.mean():.0%}", border=True,
             help="Paid in full, or short only by a bank transfer fee (振込手数料)")
card3.caption(f"{settled.sum()} of {len(invoices)} · {fee_deducted.sum()} with a fee deducted "
              f"({yen(invoices['bank_fee_jpy'].sum())} absorbed)")
card4.metric("Matches answer key", f"{matches_key.mean():.0%}", border=True,
             help="Share of invoices where the model's status equals the status the data "
                  "generator planted (seeds/expected_invoice_status.csv)")
card4.caption(f"{matches_key.sum()} of {len(invoices)} invoices")

left, right = st.columns(2)

# --- Chart 1: invoices by status ------------------------------------------------

with left:
    st.subheader("Invoices by status")
    by_status = invoices.groupby("status", as_index=False).agg(
        invoices=("invoice_id", "count"), open_jpy=("open_amount_jpy", "sum")
    )
    status_order = [s for s in STATUS_LABELS.values() if s in set(by_status["status"])]
    bars = alt.Chart(by_status).mark_bar(
        cornerRadiusEnd=4, height={"band": 0.7}, color=colors["series"][0]
    ).encode(
        y=alt.Y("status:N", sort=status_order, title=None, axis=alt.Axis(labelLimit=200)),
        x=alt.X("invoices:Q", title="Invoices"),
        tooltip=[
            alt.Tooltip("status:N", title="Status"),
            alt.Tooltip("invoices:Q", title="Invoices"),
            alt.Tooltip("open_jpy:Q", title="Open (¥)", format=","),
        ],
    )
    counts = bars.mark_text(align="left", dx=4, color=colors["text"]).encode(text="invoices:Q")
    st.altair_chart((bars + counts).properties(height=300), width="stretch")

# --- Chart 2: billed vs collected by month ----------------------------------------

with right:
    st.subheader("Billed vs collected, by invoice month")
    monthly = (
        invoices.assign(month=pd.to_datetime(invoices["invoice_date"]).dt.strftime("%Y-%m"))
        .groupby("month", as_index=False)[["invoice_amount_jpy", "total_received_jpy"]].sum()
        .rename(columns={"invoice_amount_jpy": "Billed", "total_received_jpy": "Collected"})
        .melt(id_vars="month", var_name="measure", value_name="amount_jpy")
    )
    grouped = alt.Chart(monthly).mark_bar(cornerRadiusEnd=4).encode(
        x=alt.X("month:N", title=None, axis=alt.Axis(labelAngle=0)),
        xOffset=alt.XOffset("measure:N", sort=["Billed", "Collected"]),
        y=alt.Y("amount_jpy:Q", axis=YEN_AXIS),
        color=alt.Color(
            "measure:N", sort=["Billed", "Collected"], title=None,
            scale=alt.Scale(domain=["Billed", "Collected"], range=colors["series"]),
            legend=alt.Legend(orient="top", direction="horizontal"),
        ),
        tooltip=[
            alt.Tooltip("month:N", title="Invoice month"),
            alt.Tooltip("measure:N", title=" "),
            alt.Tooltip("amount_jpy:Q", title="¥", format=","),
        ],
    )
    st.altair_chart(grouped.properties(height=300), width="stretch")
    st.caption("Recent months show less collected because many of those invoices aren't due yet.")

# --- Chart 3: when do customers pay? (a true histogram) ------------------------------

st.subheader("When customers pay, relative to the due date")
paid = invoices[invoices["last_paid_on_date"].notna() & invoices["reconciliation_status"].isin(
    SETTLED + ["overpaid"])].copy()
paid["days_vs_due"] = (pd.to_datetime(paid["last_paid_on_date"]) - pd.to_datetime(paid["due_date"])).dt.days

if paid.empty:
    st.info("No settled invoices for this selection.")
else:
    paid["timing"] = paid["days_vs_due"].map(lambda d: "Late" if d > 0 else "On time or early")
    late = paid[paid["timing"] == "Late"]
    st.caption(
        f"{len(paid)} settled invoices · {1 - len(late) / len(paid):.0%} paid on or before the "
        f"due date · {len(late)} paid late, by {late['days_vs_due'].median():.0f} days (median)"
        if len(late) else f"{len(paid)} settled invoices · all paid on or before the due date"
    )
    # 1-day bins: most payments land within a few days of the due date, so wider
    # bins would hide the shape. Late payments get the second color so the small
    # tail still stands out next to the tall on-time bars.
    timing_order = ["On time or early", "Late"]
    histogram = alt.Chart(paid).mark_bar(
        cornerRadiusEnd=4, stroke=colors["background"], strokeWidth=2
    ).encode(
        x=alt.X("days_vs_due:Q", bin=alt.Bin(step=1),
                title="Days paid after the due date (negative = early)",
                axis=alt.Axis(tickCount=12)),
        y=alt.Y("count():Q", title="Invoices"),
        color=alt.Color(
            "timing:N", sort=timing_order, title=None,
            scale=alt.Scale(domain=timing_order, range=colors["series"]),
            legend=alt.Legend(orient="top", direction="horizontal"),
        ),
        tooltip=[
            alt.Tooltip("days_vs_due:Q", title="Days after due date"),
            alt.Tooltip("count():Q", title="Invoices"),
        ],
    )
    # Count labels on the late bars only: they're 1–2 invoices tall, easy to miss
    late_counts = late.groupby("days_vs_due", as_index=False).size()
    late_counts["bar_middle"] = late_counts["days_vs_due"] + 0.5   # bin [d, d+1) is centered here
    late_labels = alt.Chart(late_counts).mark_text(dy=-8, color=colors["text"]).encode(
        x="bar_middle:Q",
        y="size:Q",
        text="size:Q",
    )
    st.altair_chart((histogram + late_labels).properties(height=260), width="stretch")

# --- Invoice table -----------------------------------------------------------------

st.subheader("Invoices")
chosen_status = st.multiselect("Status", list(STATUS_LABELS.values()), placeholder="All statuses")
table = invoices if not chosen_status else invoices[invoices["status"].isin(chosen_status)]
# Settled invoices have no days_past_due (null from the model), so show them blank.
# pandas stores a number column with nulls as decimals (123.0), so convert back to whole numbers.
table = table.assign(days_past_due=table["days_past_due"].map(
    lambda days: "" if pd.isna(days) else str(int(days))
))
st.dataframe(
    table[["invoice_id", "customer_name", "invoice_date", "due_date", "invoice_amount_jpy",
           "total_received_jpy", "open_amount_jpy", "status", "days_past_due", "payment_count"]]
    .sort_values("invoice_id"),
    hide_index=True,
    width="stretch",
    column_config={
        "invoice_id": "Invoice",
        "customer_name": "Customer",
        "invoice_date": st.column_config.DateColumn("Invoiced"),
        "due_date": st.column_config.DateColumn("Due"),
        "invoice_amount_jpy": st.column_config.NumberColumn("Billed", format="¥%,d"),
        "total_received_jpy": st.column_config.NumberColumn("Received", format="¥%,d"),
        "open_amount_jpy": st.column_config.NumberColumn("Open", format="¥%,d"),
        "status": st.column_config.TextColumn("Status", width="medium"),
        "days_past_due": "Days late",
        "payment_count": "Payments",
    },
)
