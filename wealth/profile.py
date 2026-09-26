"""User-specific settings for a general-purpose installable service."""
import re
from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

# The v1 contract uses *_cents fields, so support two-minor-unit currencies only.
TWO_DECIMAL_CURRENCIES = {
    "USD", "EUR", "GBP", "CAD", "AUD", "NZD", "CHF", "SEK", "NOK", "DKK",
    "INR", "CNY", "MXN", "BRL", "ZAR", "SGD", "HKD", "PLN", "CZK", "ILS",
    "TRY", "AED", "SAR"
}


def ensure_table(db):
    db.execute("""CREATE TABLE IF NOT EXISTS profiles (
        user_id TEXT PRIMARY KEY, currency TEXT NOT NULL,
        timezone TEXT NOT NULL, tax_jurisdiction TEXT NOT NULL)""")


def get(db, user):
    row = db.execute("SELECT currency,timezone,tax_jurisdiction FROM profiles WHERE user_id=?", (user,)).fetchone()
    return {"currency": row[0], "timezone": row[1], "tax_jurisdiction": row[2]} if row else None


def local_today(db, user):
    settings = get(db, user)
    return datetime.now(ZoneInfo(settings["timezone"] if settings else "UTC")).date()


def upsert_profile(db, user, data):
    if not isinstance(data, dict):
        raise ValueError("profile data must be an object")
    currency = data.get("currency")
    if currency not in TWO_DECIMAL_CURRENCIES:
        raise ValueError("currency must be a supported two-decimal ISO code")
    timezone = data.get("timezone")
    if not isinstance(timezone, str) or not 1 <= len(timezone) <= 80:
        raise ValueError("timezone must be an IANA zone name")
    try:
        ZoneInfo(timezone)
    except ZoneInfoNotFoundError as exc:
        raise ValueError("timezone must be an IANA zone name") from exc
    jurisdiction = data.get("tax_jurisdiction", "unspecified")
    if not isinstance(jurisdiction, str) or not 1 <= len(jurisdiction) <= 40 or not re.fullmatch(r"[A-Za-z0-9_-]+", jurisdiction):
        raise ValueError("tax_jurisdiction must be a short identifier")
    existing = get(db, user)
    if existing and existing["currency"] != currency:
        raise ValueError("currency cannot change after profile creation; export and migrate money values")
    if existing and existing["tax_jurisdiction"] != jurisdiction and db.execute(
            "SELECT 1 FROM tax_items WHERE user_id=? LIMIT 1", (user,)).fetchone():
        raise ValueError("tax jurisdiction cannot change with existing tax items; export and migrate them")
    if not existing:
        tables = ("accounts", "cashflows", "goals", "transactions", "seasonal", "tax_items", "paper_accounts")
        has_data = any(db.execute(f"SELECT 1 FROM {table} WHERE user_id=? LIMIT 1", (user,)).fetchone() for table in tables)
        if has_data and data.get("confirm_legacy_currency") is not True:
            raise ValueError("existing records have no currency; confirm_legacy_currency:true required after review")
    db.execute("INSERT INTO profiles VALUES (?,?,?,?) ON CONFLICT(user_id) DO UPDATE SET timezone=excluded.timezone,tax_jurisdiction=excluded.tax_jurisdiction",
               (user, currency, timezone, jurisdiction))
    return {"currency": currency, "timezone": timezone, "tax_jurisdiction": jurisdiction, "saved": True}
