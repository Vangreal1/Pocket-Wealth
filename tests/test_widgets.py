import sqlite3
import unittest

from wealth.core import execute, initialize


class WidgetTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        initialize(self.db)
        self.n = 0

    def tearDown(self):
        self.db.close()

    def task(self, user, action, data=None):
        self.n += 1
        return execute(self.db, {"task_id": str(self.n), "user_id": user,
                                 "action": action, "data": data or {}})["result"]

    def test_pins_are_user_scoped_and_stream_path_is_local(self):
        pinned = self.task("a", "pin_quote_widget", {"id": "home-stock", "symbol": "ABC", "display_name": "Example Co"})
        self.assertEqual(pinned["status"], "pinned_waiting_for_feed")
        self.assertEqual(pinned["stream_path"], "/api/wealth/stream/home-stock")
        self.assertEqual(len(self.task("a", "list_quote_widgets")["widgets"]), 1)
        self.assertEqual(self.task("b", "list_quote_widgets")["widgets"], [])
        self.assertFalse(self.task("b", "unpin_quote_widget", {"id": "home-stock"})["removed"])
        self.assertTrue(self.task("a", "unpin_quote_widget", {"id": "home-stock"})["removed"])
        with self.assertRaisesRegex(ValueError, "symbol"):
            self.task("a", "pin_quote_widget", {"id": "bad", "symbol": "<script>", "display_name": "Bad"})
