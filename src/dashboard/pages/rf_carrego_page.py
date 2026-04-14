"""RF Carrego page - fixed income carry analysis."""

import pandas as pd
import plotly.express as px
import streamlit as st

from src.dashboard.components.formatters import format_brl, format_pct
from src.dashboard.components.sidebar import get_sheets_client
from src.matching.engine import MatchResult
from src.views.rf_carrego import RFCarregoBuilder


def render_rf():
    """Render the RF Carrego page."""
    from src.dashboard.components.sidebar import load_client_positions

    client_id = st.session_state.get("client_id")
    if not client_id:
        st.title("RF Carrego")
        st.warning("Selecione um cliente na barra lateral.")
        return

    results = load_client_positions()
    if not results:
        st.title("RF Carrego")
        st.warning("Nenhuma posicao encontrada. Faca o upload de um PDF na pagina Importar.")
        return

    client_name = st.session_state.get("client_name", "Cliente")

    # Load CDI and IPCA from Google Sheets indicadores tab
    sheets_client = get_sheets_client()
    indicadores = sheets_client.get_indicadores()
    cdi = indicadores["cdi"]
    ipca = indicadores["ipca"]

    builder = RFCarregoBuilder(results, cdi=cdi, ipca=ipca)
    rf_assets = builder.filter_rf_carrego()

    st.title(f"RF Carrego - {client_name}")

    if not rf_assets:
        st.warning("Nenhum ativo marcado como 'Ativo de Carrego' na Base de Dados.")
        return

    # --- KPIs ---
    kpis = builder.build_kpis()

    col1, col2, col3 = st.columns(3)
    col1.metric("Total RF Carrego", format_brl(kpis["total_value"]))
    col2.metric("% do PL", format_pct(kpis["pct_pl"]))
    col3.metric("Duration Media", f"{kpis['duration_avg']:.2f} anos")

    st.divider()

    col4, col5, col6, col7 = st.columns(4)
    col4.metric("Taxa Pre Media", format_pct(kpis["taxa_pre_media"]))
    col5.metric("Taxa Real Media", format_pct(kpis["taxa_real_media"]))
    col6.metric("% CDI Medio", format_pct(kpis["pct_cdi_medio"]))
    spread = kpis["cdi_spread_medio"]
    col7.metric("CDI+", f"{'+' if spread >= 0 else ''}{spread:.2f}%")

    st.caption(f"CDI: {cdi:.2f}% | IPCA 12M: {ipca:.2f}% | Retorno Real Corrente: {cdi - ipca:.2f}%")

    st.divider()

    # --- Main positions table ---
    st.subheader("Posicoes RF Carrego")
    carrego_table = builder.build_carrego_table()

    if not carrego_table.empty:
        display_df = carrego_table.copy()
        display_df["Posicao Fmt"] = display_df["Posicao"].apply(format_brl)
        display_df["% PL Fmt"] = display_df["% PL"].apply(format_pct)
        display_df["% Classe Fmt"] = display_df["% Classe"].apply(format_pct)

        show_cols = [
            "Ativo", "Posicao Fmt", "% PL Fmt", "% Classe Fmt",
            "Emissor", "Data Aplicacao", "Vencimento", "Taxa", "Taxa Bruta",
            "Isento", "Indexador", "Duration (anos)",
        ]

        st.dataframe(
            display_df[show_cols].rename(columns={
                "Posicao Fmt": "Posicao",
                "% PL Fmt": "% PL",
                "% Classe Fmt": "% Classe",
            }),
            use_container_width=True,
            hide_index=True,
        )

    st.divider()

    # --- Allocation panels ---
    col_idx, col_iss, col_dur = st.columns(3)

    with col_idx:
        st.subheader("Alocacao por Indexador")
        idx_df = builder.build_indexer_allocation()
        if not idx_df.empty:
            display_idx = idx_df.copy()
            display_idx["Valor Fmt"] = display_idx["Valor"].apply(format_brl)
            display_idx["% RF Fmt"] = display_idx["% RF"].apply(format_pct)
            display_idx["% PL Fmt"] = display_idx["% PL"].apply(format_pct)
            st.dataframe(
                display_idx[["Indexador", "Valor Fmt", "% RF Fmt", "% PL Fmt"]].rename(
                    columns={"Valor Fmt": "Valor", "% RF Fmt": "% RF", "% PL Fmt": "% PL"}
                ),
                use_container_width=True,
                hide_index=True,
            )

    with col_iss:
        st.subheader("Alocacao por Emissor")
        iss_df = builder.build_issuer_allocation()
        if not iss_df.empty:
            display_iss = iss_df.copy()
            display_iss["Valor Fmt"] = display_iss["Valor"].apply(format_brl)
            display_iss["% RF Fmt"] = display_iss["% RF"].apply(format_pct)
            display_iss["% PL Fmt"] = display_iss["% PL"].apply(format_pct)
            st.dataframe(
                display_iss[["Emissor", "Valor Fmt", "% RF Fmt", "% PL Fmt"]].rename(
                    columns={"Valor Fmt": "Valor", "% RF Fmt": "% RF", "% PL Fmt": "% PL"}
                ),
                use_container_width=True,
                hide_index=True,
            )

    with col_dur:
        st.subheader("Duration por Indexador")
        dur_df = builder.build_duration_summary()
        if not dur_df.empty:
            display_dur = dur_df.copy()
            display_dur["Valor Fmt"] = display_dur["Valor"].apply(format_brl)
            st.dataframe(
                display_dur[["Indexador", "Duration Ponderada (anos)", "Valor Fmt"]].rename(
                    columns={"Valor Fmt": "Valor"}
                ),
                use_container_width=True,
                hide_index=True,
            )

    st.divider()

    # --- Charts ---
    col_c1, col_c2 = st.columns(2)

    with col_c1:
        if not idx_df.empty:
            st.subheader("Alocacao por Indexador")
            pie_df = idx_df.copy()
            pie_df["Label"] = pie_df.apply(
                lambda r: f"{r['Indexador']} - {r['% RF']:.1f}% ({format_brl(r['Valor'])})", axis=1
            )
            fig = px.pie(pie_df, values="Valor", names="Label", hole=0.4)
            fig.update_traces(textposition="none")
            fig.update_layout(height=400, showlegend=True, legend=dict(orientation="h", yanchor="bottom", y=-0.3))
            st.plotly_chart(fig, use_container_width=True)

    with col_c2:
        if not iss_df.empty:
            st.subheader("Alocacao por Emissor")
            bar_df = iss_df.head(10).copy()
            bar_df["Label"] = bar_df.apply(
                lambda r: f"{r['Emissor']} ({r['% PL']:.2f}% PL)", axis=1
            )
            fig = px.bar(
                bar_df,
                x="Valor",
                y="Label",
                orientation="h",
            )
            fig.update_traces(texttemplate="")
            fig.update_layout(
                height=350,
                yaxis=dict(autorange="reversed", title=""),
                showlegend=False,
            )
            st.plotly_chart(fig, use_container_width=True)
