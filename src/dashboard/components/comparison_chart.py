"""Gráfico de barras horizontais — Realizado vs. Sugerido.

Compara `% Atual` (realizado) com `% PL Sugerido` (target salvo no
backend de targets) para Macro/Micro Classe. Lê o sugerido de
`load_targets(state_key)`, então fica em sincronia com o que o usuário
digitou no editor de consolidação.

Uso típico:

```python
from src.dashboard.components.comparison_chart import render_realizado_vs_sugerido

render_realizado_vs_sugerido(
    macro_df, "Macro Classe", "cons_macro_pct",
    currency_fn=format_brl,
)
```
"""

from __future__ import annotations

from typing import Callable

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from src.dashboard.components.persistent_state import load_targets


# Cores canônicas — azul = realizado (status quo), laranja = sugerido (alvo).
_COLOR_REALIZADO = "#2e86de"
_COLOR_SUGERIDO = "#e67e22"


def _fmt_pct_br(v: float) -> str:
    return f"{v:.2f}%".replace(".", ",")


def _fmt_diff_pp(v: float) -> str:
    sign = "+" if v >= 0 else ""
    return f"{sign}{v:.2f} pp".replace(".", ",")


def render_realizado_vs_sugerido(
    current_df: pd.DataFrame,
    classe_col: str,
    state_key: str,
    *,
    currency_fn: Callable[[float], str],
    title: str | None = None,
) -> None:
    """Renderiza barras horizontais comparando % Atual vs % Sugerido.

    Args:
        current_df: DataFrame com colunas [<classe_col>, "Valor", "% Atual"].
                    Já assumido na ordem canônica (PADROES.md §6).
        classe_col: "Macro Classe" ou "Micro Classe".
        state_key:  chave usada pelo editor para persistir % sugerido.
                    Lemos os mesmos valores aqui via load_targets().
        currency_fn: format_brl / format_usd, conforme contexto.
        title: título opcional acima do gráfico.
    """
    if current_df.empty:
        return

    stored = load_targets(state_key)

    df = current_df.copy()
    df["% Sugerido"] = df[classe_col].map(stored).fillna(0.0)
    df["Diferença pp"] = df["% Atual"] - df["% Sugerido"]

    # Reverte para a ordem canônica aparecer top→bottom.
    df = df.iloc[::-1].reset_index(drop=True)

    def _hover(r: pd.Series) -> str:
        classe = r[classe_col]
        valor = currency_fn(float(r["Valor"]))
        return (
            f"<b>{classe}</b>"
            f"<br>━━━━━━━━━━━━━━━<br>"
            f"<b>Saldo Financeiro:</b> {valor}"
            f"<br><b>% Realizado:</b> {_fmt_pct_br(float(r['% Atual']))}"
            f"<br><b>% Sugerido:</b> {_fmt_pct_br(float(r['% Sugerido']))}"
            f"<br><b>Diferença:</b> {_fmt_diff_pp(float(r['Diferença pp']))}"
        )

    hover_text = df.apply(_hover, axis=1)

    fig = go.Figure()
    fig.add_trace(go.Bar(
        y=df[classe_col],
        x=df["% Atual"],
        name="Realizado",
        orientation="h",
        marker=dict(color=_COLOR_REALIZADO),
        text=df["% Atual"].map(_fmt_pct_br),
        textposition="outside",
        textfont=dict(size=11),
        customdata=hover_text,
        hovertemplate="%{customdata}<extra></extra>",
    ))
    fig.add_trace(go.Bar(
        y=df[classe_col],
        x=df["% Sugerido"],
        name="Sugerido",
        orientation="h",
        marker=dict(color=_COLOR_SUGERIDO),
        text=df["% Sugerido"].map(_fmt_pct_br),
        textposition="outside",
        textfont=dict(size=11),
        customdata=hover_text,
        hovertemplate="%{customdata}<extra></extra>",
    ))

    n = len(df)
    height = max(280, 80 + n * 50)

    # Não usar `xaxis.title` aqui: o `ticksuffix="%"` já comunica a unidade
    # nos ticks ("10%", "20%"...) e o título cairia em cima da legenda
    # horizontal embaixo do plot. PADROES.md §4 cobre essa armadilha.
    layout_kwargs = dict(
        barmode="group",
        bargap=0.25,
        bargroupgap=0.05,
        xaxis=dict(
            ticksuffix="%",
            zeroline=True,
            zerolinecolor="#999",
        ),
        yaxis=dict(title=None, automargin=True),
        height=height,
        legend=dict(
            orientation="h", yanchor="top", y=-0.15,
            xanchor="center", x=0.5, font=dict(size=12),
        ),
        margin=dict(l=10, r=50, t=50 if title else 20, b=80),
        hoverlabel=dict(
            bgcolor="white", font_size=14, align="left", bordercolor="#333",
        ),
        plot_bgcolor="rgba(0,0,0,0)",
    )
    if title:
        layout_kwargs["title"] = dict(text=title, font=dict(size=15))
    fig.update_layout(**layout_kwargs)

    st.plotly_chart(fig, use_container_width=True)
