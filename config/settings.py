"""Configuration settings for AAM Lignum."""

import os
from pathlib import Path

# Project root
PROJECT_ROOT = Path(__file__).parent.parent

# Data directories
DATA_DIR = PROJECT_ROOT / "data"
UPLOADS_DIR = DATA_DIR / "uploads"
CLIENTS_DIR = DATA_DIR / "clients"
CACHE_DIR = DATA_DIR / "cache"

# Create directories if they don't exist
for d in [DATA_DIR, UPLOADS_DIR, CLIENTS_DIR, CACHE_DIR]:
    d.mkdir(parents=True, exist_ok=True)

# Google Sheets - gspread integration
GSHEETS_SPREADSHEET_ID = "18vbgeLkAhvRz9UUHolU81K3HsyZ8Jj62QuJzI2M9iqw"
GSHEETS_WORKSHEET_NAME = "Página1"
GSHEETS_CREDENTIALS_PATH = PROJECT_ROOT / "config" / "credentials.json"
GSHEETS_SCOPES = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/drive",
]

# Google Sheets - Public CSV fallback (read-only, no auth needed)
REGISTRY_URL = (
    "https://docs.google.com/spreadsheets/d/"
    "18vbgeLkAhvRz9UUHolU81K3HsyZ8Jj62QuJzI2M9iqw"
    "/gviz/tq?tqx=out:csv&gid=0"
)
REGISTRY_CACHE_FILE = CACHE_DIR / "asset_registry.csv"
REGISTRY_CACHE_HOURS = 24

# Registry column indices (header row is merged with first data rows)
# The CSV row 0 contains header text merged with data for WEGE3, Conta Corrente, AMW Cash Clash
# Real data starts at row 1. Row 0 must be parsed specially to extract those 3 embedded entries.
REGISTRY_COLUMNS = {
    "nome": 0,           # Name as it appears in broker PDFs
    "nome_1": 1,         # Standardized display name
    "macro_classe": 2,   # e.g., "Renda Fixa", "Renda Variavel"
    "micro_classe": 3,   # e.g., "Acoes", "Renda Fixa Prefixada"
    "tipo": 4,           # e.g., "CDB", "CRI", "Acoes"
    "cnpj_ticker": 5,
    "taxa": 6,
    "emissor": 7,
    "data_aplicacao": 8,
    "data_vencimento": 9,
    "prazo_resgate": 10,
    "codigo_interno": 11,
    "ativo_carrego": 12,  # "x" = appears in RF Carrego view
    "ativo_isento": 13,   # "x" = tax-exempt asset (LCI, LCA, CRI, CRA, deb incentivada)
}

# Google Sheets - Indicadores tab
GSHEETS_INDICADORES_WORKSHEET = "Indicadores"

# Google Sheets - App data tabs (clients, uploads, positions, targets)
GSHEETS_CLIENTS_WORKSHEET = "app_clients"
GSHEETS_UPLOADS_WORKSHEET = "app_uploads"
GSHEETS_POSITIONS_WORKSHEET = "app_positions"
GSHEETS_CONSOLIDATION_TARGETS_WORKSHEET = "app_consolidation_targets"

# Fuzzy matching
FUZZY_MATCH_THRESHOLD = 0.55

# Warren PDF parsing
WARREN_PRODUTOS_START_KEYWORDS = ["Conta Corrente", "Conta Investimento", "Renda Fixa"]
WARREN_CATEGORY_HEADERS = [
    "Pós-fixado Liquidez",
    "Pós-fixado Crédito Privado",
    "Prefixado",
    "Inflação",
    "Multimercado",
    "Ações Brasil",
    "Imobiliário",
    "Outros",
]
WARREN_SKIP_KEYWORDS = [
    "Dividendo",
    "Juros sobre capital",
    "Restituição de capital",
    "Rendimento",
    "Deliberação",
]

# Streamlit
STREAMLIT_PAGE_TITLE = "AAM Lignum"
STREAMLIT_PAGE_ICON = "📊"
