"""User-controlled data portability and erasure.

The HTTP gateway separately authorizes these operations. Direct Python callers
must supply their own authenticated user binding and explicit confirmation.
"""
from datetime import datetime, timezone

TABLES = (
    "profiles", "accounts", "cashflows", "goals", "transactions", "seasonal",
    "loan_terms", "tax_items", "budgets", "paper_accounts", "paper_positions",
    "paper_orders", "market_observations", "quote_widgets", "tasks", "audit",
)


def export_user_data(db, user, data):
    if not isinstance(data, dict):
        raise ValueError("data must be an object")
    # One consistent SQLite read snapshot when called inside the enclosing
    # transaction in core.execute; no database or credential paths are exposed.
    tables = {}
    for table in TABLES:
        cursor = db.execute(f"SELECT * FROM {table} WHERE user_id=?", (user,))
        names = [column[0] for column in cursor.description]
        tables[table] = [dict(zip(names, row)) for row in cursor]
    return {"format": "pocket-wealth-user-export-v1",
            "schema_version": db.execute("PRAGMA user_version").fetchone()[0],
            "exported_at": datetime.now(timezone.utc).isoformat(),
            "user_id": user, "tables": tables,
            "warning": "Sensitive data. Save the download securely; deleting the database does not delete exported files or backups."}


def delete_user_data(db, user, data):
    if not isinstance(data, dict) or data.get("confirm") != f"ERASE {user}":
        raise ValueError("confirm must exactly match ERASE followed by the authenticated user ID")
    # Turn on SQLite secure delete for this connection. Backups, filesystem
    # snapshots and WAL remnants need their own retention/cleanup policy.
    db.execute("PRAGMA secure_delete=ON")
    removed = {}
    for table in reversed(TABLES):
        removed[table] = db.execute(f"DELETE FROM {table} WHERE user_id=?", (user,)).rowcount
    return {"erased": True, "removed_rows": removed,
            "warning": "This erases active database records only; separately manage backups, exports and filesystem snapshots."}
