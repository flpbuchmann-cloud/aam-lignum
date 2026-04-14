"""Matching engine that combines PDF parsing with the asset registry.

Takes parsed PDF output (list of {name, value, source}) and matches each
asset against the master registry. Returns matched and unmatched lists.
"""

from dataclasses import dataclass, field

from .registry import AssetRegistry


@dataclass
class MatchResult:
    """Result of matching a single parsed asset against the registry."""
    # From PDF
    pdf_name: str
    value: float
    source: str

    # Match status
    status: str = "unmatched"  # "exact", "fuzzy", "manual", "unmatched"
    confidence: float = 0.0

    # From registry (if matched)
    registry_asset: dict = field(default_factory=dict)

    # Fuzzy candidates (if status == "fuzzy" or "unmatched")
    fuzzy_candidates: list = field(default_factory=list)

    @property
    def nome_1(self) -> str:
        """Display name from registry, or PDF name if unmatched."""
        return self.registry_asset.get("nome_1", self.pdf_name)

    @property
    def macro_classe(self) -> str:
        return self.registry_asset.get("macro_classe", "")

    @property
    def micro_classe(self) -> str:
        return self.registry_asset.get("micro_classe", "")

    @property
    def tipo(self) -> str:
        return self.registry_asset.get("tipo", "")

    @property
    def codigo_interno(self) -> str:
        return self.registry_asset.get("codigo_interno", "")


class MatchingEngine:
    """Matches parsed PDF assets against the master registry.

    Usage:
        engine = MatchingEngine()
        results = engine.match(parsed_assets)
        # results is a list of MatchResult

        # User can confirm fuzzy matches:
        engine.confirm_match(result, registry_asset)

        # Or mark as manually matched:
        engine.manual_match(result, registry_asset)
    """

    def __init__(self, registry: AssetRegistry | None = None):
        self.registry = registry or AssetRegistry()
        if not self.registry._loaded:
            self.registry.load()

    def match(self, parsed_assets: list[dict], fuzzy_threshold: float = 0.55) -> list[MatchResult]:
        """Match parsed assets against the registry.

        For each asset:
        1. Try exact match (normalized name comparison)
        2. If no exact match, try fuzzy matching
        3. If best fuzzy match score >= 0.8, auto-accept it
        4. Otherwise, mark as unmatched with fuzzy candidates

        Args:
            parsed_assets: List of dicts with keys: name, value, source
            fuzzy_threshold: Minimum score for fuzzy match candidates.

        Returns:
            List of MatchResult objects.
        """
        results = []

        for asset in parsed_assets:
            name = asset["name"]
            value = asset["value"]
            source = asset.get("source", "unknown")

            result = MatchResult(
                pdf_name=name,
                value=value,
                source=source,
            )

            # Step 1: Exact match
            exact = self.registry.find_match(name)
            if exact:
                result.status = "exact"
                result.confidence = 1.0
                result.registry_asset = exact
                results.append(result)
                continue

            # Step 2: Fuzzy match
            fuzzy = self.registry.find_fuzzy_match(name, threshold=fuzzy_threshold)
            if fuzzy:
                best = fuzzy[0]
                result.fuzzy_candidates = fuzzy[:5]  # Keep top 5

                if best["score"] >= 0.80:
                    # High confidence fuzzy match - auto accept
                    result.status = "fuzzy"
                    result.confidence = best["score"]
                    result.registry_asset = best["asset"]
                else:
                    # Low confidence - needs manual review
                    result.status = "unmatched"
                    result.confidence = best["score"]
            else:
                result.status = "unmatched"
                result.confidence = 0.0

            results.append(result)

        return results

    def confirm_match(self, result: MatchResult, registry_asset: dict) -> None:
        """Confirm a fuzzy match or manually assign a registry asset.

        Args:
            result: The MatchResult to update.
            registry_asset: The registry asset dict to assign.
        """
        result.status = "manual"
        result.confidence = 1.0
        result.registry_asset = registry_asset

    def get_summary(self, results: list[MatchResult]) -> dict:
        """Get a summary of matching results.

        Returns dict with counts and lists for each status.
        """
        summary = {
            "total": len(results),
            "exact": [],
            "fuzzy": [],
            "manual": [],
            "unmatched": [],
            "total_value": 0.0,
            "matched_value": 0.0,
            "unmatched_value": 0.0,
        }

        for r in results:
            summary[r.status].append(r)
            summary["total_value"] += r.value
            if r.status in ("exact", "fuzzy", "manual"):
                summary["matched_value"] += r.value
            else:
                summary["unmatched_value"] += r.value

        return summary

    def build_allocation_table(self, results: list[MatchResult]) -> list[dict]:
        """Build the asset allocation table from matched results.

        Only includes matched assets (exact, fuzzy, manual).
        Skips unmatched assets.

        Returns list of dicts with:
            - nome_1: Display name
            - value: Position value
            - pct_pl: Percentage of total PL
            - macro_classe: Macro classification
            - micro_classe: Micro classification
            - tipo: Asset type
            - codigo_interno: Internal code
            - status: Match status
        """
        # Calculate total PL from ALL assets (including unmatched)
        total_pl = sum(r.value for r in results)

        table = []
        for r in results:
            if r.status == "unmatched":
                # Include unmatched with PDF name
                row = {
                    "nome_1": r.pdf_name,
                    "value": r.value,
                    "pct_pl": (r.value / total_pl * 100) if total_pl else 0,
                    "macro_classe": "Não Classificado",
                    "micro_classe": "Não Classificado",
                    "tipo": "",
                    "codigo_interno": "",
                    "status": r.status,
                }
            else:
                row = {
                    "nome_1": r.nome_1,
                    "value": r.value,
                    "pct_pl": (r.value / total_pl * 100) if total_pl else 0,
                    "macro_classe": r.macro_classe,
                    "micro_classe": r.micro_classe,
                    "tipo": r.tipo,
                    "codigo_interno": r.codigo_interno,
                    "status": r.status,
                }
            table.append(row)

        # Sort by value descending
        table.sort(key=lambda x: x["value"], reverse=True)
        return table
