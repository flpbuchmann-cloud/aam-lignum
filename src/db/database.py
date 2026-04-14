"""SQLite database for client and position persistence."""

import sqlite3
from datetime import datetime
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from config.settings import DATA_DIR

DB_PATH = DATA_DIR / "clients.db"


class Database:
    """SQLite database for clients, uploads, and positions."""

    def __init__(self, db_path: str | Path | None = None):
        self._path = str(db_path or DB_PATH)
        self._conn: sqlite3.Connection | None = None
        self._ensure_tables()

    @property
    def conn(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(self._path, check_same_thread=False, timeout=30)
            self._conn.row_factory = sqlite3.Row
            self._conn.execute("PRAGMA foreign_keys = ON")
        return self._conn

    def _ensure_tables(self):
        c = self.conn
        c.executescript("""
            CREATE TABLE IF NOT EXISTS clients (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS uploads (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                client_id INTEGER NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
                filename TEXT NOT NULL,
                broker TEXT NOT NULL,
                reference_date TEXT,
                uploaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS positions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                client_id INTEGER NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
                upload_id INTEGER NOT NULL REFERENCES uploads(id) ON DELETE CASCADE,
                pdf_name TEXT NOT NULL,
                value REAL NOT NULL,
                source TEXT NOT NULL,
                status TEXT DEFAULT 'unmatched',
                registry_nome TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        c.commit()

    # --- Clients ---

    def create_client(self, name: str) -> int:
        cur = self.conn.execute(
            "INSERT INTO clients (name) VALUES (?)", (name.strip(),)
        )
        self.conn.commit()
        return cur.lastrowid

    def list_clients(self) -> list[dict]:
        rows = self.conn.execute(
            "SELECT id, name, created_at FROM clients ORDER BY name"
        ).fetchall()
        return [dict(r) for r in rows]

    def get_client(self, client_id: int) -> dict | None:
        row = self.conn.execute(
            "SELECT id, name, created_at FROM clients WHERE id = ?", (client_id,)
        ).fetchone()
        return dict(row) if row else None

    def delete_client(self, client_id: int):
        self.conn.execute("DELETE FROM clients WHERE id = ?", (client_id,))
        self.conn.commit()

    # --- Uploads ---

    def create_upload(self, client_id: int, filename: str, broker: str,
                      reference_date: str = "") -> int:
        cur = self.conn.execute(
            "INSERT INTO uploads (client_id, filename, broker, reference_date) VALUES (?, ?, ?, ?)",
            (client_id, filename, broker, reference_date),
        )
        self.conn.commit()
        return cur.lastrowid

    def list_uploads(self, client_id: int) -> list[dict]:
        rows = self.conn.execute(
            """SELECT u.id, u.filename, u.broker, u.reference_date, u.uploaded_at,
                      COUNT(p.id) as position_count
               FROM uploads u
               LEFT JOIN positions p ON p.upload_id = u.id
               WHERE u.client_id = ?
               GROUP BY u.id
               ORDER BY u.uploaded_at DESC""",
            (client_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def delete_upload(self, upload_id: int):
        self.conn.execute("DELETE FROM uploads WHERE id = ?", (upload_id,))
        self.conn.commit()

    # --- Positions ---

    def save_positions(self, client_id: int, upload_id: int,
                       positions: list[dict]):
        """Batch insert positions from a parsed PDF.

        Each dict should have: pdf_name, value, source, status, registry_nome
        """
        rows = [
            (client_id, upload_id, p["pdf_name"], p["value"], p["source"],
             p.get("status", "unmatched"), p.get("registry_nome"))
            for p in positions
        ]
        self.conn.executemany(
            """INSERT INTO positions
               (client_id, upload_id, pdf_name, value, source, status, registry_nome)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            rows,
        )
        self.conn.commit()

    def get_positions(self, client_id: int) -> list[dict]:
        """Get all positions for a client across all uploads."""
        rows = self.conn.execute(
            """SELECT p.id, p.pdf_name, p.value, p.source, p.status, p.registry_nome,
                      u.filename, u.broker, u.reference_date
               FROM positions p
               JOIN uploads u ON u.id = p.upload_id
               WHERE p.client_id = ?
               ORDER BY p.value DESC""",
            (client_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def update_position_match(self, position_id: int, status: str,
                              registry_nome: str | None):
        self.conn.execute(
            "UPDATE positions SET status = ?, registry_nome = ? WHERE id = ?",
            (status, registry_nome, position_id),
        )
        self.conn.commit()

    def delete_position(self, position_id: int):
        """Delete a single position by ID."""
        self.conn.execute("DELETE FROM positions WHERE id = ?", (position_id,))
        self.conn.commit()

    def get_or_create_manual_upload(self, client_id: int) -> int:
        """Get (or create if missing) the 'manual' upload used for manually
        added positions for this client."""
        row = self.conn.execute(
            "SELECT id FROM uploads WHERE client_id = ? AND broker = ? LIMIT 1",
            (client_id, "Manual"),
        ).fetchone()
        if row:
            return row["id"]
        return self.create_upload(client_id, "Entradas manuais", "Manual", "")

    def add_manual_position(self, client_id: int, pdf_name: str, value: float,
                             registry_nome: str | None) -> int:
        """Add a manually-entered position for a client."""
        upload_id = self.get_or_create_manual_upload(client_id)
        self.conn.execute(
            """INSERT INTO positions
               (client_id, upload_id, pdf_name, value, source, status, registry_nome)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (client_id, upload_id, pdf_name, value, "manual",
             "manual" if registry_nome else "unmatched", registry_nome),
        )
        self.conn.commit()
        return self.conn.execute("SELECT last_insert_rowid() AS id").fetchone()["id"]

    def get_position_count(self, client_id: int) -> int:
        row = self.conn.execute(
            "SELECT COUNT(*) as cnt FROM positions WHERE client_id = ?",
            (client_id,),
        ).fetchone()
        return row["cnt"] if row else 0
