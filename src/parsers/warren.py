"""Warren broker PDF parser.

Parses monthly investment reports from Warren (Renascenca DTVM).

PDF structure:
    Pages 1-8: Summary, performance, allocation, sub-portfolios (skip)
    Pages 9+:  "Produtos" section with individual asset positions
    Last page: "Proventos" section with dividend history (has correct stock tickers)

Key challenges:
    - Stock tickers are corrupted by pdfplumber (only digits remain, letters stripped)
      e.g., "VALE3" appears as just "3", "PETR4" as "4", "ALOS3" as "3"
    - Category headers (subtotals) look like asset lines but must be skipped
    - Individual assets have "Inicio:" on the following line
"""

import re
import pdfplumber
from .base import BaseParser


# Category headers that appear as subtotals - these have values but should be skipped.
# They appear right before the individual assets of that category.
CATEGORY_HEADERS = {
    "Pós-fixado Liquidez",
    "Pós-fixado Crédito Privado",
    "Pós-fixado",
    "Prefixado",
    "Inflação",
    "Multimercado",
    "Ações Brasil",
    "Imobiliário",
    "Outros",
    # pdfplumber-corrupted variants (Type3 font encoding issues)
    "P\ufffds-fixado Liquidez",
    "P\ufffds-fixado Cr\ufffddito Privado",
    "P\ufffds-fixado",
    "Infla\ufffd\ufffdo",
    "A\ufffd\ufffdes Brasil",
    "Imobili\ufffdrio",
}

# Lines containing these keywords should be skipped entirely
SKIP_KEYWORDS = [
    "Dividendo",
    "Juros sobre capital",
    "Restituição de capital",
    "Rendimento",
    "Deliberação:",
    "Pagamento:",
]

# Section headers that indicate page context
SECTION_MARKERS = ["Produtos", "Proventos", "Alocação", "Performance", "Resumo"]

# Pattern: Brazilian number like 889.309,06 or -7.369,59
BR_NUMBER_PATTERN = re.compile(r"-?[\d]+(?:\.[\d]{3})*,[\d]{2}")

# Pattern: percentage like 5,78% or -0,05%
PCT_PATTERN = re.compile(r"-?[\d]+,[\d]+%")

# Pattern: "Início:" line that follows an asset line
# Handles: Início, Inicio, In�cio (corrupted í)
INICIO_PATTERN = re.compile(r"^In[ií\ufffd]cio:", re.IGNORECASE)

# Pattern for corrupted stock ticker lines (just digits, possibly with spaces)
CORRUPTED_TICKER_PATTERN = re.compile(r"^\s+\d+\s*$")

# Unicode replacement character inserted by pdfplumber for unmapped glyphs
REPLACEMENT_CHAR = "\ufffd"


def _clean_asset_name(name: str) -> str:
    """Clean up an asset name extracted from PDF.

    Handles:
    - Trailing corrupted CNPJ/codes with replacement chars (e.g., "... ���32033�HI")
    - Trailing partial codes after closing parenthesis (e.g., "...)    32033 HI")
    - Isolated replacement characters
    - Excess whitespace
    """
    if not name:
        return name

    # Remove null bytes (from Type3 font unmapped glyphs rendered as U+0000)
    # These appear in corrupted CNPJ codes and ticker fragments
    if "\x00" in name:
        # Find the first null byte - everything from there is likely garbled
        first_null = name.index("\x00")
        prefix = name[:first_null].rstrip()
        if len(prefix) >= 3:
            name = prefix
        else:
            name = name.replace("\x00", "").strip()

    # Remove sequences containing replacement chars
    if REPLACEMENT_CHAR in name:
        first_idx = name.index(REPLACEMENT_CHAR)
        prefix = name[:first_idx].rstrip()
        if len(prefix) >= 3:
            name = prefix
        else:
            name = name.replace(REPLACEMENT_CHAR, "").strip()

    # Remove trailing corrupted CNPJ/code fragments after closing paren or %
    # e.g., "PT CDB Pré BS2 (6a/8,10%)    32033 HI" → "PT CDB Pré BS2 (6a/8,10%)"
    # e.g., "PT CDB IPCA+ BS2 (6a/4,25%)    320    1" → "PT CDB IPCA+ BS2 (6a/4,25%)"
    # e.g., "CRI - VETTER - CDI+3% a.a. - 29/07/2030 - 25" → keep as-is (no garbled part)
    # Match: "name (info%)    garbled_code" or "name (info))    garbled_code"
    # The %) or ) must be followed by 3+ spaces and then non-space chars (the garbled code)
    match = re.match(r"^(.+[%)]) {3,}\S", name)
    if match:
        name = match.group(1).rstrip()

    # Also handle names ending with "- CODE" where CODE is a partial CNPJ
    # e.g., "CRI - VETTER - CDI+3% a.a. - 29/07/2030 - 25" → trim trailing " - 25"
    # Only if the last segment is very short (< 5 chars) and looks like a code fragment
    match2 = re.match(r"^(.+\d{4}) - (\w{1,4})$", name)
    if match2:
        name = match2.group(1)

    # Clean up trailing …, whitespace, dashes
    name = re.sub(r"\s+", " ", name).strip()
    name = name.rstrip(" -…\u2026")

    return name


class WarrenParser(BaseParser):
    """Parser for Warren (Renascenca DTVM) monthly investment reports."""

    def parse(self, pdf_path: str) -> list[dict]:
        """Parse a Warren PDF and extract all asset positions.

        Args:
            pdf_path: Path to the Warren PDF file.

        Returns:
            List of dicts with keys: name, value, source
        """
        with pdfplumber.open(pdf_path) as pdf:
            all_pages_text = []
            for page in pdf.pages:
                text = page.extract_text() or ""
                all_pages_text.append(text)

            # Find Produtos pages and Proventos page
            produtos_pages = []
            proventos_text = ""

            for i, text in enumerate(all_pages_text):
                first_line = text.split("\n")[0] if text else ""
                if "Produtos" in first_line:
                    produtos_pages.append(text)
                elif "Proventos" in first_line:
                    proventos_text = text

            # Extract stock ticker mapping from Proventos page
            # The Proventos page has correct tickers unlike the Produtos pages
            # Not directly usable for value matching since it shows monthly dividends,
            # not position values. We'll handle corrupted tickers differently.

            # Parse all Produtos pages
            assets = []
            for page_text in produtos_pages:
                page_assets = self._parse_produtos_page(page_text)
                assets.extend(page_assets)

            # Try to resolve corrupted stock names using Proventos
            # Since Proventos doesn't have position values, we can't match by value.
            # Instead, we pass through the corrupted names and let the matching
            # engine handle them (user will need to confirm).

            return assets

    def _parse_produtos_page(self, text: str) -> list[dict]:
        """Parse a single Produtos page and extract assets.

        The page structure is:
            Header lines (4 lines: title, dates, disclaimer)
            Section header: "Conta" / "Renda Fixa" / "Multimercado" / etc.
            Category line: "Pós-fixado Liquidez  5,78%  889.309,06  ..."  (SKIP - subtotal)
            Asset line:    "AMW Cash Clash FIRF LP  5,78%  889.309,06  ..."
            Início line:   "Início: 27/11/2023  511.698,80..."
            ...

        An asset line is identified by:
            1. Having a Brazilian number (xxx.xxx,xx) representing the value
            2. Being followed by an "Início:" line (checked via look-ahead)
            3. NOT being a category header
            4. NOT containing skip keywords
        """
        lines = text.split("\n")
        assets = []

        # Skip header lines (first 4-5 lines are page header)
        start_idx = 0
        for i, line in enumerate(lines):
            # Look for the first section/category line after headers
            if any(marker in line for marker in ["Conta ", "Renda Fixa ", "Renda Variável ",
                                                   "Multimercado ", "Alternativo ",
                                                   "Conta Corrente", "Conta Investimento",
                                                   "Saldo em Carteiras"]):
                start_idx = i
                break

        i = start_idx
        while i < len(lines):
            line = lines[i].strip()

            # Skip empty lines
            if not line:
                i += 1
                continue

            # Skip section headers like "Renda Fixa  Alocação / Qtd.  Saldo Bruto  ..."
            if self._is_section_header(line):
                i += 1
                continue

            # Skip dividend/JCP/rendimento lines
            if self._should_skip_line(line):
                i += 1
                continue

            # Skip footer lines (client name, page number, bank info)
            if self._is_footer(line):
                i += 1
                continue

            # Skip "Início:" lines (they belong to the previous asset)
            if INICIO_PATTERN.match(line):
                i += 1
                continue

            # Check if this is a category header (subtotal) - skip it
            if self._is_category_header(line):
                i += 1
                continue

            # Try to parse as an asset line
            asset = self._parse_asset_line(line, lines, i)
            if asset:
                assets.append(asset)

            i += 1

        return assets

    def _parse_asset_line(self, line: str, all_lines: list[str], idx: int) -> dict | None:
        """Try to parse a line as an asset position.

        An asset line has the format:
            "Asset Name  allocation%  value  ..."

        We verify it's a real asset (not a subtotal) by checking if the next
        non-skip line is an "Início:" line.

        Returns dict with name, value, source or None if not an asset line.
        """
        # Must contain at least one Brazilian number (the value)
        numbers = BR_NUMBER_PATTERN.findall(line)
        if not numbers:
            return None

        # Must contain at least one percentage
        percentages = PCT_PATTERN.findall(line)
        if not percentages:
            return None

        # Check that a following line has "Início:" (confirming this is an individual asset)
        has_inicio = False
        for j in range(idx + 1, min(idx + 3, len(all_lines))):
            next_line = all_lines[j].strip()
            if INICIO_PATTERN.match(next_line):
                has_inicio = True
                break
            # If we hit another asset line or category, stop looking
            if BR_NUMBER_PATTERN.search(next_line) and PCT_PATTERN.search(next_line):
                break

        if not has_inicio:
            return None

        # Extract the asset name and value
        name, value = self._extract_name_and_value(line)
        if name and value is not None:
            name = _clean_asset_name(name)
            if name:
                return {"name": name, "value": value, "source": "warren"}

        return None

    def _extract_name_and_value(self, line: str) -> tuple[str | None, float | None]:
        """Extract asset name and gross value from an asset line.

        The line format is typically:
            "Asset Name  5,78%  889.309,06  0,91%  102,64%  ..."
            "CDB Pré AGIBANK (2 anos e 16,25% a.a.) 0,96% 147.323,28 ..."
            "PT CDB Pré BS2 (6a/8,10%)    32033 HI 0,60% 92.853,86 ..."

        Challenge: asset names can contain percentages (e.g., "16,25% a.a."),
        so we can't just use the first percentage to split.

        Strategy: Find the Saldo Bruto value first. It's always a Brazilian
        number with thousand separators (e.g., 147.046,70). Then find the
        allocation percentage immediately before it, and everything before
        that percentage is the asset name.
        """
        # Find all BR numbers with thousand separators (the Saldo Bruto)
        # Pattern: at least one dot-separated group, e.g., 889.309,06
        large_num_pattern = re.compile(r"-?[\d]{1,3}(?:\.[\d]{3})+,[\d]{2}")
        large_nums = list(large_num_pattern.finditer(line))

        if large_nums:
            # Use the FIRST large number as the Saldo Bruto
            value_match = large_nums[0]
            value = self.parse_brazilian_number(value_match.group())

            # Find the allocation percentage: it's the last pct% before this value
            prefix = line[:value_match.start()].rstrip()
            pct_matches = list(PCT_PATTERN.finditer(prefix))

            if pct_matches:
                last_pct = pct_matches[-1]
                name = prefix[:last_pct.start()].strip()
                if name and value is not None:
                    return name, value

            # No percentage before the value - use everything before as name
            name = prefix.strip()
            if name and value is not None:
                return name, value

        # Fallback for small values (no thousand separators, e.g., just "42,00")
        # This is rare but handles edge cases
        br_numbers = list(BR_NUMBER_PATTERN.finditer(line))
        pct_matches = list(PCT_PATTERN.finditer(line))

        if br_numbers and pct_matches:
            # Find first pct% followed by a number
            for pct_match in pct_matches:
                after_pct = line[pct_match.end():]
                rate_desc = after_pct.lstrip()
                if rate_desc.startswith(("a.a.", "do CDI", "CDI", "a.a")):
                    continue
                next_num = BR_NUMBER_PATTERN.search(after_pct)
                if next_num:
                    value = self.parse_brazilian_number(next_num.group())
                    name = line[:pct_match.start()].strip()
                    if name and value is not None:
                        return name, value

        return None, None

    def _is_section_header(self, line: str) -> bool:
        """Check if line is a section header like 'Renda Fixa  Alocação / Qtd.  ...'"""
        section_keywords = [
            "Alocação / Qtd.",
            "Alocação Saldo Bruto",
            "Aloca\u00e7\u00e3o / Qtd.",
        ]
        return any(kw in line for kw in section_keywords)

    def _is_category_header(self, line: str) -> bool:
        """Check if line is a category subtotal header.

        Category headers look like asset lines but represent subtotals.
        They are identified by their name matching known categories AND
        not being followed by an Início line.
        """
        line_start = line.split("%")[0].strip().lower() if "%" in line else line.lower()
        # Strip replacement chars for comparison
        line_clean = line_start.replace(REPLACEMENT_CHAR, "")

        for header in CATEGORY_HEADERS:
            header_norm = header.lower()
            header_clean = header_norm.replace(REPLACEMENT_CHAR, "")
            if line_start.startswith(header_norm) or header_norm.startswith(line_start):
                return True
            if line_clean.startswith(header_clean) or header_clean.startswith(line_clean):
                return True
            # Also handle accent-stripped versions
            header_ascii = header_clean.replace("é", "e").replace("ã", "a").replace("á", "a").replace("ó", "o").replace("ç", "c")
            line_ascii = line_clean.replace("é", "e").replace("ã", "a").replace("á", "a").replace("ó", "o").replace("ç", "c")
            if line_ascii.startswith(header_ascii) or header_ascii.startswith(line_ascii):
                return True
        return False

    def _should_skip_line(self, line: str) -> bool:
        """Check if line should be skipped (dividends, JCP, etc.)."""
        line_lower = line.lower()
        for kw in SKIP_KEYWORDS:
            if kw.lower() in line_lower:
                return True
        return False

    def _is_footer(self, line: str) -> bool:
        """Check if line is a page footer."""
        if re.match(r"^Banco:", line):
            return True
        if re.match(r"^\d{2}$", line.strip()):  # Page number like "08"
            return True
        # Client name line (just a name, no numbers)
        if not BR_NUMBER_PATTERN.search(line) and not PCT_PATTERN.search(line):
            # Could be a name, but we handle this by requiring numbers for asset lines
            pass
        return False


class WarrenParserV2(WarrenParser):
    """Enhanced Warren parser that also extracts Conta Corrente / Conta Investimento.

    These lines don't have an "Início:" follow-up, so the base parser skips them.
    This version also uses PyMuPDF to resolve corrupted stock tickers.
    """

    def parse(self, pdf_path: str) -> list[dict]:
        """Parse Warren PDF including account balance lines."""
        with pdfplumber.open(pdf_path) as pdf:
            all_pages_text = []
            for page in pdf.pages:
                text = page.extract_text() or ""
                all_pages_text.append(text)

            produtos_pages = []
            for i, text in enumerate(all_pages_text):
                first_line = text.split("\n")[0] if text else ""
                if "Produtos" in first_line:
                    produtos_pages.append(text)

            assets = []
            for page_text in produtos_pages:
                account_assets = self._extract_account_lines(page_text)
                assets.extend(account_assets)

                page_assets = self._parse_produtos_page(page_text)
                assets.extend(page_assets)

            # Resolve corrupted tickers using PyMuPDF
            assets = self._resolve_corrupted_tickers(pdf_path, assets)

            # Deduplicate
            assets = self._deduplicate(assets)

            return assets

    def _resolve_corrupted_tickers(self, pdf_path: str, assets: list[dict]) -> list[dict]:
        """Decode corrupted stock tickers using PyMuPDF + Caesar cipher.

        Warren PDFs use a Type3 font with a Caesar cipher (offset +7) for
        ticker characters. pdfplumber can't extract them at all (shows just
        digits like "3", "4", "11"). PyMuPDF extracts the garbled bytes as
        ASCII characters. We decode by applying offset -7 to get real tickers.

        Example: PyMuPDF extracts "HSVZ3" → decode → "ALOS3"
        """
        try:
            import fitz
        except ImportError:
            return assets

        corrupted = [a for a in assets if self._is_corrupted_name(a["name"])]
        if not corrupted:
            return assets

        fitz_map = self._extract_fitz_tickers(pdf_path)
        if not fitz_map:
            return assets

        for asset in assets:
            if self._is_corrupted_name(asset["name"]):
                val_key = round(asset["value"], 2)
                garbled = fitz_map.get(val_key)
                if garbled:
                    asset["name"] = self._decode_ticker(garbled)

        return assets

    @staticmethod
    def _decode_ticker(garbled: str) -> str:
        """Decode a garbled ticker by reversing the Caesar cipher (offset -7).

        The Type3 font maps real letter bytes to positions +7 higher in ASCII.
        Characters in range 0x48-0x60 (H through `) are shifted letters A-Y.
        Digits and other characters pass through unchanged.
        """
        result = []
        for c in garbled:
            code = ord(c)
            if 0x48 <= code <= 0x60:  # H through ` → A through Y
                result.append(chr(code - 7))
            else:
                result.append(c)
        return "".join(result)

    @staticmethod
    def _deduplicate(assets: list[dict]) -> list[dict]:
        """Remove duplicate positions.

        Rules:
        1. If Conta Corrente and Conta Investimento have the same value,
           keep only Conta Corrente.
        2. If any asset appears multiple times with the same name AND value,
           keep only the first occurrence (position, not proventos).
        """
        # Rule 1: Conta Corrente vs Conta Investimento with same value
        cc_values = {a["value"] for a in assets if a["name"] == "Conta Corrente"}
        if cc_values:
            assets = [
                a for a in assets
                if not (a["name"] == "Conta Investimento" and a["value"] in cc_values)
            ]

        # Rule 2: General dedup by (name, value) - keep first occurrence
        seen = set()
        deduped = []
        for a in assets:
            key = (a["name"], round(a["value"], 2))
            if key not in seen:
                seen.add(key)
                deduped.append(a)

        return deduped

    @staticmethod
    def _is_corrupted_name(name: str) -> bool:
        """Check if a name is a corrupted ticker (just digits or very short)."""
        cleaned = name.strip()
        return cleaned.isdigit() or (len(cleaned) <= 3 and not cleaned.isalpha())

    @staticmethod
    def _extract_fitz_tickers(pdf_path: str) -> dict[float, str]:
        """Extract asset names from PyMuPDF keyed by their saldo bruto value."""
        import fitz

        doc = fitz.open(pdf_path)
        result = {}

        for page_idx in range(len(doc)):
            text = doc[page_idx].get_text()
            lines = text.split("\n")

            i = 0
            while i < len(lines):
                line = lines[i].strip()

                # Asset lines are followed by "Início:" on the next line
                if (i + 1 < len(lines)
                        and "Início:" in lines[i + 1]
                        and line
                        and any(c.isalpha() for c in line)
                        and len(line) <= 80):

                    # Collect numeric values after the Início line
                    nums = []
                    for j in range(i + 2, min(i + 12, len(lines))):
                        val_line = lines[j].strip()
                        m = re.match(
                            r"^-?[\d]{1,3}(?:\.[\d]{3})*,[\d]{2}$", val_line
                        )
                        if m:
                            f_val = float(
                                val_line.replace(".", "").replace(",", ".")
                            )
                            nums.append(f_val)
                            if len(nums) >= 2:
                                break

                    # The saldo bruto is the 2nd number (1st is quantity)
                    # For some assets, only 1 number appears
                    if len(nums) >= 2:
                        saldo = nums[1]
                    elif nums:
                        saldo = nums[0]
                    else:
                        i += 1
                        continue

                    result[round(saldo, 2)] = line

                i += 1

        doc.close()
        return result

    def _extract_account_lines(self, text: str) -> list[dict]:
        """Extract Conta Corrente, Conta Investimento, Saldo em Carteiras lines."""
        assets = []
        lines = text.split("\n")
        for line in lines:
            stripped = line.strip()
            for account_name in ["Conta Corrente", "Conta Investimento",
                                 "Saldo em Carteiras em trânsito",
                                 "Saldo em Carteiras em tr\u00e2nsito",
                                 "Saldo em Carteiras"]:
                if stripped.startswith(account_name):
                    numbers = BR_NUMBER_PATTERN.findall(stripped)
                    if numbers:
                        value = self.parse_brazilian_number(numbers[-1])
                        if value is not None:
                            assets.append({
                                "name": account_name.replace("\u00e2", "â"),
                                "value": value,
                                "source": "warren",
                            })
                    break
        return assets
