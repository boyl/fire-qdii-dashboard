from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from server.database import Database


class DatabaseTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database = Database(Path(self.temp_dir.name) / "test.sqlite3")
        self.database.initialize()

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_same_day_asset_snapshot_is_updated(self):
        base = {
            "snapshot_date": "2026-07-29",
            "cash": 100,
            "short_bond": 0,
            "long_bond": 0,
            "nasdaq100": 100,
            "gold": 0,
            "digital": 0,
            "note": "first",
        }
        self.database.save_asset_snapshot(base)
        self.database.save_asset_snapshot({**base, "cash": 200, "note": "updated"})
        rows = self.database.list_asset_snapshots()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["cash"], 200)
        self.assertEqual(rows[0]["note"], "updated")

    def test_backup_round_trip(self):
        self.database.upsert_fund(
            {
                "fund_code": "000834",
                "name": "测试基金",
                "category": "QDII",
                "benchmark": "纳斯达克",
                "channel_daily_limit": 10_000,
                "limit_channel": "基金公告口径",
                "limit_source_url": "https://example.com/notice",
                "limit_effective_date": "2026-06-22",
            }
        )
        backup = self.database.export_data()
        second = Database(Path(self.temp_dir.name) / "restored.sqlite3")
        second.initialize()
        restored = second.restore_data(backup)
        self.assertEqual(restored["funds"], 1)
        fund = second.list_funds()[0]
        self.assertEqual(fund["fund_code"], "000834")
        self.assertEqual(fund["channel_daily_limit"], 10_000)
        self.assertEqual(fund["limit_channel"], "基金公告口径")

    def test_fund_scale_and_qdii_quota_round_trip(self):
        self.database.upsert_fund(
            {
                "fund_code": "539001",
                "name": "建信纳斯达克100",
                "category": "QDII",
            }
        )
        self.database.save_fund_snapshot(
            {
                "fund_code": "539001",
                "fund_scale": 2_176_000_000,
                "fund_scale_source_url": "https://example.com/fund/539001",
                "fund_manager": "建信基金管理有限责任公司",
                "tracking_error": 2.26,
                "tracking_error_source_url": (
                    "https://fundf10.eastmoney.com/tsdata_539001.html"
                ),
                "tracking_error_as_of": "2026-07-28",
                "tracking_error_method": "东方财富 Choice 公布年化跟踪误差",
                "tracking_error_stale": False,
                "manager_qdii_quota_usd": 1_770_000_000,
                "qdii_quota_date": "2026-06-30",
                "qdii_quota_source_url": "https://example.com/qdii.pdf",
                "source_time": "2026-07-29T00:00:00+00:00",
                "source": "test",
            }
        )
        latest = self.database.latest_fund_snapshot("539001")
        self.assertEqual(latest["fund_scale"], 2_176_000_000)
        self.assertEqual(
            latest["fund_scale_source_url"],
            "https://example.com/fund/539001",
        )
        self.assertEqual(
            latest["manager_qdii_quota_usd"],
            1_770_000_000,
        )
        self.assertEqual(latest["qdii_quota_date"], "2026-06-30")
        self.assertEqual(latest["tracking_error"], 2.26)
        self.assertFalse(latest["tracking_error_stale"])
        self.assertEqual(
            latest["tracking_error_source_url"],
            "https://fundf10.eastmoney.com/tsdata_539001.html",
        )
        self.assertEqual(
            latest["qdii_quota_source_url"],
            "https://example.com/qdii.pdf",
        )
        with self.database.connect() as connection:
            versions = [
                row["version"]
                for row in connection.execute(
                    "SELECT version FROM schema_migrations ORDER BY version"
                )
            ]
        self.assertEqual(versions, [1, 2, 3, 4, 5])

    def test_backfills_trace_links_from_existing_snapshot_metadata(self):
        self.database.upsert_fund(
            {
                "fund_code": "021000",
                "name": "南方纳斯达克100",
                "category": "QDII",
            }
        )
        self.database.save_fund_snapshot(
            {
                "fund_code": "021000",
                "fund_scale": 3_136_000_000,
                "manager_qdii_quota_usd": 6_080_000_000,
                "source": "AKShare / 东方财富 + 天天基金 + 国家外汇管理局",
                "raw": {
                    "qdii_quota": {
                        "attachment": "https://example.com/safe-qdii.pdf",
                    }
                },
            }
        )
        self.database.initialize()
        latest = self.database.latest_fund_snapshot("021000")
        self.assertEqual(
            latest["fund_scale_source_url"],
            "https://fund.eastmoney.com/021000.html",
        )
        self.assertEqual(
            latest["qdii_quota_source_url"],
            "https://example.com/safe-qdii.pdf",
        )


if __name__ == "__main__":
    unittest.main()
