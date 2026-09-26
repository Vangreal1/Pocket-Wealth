import sqlite3
import unittest
from datetime import datetime, timedelta, timezone

from wealth.core import execute, initialize


class MarketTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        initialize(self.db)
        self.seq = 0

    def tearDown(self):
        self.db.close()

    def task(self, action, data, user="a"):
        self.seq += 1
        return execute(self.db, {"task_id": str(self.seq), "user_id": user,
                                 "action": action, "data": data})["result"]

    def test_research_request_and_sourced_observation(self):
        request = self.task("market_research_request", {"asset_class": "equity", "identifier": "ABC", "intent": "quote"})
        self.assertEqual(request["status"], "requires_external_research")
        self.assertFalse(request["execution_allowed"])
        index_request = self.task("market_research_request", {"asset_class": "index", "identifier": "S&P 500", "intent": "overview"})
        self.assertEqual(index_request["identifier"], "S&P 500")
        self.assertIn("clickable website link", index_request["instructions"])
        self.assertEqual(self.task("market_research_request", {"asset_class": "commodity", "identifier": "gold", "intent": "quote"})["status"], "requires_external_research")
        observed = (datetime.now(timezone.utc)-timedelta(hours=2)).isoformat()
        entry = {"id": "abc-quote-1", "asset_class": "equity", "identifier": "ABC",
                 "metric": "last_price", "value": "123.45", "unit": "USD",
                 "observed_at": observed, "source_url": "https://example.org/market/abc",
                 "source_title": "Example quote"}
        self.assertFalse(self.task("record_market_observation", entry)["verified_by_wealth"])
        result = self.task("market_snapshot", {"asset_class": "equity", "identifier": "ABC"})
        self.assertGreaterEqual(result["observations"][0]["age_minutes"], 119)
        self.assertEqual(self.task("market_snapshot", {"asset_class": "equity", "identifier": "ABC"}, user="b")["observations"], [])
        entry["id"] = "local"
        entry["source_url"] = "https://localhost/private"
        with self.assertRaisesRegex(ValueError, "public HTTPS"):
            self.task("record_market_observation", entry)
