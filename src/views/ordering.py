"""Ordenação canônica de Macro/Micro Classe.

Padrão global (registrado em PADROES.md, seção 6):
- Macro Classe: ordem canônica fixa (Caixa → DI/Cash → Renda Fixa →
  Renda Variável → Multimercado → Internacional → Fundo Exclusivo →
  Previdência → Alternativos). Macros não listadas vêm alfabeticamente
  depois; "Não Classificado" no fim.
- Micro Classe: agrupado pela ordem da macro mãe; dentro de cada macro,
  ordena-se por Valor (desc) para destacar maiores posições primeiro.
"""

from __future__ import annotations

import unicodedata


# Ordem canônica de Macro Classe (cash → conservador → variável → alternativos).
# Tolerante a variantes com/sem acento via _normalize_macro.
MACRO_ORDER: list[str] = [
    "Caixa",
    "DI/Cash",
    "Renda Fixa",
    "Renda Variável",
    "Multimercado",
    "Internacional",
    "Fundo Exclusivo",
    "Previdência",
    "Alternativos",
]


def _normalize_macro(s: str) -> str:
    """Lower + strip accents, para matching tolerante de variantes."""
    if s is None:
        return ""
    nfkd = unicodedata.normalize("NFKD", str(s).strip())
    return "".join(c for c in nfkd if not unicodedata.combining(c)).lower()


_MACRO_INDEX: dict[str, int] = {
    _normalize_macro(m): i for i, m in enumerate(MACRO_ORDER)
}


def macro_sort_key(macro: str) -> tuple[int, str]:
    """Chave de ordenação para macro: canônico primeiro, depois alfabético.

    - Macros em MACRO_ORDER: posição na lista
    - "Não Classificado" / "Nao Classificado": vai pro fim
    - Outros: alfabético, depois das canônicas
    """
    norm = _normalize_macro(macro)
    if norm in _MACRO_INDEX:
        return (_MACRO_INDEX[norm], "")
    if "nao classificado" in norm or "não classificado" in (macro or "").lower():
        return (len(MACRO_ORDER) + 1, norm)
    return (len(MACRO_ORDER), norm)


def disambiguate_micro_by_macro(
    df,
    *,
    micro_col: str = "Micro Classe",
    macro_col: str = "Macro Classe",
):
    """Anexa a Macro entre parênteses no nome da Micro quando ela aparece
    em mais de uma Macro Classe.

    Por que: o editor de consolidação e o storage de % Sugerido usam
    `Micro Classe` como chave única. Sem essa disambiguação, micros
    homônimas em macros distintas (ex.: "Ações" em "Renda Variável" e em
    "Internacional") colapsam num único registro — last-write-wins
    no dict de save, o usuário acha que não persistiu.

    Idempotente: se já tiver "(Macro)" sufixado, não duplica.
    """
    import pandas as pd  # local import: módulo ordering puro evita ciclo

    if df is None or df.empty or macro_col not in df.columns:
        return df
    counts = df[micro_col].value_counts()
    dupes = set(counts[counts > 1].index)
    if not dupes:
        return df

    df = df.copy()

    def _label(row):
        micro = row[micro_col]
        if micro not in dupes:
            return micro
        suffix = f" ({row[macro_col]})"
        if str(micro).endswith(suffix):
            return micro
        return f"{micro}{suffix}"

    df[micro_col] = df.apply(_label, axis=1)
    return df
