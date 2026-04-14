"""Home page - landing page with Lignum symbol."""

from pathlib import Path

import streamlit as st

PROJECT_ROOT = Path(__file__).parent.parent.parent.parent
LOGO_PATH = PROJECT_ROOT / "lignum symbol.jpeg"


def render_home():
    """Render the home/landing page."""
    _, col, _ = st.columns([1, 2, 1])
    with col:
        if LOGO_PATH.exists():
            st.image(str(LOGO_PATH), use_container_width=True)
        else:
            st.warning(f"Imagem nao encontrada: {LOGO_PATH}")
