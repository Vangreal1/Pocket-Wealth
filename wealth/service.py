"""Loopback HTTP interface for a trusted Foreman caller."""
import hmac
import json
import os
import re
# sqlcipher3's dbapi2 module is a drop-in for the stdlib's sqlite3 (same DB-API 2.0 surface,
# same Error/OperationalError hierarchy) - it's the stdlib sqlite3 C code plus SQLCipher's
# transparent AES-256 page encryption. See _connect() below for how the key gets applied; every
# other line in this file that says "sqlite3" needs no other change to get real at-rest
# encryption (data/wealth.sqlite3 was plaintext before 2026-09-28 - see GAP_PLAN.md).
from sqlcipher3 import dbapi2 as sqlite3
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .core import execute, initialize

_HEX_KEY = re.compile(r"^[0-9a-f]{64}$")


def _connect(db_path, key, timeout=5):
    """Opens an AES-256-encrypted SQLCipher connection. key is a raw 256-bit key, 64 hex
    characters - SQLCipher's `x'...'` raw-key syntax, not a passphrase run through its own KDF:
    the key is already machine-generated, high-entropy, and never typed by a person, so there's
    nothing for a passphrase-style key-derivation step to usefully add. PRAGMA key can't take a
    bound `?` parameter (it isn't DML) - the hex-format check above is what keeps this string
    interpolation safe, not escaping."""
    if not _HEX_KEY.match(key):
        raise ValueError("WEALTH_DB_KEY must be exactly 64 hex characters (a raw 256-bit key)")
    db = sqlite3.connect(db_path, timeout=timeout)
    db.execute(f"PRAGMA key = \"x'{key}'\"")
    return db


MAX_BODY = 65536
CAPABILITIES = {
    "agent": "pocket-wealth", "contract_version": 1,
    "actions": ["upsert_profile", "overview", "upsert_account", "upsert_cashflow", "upsert_goal",
                "upsert_seasonal", "add_transactions", "import_csv", "spending_report",
                "spending_trends", "upsert_budget", "upsert_loan_terms", "loan_analysis", "debt_plan",
                "compare_loan_quotes", "upsert_tax_item", "tax_organizer", "retirement_scenario",
                "paper_open", "paper_order", "paper_portfolio",
                "market_research_request", "record_market_observation", "market_snapshot",
                "pin_quote_widget", "list_quote_widgets", "unpin_quote_widget",
                "export_user_data", "delete_user_data"],
    "external_connections": False, "live_trading": False, "tax_filing": False,
}


class Handler(BaseHTTPRequestHandler):
    def respond(self, status, value):
        blob = json.dumps(value).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(blob)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(blob)

    def authenticated(self):
        provided = self.headers.get("Authorization", "")
        expected = "Bearer " + self.server.token
        return hmac.compare_digest(provided, expected)

    def do_GET(self):
        if not self.authenticated():
            return self.respond(401, {"error": "unauthorized"})
        if self.path == "/health":
            return self.respond(200, {"status": "ok"})
        if self.path == "/capabilities":
            return self.respond(200, CAPABILITIES)
        self.respond(404, {"error": "not found"})

    def do_POST(self):
        if not self.authenticated():
            return self.respond(401, {"error": "unauthorized"})
        if self.path != "/tasks":
            return self.respond(404, {"error": "not found"})
        if self.headers.get("Content-Type", "").split(";", 1)[0].strip().lower() != "application/json":
            return self.respond(415, {"status": "error", "error": "application/json required"})
        length = self.headers.get("Content-Length")
        try:
            size = int(length)
            if size < 1 or size > MAX_BODY:
                raise ValueError("invalid body length")
            payload = json.loads(self.rfile.read(size))
            if isinstance(payload, dict) and payload.get("action") in {"export_user_data", "delete_user_data"}:
                data_token = getattr(self.server, "data_token", "")
                if not data_token or not hmac.compare_digest(
                        self.headers.get("X-Wealth-Data-Token", ""), data_token):
                    return self.respond(403, {"status": "error", "error": "trusted data-control flow required"})
            if isinstance(payload, dict) and payload.get("action") in {"add_transactions", "import_csv"}:
                details = payload.get("data")
                if isinstance(details, dict) and details.get("dry_run", True) is False:
                    approval_token = getattr(self.server, "approval_token", "")
                    if not approval_token or not hmac.compare_digest(
                            self.headers.get("X-Wealth-Approval-Token", ""), approval_token):
                        return self.respond(403, {"status": "error", "error": "trusted import approval required"})
            if isinstance(payload, dict) and payload.get("action") == "record_market_observation":
                source_token = getattr(self.server, "source_token", "")
                if not source_token or not hmac.compare_digest(
                        self.headers.get("X-Wealth-Source-Token", ""), source_token):
                    return self.respond(403, {"status": "error", "error": "trusted source connector required"})
            with _connect(self.server.db_path, self.server.db_key) as db:
                initialize(db)
                result = execute(db, payload)
            self.respond(200, result)
        except (ValueError, json.JSONDecodeError) as exc:
            self.respond(400, {"status": "error", "error": str(exc)})
        except sqlite3.Error:
            self.respond(503, {"status": "error", "error": "storage unavailable"})

    def log_message(self, format, *args):
        # Never log payloads, query strings or Authorization headers.
        pass


def main():
    token = os.environ.get("WEALTH_TOKEN", "")
    db_path = os.environ.get("WEALTH_DB", "")
    db_key = os.environ.get("WEALTH_DB_KEY", "")
    if len(token) < 32 or not db_path or not os.path.isabs(db_path):
        raise SystemExit("Set WEALTH_TOKEN (32+ chars) and absolute WEALTH_DB path")
    if not _HEX_KEY.match(db_key):
        raise SystemExit("Set WEALTH_DB_KEY to a 64-character hex string (a raw 256-bit key)")
    with _connect(db_path, db_key) as db:
        initialize(db)
    server = ThreadingHTTPServer(("127.0.0.1", 8788), Handler)
    server.token = token
    server.db_key = db_key
    source_token = os.environ.get("WEALTH_SOURCE_TOKEN", "")
    if source_token and (len(source_token) < 32 or source_token == token):
        raise SystemExit("WEALTH_SOURCE_TOKEN must be distinct and at least 32 characters")
    server.source_token = source_token
    data_token = os.environ.get("WEALTH_DATA_TOKEN", "")
    approval_token = os.environ.get("WEALTH_APPROVAL_TOKEN", "")
    configured = [value for value in (token, source_token, data_token, approval_token) if value]
    if any(len(value) < 32 for value in configured) or len(configured) != len(set(configured)):
        raise SystemExit("configured Wealth tokens must be distinct and at least 32 characters")
    server.data_token = data_token
    server.approval_token = approval_token
    server.db_path = db_path
    server.serve_forever()


if __name__ == "__main__":
    main()
