from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

import server.main as main
from server.database import Database
from server.sync import SyncService


class ApiIntegrationTest(unittest.TestCase):
    def test_local_api_workflow(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            database = Database(Path(temp_dir) / "api.sqlite3")
            main.database = database
            main.sync_service = SyncService(database, main.provider)

            with TestClient(main.app) as client:
                self.assertEqual(client.get("/api/health").status_code, 200)
                response = client.post(
                    "/api/assets",
                    json={
                        "snapshot_date": "2026-07-29",
                        "cash": 200_000,
                        "short_bond": 100_000,
                        "long_bond": 100_000,
                        "nasdaq100": 400_000,
                        "gold": 100_000,
                        "digital": 100_000,
                        "note": "integration",
                    },
                )
                self.assertEqual(response.status_code, 200)

                summary = client.get("/api/portfolio/summary").json()
                self.assertEqual(summary["total"], 1_000_000)
                self.assertEqual(summary["equity_ratio"], 40)
                self.assertEqual(summary["status"], "inside")

                stress = client.post(
                    "/api/portfolio/stress",
                    json={
                        "scenarios": [
                            {
                                "name": "test",
                                "shocks": {
                                    "nasdaq100": -50,
                                    "digital": -70,
                                },
                            }
                        ]
                    },
                )
                self.assertEqual(stress.status_code, 200)
                self.assertLess(stress.json()[0]["total_after"], 1_000_000)

                sustainability = client.post(
                    "/api/sustainability",
                    json={
                        "annual_spending": [120_000],
                        "real_return": 2,
                    },
                )
                self.assertEqual(sustainability.status_code, 200)

                fund = client.post(
                    "/api/funds",
                    json={
                        "fund_code": "021000",
                        "name": "测试基金",
                        "exchange_code": "",
                        "category": "QDII",
                        "benchmark": "纳斯达克",
                        "channel_daily_limit": 10_000,
                        "limit_channel": "公告口径",
                        "limit_source_url": "https://example.com/notice",
                        "limit_effective_date": "2026-06-22",
                    },
                )
                self.assertEqual(fund.status_code, 200)
                self.assertIsNone(fund.json()["exchange_code"])
                self.assertEqual(fund.json()["channel_daily_limit"], 10_000)
                self.assertEqual(len(client.get("/api/funds").json()), 1)

                backup = client.get("/api/export/json")
                self.assertEqual(backup.status_code, 200)
                self.assertEqual(backup.json()["format"], "fire-qdii-backup-v1")

                frontend = client.get("/")
                self.assertEqual(frontend.status_code, 200)
                self.assertIn("FIRE · 本地资产控制台", frontend.text)


if __name__ == "__main__":
    unittest.main()
