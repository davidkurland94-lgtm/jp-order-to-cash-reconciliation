"""
dashboard/app.py — Streamlit dashboard over the dbt marts.

Run from the repo root:
    streamlit run dashboard/app.py

If o2c.duckdb doesn't exist yet (fresh clone), the app builds it first by running
load_raw_data.py and dbt build, so anyone can try it with one command.
"""

import shutil
import subprocess
import sys
from pathlib import Path

import altair as alt
import duckdb
import pandas as pd
import streamlit as st

REPO_ROOT = Path(__file__).resolve().parent.parent
DATABASE_FILE = REPO_ROOT / "o2c.duckdb"

# Aging buckets in order, from mart_ar_aging's column names to display labels
BUCKETS = {
    "current_jpy": "Current",
    "days_1_30_jpy": "1–30 days",
    "days_31_60_jpy": "31–60 days",
    "days_61_90_jpy": "61–90 days",
    "days_over_90_jpy": "90+ days",
}

# One blue, light -> dark = later -> worse. Checked with a palette validator:
# each step is visibly different from its neighbor, and the faintest step still
# stands out from the background. Dark mode uses its own steps of the same blue.
BUCKET_COLORS = {
    "light": ["#86b6ef", "#5598e7", "#2a78d6", "#1c5cab", "#104281"],
    "dark": ["#9ec5f4", "#6da7ec", "#3987e5", "#256abf", "#184f95"],
}


# ---------------------------------------------------------------------------
# Data
# ---------------------------------------------------------------------------

def find_dbt() -> str:
    """Prefer the dbt installed next to this Python (same venv), else whatever is on PATH."""
    beside_python = Path(sys.executable).parent / "dbt"
    return str(beside_python) if beside_python.exists() else (shutil.which("dbt") or "dbt")


def marts_exist() -> bool:
    if not DATABASE_FILE.exists():
        return False
    with duckdb.connect(str(DATABASE_FILE), read_only=True) as con:
        found = con.execute(
            "select count(*) from information_schema.tables where table_name = 'mart_ar_aging'"
        ).fetchone()[0]
    return found > 0


def build_database() -> None:
    """Same steps as CI: load the raw CSVs, then let dbt build everything."""
    steps = [
        ("Loading raw CSVs into DuckDB", [sys.executable, "load_raw_data.py"]),
        ("Installing dbt packages", [find_dbt(), "deps"]),
        ("Running dbt build", [find_dbt(), "build"]),
    ]
    for label, command in steps:
        with st.spinner(f"{label}…"):
            result = subprocess.run(command, cwd=REPO_ROOT, capture_output=True, text=True)
        if result.returncode != 0:
            st.error(f"{label} failed")
            st.code(result.stdout[-3000:] + result.stderr[-3000:])
            st.stop()


@st.cache_data
def query(sql: str) -> pd.DataFrame:
    # Open and close a read-only connection per query, so the app never holds a
    # lock that would stop you running `dbt build` while the dashboard is open.
    with duckdb.connect(str(DATABASE_FILE), read_only=True) as con:
        return con.execute(sql).df()


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------

def yen(amount: float) -> str:
    return f"¥{amount:,.0f}"


def yen_short(amount: float) -> str:
    return f"¥{amount / 1_000_000:,.1f}M"


# ---------------------------------------------------------------------------
# Page
# ---------------------------------------------------------------------------

st.set_page_config(page_title="AR Aging", page_icon="💴", layout="wide")

if not marts_exist():
    st.info("First run: building the database from raw_data/ (takes about 30 seconds).")
    build_database()
    st.cache_data.clear()
    st.rerun()

aging = query("select * from main.mart_ar_aging")
latest_payment = query("""
    select p.paid_on_date, p.amount_paid_jpy, p.payer_name, p.invoice_id, p.match_method,
           c.official_name as customer_name
    from main.int_payments_matched as p
    left join main.int_customer_names as n on n.name_variant = p.payer_name
    left join main.stg_customers as c on c.customer_id = n.customer_id
    order by p.paid_on_date desc, p.transaction_id desc
    limit 1
""").iloc[0]

as_of_date = pd.to_datetime(aging["as_of_date"].iloc[0]).date()
aging["overdue_jpy"] = aging["total_open_jpy"] - aging["current_jpy"]
worst = aging.sort_values("overdue_jpy", ascending=False).iloc[0]

theme = st.context.theme.type or "light"
colors = BUCKET_COLORS["dark" if theme == "dark" else "light"]

st.title("Accounts receivable aging")
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
card3.caption(
    f"{worst['customer_name']} · oldest invoice {worst['max_days_past_due']:.0f} days late"
)
card4.metric(
    "Latest payment",
    yen(latest_payment["amount_paid_jpy"]),
    help=f"Bank payer name: {latest_payment['payer_name']}",
    border=True,
)
matched_to = (
    f"→ {latest_payment['invoice_id']}" if latest_payment["match_method"] != "unmatched"
    else "→ not matched to an invoice"
)
card4.caption(
    f"{latest_payment['paid_on_date']:%Y-%m-%d} · "
    f"{latest_payment['customer_name'] or latest_payment['payer_name']} {matched_to}"
)

# --- Long format for charts: one row per customer per bucket ----------------

long = aging.melt(
    id_vars=["customer_name"],
    value_vars=list(BUCKETS),
    var_name="bucket_column",
    value_name="open_jpy",
)
long["bucket"] = long["bucket_column"].map(BUCKETS)
long["bucket_order"] = long["bucket_column"].map({c: i for i, c in enumerate(BUCKETS)})

bucket_scale = alt.Scale(domain=list(BUCKETS.values()), range=colors)
yen_axis = alt.Axis(labelExpr="'¥' + format(datum.value / 1000000, ',.0f') + 'M'", title=None)

# --- Chart 1: how much is owed at each level of lateness --------------------

left, right = st.columns([2, 3])

with left:
    st.subheader("Open amount by days past due")
    by_bucket = long.groupby(["bucket", "bucket_order"], as_index=False)["open_jpy"].sum()
    by_bucket["label"] = by_bucket["open_jpy"].map(yen_short)

    bars = alt.Chart(by_bucket).mark_bar(cornerRadiusEnd=4, width={"band": 0.8}).encode(
        x=alt.X("bucket:N", sort=list(BUCKETS.values()), title=None, axis=alt.Axis(labelAngle=0)),
        y=alt.Y("open_jpy:Q", axis=yen_axis),
        color=alt.Color("bucket:N", scale=bucket_scale, legend=None),
        tooltip=[
            alt.Tooltip("bucket:N", title="Days past due"),
            alt.Tooltip("open_jpy:Q", title="Open (¥)", format=","),
        ],
    )
    # Text uses the page's text color, not the bar color (Streamlit's defaults)
    text_color = "#fafafa" if theme == "dark" else "#31333f"
    labels = alt.Chart(by_bucket).mark_text(dy=-8, fontSize=12, color=text_color).encode(
        x=alt.X("bucket:N", sort=list(BUCKETS.values())),
        y="open_jpy:Q",
        text="label:N",
    )
    st.altair_chart((bars + labels).properties(height=360), width="stretch")

# --- Chart 2: who owes it -----------------------------------------------------

with right:
    st.subheader("Open amount by customer")
    customer_order = aging.sort_values("total_open_jpy", ascending=False)["customer_name"].tolist()

    # A 2px outline in the page's background color draws a thin gap between segments
    background = "#0e1117" if theme == "dark" else "#ffffff"
    stacked = alt.Chart(long[long["open_jpy"] > 0]).mark_bar(
        stroke=background, strokeWidth=2, height={"band": 0.7}
    ).encode(
        y=alt.Y("customer_name:N", sort=customer_order, title=None,
                axis=alt.Axis(labelLimit=240)),   # wide enough for full company names
        x=alt.X("open_jpy:Q", stack="zero", axis=yen_axis),
        color=alt.Color(
            "bucket:N", scale=bucket_scale, title="Days past due",
            legend=alt.Legend(orient="top", direction="horizontal"),
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
