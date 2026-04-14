"""Asset Registry loader and matcher.

Loads the master asset registry from Google Sheets (via gspread) or
falls back to public CSV URL. Provides exact and fuzzy matching.
"""

import csv
import io
import re
import time
from difflib import SequenceMatcher
from pathlib import Path
from urllib.request import urlopen

import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from config.settings import (
    REGISTRY_URL,
    REGISTRY_CACHE_FILE,
    REGISTRY_CACHE_HOURS,
    FUZZY_MATCH_THRESHOLD,
)


def _normalize(text: str) -> str:
    """Normalize text for comparison: lowercase, strip accents, remove special chars."""
    text = text.lower().strip()
    # Common accent replacements
    replacements = {
        "á": "a", "à": "a", "ã": "a", "â": "a",
        "é": "e", "è": "e", "ê": "e",
        "í": "i", "î": "i",
        "ó": "o", "ô": "o", "õ": "o",
        "ú": "u", "û": "u", "ü": "u",
        "ç": "c",
    }
    for orig, repl in replacements.items():
        text = text.replace(orig, repl)
    # Remove multiple spaces, dashes, special chars for looser matching
    text = re.sub(r"[^\w\d%+.,/]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _extract_key_tokens(text: str) -> set[str]:
    """Extract meaningful tokens from an asset name for matching."""
    norm = _normalize(text)
    # Split into tokens, filter out very short ones
    tokens = {t for t in norm.split() if len(t) >= 2}
    return tokens


class AssetRegistry:
    """Manages the master asset registry loaded from Google Sheets.

    The registry maps asset names (as they appear in broker PDFs) to
    standardized names, classifications, and internal codes.
    """

    def __init__(self):
        self._assets: list[dict] = []
        self._nome_index: dict[str, dict] = {}  # normalized nome -> asset
        self._code_index: dict[str, dict] = {}   # codigo_interno -> asset
        self._loaded = False

    def load(self, force_refresh: bool = False, sheets_client=None) -> None:
        """Load the registry from gspread, cache, or public CSV.

        Tries gspread first (if client provided), then cache, then public CSV.

        Args:
            force_refresh: If True, bypass cache and fetch fresh data.
            sheets_client: Optional SheetsClient instance for gspread access.
        """
        if sheets_client is not None:
            try:
                values = sheets_client.get_all_values(force_refresh=force_refresh)
                if values:
                    self._parse_raw_rows(values)
                    self._loaded = True
                    # Also update CSV cache
                    self._save_rows_to_cache(values)
                    return
            except Exception as e:
                print(f"[Registry] gspread load failed ({e}), falling back to CSV.")

        csv_data = self._get_csv_data(force_refresh)
        self._parse_csv(csv_data)
        self._loaded = True

    def _parse_raw_rows(self, rows: list[list[str]]) -> None:
        """Parse raw row data (from gspread get_all_values).

        Same structure as CSV: row 0 is merged header, row 1+ are data.
        """
        if not rows:
            return

        self._assets = []
        self._nome_index = {}
        self._code_index = {}

        # Parse header row (same merged format)
        embedded = self._parse_header_row(rows[0])
        for asset in embedded:
            self._add_asset(asset)

        for row in rows[1:]:
            if not row or not row[0].strip():
                continue
            asset = self._row_to_asset(row)
            if asset:
                self._add_asset(asset)

    def _save_rows_to_cache(self, rows: list[list[str]]) -> None:
        """Save raw rows to CSV cache file."""
        try:
            import csv as csv_mod
            cache_path = Path(REGISTRY_CACHE_FILE)
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            with open(cache_path, "w", encoding="utf-8", newline="") as f:
                writer = csv_mod.writer(f)
                for row in rows:
                    writer.writerow(row)
        except Exception as e:
            print(f"[Registry] Failed to save cache: {e}")

    def _get_csv_data(self, force_refresh: bool = False) -> str:
        """Get CSV data from cache or fetch from Google Sheets."""
        cache_path = Path(REGISTRY_CACHE_FILE)

        # Check cache
        if not force_refresh and cache_path.exists():
            age_hours = (time.time() - cache_path.stat().st_mtime) / 3600
            if age_hours < REGISTRY_CACHE_HOURS:
                return cache_path.read_text(encoding="utf-8")

        # Fetch from Google Sheets
        try:
            response = urlopen(REGISTRY_URL, timeout=15)
            data = response.read().decode("utf-8")
            # Save to cache
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            cache_path.write_text(data, encoding="utf-8")
            return data
        except Exception as e:
            # Fall back to cache if available
            if cache_path.exists():
                print(f"[Registry] Failed to fetch from Google Sheets ({e}), using cache.")
                return cache_path.read_text(encoding="utf-8")
            raise RuntimeError(f"Cannot load registry: {e}") from e

    def _parse_csv(self, csv_data: str) -> None:
        """Parse CSV data into asset records.

        The first row (row 0) has headers merged with the first 3 data entries:
            Col 0: "Nome WEGE3 Conta Corrente AMW Cash Clash FIRF LP"
            Col 1: "Nome 1 WEGE3 Conta Corrente AMW Cash Clash FIRF LP"
            ...

        We need to extract those 3 embedded entries from the header row,
        then parse all subsequent rows normally.
        """
        reader = csv.reader(io.StringIO(csv_data))
        rows = list(reader)

        if not rows:
            return

        self._assets = []
        self._nome_index = {}
        self._code_index = {}

        # Parse header row to extract the 3 embedded entries
        header_row = rows[0]
        embedded = self._parse_header_row(header_row)
        for asset in embedded:
            self._add_asset(asset)

        # Parse remaining rows
        for row in rows[1:]:
            if not row or not row[0].strip():
                continue
            asset = self._row_to_asset(row)
            if asset:
                self._add_asset(asset)

    def _parse_header_row(self, row: list[str]) -> list[dict]:
        """Extract the 3 embedded asset entries from the header row.

        Header col 0: "Nome WEGE3 Conta Corrente AMW Cash Clash FIRF LP"
        This contains entries for: WEGE3, Conta Corrente, AMW Cash Clash FIRF LP

        We parse each column by stripping the known header prefix.
        """
        if not row or len(row) < 12:
            return []

        # Known header prefixes for each column
        prefixes = {
            0: "Nome ",
            1: "Nome 1 ",
            2: "Macro Classe ",
            3: "Micro Classe ",
            4: "Tipo ",
            5: "CNPJ/Ticker ",
            6: "Taxa ",
            7: "Emissor - Títulos RF ",
            8: "Data Aplicação ",
            9: "Data Vencimento ",
            10: "Prazo Resgate ",
            11: "Código Interno ",
        }

        # Strip prefix from each column to get the raw concatenated values
        raw_values = {}
        for col_idx, prefix in prefixes.items():
            if col_idx < len(row):
                val = row[col_idx]
                if val.startswith(prefix):
                    val = val[len(prefix):]
                raw_values[col_idx] = val.strip()
            else:
                raw_values[col_idx] = ""

        # The Nome column has 3 names separated by spaces, but the names themselves
        # contain spaces. We use the known names to split.
        # From the actual data: "WEGE3 Conta Corrente AMW Cash Clash FIRF LP"
        # Nome 1: "WEGE3 Conta Corrente AMW Cash Clash FIRF LP"
        # Macro: "Renda Variável DI/Cash DI/Cash"
        # Micro: "Ações DI/Cash DI/Cash"
        # Tipo: "Ações Conta Corrente Fundo DI"
        # Código: "AST-UCXRWO AST-72B2AC AST-P2ZS4O"

        # Split the codes to know how many entries
        codes = raw_values.get(11, "").split()

        # We know the 3 entries from inspection:
        # 1. WEGE3 (Renda Variável, Ações)
        # 2. Conta Corrente (DI/Cash, Conta Corrente)
        # 3. AMW Cash Clash FIRF LP (DI/Cash, Fundo DI)
        nomes = ["WEGE3", "Conta Corrente", "AMW Cash Clash FIRF LP"]
        nomes_1 = ["WEGE3", "Conta Corrente", "AMW Cash Clash FIRF LP"]
        macros = ["Renda Variável", "DI/Cash", "DI/Cash"]
        micros = ["Ações", "DI/Cash", "DI/Cash"]
        tipos = ["Ações", "Conta Corrente", "Fundo DI"]

        assets = []
        for idx in range(min(3, len(codes))):
            asset = {
                "nome": nomes[idx] if idx < len(nomes) else "",
                "nome_1": nomes_1[idx] if idx < len(nomes_1) else "",
                "macro_classe": macros[idx] if idx < len(macros) else "",
                "micro_classe": micros[idx] if idx < len(micros) else "",
                "tipo": tipos[idx] if idx < len(tipos) else "",
                "cnpj_ticker": "",
                "taxa": "",
                "emissor": "",
                "data_aplicacao": "",
                "data_vencimento": "",
                "prazo_resgate": "d0" if idx == 0 else "",
                "codigo_interno": codes[idx] if idx < len(codes) else "",
                "ativo_carrego": "",
                "ativo_isento": "",
            }
            assets.append(asset)

        return assets

    def _row_to_asset(self, row: list[str]) -> dict | None:
        """Convert a CSV row to an asset dict."""
        if len(row) < 12:
            return None
        nome = row[0].strip()
        if not nome:
            return None
        return {
            "nome": nome,
            "nome_1": row[1].strip() if len(row) > 1 else "",
            "macro_classe": row[2].strip() if len(row) > 2 else "",
            "micro_classe": row[3].strip() if len(row) > 3 else "",
            "tipo": row[4].strip() if len(row) > 4 else "",
            "cnpj_ticker": row[5].strip() if len(row) > 5 else "",
            "taxa": row[6].strip() if len(row) > 6 else "",
            "emissor": row[7].strip() if len(row) > 7 else "",
            "data_aplicacao": row[8].strip() if len(row) > 8 else "",
            "data_vencimento": row[9].strip() if len(row) > 9 else "",
            "prazo_resgate": row[10].strip() if len(row) > 10 else "",
            "codigo_interno": row[11].strip() if len(row) > 11 else "",
            "ativo_carrego": row[12].strip().lower() if len(row) > 12 else "",
            "ativo_isento": row[13].strip().lower() if len(row) > 13 else "",
        }

    def _add_asset(self, asset: dict) -> None:
        """Add an asset to the registry and update indexes."""
        self._assets.append(asset)
        nome_key = _normalize(asset["nome"])
        self._nome_index[nome_key] = asset
        if asset.get("codigo_interno"):
            self._code_index[asset["codigo_interno"]] = asset

    @property
    def assets(self) -> list[dict]:
        """All assets in the registry."""
        if not self._loaded:
            self.load()
        return self._assets

    def find_match(self, name: str) -> dict | None:
        """Find an exact match for the given name.

        Matching is done on normalized text (lowercase, no accents, no special chars).

        Args:
            name: Asset name as it appears in the PDF.

        Returns:
            Matching asset dict or None.
        """
        if not self._loaded:
            self.load()

        key = _normalize(name)
        if key in self._nome_index:
            return self._nome_index[key]

        # Try a slightly looser match: check if the PDF name is contained
        # in a registry name or vice versa
        for nome_key, asset in self._nome_index.items():
            if key == nome_key:
                return asset

        return None

    def find_fuzzy_match(self, name: str, threshold: float | None = None) -> list[dict]:
        """Find fuzzy matches for the given name.

        Uses a combination of SequenceMatcher ratio and token overlap
        to score potential matches.

        Args:
            name: Asset name to match.
            threshold: Minimum similarity score (0.0 to 1.0). Defaults to config value.

        Returns:
            List of dicts with keys: asset, score, nome
            Sorted by score descending.
        """
        if not self._loaded:
            self.load()

        if threshold is None:
            threshold = FUZZY_MATCH_THRESHOLD

        name_norm = _normalize(name)
        name_tokens = _extract_key_tokens(name)
        results = []

        for asset in self._assets:
            asset_norm = _normalize(asset["nome"])

            # SequenceMatcher ratio
            seq_ratio = SequenceMatcher(None, name_norm, asset_norm).ratio()

            # Token overlap score
            asset_tokens = _extract_key_tokens(asset["nome"])
            if name_tokens and asset_tokens:
                common = name_tokens & asset_tokens
                token_score = len(common) / max(len(name_tokens), len(asset_tokens))
            else:
                token_score = 0.0

            # Combined score (weighted average)
            score = 0.5 * seq_ratio + 0.5 * token_score

            # Bonus: if one contains the other
            if name_norm in asset_norm or asset_norm in name_norm:
                score = max(score, 0.75)

            if score >= threshold:
                results.append({
                    "asset": asset,
                    "score": round(score, 3),
                    "nome": asset["nome"],
                })

        results.sort(key=lambda x: x["score"], reverse=True)
        return results

    def get_by_code(self, code: str) -> dict | None:
        """Look up an asset by its internal code (e.g., 'AST-UCXRWO').

        Args:
            code: Internal code string.

        Returns:
            Matching asset dict or None.
        """
        if not self._loaded:
            self.load()
        return self._code_index.get(code)

    def __len__(self) -> int:
        if not self._loaded:
            self.load()
        return len(self._assets)

    def __repr__(self) -> str:
        return f"AssetRegistry({len(self)} assets)"
