"""Home page - landing page with Lignum symbol."""

from pathlib import Path

import streamlit as st

PROJECT_ROOT = Path(__file__).parent.parent.parent.parent
LOGO_CANDIDATES = [
    PROJECT_ROOT / "lignum_symbol.jpeg",
    PROJECT_ROOT / "lignum symbol.jpeg",
]


def _find_logo():
    for path in LOGO_CANDIDATES:
        if path.exists():
            return path
    return None


def render_home():
    """Render the home/landing page."""
    _, col, _ = st.columns([1, 2, 1])
    with col:
        logo = _find_logo()
        if logo is not None:
            st.image(str(logo), use_container_width=True)
        else:
            st.warning(
                "Imagem nao encontrada. Procurado em: "
                + ", ".join(str(p) for p in LOGO_CANDIDATES)
            )
