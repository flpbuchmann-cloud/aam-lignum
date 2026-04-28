"""Persistência de targets % do PL com Google Sheets (primário) e
JSON local (fallback).

Por que Sheets é o primário:
- Sobrevive a deploy do Streamlit Cloud (filesystem é efêmero lá).
- Centraliza dados — qualquer ambiente (local, cloud, outro dev) lê o
  mesmo estado.

Fallback JSON em `data/consolidation_targets.json`:
- Acionado se o auth falhar (sem credentials.json e sem Streamlit secrets)
  ou se o spreadsheet ficar inacessível em runtime.

Schema da worksheet `app_consolidation_targets`:

| state_key       | classe         | pct_sugerido | updated_at          |
|-----------------|----------------|--------------|---------------------|
| cons_macro_pct  | Renda Fixa     | 60.0         | 2026-04-28T12:34:56 |
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path

import streamlit as st

from config.settings import (
    GSHEETS_CONSOLIDATION_TARGETS_WORKSHEET,
    GSHEETS_SPREADSHEET_ID,
)
from src.sheets.client import SheetsClient


_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
_TARGETS_FILE = _PROJECT_ROOT / "data" / "consolidation_targets.json"

_HEADERS = ["state_key", "classe", "pct_sugerido", "updated_at"]


# ─── JSON fallback ────────────────────────────────────────────────────

def _file_read() -> dict:
    if not _TARGETS_FILE.exists():
        return {}
    try:
        with _TARGETS_FILE.open("r", encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _file_write_full(data: dict) -> None:
    _TARGETS_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = _TARGETS_FILE.with_suffix(".json.tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2, sort_keys=True)
    os.replace(tmp, _TARGETS_FILE)


def _file_write_for_key(state_key: str, values: dict[str, float]) -> bool:
    try:
        all_data = _file_read()
        all_data[state_key] = dict(values)
        _file_write_full(all_data)
        return True
    except Exception as e:
        print(f"[targets] file write failed: {e}")
        return False


# ─── Google Sheets ────────────────────────────────────────────────────

def _get_sheets_client() -> SheetsClient:
    if "sheets_client" not in st.session_state:
        st.session_state["sheets_client"] = SheetsClient()
    return st.session_state["sheets_client"]


def _get_worksheet():
    client = _get_sheets_client()
    if not client._authenticate():
        return None
    try:
        import gspread
        spreadsheet = client._gc.open_by_key(GSHEETS_SPREADSHEET_ID)
        try:
            ws = spreadsheet.worksheet(GSHEETS_CONSOLIDATION_TARGETS_WORKSHEET)
        except gspread.exceptions.WorksheetNotFound:
            ws = spreadsheet.add_worksheet(
                title=GSHEETS_CONSOLIDATION_TARGETS_WORKSHEET,
                rows=2000,
                cols=4,
            )
            ws.update(values=[_HEADERS], range_name="A1")
        return ws
    except Exception as e:
        print(f"[targets] sheets open failed: {e}")
        return None


def _sheets_read_all() -> dict[str, dict[str, float]] | None:
    ws = _get_worksheet()
    if ws is None:
        return None
    try:
        rows = ws.get_all_values()
    except Exception as e:
        print(f"[targets] sheets read failed: {e}")
        return None
    if not rows or len(rows) < 2:
        return {}
    out: dict[str, dict[str, float]] = {}
    for row in rows[1:]:
        if len(row) < 3:
            continue
        sk = (row[0] or "").strip()
        cl = (row[1] or "").strip()
        pct_raw = (row[2] or "").strip().replace(",", ".")
        if not sk or not cl:
            continue
        try:
            pct = float(pct_raw)
        except ValueError:
            continue
        out.setdefault(sk, {})[cl] = pct
    return out


def _sheets_write_for_key(state_key: str, values: dict[str, float]) -> bool:
    ws = _get_worksheet()
    if ws is None:
        return False
    try:
        all_rows = ws.get_all_values()
        if not all_rows:
            header = _HEADERS
            others: list[list[str]] = []
        else:
            header = all_rows[0] if all_rows[0] else _HEADERS
            others = [
                r for r in all_rows[1:]
                if not (len(r) > 0 and (r[0] or "").strip() == state_key)
            ]
        now = datetime.now().isoformat(timespec="seconds")
        new_rows = [
            [state_key, classe, str(pct), now]
            for classe, pct in sorted(values.items())
        ]
        final = [header] + others + new_rows
        ws.clear()
        ws.update(values=final, range_name="A1")
        return True
    except Exception as e:
        print(f"[targets] sheets write failed: {e}")
        return False


# ─── API pública ──────────────────────────────────────────────────────

def _backend_status() -> str:
    if "_targets_backend" in st.session_state:
        return st.session_state["_targets_backend"]
    ws = _get_worksheet()
    backend = "sheets" if ws is not None else "file"
    st.session_state["_targets_backend"] = backend
    return backend


def load_targets(state_key: str) -> dict[str, float]:
    if state_key in st.session_state:
        return dict(st.session_state[state_key])

    if "_targets_loaded" not in st.session_state:
        backend = _backend_status()
        data: dict[str, dict[str, float]]
        if backend == "sheets":
            sheets_data = _sheets_read_all()
            if sheets_data is None:
                st.session_state["_targets_backend"] = "file"
                data = _file_read()
            else:
                data = sheets_data
        else:
            data = _file_read()
        for key, values in (data or {}).items():
            st.session_state[key] = dict(values)
        st.session_state["_targets_loaded"] = True

    if state_key not in st.session_state:
        st.session_state[state_key] = {}
    return dict(st.session_state[state_key])


def save_targets(state_key: str, values: dict[str, float]) -> None:
    st.session_state[state_key] = dict(values)
    backend = _backend_status()
    if backend == "sheets":
        ok = _sheets_write_for_key(state_key, values)
        if not ok:
            st.session_state["_targets_backend"] = "file"
            _file_write_for_key(state_key, values)
            st.warning(
                "⚠️ Falha ao gravar no Google Sheets — mudança salva "
                "localmente como fallback. Verifique a conexão."
            )
    else:
        _file_write_for_key(state_key, values)


def get_backend_label() -> str:
    backend = _backend_status()
    return "Google Sheets" if backend == "sheets" else "Arquivo local (JSON)"
