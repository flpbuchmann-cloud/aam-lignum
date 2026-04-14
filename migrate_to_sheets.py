"""Migrate existing SQLite data (clients, uploads, positions) to Google Sheets.

Run once before switching the app to use SheetsStorage.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from src.db.database import Database
from src.db.sheets_storage import SheetsStorage
from src.sheets.client import SheetsClient


def main():
    print("Migrando dados do SQLite para Google Sheets...")

    db = Database()
    sheets_client = SheetsClient()

    if not sheets_client._authenticate():
        print("ERRO: nao foi possivel autenticar no Google Sheets.")
        return

    storage = SheetsStorage(sheets_client)

    # 1. Migrate clients
    print("\n=== CLIENTES ===")
    existing_clients = storage.list_clients()
    existing_names = {c["name"].lower() for c in existing_clients}

    sqlite_clients = db.list_clients()
    client_id_map = {}  # old_id -> new_id

    for old_client in sqlite_clients:
        if old_client["name"].lower() in existing_names:
            new_id = next(c["id"] for c in existing_clients if c["name"].lower() == old_client["name"].lower())
            print(f"  [SKIP] Cliente '{old_client['name']}' ja existe (new_id={new_id})")
        else:
            new_id = storage.create_client(old_client["name"])
            print(f"  [OK]   Cliente '{old_client['name']}' (old_id={old_client['id']} -> new_id={new_id})")
        client_id_map[old_client["id"]] = new_id

    # 2. Migrate uploads
    print("\n=== UPLOADS ===")
    upload_id_map = {}

    for old_client in sqlite_clients:
        old_client_id = old_client["id"]
        new_client_id = client_id_map[old_client_id]
        uploads = db.list_uploads(old_client_id)
        for u in uploads:
            new_upload_id = storage.create_upload(
                new_client_id,
                u["filename"],
                u["broker"],
                u["reference_date"] or "",
            )
            upload_id_map[u["id"]] = new_upload_id
            print(f"  [OK]   Upload '{u['filename']}' ({u['broker']}) -> new_id={new_upload_id}")

    # 3. Migrate positions
    print("\n=== POSICOES ===")
    total = 0
    for old_client in sqlite_clients:
        old_client_id = old_client["id"]
        new_client_id = client_id_map[old_client_id]
        positions = db.get_positions(old_client_id)

        # Group by upload_id
        by_upload = {}
        for p in positions:
            # Find upload_id from the source upload
            old_upload_id = None
            # get_positions doesn't return upload_id directly; query DB
            row = db.conn.execute(
                "SELECT upload_id FROM positions WHERE id = ?", (p["id"],)
            ).fetchone()
            if row:
                old_upload_id = row["upload_id"]
            new_upload_id = upload_id_map.get(old_upload_id)
            if new_upload_id is None:
                continue
            by_upload.setdefault(new_upload_id, []).append({
                "pdf_name": p["pdf_name"],
                "value": p["value"],
                "source": p["source"],
                "status": p["status"],
                "registry_nome": p["registry_nome"],
            })

        for new_upload_id, pos_list in by_upload.items():
            storage.save_positions(new_client_id, new_upload_id, pos_list)
            total += len(pos_list)
            print(f"  [OK]   {len(pos_list)} posicoes para cliente '{old_client['name']}' (upload {new_upload_id})")

    print(f"\nTotal: {total} posicoes migradas.")
    print("\nMigracao concluida. Voce pode agora apagar data/clients.db se quiser.")


if __name__ == "__main__":
    main()
