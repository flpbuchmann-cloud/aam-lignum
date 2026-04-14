"""Google Sheets client for reading and writing to Base de Dados.

Provides authenticated access via gspread service account.
Falls back to public CSV URL if credentials are not available.
"""

import time
from pathlib import Path

import gspread
from google.oauth2.service_account import Credentials

import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from config.settings import (
    GSHEETS_SPREADSHEET_ID,
    GSHEETS_WORKSHEET_NAME,
    GSHEETS_INDICADORES_WORKSHEET,
    GSHEETS_CREDENTIALS_PATH,
    GSHEETS_SCOPES,
)


class SheetsClient:
    """Wrapper around gspread for Google Sheets operations."""

    def __init__(self):
        self._gc: gspread.Client | None = None
        self._worksheet: gspread.Worksheet | None = None
        self._cache: list[list[str]] | None = None
        self._cache_time: float = 0
        self._cache_ttl: float = 300  # 5 minutes
        self._authenticated = False

    def _authenticate(self) -> bool:
        """Authenticate with Google Sheets via service account.

        Tries (in order):
        1. Streamlit secrets (for Streamlit Cloud deployment)
        2. Local credentials.json file
        """
        if self._gc is not None:
            return True

        # Try Streamlit secrets first (for cloud deployment)
        try:
            import streamlit as st
            if hasattr(st, "secrets") and "gcp_service_account" in st.secrets:
                creds_dict = dict(st.secrets["gcp_service_account"])
                creds = Credentials.from_service_account_info(
                    creds_dict, scopes=GSHEETS_SCOPES
                )
                self._gc = gspread.authorize(creds)
                self._authenticated = True
                return True
        except ImportError:
            pass
        except Exception as e:
            # Log the real error so we can debug (visible in Streamlit Cloud logs)
            print(f"[SheetsClient] Streamlit secrets auth failed: {type(e).__name__}: {e}")

        # Fall back to local credentials.json
        creds_path = Path(GSHEETS_CREDENTIALS_PATH)
        if not creds_path.exists():
            return False

        try:
            creds = Credentials.from_service_account_file(
                str(creds_path), scopes=GSHEETS_SCOPES
            )
            self._gc = gspread.authorize(creds)
            self._authenticated = True
            return True
        except Exception as e:
            print(f"[SheetsClient] Authentication failed: {e}")
            return False

    @property
    def is_authenticated(self) -> bool:
        return self._authenticated

    def get_worksheet(self) -> gspread.Worksheet | None:
        """Get the Base de Dados worksheet."""
        if self._worksheet is not None:
            return self._worksheet

        if not self._authenticate():
            return None

        try:
            spreadsheet = self._gc.open_by_key(GSHEETS_SPREADSHEET_ID)
            self._worksheet = spreadsheet.worksheet(GSHEETS_WORKSHEET_NAME)
            return self._worksheet
        except Exception as e:
            print(f"[SheetsClient] Failed to open worksheet: {e}")
            return None

    def get_all_values(self, force_refresh: bool = False) -> list[list[str]]:
        """Get all cell values from the worksheet.

        Returns cached values if available and fresh.
        """
        now = time.time()
        if not force_refresh and self._cache and (now - self._cache_time) < self._cache_ttl:
            return self._cache

        ws = self.get_worksheet()
        if ws is None:
            return self._cache or []

        try:
            self._cache = ws.get_all_values()
            self._cache_time = now
            return self._cache
        except Exception as e:
            print(f"[SheetsClient] Failed to get values: {e}")
            return self._cache or []

    def get_existing_names(self) -> set[str]:
        """Get all existing asset names from column A (Nome)."""
        values = self.get_all_values(force_refresh=True)
        names = set()
        for row in values:
            if row and row[0].strip():
                names.add(row[0].strip())
        return names

    def get_indicadores(self) -> dict:
        """Read CDI and IPCA from the Indicadores tab.

        Returns dict with keys: cdi (float), ipca (float)
        """
        if not self._authenticate():
            return {"cdi": 0.0, "ipca": 0.0}

        try:
            spreadsheet = self._gc.open_by_key(GSHEETS_SPREADSHEET_ID)
            ws = spreadsheet.worksheet(GSHEETS_INDICADORES_WORKSHEET)
            cdi_raw = ws.acell("B1").value or "0"
            ipca_raw = ws.acell("B2").value or "0"

            # Parse Brazilian number format (e.g., "14,90%" or "14,90")
            def parse_pct(val: str) -> float:
                val = val.strip().replace("%", "").replace(",", ".")
                try:
                    return float(val)
                except ValueError:
                    return 0.0

            return {"cdi": parse_pct(cdi_raw), "ipca": parse_pct(ipca_raw)}
        except Exception as e:
            print(f"[SheetsClient] Failed to read indicadores: {e}")
            return {"cdi": 0.0, "ipca": 0.0}

    def push_unmatched_names(self, names: list[str]) -> int:
        """Push new asset names to column A of the worksheet.

        Only writes names that don't already exist. Writes only to
        column A (Nome) - all other columns are left blank for
        manual classification by the user.

        Returns count of names actually written.
        """
        ws = self.get_worksheet()
        if ws is None:
            raise RuntimeError(
                "Nao foi possivel conectar ao Google Sheets. "
                "Verifique se credentials.json existe em config/"
            )

        existing = self.get_existing_names()
        new_names = [n for n in names if n.strip() and n.strip() not in existing]

        if not new_names:
            return 0

        # Find first empty row in column A
        col_a = ws.col_values(1)
        next_row = len(col_a) + 1

        # Build rows to append (only column A filled)
        rows = [[name] for name in new_names]
        ws.update(f"A{next_row}", rows)

        # Invalidate cache
        self._cache = None
        return len(new_names)
