"""Import page - PDF upload, parsing, match review, and position management."""

import pandas as pd
import streamlit as st

from src.dashboard.components.formatters import format_brl
from src.dashboard.components.sidebar import (
    get_db, get_engine, get_registry, get_sheets_client, load_client_positions,
    refresh_registry,
)
from src.matching.engine import MatchResult


def render_import():
    """Render the import/review page."""
    client_id = st.session_state.get("client_id")

    if not client_id:
        st.title("Importar")
        st.warning("Selecione ou crie um cliente na barra lateral.")
        return

    client_name = st.session_state.get("client_name", "Cliente")
    st.title(f"Importar - {client_name}")

    _render_uploads_table(client_id)
    st.divider()

    last_results = st.session_state.get("last_upload_results")
    if last_results:
        _render_review(last_results)
        st.divider()

    _render_all_positions(client_id)


def _render_uploads_table(client_id: int):
    """Show uploads already done for this client."""
    db = get_db()
    uploads = db.list_uploads(client_id)

    if not uploads:
        st.info("Nenhum upload realizado. Faca o upload de um PDF na barra lateral.")
        return

    st.subheader(f"Uploads ({len(uploads)})")
    upload_data = [{
        "ID": u["id"],
        "Arquivo": u["filename"],
        "Corretora": u["broker"],
        "Referencia": u["reference_date"] or "-",
        "Posicoes": u["position_count"],
        "Data Upload": u["uploaded_at"][:16] if u["uploaded_at"] else "",
    } for u in uploads]
    st.dataframe(pd.DataFrame(upload_data), use_container_width=True, hide_index=True)

    with st.expander("Remover upload"):
        upload_ids = [u["id"] for u in uploads]
        upload_labels = [f"#{u['id']} - {u['filename']} ({u['broker']})" for u in uploads]
        selected = st.selectbox("Selecionar upload para remover:", upload_labels, key="del_upload")
        if st.button("Remover", key="btn_del_upload", type="secondary"):
            idx = upload_labels.index(selected)
            db.delete_upload(upload_ids[idx])
            st.session_state.last_upload_results = None
            st.success("Upload e posicoes removidos!")
            st.rerun()


def _render_review(results: list[MatchResult]):
    """Show match review for the last upload."""
    engine = get_engine()
    summary = engine.get_summary(results)

    st.subheader("Resultado do Ultimo Upload")

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Total", summary["total"])
    col2.metric("Exato", len(summary["exact"]))
    col3.metric("Fuzzy", len(summary["fuzzy"]))
    col4.metric("Sem Match", len(summary["unmatched"]))

    # Exact matches
    if summary["exact"]:
        with st.expander(f"Matches Exatos ({len(summary['exact'])})", expanded=False):
            exact_data = [{
                "PDF": r.pdf_name,
                "Cadastro": r.nome_1,
                "Valor": format_brl(r.value),
                "Macro": r.macro_classe,
            } for r in summary["exact"]]
            st.dataframe(pd.DataFrame(exact_data), use_container_width=True, hide_index=True)

    # Fuzzy matches
    if summary["fuzzy"]:
        with st.expander(f"Matches Aproximados ({len(summary['fuzzy'])})", expanded=True):
            for i, r in enumerate(summary["fuzzy"]):
                with st.container(border=True):
                    st.write(f"**PDF:** {r.pdf_name} -> **Match ({r.confidence:.0%}):** {r.nome_1} | {format_brl(r.value)}")
                    col_c, col_r = st.columns(2)
                    with col_c:
                        if st.button("Confirmar", key=f"fc_{i}", type="primary"):
                            engine.confirm_match(r, r.registry_asset)
                            _update_db_match_by_id(r, "manual", r.registry_asset.get("nome"))
                            st.rerun()
                    with col_r:
                        if st.button("Rejeitar", key=f"fr_{i}"):
                            r.status = "unmatched"
                            r.registry_asset = {}
                            _update_db_match_by_id(r, "unmatched", None)
                            st.rerun()

    # Unmatched
    if summary["unmatched"]:
        _render_unmatched(summary["unmatched"])


def _render_unmatched(unmatched: list[MatchResult]):
    """Render unmatched assets with Cadastro Novo / Match options."""
    st.subheader(f"Sem Match ({len(unmatched)})")

    engine = get_engine()
    registry = get_registry()

    for i, r in enumerate(unmatched):
        with st.container(border=True):
            st.write(f"**{r.pdf_name}** | {format_brl(r.value)}")

            action = st.radio(
                "Acao:",
                ["Cadastro Novo", "Match com existente"],
                key=f"action_{i}",
                horizontal=True,
            )

            if action == "Cadastro Novo":
                nome1 = st.text_input(
                    "Nome 1 (nome padronizado):",
                    key=f"nome1_{i}",
                    placeholder="Ex: CDB Agibank - 16,25% - Vencimento 12/01/2027",
                )

                if nome1.strip():
                    if st.button("Confirmar cadastro", key=f"cnew_{i}", type="primary"):
                        # Use Nome 1 as the name in both columns if pdf_name is corrupted
                        # (e.g., "3" for stock tickers)
                        pdf_name = r.pdf_name.strip()
                        display_name = nome1.strip()

                        # For corrupted tickers (just digits), use Nome 1 as Nome too
                        if pdf_name.isdigit() or len(pdf_name) <= 3:
                            sheet_nome = display_name
                        else:
                            sheet_nome = pdf_name

                        success = _send_single_to_sheets(sheet_nome, display_name)
                        if success:
                            # Update DB: set registry_nome to the nome we sent to sheets
                            _update_db_match_by_id(r, "manual", sheet_nome)
                            st.rerun()

            else:  # Match com existente
                search = st.text_input(
                    "Buscar no cadastro:",
                    key=f"msrch_{i}",
                    placeholder="Digite para buscar...",
                )

                candidates = []
                if r.fuzzy_candidates:
                    candidates = list(r.fuzzy_candidates[:5])

                if search:
                    search_results = registry.find_fuzzy_match(search, threshold=0.3)
                    existing_nomes = {c["nome"] for c in candidates}
                    for sr in search_results[:10]:
                        if sr["nome"] not in existing_nomes:
                            candidates.append(sr)

                if candidates:
                    options = [f"{c['nome']} ({c['score']:.0%})" for c in candidates]
                    selected = st.selectbox("Selecionar:", options, key=f"msel_{i}")

                    if st.button("Confirmar match", key=f"cmatch_{i}", type="primary"):
                        idx = options.index(selected)
                        engine.confirm_match(r, candidates[idx]["asset"])
                        _update_db_match_by_id(r, "manual", candidates[idx]["asset"].get("nome"))
                        st.rerun()
                else:
                    if not search:
                        st.caption("Digite acima para buscar no cadastro.")
                    else:
                        st.caption("Nenhum resultado encontrado.")


def _send_single_to_sheets(nome: str, nome_1: str) -> bool:
    """Send Nome + Nome 1 to Google Sheets. Returns True on success."""
    sheets_client = get_sheets_client()
    if not sheets_client.is_authenticated:
        st.warning("Configure credentials.json para enviar ao Google Sheets.")
        return False

    try:
        ws = sheets_client.get_worksheet()
        if ws is None:
            st.error("Nao foi possivel conectar ao Google Sheets.")
            return False

        # Check if this exact nome already exists
        existing = sheets_client.get_existing_names()
        if nome.strip() in existing:
            st.info(f"'{nome}' ja existe na Base de Dados.")
            return True  # Already exists, treat as success

        col_a = ws.col_values(1)
        next_row = len(col_a) + 1
        ws.update(f"A{next_row}", [[nome, nome_1]])
        sheets_client._cache = None

        # Auto-refresh registry so new asset is immediately available for matching
        refresh_registry()

        st.success(f"Cadastrado: {nome} | {nome_1}")
        return True
    except Exception as e:
        st.error(f"Erro ao enviar: {e}")
        return False


def _render_all_positions(client_id: int):
    """Show all positions consolidated for the client with delete option."""
    db = get_db()
    positions = db.get_positions(client_id)
    if not positions:
        return

    registry = get_registry()
    total = sum(p["value"] for p in positions)

    st.subheader(f"Todas as Posicoes ({len(positions)})")
    st.metric("Patrimonio Total", format_brl(total))

    rows = []
    for p in positions:
        reg_nome = p["registry_nome"] or p["pdf_name"]
        match = registry.find_match(reg_nome)
        nome_display = match.get("nome_1", p["pdf_name"]) if match else p["pdf_name"]
        rows.append({
            "ID": p["id"],
            "Ativo": nome_display,
            "Valor": format_brl(p["value"]),
            "Status": p["status"],
            "Fonte": p["source"],
        })

    st.dataframe(
        pd.DataFrame(rows)[["Ativo", "Valor", "Status", "Fonte"]],
        use_container_width=True,
        hide_index=True,
    )

    pos_labels = [f"{r['Ativo']} | {r['Valor']} ({r['Fonte']})" for r in rows]
    pos_ids = [r["ID"] for r in rows]

    # Edit position match
    with st.expander("Editar vinculo de posicao"):
        st.caption(
            "Altere o ativo vinculado a uma posicao (troca para outro cadastro existente "
            "ou cria novo cadastro na Base de Dados)."
        )
        sel_edit = st.selectbox("Selecionar posicao:", pos_labels, key="edit_pos_select")
        edit_idx = pos_labels.index(sel_edit)
        edit_pos = positions[edit_idx]
        edit_pos_id = pos_ids[edit_idx]

        # Show current link
        current_reg_nome = edit_pos["registry_nome"] or edit_pos["pdf_name"]
        current_match = registry.find_match(current_reg_nome)
        current_nome1 = current_match.get("nome_1", "") if current_match else ""

        st.info(
            f"**Nome PDF:** {edit_pos['pdf_name']}  \n"
            f"**Nome cadastro atual:** {current_reg_nome}  \n"
            f"**Nome 1 atual:** {current_nome1 or '(sem match)'}"
        )

        action = st.radio(
            "Acao:",
            ["Vincular a outro cadastro", "Criar novo cadastro"],
            key="edit_action",
            horizontal=True,
        )

        if action == "Vincular a outro cadastro":
            search = st.text_input(
                "Buscar no cadastro:",
                key="edit_search",
                placeholder="Digite para buscar...",
            )
            if search:
                matches = registry.find_fuzzy_match(search, threshold=0.3)
                if matches:
                    sopts = [f"{m['nome']} - {m['asset'].get('nome_1','')} ({m['score']:.0%})" for m in matches[:15]]
                    sel = st.selectbox("Resultados:", sopts, key="edit_search_result")
                    if st.button("Confirmar vinculo", key="edit_confirm", type="primary"):
                        idx = sopts.index(sel)
                        new_nome = matches[idx]["asset"]["nome"]
                        db.update_position_match(edit_pos_id, "manual", new_nome)
                        st.success(f"Vinculado a: {new_nome}")
                        st.rerun()
                else:
                    st.caption("Nenhum resultado encontrado.")

        else:  # Criar novo cadastro
            new_nome1 = st.text_input(
                "Nome 1 (nome padronizado do novo cadastro):",
                key="edit_new_nome1",
                placeholder="Ex: CDB Agibank - 16,25% - Vencimento 12/01/2027",
            )
            if new_nome1.strip():
                if st.button("Criar cadastro e vincular", key="edit_create", type="primary"):
                    pdf_name = edit_pos["pdf_name"].strip()
                    sheet_nome = new_nome1.strip() if (pdf_name.isdigit() or len(pdf_name) <= 3) else pdf_name
                    success = _send_single_to_sheets(sheet_nome, new_nome1.strip())
                    if success:
                        db.update_position_match(edit_pos_id, "manual", sheet_nome)
                        st.rerun()

    # Remove individual position
    with st.expander("Remover posicao"):
        sel_del = st.selectbox("Selecionar posicao:", pos_labels, key="del_pos_select")
        if st.button("Remover posicao", key="btn_del_pos", type="secondary"):
            idx = pos_labels.index(sel_del)
            db.delete_position(pos_ids[idx])
            st.success(f"Posicao removida: {pos_labels[idx]}")
            st.rerun()


def _update_db_match_by_id(r: MatchResult, status: str, registry_nome: str | None):
    """Update match status in storage using pdf_name + value + upload_id."""
    db = get_db()
    upload_id = st.session_state.get("last_upload_id")
    if not upload_id:
        return

    client_id = st.session_state.get("client_id")
    if not client_id:
        return

    # Find the specific position (handles duplicates like multiple "3" tickers)
    for p in db._list_all_positions():
        if (p["upload_id"] == upload_id
                and p["pdf_name"] == r.pdf_name
                and abs(p["value"] - r.value) < 0.01
                and p["status"] in ("unmatched", "fuzzy")):
            db.update_position_match(p["id"], status, registry_nome)
            break
