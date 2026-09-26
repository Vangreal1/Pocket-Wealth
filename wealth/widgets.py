"""Per-user home-screen quote widget preferences."""
import re
from datetime import datetime, timezone


def ensure_table(db):
    db.execute("""CREATE TABLE IF NOT EXISTS quote_widgets (
        user_id TEXT NOT NULL, id TEXT NOT NULL, symbol TEXT NOT NULL,
        display_name TEXT NOT NULL, asset_class TEXT NOT NULL, created_at TEXT NOT NULL,
        PRIMARY KEY(user_id,id))""")


def pin(db, user, data):
    if not isinstance(data, dict):
        raise ValueError("data must be an object")
    widget_id, sym, name = data.get("id"), data.get("symbol"), data.get("display_name")
    if not isinstance(widget_id, str) or not re.fullmatch(r"[a-zA-Z0-9_-]{1,80}", widget_id):
        raise ValueError("id must be a safe widget identifier")
    if not isinstance(sym, str) or not re.fullmatch(r"[A-Za-z0-9.:/-]{1,24}", sym):
        raise ValueError("symbol must identify one feed instrument")
    if not isinstance(name, str) or not 1 <= len(name.strip()) <= 80:
        raise ValueError("display_name is required")
    kind = data.get("asset_class", "equity")
    if kind not in {"equity", "fund", "index", "commodity", "crypto", "currency"}:
        raise ValueError("asset_class is not supported for quote widgets")
    db.execute("INSERT INTO quote_widgets VALUES (?,?,?,?,?,?) ON CONFLICT(user_id,id) DO UPDATE SET symbol=excluded.symbol,display_name=excluded.display_name,asset_class=excluded.asset_class",
               (user, widget_id, sym.upper(), name.strip(), kind, datetime.now(timezone.utc).isoformat()))
    return {"id": widget_id, "symbol": sym.upper(), "asset_class": kind,
            "status": "pinned_waiting_for_feed", "saved": True,
            "stream_path": f"/api/wealth/stream/{widget_id}"}


def list_widgets(db, user, data):
    rows = db.execute("SELECT id,symbol,display_name,asset_class FROM quote_widgets WHERE user_id=? ORDER BY created_at,id", (user,)).fetchall()
    return {"widgets": [{"id": item_id, "symbol": sym, "display_name": name,
                         "asset_class": kind, "stream_path": f"/api/wealth/stream/{item_id}"}
                        for item_id, sym, name, kind in rows]}


def unpin(db, user, data):
    if not isinstance(data, dict) or not isinstance(data.get("id"), str):
        raise ValueError("id is required")
    cursor = db.execute("DELETE FROM quote_widgets WHERE user_id=? AND id=?", (user, data["id"]))
    return {"id": data["id"], "removed": cursor.rowcount == 1}
