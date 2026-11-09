"""
dashboard/app.py — entry point for the Streamlit dashboard over the dbt marts.

Run from the repo root:
    streamlit run dashboard/app.py

If o2c.duckdb doesn't exist yet (fresh clone), the app builds it first by running
load_raw_data.py and dbt build, so anyone can try it with one command.

Each page lives in dashboard/views/. st.navigation builds the sidebar menu from the
list below and runs whichever page is selected.
"""

import streamlit as st

from common import build_database, marts_exist

st.set_page_config(page_title="Order-to-Cash", page_icon="💴", layout="wide")

if not marts_exist():
    st.info("First run: building the database from raw_data/ (takes about 30 seconds).")
    build_database()
    st.cache_data.clear()
    st.rerun()

page = st.navigation([
    st.Page("views/aging.py", title="AR aging", icon=":material/hourglass_bottom:", default=True),
    st.Page("views/reconciliation.py", title="Invoice reconciliation", icon=":material/receipt_long:"),
    st.Page("views/exceptions.py", title="Exceptions", icon=":material/report:"),
])
page.run()
