"""
common.py — helpers shared by every dashboard page: building/reading the database,
yen formatting, and chart colors that work in both light and dark mode.
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


# ---------------------------------------------------------------------------
# Database
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
# Formatting
# ---------------------------------------------------------------------------

def yen(amount: float) -> str:
    return f"-¥{-amount:,.0f}" if amount < 0 else f"¥{amount:,.0f}"


def yen_short(amount: float) -> str:
    return f"¥{amount / 1_000_000:,.1f}M"


# Axis labels in millions of yen: ¥0M, ¥10M, ...
YEN_AXIS = alt.Axis(labelExpr="'¥' + format(datum.value / 1000000, ',.0f') + 'M'", title=None)


# ---------------------------------------------------------------------------
# Colors (all checked with a palette validator, in both light and dark mode)
# ---------------------------------------------------------------------------

def theme_colors() -> dict:
    dark = st.context.theme.type == "dark"
    return {
        # Ordered blues for aging buckets: lighter = more recent, darker = later
        "buckets": ["#9ec5f4", "#6da7ec", "#3987e5", "#256abf", "#184f95"] if dark
                   else ["#86b6ef", "#5598e7", "#2a78d6", "#1c5cab", "#104281"],
        # Two distinct series (blue, orange) for comparisons like billed vs collected
        "series": ["#3987e5", "#d95926"] if dark else ["#2a78d6", "#eb6834"],
        # Text and background match Streamlit's own theme
        "text": "#fafafa" if dark else "#31333f",
        "background": "#0e1117" if dark else "#ffffff",
    }
