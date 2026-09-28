import http.client
import json
import os
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer

from wealth.service import Handler


class ServiceTests(unittest.TestCase):
    def test_auth_and_task_http(self):
        with tempfile.TemporaryDirectory() as directory:
            server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
            server.token = "x" * 40
            server.data_token = "d" * 40
            server.approval_token = "a" * 40
            server.db_path = os.path.join(directory, "wealth.db")
            server.db_key = "a" * 64
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                conn = http.client.HTTPConnection("127.0.0.1", server.server_port)
                conn.request("GET", "/health")
                response = conn.getresponse()
                self.assertEqual(response.status, 401)
                response.read()
                conn.request("POST", "/tasks", body=json.dumps({"task_id": "export-no-token", "user_id": "a", "action": "export_user_data", "data": {}}),
                             headers={"Authorization": "Bearer " + server.token, "Content-Type": "application/json"})
                response = conn.getresponse()
                self.assertEqual(response.status, 403)
                response.read()
                conn.request("POST", "/tasks", body=json.dumps({"task_id": "export-allowed", "user_id": "a", "action": "export_user_data", "data": {}}),
                             headers={"Authorization": "Bearer " + server.token, "X-Wealth-Data-Token": server.data_token,
                                      "Content-Type": "application/json"})
                response = conn.getresponse()
                self.assertEqual(response.status, 200)
                self.assertEqual(json.load(response)["result"]["format"], "pocket-wealth-user-export-v1")
                conn.request("POST", "/tasks", body=json.dumps({"task_id": "import-no-token", "user_id": "a", "action": "import_csv",
                                                             "data": {"dry_run": False, "approved": True, "csv_text": "x"}}),
                             headers={"Authorization": "Bearer " + server.token, "Content-Type": "application/json"})
                response = conn.getresponse()
                self.assertEqual(response.status, 403)
                response.read()
                conn.request("POST", "/tasks", body=json.dumps({"task_id": "market", "user_id": "a", "action": "record_market_observation", "data": {}}),
                             headers={"Authorization": "Bearer " + server.token, "Content-Type": "application/json"})
                response = conn.getresponse()
                self.assertEqual(response.status, 403)
                response.read()
                conn.request("GET", "/capabilities", headers={"Authorization": "Bearer " + server.token})
                response = conn.getresponse()
                self.assertEqual(response.status, 200)
                self.assertFalse(json.load(response)["live_trading"])
                conn.request("POST", "/tasks", body=json.dumps({"task_id": "1", "user_id": "a", "action": "overview"}),
                             headers={"Authorization": "Bearer " + server.token, "Content-Type": "application/json"})
                response = conn.getresponse()
                self.assertEqual(response.status, 200)
                self.assertEqual(json.load(response)["result"]["trajectory_status"], "insufficient_data")
                conn.close()
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)
