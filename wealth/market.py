"""On-demand market research contract for Pocket/Foreman's internet tools.

This module never fetches URLs. Foreman researches sources, then records
observations for user-facing analysis. Observations are not execution prices.
"""
import re
import ipaddress
from datetime import datetime, timezone
from urllib.parse import urlparse

ASSET_CLASSES = {"equity", "index", "fund", "bond", "currency", "commodity", "crypto", "economic_series", "other"}
INTENTS = {"quote", "overview", "fundamentals", "macro", "news"}


def ensure_table(db):
    db.execute("""CREATE TABLE IF NOT EXISTS market_observations (
        user_id TEXT NOT NULL, id TEXT NOT NULL, asset_class TEXT NOT NULL,
        identifier TEXT NOT NULL, metric TEXT NOT NULL, value TEXT NOT NULL,
        unit TEXT NOT NULL, observed_at TEXT NOT NULL, retrieved_at TEXT NOT NULL,
        source_url TEXT NOT NULL, source_title TEXT NOT NULL,
        PRIMARY KEY(user_id,id))""")


def _identifier(value, label, limit=80):
    if not isinstance(value, str) or not 1 <= len(value) <= limit or not value.strip() or not re.fullmatch(r"[\w .:/&+-]+", value, re.UNICODE):
        raise ValueError(f"invalid {label}")
    return value.strip()


def research_request(db, user, data):
    if not isinstance(data, dict):
        raise ValueError("data must be an object")
    kind = data.get("asset_class")
    intent = data.get("intent", "quote")
    if kind not in ASSET_CLASSES or intent not in INTENTS:
        raise ValueError("invalid asset_class or intent")
    identifier = _identifier(data.get("identifier"), "identifier")
    return {"status": "requires_external_research", "asset_class": kind,
            "identifier": identifier, "intent": intent,
            "instructions": "Foreman must use an authorized internet source, distinguish exchange/official data from aggregation, record source URL and observation time, and state unknown or delayed freshness. Return a source-backed answer to the user with a clickable website link. For an index overview, include level and change with period when available.",
            "execution_allowed": False}


def record_observation(db, user, data):
    if not isinstance(data, dict):
        raise ValueError("data must be an object")
    if data.get("asset_class") not in ASSET_CLASSES:
        raise ValueError("invalid asset_class")
    item_id = _identifier(data.get("id"), "id")
    identifier = _identifier(data.get("identifier"), "identifier")
    metric = _identifier(data.get("metric"), "metric")
    value = data.get("value")
    if not isinstance(value, str) or not 1 <= len(value) <= 100:
        raise ValueError("value must be a source-derived string")
    unit = _identifier(data.get("unit"), "unit", 30)
    source_url = data.get("source_url")
    if not isinstance(source_url, str) or len(source_url) > 1000:
        raise ValueError("source_url must be HTTPS")
    parsed = urlparse(source_url)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("source_url must be a public HTTPS URL")
    hostname = parsed.hostname.lower()
    if hostname in {"localhost", "localhost.localdomain"} or hostname.endswith((".local", ".internal")):
        raise ValueError("source_url must be a public HTTPS URL")
    try:
        address = ipaddress.ip_address(hostname)
    except ValueError:
        pass
    else:
        if not address.is_global:
            raise ValueError("source_url must be a public HTTPS URL")
    source_title = data.get("source_title")
    if not isinstance(source_title, str) or not 1 <= len(source_title) <= 200:
        raise ValueError("source_title is required")
    observed = data.get("observed_at")
    if not isinstance(observed, str):
        raise ValueError("observed_at must include timezone")
    try:
        dt = datetime.fromisoformat(observed.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("observed_at must be ISO date-time") from exc
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise ValueError("observed_at must include timezone")
    now = datetime.now(timezone.utc)
    if dt.astimezone(timezone.utc) > now:
        raise ValueError("observed_at cannot be in the future")
    db.execute("INSERT INTO market_observations VALUES (?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(user_id,id) DO UPDATE SET asset_class=excluded.asset_class,identifier=excluded.identifier,metric=excluded.metric,value=excluded.value,unit=excluded.unit,observed_at=excluded.observed_at,retrieved_at=excluded.retrieved_at,source_url=excluded.source_url,source_title=excluded.source_title",
               (user, item_id, data["asset_class"], identifier, metric, value.strip(), unit,
                dt.isoformat(), now.isoformat(), source_url, source_title.strip()))
    return {"id": item_id, "saved": True, "source_supplied_by": "trusted_caller", "verified_by_wealth": False}


def snapshot(db, user, data):
    if not isinstance(data, dict):
        raise ValueError("data must be an object")
    identifier = _identifier(data.get("identifier"), "identifier")
    kind = data.get("asset_class")
    if kind not in ASSET_CLASSES:
        raise ValueError("invalid asset_class")
    rows = db.execute("SELECT metric,value,unit,observed_at,retrieved_at,source_url,source_title FROM market_observations WHERE user_id=? AND asset_class=? AND identifier=? ORDER BY retrieved_at DESC LIMIT 20", (user, kind, identifier)).fetchall()
    now = datetime.now(timezone.utc)
    observations = [{"metric": m, "value": v, "unit": u, "observed_at": at,
                     "retrieved_at": retrieved, "age_minutes": max(0, round((now-datetime.fromisoformat(at)).total_seconds()/60)),
                     "source_url": url, "source_title": title, "verified_by_wealth": False}
                    for m, v, u, at, retrieved, url, title in rows]
    return {"asset_class": kind, "identifier": identifier, "observations": observations,
            "warning": "These observations were supplied by Pocket/Foreman, not independently verified by Wealth. Age is measured from the source observation time. Research current data before acting; never use these records as broker execution prices."}
