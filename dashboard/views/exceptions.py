"""Exceptions page — the finance team's to-do list. Source: mart_exceptions."""

import altair as alt
import streamlit as st

from common import query, theme_colors, yen, yen_short

TYPE_LABELS = {
    "unpaid_overdue": "Unpaid, overdue",
    "unmatched_payment": "Unmatched payment",
    "overpaid": "Overpaid",
    "partial_payment": "Partial payment",
    "amount_differs_from_order": "Amount differs from order",
    "invoice_without_order": "Invoice without order",
}

colors = theme_colors()

exceptions = query("select * from main.mart_exceptions")
exceptions["type"] = exceptions["exception_type"].map(TYPE_LABELS)


def of_type(exception_type: str):
    return exceptions[exceptions["exception_type"] == exception_type]


st.title("Exceptions")
st.caption("Everything that needs a person to look at it · source: `mart_exceptions` (dbt)")

# --- KPI cards -------------------------------------------------------------

overdue = of_type("unpaid_overdue")
unmatched = of_type("unmatched_payment")
overpaid = of_type("overpaid")

card1, card2, card3, card4 = st.columns(4)
card1.metric("Items to review", len(exceptions), border=True)
card1.caption(f"{exceptions['exception_type'].nunique()} kinds of problem")
card2.metric("Overdue to chase", yen_short(overdue["amount_jpy"].sum()), border=True,
             help=f"{yen(overdue['amount_jpy'].sum())}: send payment reminders (督促)")
card2.caption(f"{len(overdue)} invoices")
card3.metric("Unidentified deposits", yen_short(unmatched["amount_jpy"].sum()), border=True,
             help=f"{yen(unmatched['amount_jpy'].sum())} arrived in the bank but couldn't be "
                  "tied to an invoice")
card3.caption(f"{len(unmatched)} bank transactions")
card4.metric("Refunds owed", yen_short(-overpaid["amount_jpy"].sum()), border=True,
             help=f"{yen(-overpaid['amount_jpy'].sum())} customers paid more than billed")
card4.caption(f"{len(overpaid)} invoices")

# --- Chart: exceptions by type -----------------------------------------------------

st.subheader("Exceptions by type")
by_type = exceptions.groupby("type", as_index=False).agg(
    items=("exception_id", "count"), amount_jpy=("amount_jpy", "sum")
)
type_order = by_type.sort_values("items", ascending=False)["type"].tolist()
bars = alt.Chart(by_type).mark_bar(
    cornerRadiusEnd=4, height={"band": 0.7}, color=colors["series"][0]
).encode(
    y=alt.Y("type:N", sort=type_order, title=None, axis=alt.Axis(labelLimit=220)),
    x=alt.X("items:Q", title="Items", axis=alt.Axis(tickCount=6)),
    tooltip=[
        alt.Tooltip("type:N", title="Type"),
        alt.Tooltip("items:Q", title="Items"),
        alt.Tooltip("amount_jpy:Q", title="Amount involved (¥)", format=","),
    ],
)
counts = bars.mark_text(align="left", dx=4, color=colors["text"]).encode(text="items:Q")
st.altair_chart((bars + counts).properties(height=240), width="stretch")

# --- To-do list ------------------------------------------------------------------------

st.subheader("To-do list")
filter1, filter2 = st.columns(2)
chosen_types = filter1.multiselect("Type", list(TYPE_LABELS.values()), placeholder="All types")
search = filter2.text_input("Search name or ID", placeholder="e.g. サクラ, INV-2042, T-00006")

todo = exceptions
if chosen_types:
    todo = todo[todo["type"].isin(chosen_types)]
if search:
    haystack = todo[["name_on_record", "invoice_id", "transaction_id"]].fillna("").agg(" ".join, axis=1)
    todo = todo[haystack.str.contains(search, case=False, regex=False)]

todo = todo.sort_values("exception_date")   # oldest problems first
columns = ["type", "exception_date", "name_on_record", "invoice_id", "transaction_id",
           "amount_jpy", "next_step"]
st.dataframe(
    todo[columns].fillna({"invoice_id": "", "transaction_id": ""}),   # blank, not "None"
    hide_index=True,
    width="stretch",
    column_config={
        "type": "Type",
        "exception_date": st.column_config.DateColumn("Date"),
        "name_on_record": "Name on record",
        "invoice_id": "Invoice",
        "transaction_id": "Bank txn",
        "amount_jpy": st.column_config.NumberColumn("Amount", format="¥%,d"),
        "next_step": st.column_config.TextColumn("Next step", width="large"),
    },
)
st.download_button(
    f"Download these {len(todo)} rows as CSV",
    todo[columns].to_csv(index=False).encode("utf-8-sig"),   # utf-8-sig so Excel shows Japanese correctly
    file_name="o2c_exceptions.csv",
    mime="text/csv",
)
