"""RF Carrego (fixed income carry) view builder.

Filters matched assets marked as "Ativo de Carrego" in the Base de Dados
and builds carry analysis with duration, gross-up for tax-exempt assets,
and weighted average rate calculations.

Duration: For bullet bonds (no intermediate cash flows),
    Duration = (Data Vencimento - Hoje) in years

Gross-up (for tax-exempt assets like LCI, LCA, CRI, CRA, deb incentivada):
    IR regressivo brackets based on remaining days to maturity:
      0-180 days:  22.5%
      181-360:     20.0%
      361-720:     17.5%
      721+:        15.0%
    Taxa Bruta = Taxa Liquida / (1 - aliquota)

Indexador naming:
    "Renda Fixa Prefixada" / "IRF-M" -> PRE
    "Renda Fixa IPCA+" / "IMA-B"    -> IPCA
    "Renda Fixa Pos" / "DI/Cash"    -> POS
"""

from datetime import datetime

import pandas as pd

from src.matching.engine import MatchResult


def _parse_taxa(taxa_str: str) -> float:
    """Parse a Brazilian percentage string to float. Returns 0 if invalid."""
    if not taxa_str:
        return 0.0
    cleaned = taxa_str.strip().replace("%", "").replace(",", ".")
    try:
        return float(cleaned)
    except ValueError:
        return 0.0


def _parse_date(date_str: str) -> datetime | None:
    """Parse DD/MM/YYYY date string."""
    if not date_str or not date_str.strip():
        return None
    try:
        return datetime.strptime(date_str.strip(), "%d/%m/%Y")
    except ValueError:
        return None


def _get_indexador(micro_classe: str) -> str:
    """Map micro_classe to indexador name."""
    micro = micro_classe.upper() if micro_classe else ""
    if any(k in micro for k in ["PREFIXADA", "PRÉ", "PRE", "IRF-M", "IRF M"]):
        return "Renda Fixa Prefixada"
    if any(k in micro for k in ["IPCA", "IMA-B", "IMA B"]):
        return "Renda Fixa IPCA+"
    if any(k in micro for k in ["POS", "PÓS", "DI/CASH", "DI CASH"]):
        return "Renda Fixa Pós"
    return "Renda Fixa Pós"


def _get_ir_bracket(days_to_maturity: int) -> float:
    """Get IR aliquota based on remaining days to maturity."""
    if days_to_maturity <= 180:
        return 0.225
    elif days_to_maturity <= 360:
        return 0.20
    elif days_to_maturity <= 720:
        return 0.175
    else:
        return 0.15


def _gross_up(taxa: float, aliquota: float) -> float:
    """Gross up a tax-exempt rate to its taxable equivalent.

    taxa_bruta = taxa_liquida / (1 - aliquota)
    """
    if aliquota >= 1.0:
        return taxa
    return taxa / (1 - aliquota)


def _duration_years(data_vencimento: str) -> float | None:
    """Compute duration in years for a bullet bond (no cash flows)."""
    dt = _parse_date(data_vencimento)
    if dt is None:
        return None
    days = (dt - datetime.now()).days
    if days < 0:
        return 0.0
    return round(days / 365.25, 2)


def _duration_days(data_vencimento: str) -> int | None:
    """Compute remaining days to maturity."""
    dt = _parse_date(data_vencimento)
    if dt is None:
        return None
    days = (dt - datetime.now()).days
    return max(days, 0)


class RFCarregoBuilder:
    """Builds RF Carrego analysis from match results."""

    def __init__(self, results: list[MatchResult], cdi: float = 0.0, ipca: float = 0.0):
        """
        Args:
            results: All client positions (matched).
            cdi: Current CDI rate (annual, e.g., 14.90 for 14.90%).
            ipca: IPCA 12M rate (e.g., 5.35 for 5.35%).
        """
        self.all_results = results
        self.total_pl = sum(r.value for r in results)
        self.cdi = cdi
        self.ipca = ipca

    def filter_rf_carrego(self) -> list[MatchResult]:
        """Filter to RF positions marked as 'Ativo de Carrego' in Base de Dados."""
        filtered = []
        for r in self.all_results:
            if r.status == "unmatched":
                continue
            carrego = r.registry_asset.get("ativo_carrego", "")
            if carrego == "x":
                filtered.append(r)
        return filtered

    def build_carrego_table(self) -> pd.DataFrame:
        """Build the RF Carrego positions table with all analytics."""
        rf_assets = self.filter_rf_carrego()
        if not rf_assets:
            return pd.DataFrame()

        total_rf = sum(r.value for r in rf_assets)
        rows = []

        for r in rf_assets:
            asset = r.registry_asset
            taxa_raw = _parse_taxa(asset.get("taxa", ""))
            micro = r.micro_classe
            indexador = _get_indexador(micro)
            is_exempt = asset.get("ativo_isento", "") == "x"
            vencimento = asset.get("data_vencimento", "")
            duration = _duration_years(vencimento)
            days = _duration_days(vencimento)

            # Gross up for exempt assets
            taxa_bruta = taxa_raw
            if is_exempt and days is not None:
                aliquota = _get_ir_bracket(days)
                taxa_bruta = round(_gross_up(taxa_raw, aliquota), 2)

            # Convert to equivalent pre rate (annual)
            taxa_pre = self._to_pre_rate(taxa_bruta, indexador)

            # Convert to real rate (adjusted for inflation)
            taxa_real = self._to_real_rate(taxa_pre)

            # Convert to % CDI
            pct_cdi = self._to_pct_cdi(taxa_pre)

            # Convert to CDI+ spread
            cdi_spread = self._to_cdi_spread(taxa_pre)

            pct_pl = (r.value / self.total_pl * 100) if self.total_pl else 0
            pct_classe = (r.value / total_rf * 100) if total_rf else 0

            rows.append({
                "Ativo": r.nome_1,
                "Posicao": r.value,
                "% PL": round(pct_pl, 2),
                "% Classe": round(pct_classe, 2),
                "Emissor": asset.get("emissor", ""),
                "Data Aplicacao": asset.get("data_aplicacao", ""),
                "Vencimento": vencimento,
                "Taxa": asset.get("taxa", ""),
                "Taxa Bruta": f"{taxa_bruta:.2f}%" if taxa_bruta else "",
                "Isento": "Sim" if is_exempt else "",
                "Indexador": indexador,
                "Duration (anos)": duration if duration is not None else "",
                # Hidden columns for calculations
                "_taxa_pre": taxa_pre,
                "_taxa_real": taxa_real,
                "_pct_cdi": pct_cdi,
                "_cdi_spread": cdi_spread,
                "_value": r.value,
            })

        df = pd.DataFrame(rows)
        if not df.empty:
            df = df.sort_values("Posicao", ascending=False).reset_index(drop=True)
        return df

    def _to_pre_rate(self, taxa: float, indexador: str) -> float:
        """Convert any rate to equivalent pre-fixed annual rate."""
        if not taxa:
            return 0.0

        if indexador == "Renda Fixa Prefixada":
            return taxa

        if indexador == "Renda Fixa IPCA+":
            # Fisher: (1 + nominal) = (1 + real)(1 + inflacao)
            # taxa here is the real spread, e.g., 6.38%
            nominal = (1 + taxa / 100) * (1 + self.ipca / 100) - 1
            return round(nominal * 100, 2)

        if indexador == "Renda Fixa Pós":
            if taxa > 50:
                # % of CDI (e.g., 104% CDI)
                return round(self.cdi * taxa / 100, 2)
            else:
                # CDI + spread (e.g., CDI + 5.35%)
                return round(self.cdi + taxa, 2)

        return taxa

    def _to_real_rate(self, taxa_pre: float) -> float:
        """Convert pre rate to real rate (inflation-adjusted)."""
        if not taxa_pre or not self.ipca:
            return 0.0
        # Fisher: real = (1 + nominal)/(1 + inflacao) - 1
        real = (1 + taxa_pre / 100) / (1 + self.ipca / 100) - 1
        return round(real * 100, 2)

    def _to_pct_cdi(self, taxa_pre: float) -> float:
        """Convert pre rate to % of CDI."""
        if not taxa_pre or not self.cdi:
            return 0.0
        return round(taxa_pre / self.cdi * 100, 2)

    def _to_cdi_spread(self, taxa_pre: float) -> float:
        """Convert pre rate to CDI+ spread."""
        if not taxa_pre:
            return 0.0
        return round(taxa_pre - self.cdi, 2)

    def build_kpis(self) -> dict:
        """Build key performance indicators for the RF Carrego portfolio.

        Returns dict with:
            total_value, pct_pl, duration_avg,
            taxa_pre_media, taxa_real_media, pct_cdi_medio, cdi_spread_medio
        """
        table = self.build_carrego_table()
        if table.empty:
            return {}

        total_rf = table["_value"].sum()
        pct_pl = (total_rf / self.total_pl * 100) if self.total_pl else 0

        # Weighted average duration
        dur_rows = table[table["Duration (anos)"] != ""].copy()
        if not dur_rows.empty:
            dur_rows["Duration (anos)"] = pd.to_numeric(dur_rows["Duration (anos)"])
            duration_avg = (dur_rows["Duration (anos)"] * dur_rows["_value"]).sum() / dur_rows["_value"].sum()
        else:
            duration_avg = 0

        # Weighted average rates
        weights = table["_value"]
        total_w = weights.sum()

        if total_w > 0:
            taxa_pre_media = (table["_taxa_pre"] * weights).sum() / total_w
            taxa_real_media = (table["_taxa_real"] * weights).sum() / total_w
            pct_cdi_medio = (table["_pct_cdi"] * weights).sum() / total_w
            cdi_spread_medio = (table["_cdi_spread"] * weights).sum() / total_w
        else:
            taxa_pre_media = taxa_real_media = pct_cdi_medio = cdi_spread_medio = 0

        return {
            "total_value": total_rf,
            "pct_pl": round(pct_pl, 2),
            "duration_avg": round(duration_avg, 2),
            "taxa_pre_media": round(taxa_pre_media, 2),
            "taxa_real_media": round(taxa_real_media, 2),
            "pct_cdi_medio": round(pct_cdi_medio, 2),
            "cdi_spread_medio": round(cdi_spread_medio, 2),
        }

    def build_indexer_allocation(self) -> pd.DataFrame:
        """Build allocation by indexer."""
        table = self.build_carrego_table()
        if table.empty:
            return pd.DataFrame()

        total_rf = table["Posicao"].sum()
        grouped = table.groupby("Indexador")["Posicao"].sum().reset_index()
        grouped.columns = ["Indexador", "Valor"]
        grouped["% RF"] = (grouped["Valor"] / total_rf * 100).round(2) if total_rf else 0
        grouped["% PL"] = (grouped["Valor"] / self.total_pl * 100).round(2) if self.total_pl else 0
        return grouped.sort_values("Valor", ascending=False).reset_index(drop=True)

    def build_issuer_allocation(self) -> pd.DataFrame:
        """Build allocation by issuer/institution."""
        table = self.build_carrego_table()
        if table.empty:
            return pd.DataFrame()

        total_rf = table["Posicao"].sum()
        grouped = table.groupby("Emissor")["Posicao"].sum().reset_index()
        grouped.columns = ["Emissor", "Valor"]
        grouped["% RF"] = (grouped["Valor"] / total_rf * 100).round(2) if total_rf else 0
        grouped["% PL"] = (grouped["Valor"] / self.total_pl * 100).round(2) if self.total_pl else 0
        return grouped.sort_values("Valor", ascending=False).reset_index(drop=True)

    def build_duration_summary(self) -> pd.DataFrame:
        """Build duration summary by indexer."""
        table = self.build_carrego_table()
        if table.empty:
            return pd.DataFrame()

        df = table[table["Duration (anos)"] != ""].copy()
        if df.empty:
            return pd.DataFrame()

        df["Duration (anos)"] = pd.to_numeric(df["Duration (anos)"])
        rows = []
        for idx_name, group in df.groupby("Indexador"):
            total_val = group["Posicao"].sum()
            weighted_dur = (group["Duration (anos)"] * group["Posicao"]).sum() / total_val if total_val else 0
            rows.append({
                "Indexador": idx_name,
                "Duration Ponderada (anos)": round(weighted_dur, 2),
                "Valor": total_val,
            })
        return pd.DataFrame(rows).sort_values("Valor", ascending=False).reset_index(drop=True)
