"""Google Sheets-backed storage for app data (clients, uploads, positions).

Same API as Database (SQLite) but backed by Google Sheets tabs.
Used for persistence when deployed to Streamlit Cloud where filesystem is ephemeral.

Tabs used in the Base de Dados spreadsheet:
    app_clients:   id | name | created_at
    app_uploads:   id | client_id | filename | broker | reference_date | uploaded_at
    app_positions: id | client_id | upload_id | pdf_name | value | source | status | registry_nome | created_at
"""

import time
from datetime import datetime
from pathlib import Path

import gspread

import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from config.settings import (
    GSHEETS_SPREADSHEET_ID,
    GSHEETS_CLIENTS_WORKSHEET,
    GSHEETS_UPLOADS_WORKSHEET,
    GSHEETS_POSITIONS_WORKSHEET,
)


CLIENTS_HEADERS = ["id", "name", "created_at"]
UPLOADS_HEADERS = ["id", "client_id", "filename", "broker", "reference_date", "uploaded_at"]
POSITIONS_HEADERS = [
    "id", "client_id", "upload_id", "pdf_name", "value", "source",
    "status", "registry_nome", "created_at",
]


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


class SheetsStorage:
    """Persistence backend using Google Sheets tabs."""

    def __init__(self, sheets_client):
        self._sheets_client = sheets_client
        self._cache_clients = None
        self._cache_uploads = None
        self._cache_positions = None
        self._worksheets = {}

    # --- Helpers ---

    def _get_ws(self, name: str, headers: list[str]) -> gspread.Worksheet:
        """Get or create a worksheet by name."""
        if name in self._worksheets:
            return self._worksheets[name]

        if not self._sheets_client._authenticate():
            raise RuntimeError("Google Sheets nao autenticado. Configure credentials.")

        spreadsheet = self._sheets_client._gc.open_by_key(GSHEETS_SPREADSHEET_ID)

        try:
            ws = spreadsheet.worksheet(name)
        except gspread.WorksheetNotFound:
            ws = spreadsheet.add_worksheet(title=name, rows=1000, cols=len(headers))
            ws.update("A1", [headers])

        # Ensure header row exists
        first_row = ws.row_values(1)
        if not first_row or first_row != headers:
            ws.update("A1", [headers])

        self._worksheets[name] = ws
        return ws

    def _read_all(self, ws_name: str, headers: list[str]) -> list[dict]:
        """Read all rows from a worksheet as list of dicts."""
        ws = self._get_ws(ws_name, headers)
        values = ws.get_all_values()
        if len(values) <= 1:
            return []

        rows = []
        for row in values[1:]:
            if not row or not row[0].strip():
                continue
            d = {}
            for i, h in enumerate(headers):
                val = row[i] if i < len(row) else ""
                d[h] = val
            rows.append(d)
        return rows

    def _next_id(self, rows: list[dict]) -> int:
        """Get the next available integer ID."""
        if not rows:
            return 1
        ids = []
        for r in rows:
            try:
                ids.append(int(r["id"]))
            except (ValueError, KeyError):
                pass
        return max(ids) + 1 if ids else 1

    def _invalidate_cache(self):
        self._cache_clients = None
        self._cache_uploads = None
        self._cache_positions = None

    # --- Clients ---

    def list_clients(self) -> list[dict]:
        if self._cache_clients is None:
            raw = self._read_all(GSHEETS_CLIENTS_WORKSHEET, CLIENTS_HEADERS)
            self._cache_clients = [
                {"id": int(r["id"]), "name": r["name"], "created_at": r["created_at"]}
                for r in raw
            ]
            self._cache_clients.sort(key=lambda c: c["name"].lower())
        return list(self._cache_clients)

    def create_client(self, name: str) -> int:
        clients = self.list_clients()
        if any(c["name"].lower() == name.strip().lower() for c in clients):
            raise ValueError(f"Cliente '{name}' ja existe")

        new_id = self._next_id([{"id": c["id"]} for c in clients])
        ws = self._get_ws(GSHEETS_CLIENTS_WORKSHEET, CLIENTS_HEADERS)
        ws.append_row([new_id, name.strip(), _now()], value_input_option="USER_ENTERED")
        self._cache_clients = None
        return new_id

    def get_client(self, client_id: int) -> dict | None:
        for c in self.list_clients():
            if c["id"] == client_id:
                return c
        return None

    def delete_client(self, client_id: int):
        # Delete uploads and positions first
        for u in self.list_uploads(client_id):
            self.delete_upload(u["id"])

        ws = self._get_ws(GSHEETS_CLIENTS_WORKSHEET, CLIENTS_HEADERS)
        self._delete_row_by_id(ws, client_id)
        self._cache_clients = None

    # --- Uploads ---

    def _list_all_uploads(self) -> list[dict]:
        if self._cache_uploads is None:
            raw = self._read_all(GSHEETS_UPLOADS_WORKSHEET, UPLOADS_HEADERS)
            self._cache_uploads = [
                {
                    "id": int(r["id"]),
                    "client_id": int(r["client_id"]),
                    "filename": r["filename"],
                    "broker": r["broker"],
                    "reference_date": r["reference_date"],
                    "uploaded_at": r["uploaded_at"],
                }
                for r in raw
            ]
        return list(self._cache_uploads)

    def list_uploads(self, client_id: int) -> list[dict]:
        all_uploads = self._list_all_uploads()
        all_positions = self._list_all_positions()
        position_count_by_upload = {}
        for p in all_positions:
            uid = p["upload_id"]
            position_count_by_upload[uid] = position_count_by_upload.get(uid, 0) + 1

        result = []
        for u in all_uploads:
            if u["client_id"] == client_id:
                d = dict(u)
                d["position_count"] = position_count_by_upload.get(u["id"], 0)
                result.append(d)
        result.sort(key=lambda u: u["uploaded_at"], reverse=True)
        return result

    def create_upload(self, client_id: int, filename: str, broker: str,
                      reference_date: str = "") -> int:
        all_uploads = self._list_all_uploads()
        new_id = self._next_id([{"id": u["id"]} for u in all_uploads])
        ws = self._get_ws(GSHEETS_UPLOADS_WORKSHEET, UPLOADS_HEADERS)
        ws.append_row(
            [new_id, client_id, filename, broker, reference_date, _now()],
            value_input_option="USER_ENTERED",
        )
        self._cache_uploads = None
        return new_id

    def delete_upload(self, upload_id: int):
        # Delete associated positions first
        for p in self._list_all_positions():
            if p["upload_id"] == upload_id:
                self._delete_position_row(p["id"])

        ws = self._get_ws(GSHEETS_UPLOADS_WORKSHEET, UPLOADS_HEADERS)
        self._delete_row_by_id(ws, upload_id)
        self._cache_uploads = None
        self._cache_positions = None

    def get_or_create_manual_upload(self, client_id: int) -> int:
        for u in self.list_uploads(client_id):
            if u["broker"] == "Manual":
                return u["id"]
        return self.create_upload(client_id, "Entradas manuais", "Manual", "")

    # --- Positions ---

    def _list_all_positions(self) -> list[dict]:
        if self._cache_positions is None:
            raw = self._read_all(GSHEETS_POSITIONS_WORKSHEET, POSITIONS_HEADERS)
            self._cache_positions = [
                {
                    "id": int(r["id"]),
                    "client_id": int(r["client_id"]),
                    "upload_id": int(r["upload_id"]),
                    "pdf_name": r["pdf_name"],
                    "value": float(r["value"].replace(",", ".")) if r["value"] else 0.0,
                    "source": r["source"],
                    "status": r["status"],
                    "registry_nome": r["registry_nome"] or None,
                    "created_at": r["created_at"],
                }
                for r in raw
            ]
        return list(self._cache_positions)

    def get_positions(self, client_id: int) -> list[dict]:
        all_pos = self._list_all_positions()
        all_uploads_map = {u["id"]: u for u in self._list_all_uploads()}

        result = []
        for p in all_pos:
            if p["client_id"] != client_id:
                continue
            upload = all_uploads_map.get(p["upload_id"], {})
            d = dict(p)
            d["filename"] = upload.get("filename", "")
            d["broker"] = upload.get("broker", "")
            d["reference_date"] = upload.get("reference_date", "")
            result.append(d)
        result.sort(key=lambda p: p["value"], reverse=True)
        return result

    def save_positions(self, client_id: int, upload_id: int, positions: list[dict]):
        all_pos = self._list_all_positions()
        next_id = self._next_id([{"id": p["id"]} for p in all_pos])

        ws = self._get_ws(GSHEETS_POSITIONS_WORKSHEET, POSITIONS_HEADERS)
        rows = []
        for p in positions:
            rows.append([
                next_id, client_id, upload_id,
                p["pdf_name"], p["value"], p["source"],
                p.get("status", "unmatched"),
                p.get("registry_nome", "") or "",
                _now(),
            ])
            next_id += 1

        if rows:
            ws.append_rows(rows, value_input_option="USER_ENTERED")
        self._cache_positions = None

    def update_position_match(self, position_id: int, status: str,
                              registry_nome: str | None):
        ws = self._get_ws(GSHEETS_POSITIONS_WORKSHEET, POSITIONS_HEADERS)
        row_idx = self._find_row_by_id(ws, position_id)
        if row_idx is None:
            return

        # status is column G (index 7), registry_nome is column H (index 8)
        ws.update(f"G{row_idx}:H{row_idx}", [[status, registry_nome or ""]])
        self._cache_positions = None

    def delete_position(self, position_id: int):
        self._delete_position_row(position_id)
        self._cache_positions = None

    def _delete_position_row(self, position_id: int):
        ws = self._get_ws(GSHEETS_POSITIONS_WORKSHEET, POSITIONS_HEADERS)
        self._delete_row_by_id(ws, position_id)

    def add_manual_position(self, client_id: int, pdf_name: str, value: float,
                             registry_nome: str | None) -> int:
        upload_id = self.get_or_create_manual_upload(client_id)
        all_pos = self._list_all_positions()
        new_id = self._next_id([{"id": p["id"]} for p in all_pos])

        ws = self._get_ws(GSHEETS_POSITIONS_WORKSHEET, POSITIONS_HEADERS)
        ws.append_row(
            [new_id, client_id, upload_id, pdf_name, value, "manual",
             "manual" if registry_nome else "unmatched",
             registry_nome or "", _now()],
            value_input_option="USER_ENTERED",
        )
        self._cache_positions = None
        return new_id

    def get_position_count(self, client_id: int) -> int:
        return len([p for p in self._list_all_positions() if p["client_id"] == client_id])

    # --- Helpers for row deletion ---

    def _find_row_by_id(self, ws: gspread.Worksheet, target_id: int) -> int | None:
        """Find the 1-based row number for a given id (column A)."""
        col_a = ws.col_values(1)
        for i, val in enumerate(col_a[1:], start=2):  # Skip header
            try:
                if int(val) == target_id:
                    return i
            except ValueError:
                continue
        return None

    def _delete_row_by_id(self, ws: gspread.Worksheet, target_id: int):
        row_idx = self._find_row_by_id(ws, target_id)
        if row_idx:
            ws.delete_rows(row_idx)
