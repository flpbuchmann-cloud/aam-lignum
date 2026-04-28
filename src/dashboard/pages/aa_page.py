"""Asset Allocation page - positions, recommendations, and consolidation."""

import pandas as pd
import plotly.express as px
import streamlit as st

from src.dashboard.components.comparison_chart import render_realizado_vs_sugerido
from src.dashboard.components.formatters import format_brl, format_pct
from src.dashboard.components.persistent_state import load_targets, save_targets
from src.matching.engine import MatchResult
from src.views.aa_view import AAViewBuilder
from src.views.ordering import disambiguate_micro_by_macro


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

    st.title(f"Asset Allocation - {client_name}")

    def _corretora_label(source: str | None) -> str:
        label = (source or "").strip().title()
        return label or "Sem fonte"

    corretoras = sorted({_corretora_label(r.source) for r in results})

    col_sel, col_metric = st.columns([1, 2])
    with col_sel:
        sel_corretora = st.selectbox(
            "Instituição",
            ["Todas"] + corretoras,
            key="aa_corretora_filter",
            help="Filtra toda a visualização para a instituição selecionada.",
        )

    if sel_corretora != "Todas":
        results = [r for r in results if _corretora_label(r.source) == sel_corretora]
        if not results:
            st.warning(f"Nenhuma posição encontrada para {sel_corretora}.")
            return

    builder = AAViewBuilder(results)
    positions = builder.build_positions_table()

    if positions.empty:
        return

    with col_metric:
        label = "Patrimonio Bruto Total" if sel_corretora == "Todas" else f"Patrimonio em {sel_corretora}"
        st.metric(label, format_brl(builder.total_pl))
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
    # 3. CHARTS ROW: Macro pie | Micro pie | Alocação por Instituição
    #    Three columns with equal width sharing a single row.
    # =====================================================================
    macro_df = builder.build_macro_consolidation()
    micro_df = builder.build_micro_consolidation()
    corretora_df = builder.build_corretora_consolidation()

    col_macro_pie, col_micro_pie, col_inst = st.columns(3)

    # Subheaders com altura fixa (min-height = 2 linhas) para alinhar os 3
    # gráficos no topo da row. Sem isso, "Alocação por Instituição" quebra em
    # 2 linhas em colunas estreitas e os outros 2 (1 linha cada) ficam
    # visualmente acima.
    PIE_HEADER = (
        "<div style='min-height: 56px; display: flex; align-items: flex-end; "
        "padding-bottom: 8px'>"
        "<span style='font-size: 1.5rem; font-weight: 600; line-height: 1.3'>"
        "{}</span></div>"
    )

    with col_macro_pie:
        st.markdown(PIE_HEADER.format("Macro Classe"), unsafe_allow_html=True)
        if not macro_df.empty:
            pie_macro = macro_df.copy()
            pie_macro["Label"] = pie_macro.apply(
                lambda r: f"{r['Macro Classe']} - {r['% Atual']:.2f}%", axis=1
            )
            pie_macro["Hover"] = pie_macro.apply(
                lambda r: (
                    f"<b>{r['Macro Classe']}</b>"
                    f"<br>━━━━━━━━━━━━━━━<br>"
                    f"<b>Saldo Financeiro:</b> {format_brl(r['Valor'])}"
                    f"<br><b>% do PL:</b> {r['% Atual']:.2f}%"
                ),
                axis=1,
            )
            fig = px.pie(
                pie_macro, values="Valor", names="Label", hole=0.4,
                custom_data=["Hover"],
            )
            fig.update_traces(
                textposition="none",
                hovertemplate="%{customdata[0]}<extra></extra>",
            )
            n_items = len(pie_macro)
            fig.update_layout(
                showlegend=True,
                height=420 + max(0, (n_items - 5) * 25),
                legend=dict(
                    orientation="h", yanchor="top", y=-0.05,
                    xanchor="center", x=0.5, font=dict(size=11),
                ),
                margin=dict(b=max(80, n_items * 20)),
                hoverlabel=dict(bgcolor="white", font_size=14, align="left",
                                bordercolor="#333"),
            )
            st.plotly_chart(fig, use_container_width=True)

    with col_micro_pie:
        st.markdown(PIE_HEADER.format("Micro Classe"), unsafe_allow_html=True)
        if not micro_df.empty:
            pie_micro = micro_df.copy()
            pie_micro["Label"] = pie_micro.apply(
                lambda r: f"{r['Micro Classe']} - {r['% Atual']:.2f}%", axis=1
            )
            pie_micro["Hover"] = pie_micro.apply(
                lambda r: (
                    f"<b>{r['Micro Classe']}</b>"
                    f"<br>━━━━━━━━━━━━━━━<br>"
                    f"<b>Saldo Financeiro:</b> {format_brl(r['Valor'])}"
                    f"<br><b>% do PL:</b> {r['% Atual']:.2f}%"
                ),
                axis=1,
            )
            fig = px.pie(
                pie_micro, values="Valor", names="Label", hole=0.4,
                custom_data=["Hover"],
            )
            fig.update_traces(
                textposition="none",
                hovertemplate="%{customdata[0]}<extra></extra>",
            )
            n_items = len(pie_micro)
            fig.update_layout(
                showlegend=True,
                height=420 + max(0, (n_items - 5) * 25),
                legend=dict(
                    orientation="h", yanchor="top", y=-0.05,
                    xanchor="center", x=0.5, font=dict(size=11),
                ),
                margin=dict(b=max(80, n_items * 20)),
                hoverlabel=dict(bgcolor="white", font_size=14, align="left",
                                bordercolor="#333"),
            )
            st.plotly_chart(fig, use_container_width=True)

    with col_inst:
        st.markdown(PIE_HEADER.format("Alocação por Instituição"), unsafe_allow_html=True)
        if not corretora_df.empty:
            pie_inst = corretora_df.copy()
            pie_inst["Label"] = pie_inst.apply(
                lambda r: f"{r['Corretora']} - {r['% PL']:.2f}%", axis=1
            )
            pie_inst["Hover"] = pie_inst.apply(
                lambda r: (
                    f"<b>{r['Corretora']}</b>"
                    f"<br>━━━━━━━━━━━━━━━<br>"
                    f"<b>Saldo Financeiro:</b> {format_brl(r['Valor'])}"
                    f"<br><b>% do PL:</b> {r['% PL']:.2f}%"
                ),
                axis=1,
            )
            fig = px.pie(
                pie_inst, values="Valor", names="Label", hole=0.4,
                custom_data=["Hover"],
            )
            fig.update_traces(
                textposition="none",
                hovertemplate="%{customdata[0]}<extra></extra>",
            )
            n_items = len(pie_inst)
            fig.update_layout(
                showlegend=True,
                height=420 + max(0, (n_items - 5) * 25),
                legend=dict(
                    orientation="h", yanchor="top", y=-0.05,
                    xanchor="center", x=0.5, font=dict(size=11),
                ),
                margin=dict(b=max(80, n_items * 20)),
                hoverlabel=dict(bgcolor="white", font_size=14, align="left",
                                bordercolor="#333"),
            )
            st.plotly_chart(fig, use_container_width=True)

    st.divider()

    # =====================================================================
    # 4. CONSOLIDATION TABLES: Macro first, Micro below, each full-width.
    #    % PL Sugerido is editable; Valor Sugerido and Diferença R$ update
    #    automatically from the typed %.
    # =====================================================================
    st.subheader("Macro Classe")
    _render_consolidation_editor(macro_df, "Macro Classe", total_pl, "cons_macro_pct")
    st.markdown("**Realizado vs. Sugerido — Macro Classe**")
    render_realizado_vs_sugerido(
        macro_df, "Macro Classe", "cons_macro_pct", currency_fn=format_brl,
    )

    st.divider()

    st.subheader("Micro Classe")
    # Disambigua "Ações (Renda Variável)" vs "Ações (Internacional)" etc.
    # quando a mesma Micro aparece em macros diferentes (sem isso o save
    # do % PL Sugerido sobrescreve a chave duplicada e o usuário não vê
    # o registro).
    micro_df_uniq = disambiguate_micro_by_macro(micro_df)
    _render_consolidation_editor(micro_df_uniq, "Micro Classe", total_pl, "cons_micro_pct")
    st.markdown("**Realizado vs. Sugerido — Micro Classe**")
    render_realizado_vs_sugerido(
        micro_df_uniq, "Micro Classe", "cons_micro_pct", currency_fn=format_brl,
    )


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


def _render_consolidation_editor(
    current_df: pd.DataFrame,
    classe_col: str,
    total_pl: float,
    state_key: str,
) -> None:
    """Render a consolidation table with editable "% PL Sugerido".

    Valor Sugerido and Diferença R$ are derived from the typed percentage
    and the current Patrimônio Bruto (total_pl). Edited percentages are
    persisted in st.session_state under `state_key` so they survive reruns.

    Input df must have columns: <classe_col>, "Valor", "% Atual".
    """
    if current_df.empty:
        return

    # Carrega persistido em disco (sobrevive a F5 / restart / deploy).
    stored: dict[str, float] = load_targets(state_key)

    rows = []
    for _, r in current_df.iterrows():
        classe = r[classe_col]
        valor_atual = float(r["Valor"])
        pct_atual = float(r["% Atual"])
        pct_sugerido = float(stored.get(classe, 0.0))
        valor_sugerido = pct_sugerido / 100.0 * total_pl
        diferenca = valor_sugerido - valor_atual
        rows.append({
            classe_col: classe,
            "Valor Atual": _fmt_valor(valor_atual),
            "% PL Atual": _fmt_pct(pct_atual),
            "% PL Sugerido": _fmt_pct(pct_sugerido),
            "Valor Sugerido": _fmt_valor(valor_sugerido),
            "Diferença R$": _fmt_signed_brl(diferenca),
        })
    display_df = pd.DataFrame(rows)

    edited = st.data_editor(
        display_df,
        column_config={
            classe_col: st.column_config.TextColumn(classe_col, disabled=True, width="medium"),
            "Valor Atual": st.column_config.TextColumn("Valor Atual", disabled=True),
            "% PL Atual": st.column_config.TextColumn("% PL Atual", disabled=True),
            "% PL Sugerido": st.column_config.TextColumn(
                "% PL Sugerido",
                help="Digite o percentual alvo (ex: 15, 15,50 ou 15,5%)",
            ),
            "Valor Sugerido": st.column_config.TextColumn("Valor Sugerido", disabled=True),
            "Diferença R$": st.column_config.TextColumn("Diferença R$", disabled=True),
        },
        use_container_width=True,
        hide_index=True,
        key=f"{state_key}_editor",
    )

    # Parse edited % values back into session state. If parsing fails,
    # keep the previously stored value so a typo doesn't clobber the cell.
    new_stored: dict[str, float] = {}
    for _, r in edited.iterrows():
        classe = r[classe_col]
        pct = _parse_pct_input(str(r.get("% PL Sugerido", "")))
        new_stored[classe] = pct if pct is not None else stored.get(classe, 0.0)

    # Mescla com targets antigos para classes que sumiram da view atual
    # (ex.: trocou de cliente e voltou). Preserva targets ocultos.
    merged = {**stored, **new_stored}

    if merged != stored:
        # Salva session_state + arquivo (write-through). Sobrevive F5/restart.
        save_targets(state_key, merged)
        editor_key = f"{state_key}_editor"
        if editor_key in st.session_state:
            del st.session_state[editor_key]
        st.rerun()
    else:
        st.session_state[state_key] = merged


def _parse_pct_input(s: str) -> float | None:
    """Parse a percentage string: '15', '15,50', '15.5', '15%', '15,50%'."""
    if s is None:
        return 0.0
    cleaned = s.strip().replace("%", "").strip()
    if not cleaned:
        return 0.0
    cleaned = cleaned.replace(",", ".")
    try:
        return float(cleaned)
    except ValueError:
        return None


def _fmt_signed_brl(v: float) -> str:
    """Format BR value with explicit sign: '+1.234,56' or '-1.234,56'."""
    if v is None or (isinstance(v, float) and pd.isna(v)) or abs(v) < 0.005:
        return _fmt_valor(0.0)
    return f"+{_fmt_valor(v)}" if v > 0 else _fmt_valor(v)


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
