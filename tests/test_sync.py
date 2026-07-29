from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from server.database import Database
from server.sync import SyncService


class FakeProvider:
    name = "fake"

    def __init__(self):
        self.limit = 10.0
        self.status = "限制大额申购"
        self.fail = False

    def collect(self, watches, mode="full"):
        now = datetime.now(timezone.utc).isoformat()
        if self.fail:
            raise RuntimeError("offline")
        return {
            watch["fund_code"]: {
                "fund_code": watch["fund_code"],
                "name": watch["name"],
                "business_date": "2026-07-29",
                "estimate": 1.02,
                "nav": 1.01,
                "estimate_error": 0.99,
                "market_price": None,
                "iopv": None,
                "premium": None,
                "premium_basis": None,
                "tracking_error": None,
                "purchase_status": self.status,
                "daily_limit": self.limit,
                "source_time": now,
                "source": self.name,
                "errors": [],
                "raw": {},
            }
            for watch in watches
        }


class SyncTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database = Database(Path(self.temp_dir.name) / "sync.sqlite3")
        self.database.initialize()
        self.database.update_settings(
            {
                **self.database.get_settings(),
                "notifications_enabled": False,
            }
        )
        self.database.upsert_fund(
            {
                "fund_code": "000834",
                "name": "测试基金",
                "category": "QDII",
            }
        )
        self.provider = FakeProvider()
        self.service = SyncService(self.database, self.provider)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_limit_relaxation_alerts_once(self):
        self.assertTrue(self.service.run()["ok"])
        self.assertEqual(self.database.list_alerts(), [])

        self.provider.limit = 100.0
        self.assertTrue(self.service.run()["ok"])
        self.assertEqual(len(self.database.list_alerts()), 1)

        self.assertTrue(self.service.run()["ok"])
        self.assertEqual(len(self.database.list_alerts()), 1)

    def test_failure_carries_forward_and_marks_stale(self):
        self.service.run()
        self.provider.fail = True
        result = self.service.run()
        self.assertFalse(result["ok"])
        latest = self.database.latest_fund_snapshot("000834")
        self.assertTrue(latest["stale"])
        self.assertEqual(latest["nav"], 1.01)


if __name__ == "__main__":
    unittest.main()
