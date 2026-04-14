"""Shared sidebar component for the dashboard."""

import time
import streamlit as st

from config.settings import UPLOADS_DIR
from src.db.sheets_storage import SheetsStorage
from src.parsers import get_parser, available_brokers
from src.matching.engine import MatchingEngine, MatchResult
from src.matching.registry import AssetRegistry
from src.sheets.client import SheetsClient


def get_db() -> SheetsStorage:
    """Get or create the storage (Google Sheets backed)."""
    if st.session_state.get("db") is None:
        st.session_state.db = SheetsStorage(get_sheets_client())
    return st.session_state.db


def get_sheets_client() -> SheetsClient:
    """Get or create the Google Sheets client (cached in session state)."""
    if st.session_state.get("sheets_client") is None:
        st.session_state.sheets_client = SheetsClient()
    return st.session_state.sheets_client


REGISTRY_TTL = 30  # seconds - auto-refresh registry every 30s


def get_registry() -> AssetRegistry:
    """Get the registry, auto-refreshing from Sheets every REGISTRY_TTL seconds."""
    now = time.time()
    last_loaded = st.session_state.get("registry_loaded_at", 0)

    if st.session_state.get("registry") is None or (now - last_loaded) > REGISTRY_TTL:
        registry = AssetRegistry()
        client = get_sheets_client()
        if client.is_authenticated or client._authenticate():
            # Force refresh from sheets (bypasses sheets cache)
            client._cache = None
            registry.load(force_refresh=True, sheets_client=client)
        else:
            registry.load()
        st.session_state.registry = registry
        st.session_state.registry_loaded_at = now
        # Reset engine so it uses the fresh registry
        st.session_state.engine = None
    return st.session_state.registry


def get_engine() -> MatchingEngine:
    """Get or create the matching engine."""
    if st.session_state.get("engine") is None:
        st.session_state.engine = MatchingEngine(get_registry())
    return st.session_state.engine


def refresh_registry():
    """Force reload the registry from Google Sheets (sync latest changes)."""
    client = get_sheets_client()
    # Invalidate sheets client cache
    client._cache = None
    # Rebuild registry from fresh sheet data
    registry = AssetRegistry()
    if client.is_authenticated or client._authenticate():
        registry.load(force_refresh=True, sheets_client=client)
    else:
        registry.load(force_refresh=True)
    st.session_state.registry = registry
    st.session_state.engine = None  # Force engine rebuild on next access


def load_client_positions() -> list[MatchResult]:
    """Load all positions for the current client from DB and build MatchResults."""
    client_id = st.session_state.get("client_id")
    if not client_id:
        return []

    db = get_db()
    positions = db.get_positions(client_id)
    if not positions:
        return []

    registry = get_registry()
    results = []

    for pos in positions:
        r = MatchResult(
            pdf_name=pos["pdf_name"],
            value=pos["value"],
            source=pos["source"],
        )
        r.status = pos["status"]

        # Try to find the registry asset
        reg_nome = pos["registry_nome"] or pos["pdf_name"]
        match = registry.find_match(reg_nome)
        if match:
            r.registry_asset = match
            if r.status == "unmatched":
                r.status = "exact"
        elif pos["registry_nome"]:
            match = registry.find_match(pos["registry_nome"])
            if match:
                r.registry_asset = match

        r.confidence = 1.0 if r.status in ("exact", "fuzzy", "manual") else 0.0
        results.append(r)

    return results


def render_sidebar():
    """Render the shared sidebar with client management and PDF upload."""
    db = get_db()

    with st.sidebar:
        st.header("AAM Lignum")
        st.divider()

        # --- Client Management ---
        st.subheader("Cliente")
        clients = db.list_clients()
        client_names = [c["name"] for c in clients]

        if client_names:
            # Build options: existing clients
            selected_name = st.selectbox(
                "Selecionar cliente",
                client_names,
                index=client_names.index(st.session_state.get("client_name", client_names[0]))
                if st.session_state.get("client_name") in client_names
                else 0,
                key="client_selector",
            )

            # Find the client id
            selected_client = next(c for c in clients if c["name"] == selected_name)
            if st.session_state.get("client_id") != selected_client["id"]:
                st.session_state.client_id = selected_client["id"]
                st.session_state.client_name = selected_client["name"]
                # Clear current results when switching clients
                st.session_state.match_results = None
                st.session_state.last_upload_results = None
                st.rerun()
        else:
            st.info("Nenhum cliente cadastrado.")

        # New client
        with st.expander("Novo Cliente"):
            new_name = st.text_input("Nome do cliente", key="new_client_name")
            if st.button("Criar", key="create_client") and new_name.strip():
                existing = [c["name"].lower() for c in clients]
                if new_name.strip().lower() in existing:
                    st.error(f"Cliente '{new_name.strip()}' ja existe. Selecione na lista acima.")
                else:
                    try:
                        client_id = db.create_client(new_name.strip())
                        st.session_state.client_id = client_id
                        st.session_state.client_name = new_name.strip()
                        st.session_state.match_results = None
                        st.session_state.last_upload_results = None
                        st.success(f"Cliente '{new_name.strip()}' criado!")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Erro: {e}")

        st.divider()

        # --- PDF Upload (only if client selected) ---
        if st.session_state.get("client_id"):
            st.subheader("Upload do Relatorio")
            brokers = available_brokers()
            broker = st.selectbox("Corretora", brokers, index=0)

            ref_date = st.text_input(
                "Data referencia (mes/ano)",
                placeholder="Ex: 03/2026",
                key="ref_date",
            )

            uploaded_file = st.file_uploader(
                "Selecione o PDF mensal",
                type=["pdf"],
                help="Relatorio mensal de investimentos da corretora",
            )

            if uploaded_file is not None:
                client_id = st.session_state.client_id

                if st.button("Processar PDF", type="primary", use_container_width=True):
                    with st.spinner("Atualizando cadastro..."):
                        refresh_registry()

                    with st.spinner("Extraindo ativos do PDF..."):
                        # Save to temp file for parsing (pdfplumber/fitz need a path)
                        import tempfile
                        with tempfile.NamedTemporaryFile(
                            suffix=".pdf", delete=False
                        ) as tmp:
                            tmp.write(uploaded_file.getvalue())
                            tmp_path = tmp.name

                        try:
                            parser = get_parser(broker)
                            parsed = parser.parse(tmp_path)
                        finally:
                            # Delete temp file after parsing
                            import os
                            try:
                                os.unlink(tmp_path)
                            except OSError:
                                pass

                        # Match
                        engine = get_engine()
                        results = engine.match(parsed)

                        # Save to DB
                        upload_id = db.create_upload(
                            client_id, uploaded_file.name, broker, ref_date
                        )
                        pos_rows = []
                        for r in results:
                            pos_rows.append({
                                "pdf_name": r.pdf_name,
                                "value": r.value,
                                "source": r.source,
                                "status": r.status,
                                "registry_nome": r.registry_asset.get("nome") if r.registry_asset else None,
                            })
                        db.save_positions(client_id, upload_id, pos_rows)

                        # Store last upload results for review
                        st.session_state.last_upload_results = results
                        st.session_state.last_upload_id = upload_id
                        st.rerun()

            st.divider()

        # --- Registry info ---
        registry = get_registry()
        sheets_client = get_sheets_client()
        mode = "gspread" if sheets_client.is_authenticated else "CSV (read-only)"
        st.caption(f"Ativos no cadastro: {len(registry)}")
        st.caption(f"Modo: {mode}")

        if st.button("Atualizar Cadastro", use_container_width=True):
            refresh_registry()
            st.success("Cadastro atualizado!")
