"""Streamlit dashboard for AAM Lignum.

Multi-page app with:
- Importar: PDF upload, parsing, and match review
- Asset Allocation: Positions table with macro/micro consolidation
- RF Carrego: Fixed income carry analysis

Run with: streamlit run src/dashboard/app.py
"""

import sys
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import streamlit as st

from config.settings import STREAMLIT_PAGE_TITLE
from src.dashboard.components.sidebar import render_sidebar
from src.dashboard.pages.import_page import render_import
from src.dashboard.pages.aa_page import render_aa
from src.dashboard.pages.rf_carrego_page import render_rf
from src.dashboard.pages.consulta_page import render_consulta


def init_session_state():
    """Initialize session state variables."""
    defaults = {
        "client_id": None,
        "client_name": "",
        "parsed_assets": None,
        "match_results": None,
        "last_upload_results": None,
        "last_upload_id": None,
        "registry": None,
        "engine": None,
        "db": None,
        "aa_targets": {},
    }
    for key, val in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = val


def main():
    """Main Streamlit app entry point."""
    st.set_page_config(
        page_title=STREAMLIT_PAGE_TITLE,
        page_icon=":material/monitoring:",
        layout="wide",
    )

    init_session_state()

    # Multi-page navigation
    pages = [
        st.Page(render_import, title="Importar", icon=":material/upload_file:"),
        st.Page(render_aa, title="Asset Allocation", icon=":material/pie_chart:"),
        st.Page(render_rf, title="RF Carrego", icon=":material/account_balance:"),
        st.Page(render_consulta, title="Consulta", icon=":material/search:"),
    ]

    nav = st.navigation(pages)
    render_sidebar()
    nav.run()


if __name__ == "__main__":
    main()
