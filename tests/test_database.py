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
            }
        )
        backup = self.database.export_data()
        second = Database(Path(self.temp_dir.name) / "restored.sqlite3")
        second.initialize()
        restored = second.restore_data(backup)
        self.assertEqual(restored["funds"], 1)
        self.assertEqual(second.list_funds()[0]["fund_code"], "000834")


if __name__ == "__main__":
    unittest.main()
