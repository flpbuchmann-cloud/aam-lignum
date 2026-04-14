"""XP Investimentos broker PDF parser.

Parses monthly investment reports (XPerformance) from XP.

PDF structure:
    Pages 1-6: Summary, performance, composition (skip)
    Pages 7+:  "POSICAO DETALHADA" with individual asset positions
    Last page: Disclaimer

Position line format:
    "Asset Name R$ XX.XXX,XX  Quantity  %Aloc  Rent  %CDI  ..."

Strategy subtotal lines have "-" as quantity and are skipped.
Options (CALL/PUT) are skipped.
"""

import re
import pdfplumber
from .base import BaseParser

# Strategy headers (subtotals) - skip these
STRATEGY_HEADERS = {
    "Pós Fixado",
    "Inflação",
    "Pré Fixado",
    "Renda Variável Brasil",
    "Fundos Listados",
    "Caixa",
    "Proventos",
    "Internacional",
    "Multimercado",
    "Alternativo",
}

# Skip options and derivatives
SKIP_PATTERNS = ["(CALL)", "(PUT)", "(TERMO)", "Futuros", "Derivativos"]

# Brazilian number: R$ XX.XXX,XX or -R$ XX.XXX,XX
BR_VALUE_PATTERN = re.compile(r"-?R\$\s*[\d]+(?:\.[\d]{3})*,[\d]{2}")
BR_NUMBER_PATTERN = re.compile(r"-?[\d]+(?:\.[\d]{3})*,[\d]{2}")


class XPParser(BaseParser):
    """Parser for XP Investimentos monthly reports (XPerformance)."""

    def parse(self, pdf_path: str) -> list[dict]:
        """Parse an XP PDF and extract all asset positions."""
        with pdfplumber.open(pdf_path) as pdf:
            all_text = []
            for page in pdf.pages:
                text = page.extract_text() or ""
                all_text.append(text)

            # Find "POSICAO DETALHADA" pages
            position_pages = []
            for text in all_text:
                if "POSIÇÃO DETALHADA" in text or "POSICAO DETALHADA" in text:
                    position_pages.append(text)

            assets = []
            for page_text in position_pages:
                page_assets = self._parse_position_page(page_text)
                assets.extend(page_assets)

            # Extract Caixa from composition page if available
            caixa = self._extract_caixa(all_text)
            if caixa:
                assets.append(caixa)

            return assets

    def _parse_position_page(self, text: str) -> list[dict]:
        """Parse a POSICAO DETALHADA page."""
        lines = text.split("\n")
        assets = []

        for line in lines:
            stripped = line.strip()
            if not stripped:
                continue

            # Skip header lines
            if any(h in stripped for h in [
                "POSIÇÃO DETALHADA", "POSICAO DETALHADA",
                "PRECIFICAÇÃO", "MÊS ATUAL", "Estratégia",
                "Relatório informativo", "*Aviso",
            ]):
                continue

            # Skip page numbers
            if re.match(r"^\d{2}$", stripped):
                continue

            # Skip options/derivatives
            if any(pat in stripped for pat in SKIP_PATTERNS):
                continue

            # Try to parse as asset line
            asset = self._parse_asset_line(stripped)
            if asset:
                assets.append(asset)

        return assets

    def _parse_asset_line(self, line: str) -> dict | None:
        """Try to parse a line as an asset position.

        XP format: "Asset Name R$ XX.XXX,XX Qty %Aloc ..."
        Strategy subtotals have "-" as Qty, individual assets have numbers.
        """
        # Must contain R$ value
        value_match = BR_VALUE_PATTERN.search(line)
        if not value_match:
            return None

        # Extract the value
        value_str = value_match.group()
        value = self._parse_value(value_str)
        if value is None:
            return None

        # Everything before R$ is the asset name
        name = line[:value_match.start()].strip()
        if not name:
            return None

        # Check if this is a strategy subtotal (has "-" as quantity after value)
        after_value = line[value_match.end():].strip()

        # Strategy subtotals: "R$ 59.647,97 - 10,38% ..."
        # Individual assets: "R$ 30.297,25 30 5,27% ..."
        # Strategy lines have "-" as first token after value
        if after_value.startswith("- ") or after_value == "-":
            # Check if name matches known strategy
            name_lower = name.lower()
            for strategy in STRATEGY_HEADERS:
                if name_lower.startswith(strategy.lower()):
                    return None  # Skip strategy subtotal
            # If not a known strategy but has "-" qty, still might be subtotal
            # Check: if the name contains a percentage in parentheses, it's a strategy
            if re.search(r"\(\d+[.,]\d+%\)", name):
                return None

        # Clean up name - remove trailing whitespace
        name = name.strip()

        # Skip if value is 0
        if value == 0:
            return None

        return {"name": name, "value": value, "source": "xp"}

    def _extract_caixa(self, all_text: list[str]) -> dict | None:
        """Extract Caixa (cash) position from composition page."""
        for text in all_text:
            if "COMPOSIÇÃO" in text or "COMPOSICAO" in text:
                lines = text.split("\n")
                for line in lines:
                    # Pattern: "Caixa (X,XX%) R$ XXX,XX"
                    if line.strip().startswith("Caixa"):
                        value_match = BR_VALUE_PATTERN.search(line)
                        if value_match:
                            value = self._parse_value(value_match.group())
                            if value and value > 0:
                                return {"name": "Caixa", "value": value, "source": "xp"}
        return None

    @staticmethod
    def _parse_value(value_str: str) -> float | None:
        """Parse a Brazilian R$ value string to float."""
        # Remove "R$" and whitespace
        cleaned = value_str.replace("R$", "").strip()
        # Handle negative
        negative = cleaned.startswith("-")
        cleaned = cleaned.lstrip("-").strip()
        # Remove thousand separators and convert decimal
        cleaned = cleaned.replace(".", "").replace(",", ".")
        try:
            val = float(cleaned)
            return -val if negative else val
        except ValueError:
            return None
