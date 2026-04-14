"""Consulta page - search positions across all clients by various criteria."""

import pandas as pd
import streamlit as st

from src.dashboard.components.formatters import format_brl, format_pct
from src.dashboard.components.sidebar import get_db, get_registry


def render_consulta():
    """Render the Consulta (search) page."""
    st.title("Consulta")
    st.caption(
        "Busque posicoes em todos os clientes por Macro/Micro Classe, Tipo, "
        "CNPJ/Ticker, Emissor, e flags Isento/Carrego."
    )

    db = get_db()
    registry = get_registry()

    # Build options from registry
    assets = registry.assets
    if not assets:
        st.warning("Cadastro de ativos vazio.")
        return

    macro_options = [""] + sorted({a.get("macro_classe", "") for a in assets if a.get("macro_classe")})
    micro_options = [""] + sorted({a.get("micro_classe", "") for a in assets if a.get("micro_classe")})
    tipo_options = [""] + sorted({a.get("tipo", "") for a in assets if a.get("tipo")})
    emissor_options = [""] + sorted({a.get("emissor", "") for a in assets if a.get("emissor")})
    ticker_options = [""] + sorted({a.get("cnpj_ticker", "") for a in assets if a.get("cnpj_ticker")})

    # --- Filter UI ---
    st.subheader("Filtros")
    col1, col2, col3 = st.columns(3)

    with col1:
        sel_macro = st.selectbox("Macro Classe", macro_options, key="cons_macro")
        sel_emissor = st.selectbox("Emissor", emissor_options, key="cons_emissor")
        sel_isento = st.radio("Ativo Isento", ["Todos", "Sim", "Nao"], horizontal=True, key="cons_isento")

    with col2:
        sel_micro = st.selectbox("Micro Classe", micro_options, key="cons_micro")
        sel_ticker = st.selectbox("CNPJ/Ticker", ticker_options, key="cons_ticker")
        sel_carrego = st.radio("Ativo de Carrego", ["Todos", "Sim", "Nao"], horizontal=True, key="cons_carrego")

    with col3:
        sel_tipo = st.selectbox("Tipo", tipo_options, key="cons_tipo")
        sel_nome_search = st.text_input("Buscar por nome (opcional)", key="cons_nome")

    st.divider()

    # --- Collect all positions from all clients ---
    clients = db.list_clients()
    if not clients:
        st.info("Nenhum cliente cadastrado.")
        return

    # Build a lookup of clients and their total PL
    client_pl = {}  # client_id -> total_pl
    all_rows = []

    for c in clients:
        positions = db.get_positions(c["id"])
        if not positions:
            continue
        total_pl = sum(p["value"] for p in positions)
        client_pl[c["id"]] = total_pl

        for p in positions:
            # Lookup registry
            reg_nome = p["registry_nome"] or p["pdf_name"]
            match = registry.find_match(reg_nome)

            nome_1 = match.get("nome_1", p["pdf_name"]) if match else p["pdf_name"]
            macro = match.get("macro_classe", "") if match else ""
            micro = match.get("micro_classe", "") if match else ""
            tipo = match.get("tipo", "") if match else ""
            emissor = match.get("emissor", "") if match else ""
            ticker = match.get("cnpj_ticker", "") if match else ""
            isento = match.get("ativo_isento", "") if match else ""
            carrego = match.get("ativo_carrego", "") if match else ""

            all_rows.append({
                "Cliente": c["name"],
                "Ativo": nome_1,
                "Valor": p["value"],
                "% PL": (p["value"] / total_pl * 100) if total_pl else 0,
                "Macro Classe": macro,
                "Micro Classe": micro,
                "Tipo": tipo,
                "Emissor": emissor,
                "CNPJ/Ticker": ticker,
                "Isento": "Sim" if isento == "x" else "Nao",
                "Carrego": "Sim" if carrego == "x" else "Nao",
                "Corretora": (p.get("source") or "").title(),
            })

    if not all_rows:
        st.info("Nenhuma posicao encontrada.")
        return

    df = pd.DataFrame(all_rows)

    # --- Apply filters ---
    if sel_macro:
        df = df[df["Macro Classe"] == sel_macro]
    if sel_micro:
        df = df[df["Micro Classe"] == sel_micro]
    if sel_tipo:
        df = df[df["Tipo"] == sel_tipo]
    if sel_ticker:
        df = df[df["CNPJ/Ticker"] == sel_ticker]
    if sel_emissor:
        df = df[df["Emissor"] == sel_emissor]
    if sel_isento != "Todos":
        df = df[df["Isento"] == sel_isento]
    if sel_carrego != "Todos":
        df = df[df["Carrego"] == sel_carrego]
    if sel_nome_search.strip():
        df = df[df["Ativo"].str.contains(sel_nome_search.strip(), case=False, na=False)]

    df = df.sort_values(["Cliente", "Valor"], ascending=[True, False]).reset_index(drop=True)

    # --- Results ---
    st.subheader(f"Resultados ({len(df)} posicao(oes))")

    if df.empty:
        st.info("Nenhuma posicao encontrada com os filtros selecionados.")
        return

    # Summary metrics
    total_valor = df["Valor"].sum()
    n_clientes = df["Cliente"].nunique()
    col_m1, col_m2, col_m3 = st.columns(3)
    col_m1.metric("Total", len(df))
    col_m2.metric("Clientes", n_clientes)
    col_m3.metric("Valor Total", format_brl(total_valor))

    # Display table
    display = df.copy()
    display["Valor"] = display["Valor"].apply(format_brl)
    display["% PL"] = display["% PL"].apply(format_pct)

    show_cols = [
        "Cliente", "Ativo", "Valor", "% PL",
        "Macro Classe", "Micro Classe", "Tipo", "Emissor",
        "Isento", "Carrego", "Corretora",
    ]
    st.dataframe(display[show_cols], use_container_width=True, hide_index=True)

    # Breakdown by client
    st.divider()
    st.subheader("Consolidado por Cliente")
    by_client = df.groupby("Cliente").agg(
        Posicoes=("Ativo", "count"),
        Valor=("Valor", "sum"),
    ).reset_index()
    by_client["% Total"] = (by_client["Valor"] / total_valor * 100).round(2)
    by_client = by_client.sort_values("Valor", ascending=False)
    by_client["Valor Fmt"] = by_client["Valor"].apply(format_brl)
    by_client["% Total Fmt"] = by_client["% Total"].apply(format_pct)

    st.dataframe(
        by_client[["Cliente", "Posicoes", "Valor Fmt", "% Total Fmt"]].rename(
            columns={"Valor Fmt": "Valor", "% Total Fmt": "% Total"}
        ),
        use_container_width=True,
        hide_index=True,
    )
