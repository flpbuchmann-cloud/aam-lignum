"""Asset Allocation view builder.

Builds positions table and macro/micro class consolidation
from MatchResult data.
"""

import pandas as pd

from src.matching.engine import MatchResult
from src.views.ordering import macro_sort_key


class AAViewBuilder:
    """Builds Asset Allocation tables from match results."""

    def __init__(self, results: list[MatchResult]):
        self.results = results
        self.total_pl = sum(r.value for r in results)

    def build_positions_table(self) -> pd.DataFrame:
        """Build the full positions table.

        Returns DataFrame with columns:
            Ativo, Valor, % PL, Macro Classe, Micro Classe, Tipo, Status, Corretora
        """
        rows = []
        for r in self.results:
            if r.status == "unmatched":
                nome = r.pdf_name
                macro = "Nao Classificado"
                micro = "Nao Classificado"
                tipo = ""
            else:
                nome = r.nome_1
                macro = r.macro_classe
                micro = r.micro_classe
                tipo = r.tipo

            pct = (r.value / self.total_pl * 100) if self.total_pl else 0
            rows.append({
                "Ativo": nome,
                "Valor": r.value,
                "% PL": pct,
                "Macro Classe": macro,
                "Micro Classe": micro,
                "Tipo": tipo,
                "Status": r.status,
                "Corretora": (r.source or "").title() if r.source else "",
            })

        df = pd.DataFrame(rows)
        if not df.empty:
            df = df.sort_values("Valor", ascending=False).reset_index(drop=True)
        return df

    def build_macro_consolidation(self, targets: dict[str, float] | None = None) -> pd.DataFrame:
        """Build consolidation by Macro Classe.

        Args:
            targets: Dict of macro_classe -> target % (e.g., {"DI/Cash": 5.0})

        Returns DataFrame with columns:
            Macro Classe, Valor, % Atual, % Target, Diferenca
        """
        if targets is None:
            targets = {}

        positions = self.build_positions_table()
        if positions.empty:
            return pd.DataFrame()

        grouped = positions.groupby("Macro Classe")["Valor"].sum().reset_index()
        grouped.columns = ["Macro Classe", "Valor"]
        grouped["% Atual"] = (grouped["Valor"] / self.total_pl * 100).round(2)
        grouped["% Target"] = grouped["Macro Classe"].map(
            lambda x: targets.get(x, 0.0)
        )
        grouped["Diferenca"] = (grouped["% Atual"] - grouped["% Target"]).round(2)
        # Ordem canônica (PADROES.md §6): Caixa → DI/Cash → RF → RV → Mm →
        # Internacional → Fundo Exclusivo → Previdência → Alternativos.
        grouped["_sort"] = grouped["Macro Classe"].apply(macro_sort_key)
        grouped = grouped.sort_values("_sort").drop(columns="_sort").reset_index(drop=True)
        return grouped

    def build_corretora_consolidation(self) -> pd.DataFrame:
        """Build consolidation by Corretora (broker/institution).

        Returns DataFrame with columns: Corretora, Valor, % PL
        """
        positions = self.build_positions_table()
        if positions.empty:
            return pd.DataFrame()

        grouped = positions.groupby("Corretora")["Valor"].sum().reset_index()
        grouped.columns = ["Corretora", "Valor"]
        grouped["% PL"] = (grouped["Valor"] / self.total_pl * 100).round(2)
        grouped = grouped.sort_values("Valor", ascending=False).reset_index(drop=True)
        return grouped

    def build_micro_consolidation(self) -> pd.DataFrame:
        """Build consolidation by Micro Classe.

        Returns DataFrame with columns:
            Macro Classe, Micro Classe, Valor, % Atual

        Ordenado pela ordem canônica de Macro (PADROES.md §6) e, dentro de
        cada macro, por Valor decrescente.
        """
        positions = self.build_positions_table()
        if positions.empty:
            return pd.DataFrame()

        grouped = (
            positions.groupby(["Macro Classe", "Micro Classe"])["Valor"]
            .sum()
            .reset_index()
        )
        grouped["% Atual"] = (grouped["Valor"] / self.total_pl * 100).round(2)
        grouped["_sort"] = grouped["Macro Classe"].apply(macro_sort_key)
        grouped = (
            grouped.sort_values(["_sort", "Valor"], ascending=[True, False])
            .drop(columns="_sort")
            .reset_index(drop=True)
        )
        return grouped
