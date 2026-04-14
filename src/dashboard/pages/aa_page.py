"""Asset Allocation page - positions, recommendations, and consolidation."""

import pandas as pd
import plotly.express as px
import streamlit as st

from src.dashboard.components.formatters import format_brl, format_pct
from src.matching.engine import MatchResult
from src.views.aa_view import AAViewBuilder


# CSS to center all data_editor cells except first column
CENTER_CSS = """
<style>
    /* Center all cells in data_editor */
    div[data-testid="stDataEditor"] td {
        text-align: center !important;
    }
    /* Left-align first column (Ativo) */
    div[data-testid="stDataEditor"] td:first-child {
        text-align: left !important;
    }
    /* Center headers */
    div[data-testid="stDataEditor"] th {
        text-align: center !important;
    }
</style>
"""


def _fmt_valor(v):
    """Format number as Brazilian: XX.XXX,XX"""
    if pd.isna(v) or v is None:
        return ""
    if v < 0:
        return f"-{abs(v):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _fmt_pct(v):
    """Format as XX,XX%"""
    if pd.isna(v) or v is None:
        return ""
    return f"{v:.2f}%".replace(".", ",")


def _parse_br_number(s) -> float:
    """Parse a Brazilian number string (1.234,56 or 1234.56) to float."""
    if s is None or (isinstance(s, float) and pd.isna(s)):
        return 0.0
    if isinstance(s, (int, float)):
        return float(s)
    s = str(s).strip().replace("R$", "").strip()
    if not s:
        return 0.0
    # Detect format: if has comma and dot, BR format (dot=thousand, comma=decimal)
    # If only dot, could be US (dot=decimal) or BR thousand (1.234 without decimal)
    # If only comma, BR format (comma=decimal)
    if "," in s:
        # BR format
        s = s.replace(".", "").replace(",", ".")
    # else: keep as is (US or plain integer)
    try:
        return float(s)
    except ValueError:
        return 0.0


def render_aa():
    """Render the Asset Allocation page."""
    from src.dashboard.components.sidebar import load_client_positions

    client_id = st.session_state.get("client_id")
    if not client_id:
        st.title("Asset Allocation")
        st.warning("Selecione um cliente na barra lateral.")
        return

    results = load_client_positions()
    if not results:
        st.title("Asset Allocation")
        st.warning("Nenhuma posicao encontrada. Faca o upload de um PDF na pagina Importar.")
        return

    client_name = st.session_state.get("client_name", "Cliente")
    builder = AAViewBuilder(results)
    positions = builder.build_positions_table()

    if positions.empty:
        return

    st.title(f"Asset Allocation - {client_name}")
    st.metric("Patrimonio Bruto Total", format_brl(builder.total_pl))
    st.divider()

    # Inject centering CSS
    st.markdown(CENTER_CSS, unsafe_allow_html=True)

    total_pl = builder.total_pl
    macro_options = sorted(positions["Macro Classe"].unique().tolist())
    micro_options = sorted(positions["Micro Classe"].unique().tolist())

    # =====================================================================
    # 1. POSICOES
    # =====================================================================
    st.subheader("Posições")

    # Initialize suggested values in session state (persist across reruns)
    if "pos_sugerido" not in st.session_state or len(st.session_state.pos_sugerido) != len(positions):
        st.session_state.pos_sugerido = positions["Valor"].tolist()

    # Build display dataframe with Brazilian formatting (all as text)
    pos_display = pd.DataFrame({
        "Ativo": positions["Ativo"],
        "Valor": positions["Valor"].apply(_fmt_valor),
        "% PL": positions["% PL"].apply(_fmt_pct),
        "Valor Sugerido": [_fmt_valor(v) for v in st.session_state.pos_sugerido],
        "% PL Sugerido": "",
        "Macro Classe": positions["Macro Classe"],
        "Micro Classe": positions["Micro Classe"],
    })

    # Recalculate % PL Sugerido
    for i, val in enumerate(st.session_state.pos_sugerido):
        if total_pl > 0 and val is not None:
            pos_display.at[i, "% PL Sugerido"] = _fmt_pct(val / total_pl * 100)

    edited_pos = st.data_editor(
        pos_display,
        column_config={
            "Ativo": st.column_config.TextColumn("Ativo", disabled=True, width="large"),
            "Valor": st.column_config.TextColumn("Valor", disabled=True),
            "% PL": st.column_config.TextColumn("% PL", disabled=True),
            "Valor Sugerido": st.column_config.TextColumn(
                "Valor Sugerido",
                help="Digite o valor no formato 1.234,56 ou 1234,56",
            ),
            "% PL Sugerido": st.column_config.TextColumn("% PL Sugerido", disabled=True),
            "Macro Classe": st.column_config.TextColumn("Macro Classe", disabled=True),
            "Micro Classe": st.column_config.TextColumn("Micro Classe", disabled=True),
        },
        use_container_width=True,
        hide_index=True,
        key="pos_editor",
    )

    # Parse edited values back to float
    sugerido_values = [_parse_br_number(v) for v in edited_pos["Valor Sugerido"].tolist()]
    st.session_state.pos_sugerido = sugerido_values

    # Build numeric version for consolidation
    pos_for_consol = positions[["Macro Classe", "Micro Classe"]].copy()
    pos_for_consol["Valor Sugerido"] = sugerido_values

    # --- Add / Remove position ---
    col_add, col_del = st.columns(2)

    with col_add:
        with st.expander("Adicionar posicao"):
            _render_add_position_form(client_id)

    with col_del:
        with st.expander("Remover posicao"):
            _render_remove_position_form(client_id, positions)

    st.divider()

    # =====================================================================
    # 2. RECOMENDACAO
    # =====================================================================
    st.subheader("Recomendação")

    if "reco_data" not in st.session_state:
        st.session_state.reco_data = pd.DataFrame(
            columns=["Ativo", "Valor", "% PL", "Macro Classe", "Micro Classe"]
        )

    reco_template = pd.DataFrame({
        "Ativo": pd.Series(dtype="str"),
        "Valor": pd.Series(dtype="str"),
        "% PL": pd.Series(dtype="str"),
        "Macro Classe": pd.Series(dtype="str"),
        "Micro Classe": pd.Series(dtype="str"),
    })

    current_reco = st.session_state.reco_data
    if current_reco.empty:
        current_reco = reco_template

    edited_reco = st.data_editor(
        current_reco,
        column_config={
            "Ativo": st.column_config.TextColumn("Ativo", width="large"),
            "Valor": st.column_config.TextColumn(
                "Valor",
                help="Digite o valor no formato 1.234,56 ou 1234,56",
            ),
            "% PL": st.column_config.TextColumn("% PL", disabled=True),
            "Macro Classe": st.column_config.SelectboxColumn("Macro Classe", options=macro_options),
            "Micro Classe": st.column_config.SelectboxColumn("Micro Classe", options=micro_options),
        },
        num_rows="dynamic",
        use_container_width=True,
        hide_index=True,
        key="reco_editor",
    )

    # Parse Valor from BR format and recalculate % PL
    if not edited_reco.empty:
        # Create a numeric column for calculations
        edited_reco = edited_reco.copy()
        edited_reco["_valor_num"] = edited_reco["Valor"].apply(_parse_br_number)

        if total_pl > 0:
            edited_reco["% PL"] = edited_reco["_valor_num"].apply(
                lambda v: _fmt_pct(v / total_pl * 100) if v > 0 else ""
            )

        # Re-format Valor to ensure consistent display
        edited_reco["Valor"] = edited_reco["_valor_num"].apply(
            lambda v: _fmt_valor(v) if v > 0 else ""
        )

    st.session_state.reco_data = edited_reco[
        ["Ativo", "Valor", "% PL", "Macro Classe", "Micro Classe"]
    ] if not edited_reco.empty else edited_reco

    st.divider()

    # =====================================================================
    # 3. PIE CHARTS
    # =====================================================================
    macro_df = builder.build_macro_consolidation()
    micro_df = builder.build_micro_consolidation()

    col_chart1, col_chart2 = st.columns(2)

    with col_chart1:
        st.subheader("Macro Classe")
        if not macro_df.empty:
            pie_macro = macro_df.copy()
            pie_macro["Label"] = pie_macro.apply(
                lambda r: f"{r['Macro Classe']} - {r['% Atual']:.2f}%", axis=1
            )
            pie_macro["Valor Fmt"] = pie_macro["Valor"].apply(format_brl)
            fig = px.pie(
                pie_macro, values="Valor", names="Label", hole=0.4,
                custom_data=["Valor Fmt", "% Atual"],
            )
            fig.update_traces(
                textposition="none",
                hovertemplate="%{customdata[0]}<br>%{customdata[1]:.2f}% PL<extra></extra>",
            )
            fig.update_layout(
                showlegend=True, height=400,
                legend=dict(orientation="h", yanchor="bottom", y=-0.3),
            )
            st.plotly_chart(fig, use_container_width=True)

    with col_chart2:
        st.subheader("Micro Classe")
        if not micro_df.empty:
            pie_micro = micro_df.copy()
            pie_micro["Label"] = pie_micro.apply(
                lambda r: f"{r['Micro Classe']} - {r['% Atual']:.2f}%", axis=1
            )
            pie_micro["Valor Fmt"] = pie_micro["Valor"].apply(format_brl)
            fig = px.pie(
                pie_micro, values="Valor", names="Label", hole=0.4,
                custom_data=["Valor Fmt", "% Atual"],
            )
            fig.update_traces(
                textposition="none",
                hovertemplate="%{customdata[0]}<br>%{customdata[1]:.2f}% PL<extra></extra>",
            )
            n_items = len(pie_micro)
            fig.update_layout(
                showlegend=True,
                height=400 + max(0, (n_items - 5) * 25),
                legend=dict(
                    orientation="h", yanchor="top", y=-0.05,
                    xanchor="center", x=0.5, font=dict(size=11),
                ),
                margin=dict(b=max(80, n_items * 20)),
            )
            st.plotly_chart(fig, use_container_width=True)

    st.divider()

    # =====================================================================
    # 3.5. ALOCACAO POR INSTITUICAO
    # =====================================================================
    st.subheader("Alocação por Instituição")
    corretora_df = builder.build_corretora_consolidation()
    if not corretora_df.empty:
        # Sort ascending for horizontal bar (larger on top)
        plot_df = corretora_df.sort_values("Valor", ascending=True).copy()
        plot_df["Label"] = plot_df.apply(
            lambda r: f"{r['Corretora']} ({r['% PL']:.2f}% PL)", axis=1
        )
        plot_df["Valor Fmt"] = plot_df["Valor"].apply(format_brl)

        fig = px.bar(
            plot_df,
            x="Valor",
            y="Label",
            orientation="h",
            text="Valor Fmt",
            custom_data=["Valor Fmt", "% PL"],
        )
        fig.update_traces(
            textposition="outside",
            hovertemplate="%{customdata[0]}<br>%{customdata[1]:.2f}% PL<extra></extra>",
        )
        fig.update_layout(
            height=max(250, 60 * len(plot_df) + 150),
            yaxis=dict(title=""),
            xaxis=dict(title="Valor (R$)"),
            showlegend=False,
        )
        st.plotly_chart(fig, use_container_width=True)

    st.divider()

    # =====================================================================
    # 4. CONSOLIDATION TABLES
    # =====================================================================
    suggested_macro, suggested_micro = _build_suggested_consolidation(
        pos_for_consol, edited_reco, total_pl
    )

    col_cons1, col_cons2 = st.columns(2)

    with col_cons1:
        st.subheader("Macro Classe")
        if not macro_df.empty:
            cons_macro = _merge_consolidation(macro_df, suggested_macro, "Macro Classe", total_pl)
            st.dataframe(cons_macro, use_container_width=True, hide_index=True)

    with col_cons2:
        st.subheader("Micro Classe")
        if not micro_df.empty:
            cons_micro = _merge_consolidation(micro_df, suggested_micro, "Micro Classe", total_pl)
            st.dataframe(cons_micro, use_container_width=True, hide_index=True)


def _render_add_position_form(client_id: int):
    """Form to add a manual position (existing or new asset)."""
    from src.dashboard.components.sidebar import get_db, get_registry, refresh_registry
    from src.sheets.client import SheetsClient
    from src.dashboard.components.sidebar import get_sheets_client

    db = get_db()
    registry = get_registry()

    mode = st.radio(
        "Tipo:",
        ["Ativo existente no cadastro", "Novo ativo (criar no cadastro)"],
        key="add_pos_mode",
        horizontal=True,
    )

    if mode == "Ativo existente no cadastro":
        search = st.text_input("Buscar ativo no cadastro:", key="add_pos_search")
        selected_asset = None
        if search:
            matches = registry.find_fuzzy_match(search, threshold=0.3)
            if matches:
                sopts = [f"{m['nome']} - {m['asset'].get('nome_1','')} ({m['score']:.0%})" for m in matches[:10]]
                sel = st.selectbox("Resultados:", sopts, key="add_pos_result")
                idx = sopts.index(sel)
                selected_asset = matches[idx]["asset"]
            else:
                st.caption("Nenhum resultado encontrado.")

        valor_str = st.text_input(
            "Valor (ex: 1.234,56):", key="add_pos_valor",
            placeholder="1.234,56",
        )

        if selected_asset and valor_str:
            if st.button("Adicionar posicao", key="btn_add_pos", type="primary"):
                valor = _parse_br_number(valor_str)
                if valor <= 0:
                    st.error("Valor invalido.")
                    return
                nome = selected_asset["nome"]
                db.add_manual_position(client_id, nome, valor, nome)
                st.success(f"Posicao adicionada: {selected_asset.get('nome_1', nome)} - {_fmt_valor(valor)}")
                st.rerun()

    else:  # Novo ativo
        st.caption(
            "Cria um novo cadastro na Base de Dados (colunas Nome e Nome 1) "
            "e adiciona a posicao ao cliente. Complete a classificacao na planilha."
        )
        nome_pdf = st.text_input(
            "Nome (coluna A da planilha):",
            key="add_new_nome",
            placeholder="Ex: CDB XP - 14,5% - Vencimento 01/2030",
        )
        nome_1 = st.text_input(
            "Nome 1 (nome padronizado):",
            key="add_new_nome1",
            placeholder="Ex: CDB XP - 14,5% - Vencimento 01/2030",
        )
        valor_str = st.text_input(
            "Valor (ex: 1.234,56):", key="add_new_valor",
            placeholder="1.234,56",
        )

        if nome_pdf.strip() and nome_1.strip() and valor_str:
            if st.button("Cadastrar e adicionar posicao", key="btn_add_new_pos", type="primary"):
                valor = _parse_br_number(valor_str)
                if valor <= 0:
                    st.error("Valor invalido.")
                    return

                # 1. Write to Google Sheets
                sheets_client = get_sheets_client()
                if not sheets_client.is_authenticated:
                    st.error("Configure credentials.json para enviar ao Google Sheets.")
                    return

                try:
                    ws = sheets_client.get_worksheet()
                    existing = sheets_client.get_existing_names()
                    if nome_pdf.strip() not in existing:
                        col_a = ws.col_values(1)
                        next_row = len(col_a) + 1
                        ws.update(f"A{next_row}", [[nome_pdf.strip(), nome_1.strip()]])
                        sheets_client._cache = None
                        refresh_registry()

                    # 2. Add position to client
                    db.add_manual_position(client_id, nome_pdf.strip(), valor, nome_pdf.strip())
                    st.success(
                        f"Cadastrado e adicionado: {nome_1.strip()} - {_fmt_valor(valor)}. "
                        "Complete a classificacao (Macro/Micro/Tipo) na planilha."
                    )
                    st.rerun()
                except Exception as e:
                    st.error(f"Erro: {e}")


def _render_remove_position_form(client_id: int, positions_df: pd.DataFrame):
    """Form to remove a position."""
    from src.dashboard.components.sidebar import get_db

    db = get_db()
    all_positions = db.get_positions(client_id)

    pos_labels = []
    pos_ids = []
    for p in all_positions:
        # Find display name from positions_df (match by value)
        nome = p["pdf_name"]
        for _, row in positions_df.iterrows():
            if abs(row["Valor"] - p["value"]) < 0.01:
                nome = row["Ativo"]
                break
        label = f"{nome} | {_fmt_valor(p['value'])} ({p['source'].title()})"
        pos_labels.append(label)
        pos_ids.append(p["id"])

    if not pos_labels:
        st.caption("Nenhuma posicao disponivel.")
        return

    selected = st.selectbox("Selecionar posicao:", pos_labels, key="rm_pos_select")
    if st.button("Remover posicao", key="btn_rm_pos", type="secondary"):
        idx = pos_labels.index(selected)
        db.delete_position(pos_ids[idx])
        st.success(f"Posicao removida: {pos_labels[idx]}")
        st.rerun()


def _build_suggested_consolidation(
    pos_for_consol: pd.DataFrame, edited_reco: pd.DataFrame, total_pl: float
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Build suggested consolidation from edited positions + recommendations."""
    pos_macro = pos_for_consol.groupby("Macro Classe")["Valor Sugerido"].sum().reset_index()
    pos_macro.columns = ["Classe", "Valor Sugerido"]

    pos_micro = pos_for_consol.groupby("Micro Classe")["Valor Sugerido"].sum().reset_index()
    pos_micro.columns = ["Classe", "Valor Sugerido"]

    if not edited_reco.empty:
        reco_copy = edited_reco.copy()
        reco_copy["_valor_num"] = reco_copy["Valor"].apply(_parse_br_number)
        reco_clean = reco_copy[reco_copy["_valor_num"] > 0]

        if not reco_clean.empty and "Macro Classe" in reco_clean.columns:
            reco_macro = reco_clean.dropna(subset=["Macro Classe"]).groupby("Macro Classe")["_valor_num"].sum().reset_index()
            reco_macro.columns = ["Classe", "Valor Sugerido"]
            pos_macro = pd.concat([pos_macro, reco_macro]).groupby("Classe")["Valor Sugerido"].sum().reset_index()

            reco_micro = reco_clean.dropna(subset=["Micro Classe"]).groupby("Micro Classe")["_valor_num"].sum().reset_index()
            reco_micro.columns = ["Classe", "Valor Sugerido"]
            pos_micro = pd.concat([pos_micro, reco_micro]).groupby("Classe")["Valor Sugerido"].sum().reset_index()

    return pos_macro, pos_micro


def _merge_consolidation(
    current_df: pd.DataFrame, suggested_df: pd.DataFrame,
    classe_col: str, total_pl: float
) -> pd.DataFrame:
    """Merge current and suggested consolidation into display table."""
    current = current_df[[classe_col, "Valor", "% Atual"]].copy()
    current.columns = [classe_col, "Valor Atual", "% PL Atual"]

    suggested = suggested_df.copy()
    suggested.columns = [classe_col, "Valor Sugerido"]

    merged = current.merge(suggested, on=classe_col, how="outer").fillna(0)

    if total_pl > 0:
        merged["% PL Sugerido_num"] = (merged["Valor Sugerido"] / total_pl * 100).round(2)
    else:
        merged["% PL Sugerido_num"] = 0.0

    merged["Diferenca_num"] = merged["Valor Sugerido"] - merged["Valor Atual"]
    merged = merged.sort_values("Valor Atual", ascending=False).reset_index(drop=True)

    # Format Brazilian
    display = pd.DataFrame()
    display[classe_col] = merged[classe_col]
    display["Valor Atual"] = merged["Valor Atual"].apply(_fmt_valor)
    display["% PL Atual"] = merged["% PL Atual"].apply(_fmt_pct)
    display["Valor Sugerido"] = merged["Valor Sugerido"].apply(_fmt_valor)
    display["% PL Sugerido"] = merged["% PL Sugerido_num"].apply(_fmt_pct)
    display["Diferença R$"] = merged["Diferenca_num"].apply(
        lambda x: f"+{_fmt_valor(x)}" if x > 0 else _fmt_valor(x)
    )

    return display


def _fmt_valor(v):
    """Format number as Brazilian: XX.XXX,XX"""
    if pd.isna(v) or v is None:
        return ""
    if v < 0:
        return f"-{abs(v):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _fmt_pct(v):
    """Format as XX,XX%"""
    if pd.isna(v) or v is None:
        return ""
    return f"{v:.2f}%".replace(".", ",")
