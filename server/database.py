from __future__ import annotations

import csv
import io
import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Any, Iterator, Sequence

from .calculations import ASSET_KEYS, premium_rate
from .config import DATABASE_PATH

SCHEMA_VERSION = 5


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def to_cents(value: float | int | str | Decimal | None) -> int | None:
    if value is None:
        return None
    return int(
        (Decimal(str(value)) * Decimal("100")).quantize(
            Decimal("1"), rounding=ROUND_HALF_UP
        )
    )


def from_cents(value: int | None) -> float | None:
    return None if value is None else float(Decimal(value) / Decimal("100"))


class Database:
    def __init__(self, path: Path = DATABASE_PATH):
        self.path = path

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def initialize(self) -> None:
        statements = [
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version INTEGER PRIMARY KEY,
                applied_at TEXT NOT NULL
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS asset_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                snapshot_date TEXT NOT NULL UNIQUE,
                cash_cents INTEGER NOT NULL DEFAULT 0 CHECK(cash_cents >= 0),
                short_bond_cents INTEGER NOT NULL DEFAULT 0 CHECK(short_bond_cents >= 0),
                long_bond_cents INTEGER NOT NULL DEFAULT 0 CHECK(long_bond_cents >= 0),
                nasdaq100_cents INTEGER NOT NULL DEFAULT 0 CHECK(nasdaq100_cents >= 0),
                gold_cents INTEGER NOT NULL DEFAULT 0 CHECK(gold_cents >= 0),
                digital_cents INTEGER NOT NULL DEFAULT 0 CHECK(digital_cents >= 0),
                note TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS fund_watches (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                fund_code TEXT NOT NULL UNIQUE,
                name TEXT NOT NULL DEFAULT '',
                exchange_code TEXT,
                category TEXT NOT NULL DEFAULT 'QDII',
                benchmark TEXT,
                channel_daily_limit_cents INTEGER,
                limit_channel TEXT,
                limit_source_url TEXT,
                limit_effective_date TEXT,
                active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS fund_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                fund_code TEXT NOT NULL,
                business_date TEXT,
                estimate REAL,
                nav REAL,
                estimate_error REAL,
                market_price REAL,
                iopv REAL,
                premium REAL,
                premium_basis TEXT,
                tracking_error REAL,
                tracking_error_source_url TEXT,
                tracking_error_as_of TEXT,
                tracking_error_method TEXT,
                tracking_error_stale INTEGER NOT NULL DEFAULT 1,
                purchase_status TEXT,
                daily_limit_cents INTEGER,
                fund_scale_cents INTEGER,
                fund_scale_source_url TEXT,
                fund_manager TEXT,
                manager_qdii_quota_usd_cents INTEGER,
                qdii_quota_date TEXT,
                qdii_quota_source_url TEXT,
                source_time TEXT NOT NULL,
                source TEXT NOT NULL DEFAULT 'AKShare/Eastmoney',
                stale INTEGER NOT NULL DEFAULT 0,
                corrected INTEGER NOT NULL DEFAULT 0,
                correction_note TEXT,
                raw_json TEXT NOT NULL DEFAULT '{}',
                FOREIGN KEY(fund_code) REFERENCES fund_watches(fund_code) ON DELETE CASCADE
            )
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_fund_snapshots_code_time
            ON fund_snapshots(fund_code, source_time DESC)
            """,
            """
            CREATE TABLE IF NOT EXISTS fund_status_changes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                fund_code TEXT NOT NULL,
                old_status TEXT,
                new_status TEXT,
                old_limit_cents INTEGER,
                new_limit_cents INTEGER,
                relaxed INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                FOREIGN KEY(fund_code) REFERENCES fund_watches(fund_code) ON DELETE CASCADE
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS alerts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                fund_code TEXT NOT NULL,
                title TEXT NOT NULL,
                message TEXT NOT NULL,
                event_type TEXT NOT NULL,
                dedupe_key TEXT NOT NULL UNIQUE,
                created_at TEXT NOT NULL,
                read_at TEXT,
                FOREIGN KEY(fund_code) REFERENCES fund_watches(fund_code) ON DELETE CASCADE
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS sync_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                mode TEXT NOT NULL,
                started_at TEXT NOT NULL,
                finished_at TEXT,
                status TEXT NOT NULL,
                items_total INTEGER NOT NULL DEFAULT 0,
                items_succeeded INTEGER NOT NULL DEFAULT 0,
                error TEXT
            )
            """,
        ]
        with self.connect() as connection:
            for statement in statements:
                connection.execute(statement)
            connection.execute(
                "INSERT OR IGNORE INTO schema_migrations(version, applied_at) VALUES (?, ?)",
                (1, utc_now()),
            )
            snapshot_columns = {
                row["name"]
                for row in connection.execute(
                    "PRAGMA table_info(fund_snapshots)"
                ).fetchall()
            }
            migrations = {
                "fund_scale_cents": "INTEGER",
                "fund_manager": "TEXT",
                "manager_qdii_quota_usd_cents": "INTEGER",
                "qdii_quota_date": "TEXT",
            }
            for column, column_type in migrations.items():
                if column not in snapshot_columns:
                    connection.execute(
                        f"ALTER TABLE fund_snapshots ADD COLUMN {column} {column_type}"
                    )
            connection.execute(
                "INSERT OR IGNORE INTO schema_migrations(version, applied_at) VALUES (?, ?)",
                (2, utc_now()),
            )
            watch_columns = {
                row["name"]
                for row in connection.execute(
                    "PRAGMA table_info(fund_watches)"
                ).fetchall()
            }
            watch_migrations = {
                "channel_daily_limit_cents": "INTEGER",
                "limit_channel": "TEXT",
                "limit_source_url": "TEXT",
                "limit_effective_date": "TEXT",
            }
            for column, column_type in watch_migrations.items():
                if column not in watch_columns:
                    connection.execute(
                        f"ALTER TABLE fund_watches ADD COLUMN {column} {column_type}"
                    )
            connection.execute(
                "INSERT OR IGNORE INTO schema_migrations(version, applied_at) VALUES (?, ?)",
                (3, utc_now()),
            )
            snapshot_source_migrations = {
                "fund_scale_source_url": "TEXT",
                "qdii_quota_source_url": "TEXT",
            }
            for column, column_type in snapshot_source_migrations.items():
                if column not in snapshot_columns:
                    connection.execute(
                        f"ALTER TABLE fund_snapshots ADD COLUMN {column} {column_type}"
                    )
            connection.execute(
                "INSERT OR IGNORE INTO schema_migrations(version, applied_at) VALUES (?, ?)",
                (4, utc_now()),
            )
            tracking_error_migrations = {
                "tracking_error_source_url": "TEXT",
                "tracking_error_as_of": "TEXT",
                "tracking_error_method": "TEXT",
                "tracking_error_stale": "INTEGER NOT NULL DEFAULT 1",
            }
            for column, column_type in tracking_error_migrations.items():
                if column not in snapshot_columns:
                    connection.execute(
                        f"ALTER TABLE fund_snapshots ADD COLUMN {column} {column_type}"
                    )
            connection.execute(
                "INSERT OR IGNORE INTO schema_migrations(version, applied_at) VALUES (?, ?)",
                (SCHEMA_VERSION, utc_now()),
            )
            connection.execute(
                """
                UPDATE fund_snapshots
                SET fund_scale_source_url = CASE
                    WHEN EXISTS (
                        SELECT 1 FROM fund_watches
                        WHERE fund_watches.fund_code = fund_snapshots.fund_code
                          AND fund_watches.exchange_code IS NOT NULL
                    ) THEN (
                        SELECT 'https://quote.eastmoney.com/'
                            || CASE
                                WHEN substr(exchange_code, 1, 1) = '5' THEN 'sh'
                                ELSE 'sz'
                            END
                            || exchange_code || '.html'
                        FROM fund_watches
                        WHERE fund_watches.fund_code = fund_snapshots.fund_code
                    )
                    WHEN source LIKE '%雪球基金%'
                        THEN 'https://danjuanfunds.com/djapi/fund/' || fund_code
                    WHEN source LIKE '%天天基金%'
                        THEN 'https://fund.eastmoney.com/' || fund_code || '.html'
                    ELSE NULL
                END
                WHERE fund_scale_source_url IS NULL
                  AND fund_scale_cents IS NOT NULL
                """
            )
            connection.execute(
                """
                UPDATE fund_snapshots
                SET qdii_quota_source_url =
                    json_extract(raw_json, '$.qdii_quota.attachment')
                WHERE qdii_quota_source_url IS NULL
                  AND manager_qdii_quota_usd_cents IS NOT NULL
                  AND json_valid(raw_json)
                """
            )
        self._ensure_defaults()

    def _ensure_defaults(self) -> None:
        defaults = {
            "target_equity": "50",
            "rebalance_band": "10",
            "morning_sync": "09:35",
            "evening_sync": "22:30",
            "notifications_enabled": "true",
        }
        now = utc_now()
        with self.connect() as connection:
            connection.executemany(
                """
                INSERT OR IGNORE INTO settings(key, value, updated_at)
                VALUES (?, ?, ?)
                """,
                [(key, value, now) for key, value in defaults.items()],
            )

    def health(self) -> str:
        with self.connect() as connection:
            connection.execute("SELECT 1").fetchone()
        return "ok"

    def get_settings(self) -> dict[str, Any]:
        with self.connect() as connection:
            rows = connection.execute("SELECT key, value FROM settings").fetchall()
        values = {row["key"]: row["value"] for row in rows}
        return {
            "target_equity": float(values.get("target_equity", 50)),
            "rebalance_band": float(values.get("rebalance_band", 10)),
            "morning_sync": values.get("morning_sync", "09:35"),
            "evening_sync": values.get("evening_sync", "22:30"),
            "notifications_enabled": values.get("notifications_enabled", "true")
            == "true",
        }

    def update_settings(self, values: dict[str, Any]) -> dict[str, Any]:
        now = utc_now()
        payload = {
            "target_equity": str(values["target_equity"]),
            "rebalance_band": str(values["rebalance_band"]),
            "morning_sync": str(values["morning_sync"]),
            "evening_sync": str(values["evening_sync"]),
            "notifications_enabled": "true"
            if values["notifications_enabled"]
            else "false",
        }
        with self.connect() as connection:
            connection.executemany(
                """
                INSERT INTO settings(key, value, updated_at) VALUES (?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET
                    value = excluded.value,
                    updated_at = excluded.updated_at
                """,
                [(key, value, now) for key, value in payload.items()],
            )
        return self.get_settings()

    @staticmethod
    def _asset_row(row: sqlite3.Row) -> dict:
        result = {
            "id": row["id"],
            "snapshot_date": row["snapshot_date"],
            "note": row["note"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }
        for key in ASSET_KEYS:
            result[key] = from_cents(row[f"{key}_cents"]) or 0.0
        return result

    def save_asset_snapshot(self, values: dict[str, Any]) -> dict:
        now = utc_now()
        columns = [f"{key}_cents" for key in ASSET_KEYS]
        cents = [to_cents(values.get(key, 0)) or 0 for key in ASSET_KEYS]
        assignments = ", ".join(f"{column}=excluded.{column}" for column in columns)
        placeholders = ", ".join("?" for _ in range(len(columns) + 4))
        with self.connect() as connection:
            connection.execute(
                f"""
                INSERT INTO asset_snapshots(
                    snapshot_date, {", ".join(columns)}, note, created_at, updated_at
                ) VALUES ({placeholders})
                ON CONFLICT(snapshot_date) DO UPDATE SET
                    {assignments},
                    note=excluded.note,
                    updated_at=excluded.updated_at
                """,
                [
                    values["snapshot_date"],
                    *cents,
                    values.get("note", ""),
                    now,
                    now,
                ],
            )
            row = connection.execute(
                "SELECT * FROM asset_snapshots WHERE snapshot_date=?",
                (values["snapshot_date"],),
            ).fetchone()
        return self._asset_row(row)

    def list_asset_snapshots(self, limit: int = 365) -> list[dict]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM asset_snapshots
                ORDER BY snapshot_date DESC, id DESC LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [self._asset_row(row) for row in rows]

    def latest_asset_snapshot(self) -> dict | None:
        snapshots = self.list_asset_snapshots(limit=1)
        return snapshots[0] if snapshots else None

    @staticmethod
    def _snapshot_row(row: sqlite3.Row | None) -> dict | None:
        if row is None:
            return None
        try:
            raw = json.loads(row["raw_json"] or "{}")
        except (TypeError, ValueError):
            raw = {}
        return {
            "id": row["id"],
            "fund_code": row["fund_code"],
            "business_date": row["business_date"],
            "estimate": row["estimate"],
            "nav": row["nav"],
            "estimate_error": row["estimate_error"],
            "market_price": row["market_price"],
            "iopv": row["iopv"],
            "premium": row["premium"],
            "premium_basis": row["premium_basis"],
            "tracking_error": row["tracking_error"],
            "tracking_error_source_url": row["tracking_error_source_url"],
            "tracking_error_as_of": row["tracking_error_as_of"],
            "tracking_error_method": row["tracking_error_method"],
            "tracking_error_stale": bool(row["tracking_error_stale"]),
            "purchase_status": row["purchase_status"],
            "daily_limit": from_cents(row["daily_limit_cents"]),
            "fund_scale": from_cents(row["fund_scale_cents"]),
            "fund_scale_source_url": row["fund_scale_source_url"],
            "fund_manager": row["fund_manager"],
            "manager_qdii_quota_usd": from_cents(
                row["manager_qdii_quota_usd_cents"]
            ),
            "qdii_quota_date": row["qdii_quota_date"],
            "qdii_quota_source_url": row["qdii_quota_source_url"],
            "source_time": row["source_time"],
            "source": row["source"],
            "stale": bool(row["stale"]),
            "corrected": bool(row["corrected"]),
            "correction_note": row["correction_note"],
            "raw_json": row["raw_json"],
            "carried_fields": raw.get("carried_fields") or [],
        }

    def list_funds(self, active_only: bool = True) -> list[dict]:
        condition = "WHERE active=1" if active_only else ""
        with self.connect() as connection:
            rows = connection.execute(
                f"SELECT * FROM fund_watches {condition} ORDER BY created_at"
            ).fetchall()
            output = []
            for row in rows:
                latest = connection.execute(
                    """
                    SELECT * FROM fund_snapshots
                    WHERE fund_code=? ORDER BY source_time DESC, id DESC LIMIT 1
                    """,
                    (row["fund_code"],),
                ).fetchone()
                output.append(
                    {
                        "id": row["id"],
                        "fund_code": row["fund_code"],
                        "name": row["name"],
                        "exchange_code": row["exchange_code"],
                        "category": row["category"],
                        "benchmark": row["benchmark"],
                        "channel_daily_limit": from_cents(
                            row["channel_daily_limit_cents"]
                        ),
                        "limit_channel": row["limit_channel"],
                        "limit_source_url": row["limit_source_url"],
                        "limit_effective_date": row["limit_effective_date"],
                        "active": bool(row["active"]),
                        "created_at": row["created_at"],
                        "latest": self._snapshot_row(latest),
                    }
                )
        return output

    def get_fund(self, code: str) -> dict | None:
        return next(
            (
                fund
                for fund in self.list_funds(active_only=False)
                if fund["fund_code"] == code
            ),
            None,
        )

    def upsert_fund(self, values: dict[str, Any]) -> dict:
        now = utc_now()
        code = str(values["fund_code"])
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO fund_watches(
                    fund_code, name, exchange_code, category, benchmark,
                    channel_daily_limit_cents, limit_channel, limit_source_url,
                    limit_effective_date, active, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?)
                ON CONFLICT(fund_code) DO UPDATE SET
                    name=CASE WHEN excluded.name='' THEN fund_watches.name ELSE excluded.name END,
                    exchange_code=excluded.exchange_code,
                    category=excluded.category,
                    benchmark=excluded.benchmark,
                    channel_daily_limit_cents=COALESCE(
                        excluded.channel_daily_limit_cents,
                        fund_watches.channel_daily_limit_cents
                    ),
                    limit_channel=COALESCE(
                        excluded.limit_channel,
                        fund_watches.limit_channel
                    ),
                    limit_source_url=COALESCE(
                        excluded.limit_source_url,
                        fund_watches.limit_source_url
                    ),
                    limit_effective_date=COALESCE(
                        excluded.limit_effective_date,
                        fund_watches.limit_effective_date
                    ),
                    active=1,
                    updated_at=excluded.updated_at
                """,
                (
                    code,
                    values.get("name", ""),
                    values.get("exchange_code") or None,
                    values.get("category", "QDII"),
                    values.get("benchmark") or None,
                    to_cents(values.get("channel_daily_limit")),
                    values.get("limit_channel") or None,
                    values.get("limit_source_url") or None,
                    values.get("limit_effective_date") or None,
                    now,
                    now,
                ),
            )
        return self.get_fund(code) or {}

    def update_fund_name_if_empty(self, code: str, name: str) -> None:
        if not name:
            return
        with self.connect() as connection:
            connection.execute(
                """
                UPDATE fund_watches SET name=?, updated_at=?
                WHERE fund_code=? AND name=''
                """,
                (name, utc_now(), code),
            )

    def update_fund_benchmark(self, code: str, benchmark: str) -> None:
        if not benchmark:
            return
        with self.connect() as connection:
            connection.execute(
                """
                UPDATE fund_watches SET benchmark=?, updated_at=?
                WHERE fund_code=?
                """,
                (benchmark, utc_now(), code),
            )

    def update_fund_direct_limit(
        self,
        code: str,
        daily_limit: float,
        channel: str,
        source_url: str | None,
        effective_date: str | None,
    ) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                UPDATE fund_watches
                SET channel_daily_limit_cents=?,
                    limit_channel=?,
                    limit_source_url=?,
                    limit_effective_date=?,
                    updated_at=?
                WHERE fund_code=?
                  AND (
                    limit_effective_date IS NULL
                    OR (? IS NOT NULL AND limit_effective_date <= ?)
                  )
                """,
                (
                    to_cents(daily_limit),
                    channel,
                    source_url,
                    effective_date,
                    utc_now(),
                    code,
                    effective_date,
                    effective_date,
                ),
            )

    def deactivate_fund(self, code: str) -> bool:
        with self.connect() as connection:
            cursor = connection.execute(
                "UPDATE fund_watches SET active=0, updated_at=? WHERE fund_code=?",
                (utc_now(), code),
            )
        return cursor.rowcount > 0

    def save_fund_snapshot(self, values: dict[str, Any]) -> dict:
        with self.connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO fund_snapshots(
                    fund_code, business_date, estimate, nav, estimate_error,
                    market_price, iopv, premium, premium_basis, tracking_error,
                    tracking_error_source_url, tracking_error_as_of,
                    tracking_error_method, tracking_error_stale,
                    purchase_status, daily_limit_cents, fund_scale_cents,
                    fund_scale_source_url, fund_manager,
                    manager_qdii_quota_usd_cents, qdii_quota_date,
                    qdii_quota_source_url, source_time, source, stale,
                    corrected, correction_note, raw_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, NULL, ?)
                """,
                (
                    values["fund_code"],
                    values.get("business_date"),
                    values.get("estimate"),
                    values.get("nav"),
                    values.get("estimate_error"),
                    values.get("market_price"),
                    values.get("iopv"),
                    values.get("premium"),
                    values.get("premium_basis"),
                    values.get("tracking_error"),
                    values.get("tracking_error_source_url"),
                    values.get("tracking_error_as_of"),
                    values.get("tracking_error_method"),
                    1 if values.get("tracking_error_stale") else 0,
                    values.get("purchase_status"),
                    to_cents(values.get("daily_limit")),
                    to_cents(values.get("fund_scale")),
                    values.get("fund_scale_source_url"),
                    values.get("fund_manager"),
                    to_cents(values.get("manager_qdii_quota_usd")),
                    values.get("qdii_quota_date"),
                    values.get("qdii_quota_source_url"),
                    values.get("source_time", utc_now()),
                    values.get("source", "AKShare/Eastmoney"),
                    1 if values.get("stale") else 0,
                    json.dumps(
                        values.get("raw", {}),
                        ensure_ascii=False,
                        default=str,
                        separators=(",", ":"),
                    ),
                ),
            )
            row = connection.execute(
                "SELECT * FROM fund_snapshots WHERE id=?", (cursor.lastrowid,)
            ).fetchone()
        return self._snapshot_row(row) or {}

    def list_fund_history(self, code: str, limit: int = 365) -> list[dict]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM fund_snapshots WHERE fund_code=?
                ORDER BY source_time DESC, id DESC LIMIT ?
                """,
                (code, limit),
            ).fetchall()
        return [self._snapshot_row(row) or {} for row in rows]

    def latest_fund_snapshot(self, code: str) -> dict | None:
        history = self.list_fund_history(code, limit=1)
        return history[0] if history else None

    def correct_fund_snapshot(
        self, code: str, snapshot_id: int, values: dict[str, Any]
    ) -> dict | None:
        allowed = {
            "estimate": "estimate",
            "nav": "nav",
            "market_price": "market_price",
            "purchase_status": "purchase_status",
            "daily_limit": "daily_limit_cents",
            "fund_scale": "fund_scale_cents",
            "fund_manager": "fund_manager",
            "manager_qdii_quota_usd": "manager_qdii_quota_usd_cents",
            "qdii_quota_date": "qdii_quota_date",
        }
        assignments = []
        params: list[Any] = []
        for key, column in allowed.items():
            if key in values and values[key] is not None:
                assignments.append(f"{column}=?")
                params.append(
                    to_cents(values[key])
                    if key
                    in {"daily_limit", "fund_scale", "manager_qdii_quota_usd"}
                    else values[key]
                )
        assignments.extend(["corrected=1", "correction_note=?"])
        params.append(values["correction_note"])
        params.extend([snapshot_id, code])
        with self.connect() as connection:
            connection.execute(
                f"""
                UPDATE fund_snapshots SET {", ".join(assignments)}
                WHERE id=? AND fund_code=?
                """,
                params,
            )
            row = connection.execute(
                "SELECT * FROM fund_snapshots WHERE id=? AND fund_code=?",
                (snapshot_id, code),
            ).fetchone()
            if row:
                premium, basis = premium_rate(
                    row["market_price"], row["iopv"], row["nav"]
                )
                estimate_error = (
                    (row["estimate"] - row["nav"]) / row["nav"] * 100
                    if row["estimate"] is not None
                    and row["nav"] not in (None, 0)
                    else row["estimate_error"]
                )
                connection.execute(
                    """
                    UPDATE fund_snapshots SET premium=?, premium_basis=?,
                        estimate_error=? WHERE id=?
                    """,
                    (premium, basis, estimate_error, snapshot_id),
                )
                row = connection.execute(
                    "SELECT * FROM fund_snapshots WHERE id=? AND fund_code=?",
                    (snapshot_id, code),
                ).fetchone()
        return self._snapshot_row(row)

    def record_status_change(
        self,
        code: str,
        old_status: str | None,
        new_status: str | None,
        old_limit: float | None,
        new_limit: float | None,
        relaxed: bool,
    ) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO fund_status_changes(
                    fund_code, old_status, new_status, old_limit_cents,
                    new_limit_cents, relaxed, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    code,
                    old_status,
                    new_status,
                    to_cents(old_limit),
                    to_cents(new_limit),
                    1 if relaxed else 0,
                    utc_now(),
                ),
            )

    def create_alert(
        self,
        *,
        code: str,
        title: str,
        message: str,
        event_type: str,
        dedupe_key: str,
    ) -> bool:
        with self.connect() as connection:
            cursor = connection.execute(
                """
                INSERT OR IGNORE INTO alerts(
                    fund_code, title, message, event_type,
                    dedupe_key, created_at, read_at
                ) VALUES (?, ?, ?, ?, ?, ?, NULL)
                """,
                (code, title, message, event_type, dedupe_key, utc_now()),
            )
        return cursor.rowcount > 0

    def list_alerts(self, limit: int = 100) -> list[dict]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM alerts ORDER BY created_at DESC, id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def mark_alerts_read(self, ids: Sequence[int] | None = None) -> int:
        with self.connect() as connection:
            if ids:
                placeholders = ",".join("?" for _ in ids)
                cursor = connection.execute(
                    f"""
                    UPDATE alerts SET read_at=?
                    WHERE read_at IS NULL AND id IN ({placeholders})
                    """,
                    [utc_now(), *ids],
                )
            else:
                cursor = connection.execute(
                    "UPDATE alerts SET read_at=? WHERE read_at IS NULL",
                    (utc_now(),),
                )
        return cursor.rowcount

    def start_sync_run(self, mode: str, total: int) -> int:
        with self.connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO sync_runs(
                    mode, started_at, status, items_total, items_succeeded
                ) VALUES (?, ?, 'running', ?, 0)
                """,
                (mode, utc_now(), total),
            )
        return int(cursor.lastrowid)

    def finish_sync_run(
        self, run_id: int, *, succeeded: int, error: str | None = None
    ) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                UPDATE sync_runs SET finished_at=?, status=?,
                    items_succeeded=?, error=? WHERE id=?
                """,
                (
                    utc_now(),
                    "failed" if error else "success",
                    succeeded,
                    error,
                    run_id,
                ),
            )

    def last_sync_run(self) -> dict | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM sync_runs ORDER BY started_at DESC, id DESC LIMIT 1"
            ).fetchone()
        return dict(row) if row else None

    def export_data(self) -> dict[str, Any]:
        tables = (
            "asset_snapshots",
            "fund_watches",
            "fund_snapshots",
            "fund_status_changes",
            "alerts",
            "sync_runs",
            "settings",
        )
        result: dict[str, Any] = {
            "format": "fire-qdii-backup-v1",
            "exported_at": utc_now(),
        }
        with self.connect() as connection:
            for table in tables:
                result[table] = [
                    dict(row)
                    for row in connection.execute(f"SELECT * FROM {table}").fetchall()
                ]
        return result

    def export_csv(self) -> str:
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(
            [
                "record_type",
                "code_or_date",
                "name_or_note",
                "status",
                "daily_limit_cny",
                "channel_daily_limit_cny",
                "limit_channel",
                "limit_source_url",
                "limit_effective_date",
                "fund_scale_cny",
                "fund_scale_source_url",
                "fund_manager",
                "manager_qdii_quota_usd",
                "qdii_quota_date",
                "qdii_quota_source_url",
                "nav",
                "estimate",
                "market_price",
                "premium_pct",
                "published_tracking_error_pct",
                "tracking_error_as_of",
                "tracking_error_source_url",
                "tracking_error_stale",
                "source_time",
            ]
        )
        for item in self.list_asset_snapshots(limit=100000):
            writer.writerow(
                [
                    "asset_snapshot",
                    item["snapshot_date"],
                    item["note"],
                    "",
                    "",
                    "",
                    "",
                    "",
                    "",
                    item["updated_at"],
                ]
            )
        for fund in self.list_funds(active_only=False):
            for item in self.list_fund_history(fund["fund_code"], limit=100000):
                writer.writerow(
                    [
                        "fund_snapshot",
                        fund["fund_code"],
                        fund["name"],
                        item["purchase_status"],
                        item["daily_limit"],
                        fund["channel_daily_limit"],
                        fund["limit_channel"],
                        fund["limit_source_url"],
                        fund["limit_effective_date"],
                        item["fund_scale"],
                        item["fund_scale_source_url"],
                        item["fund_manager"],
                        item["manager_qdii_quota_usd"],
                        item["qdii_quota_date"],
                        item["qdii_quota_source_url"],
                        item["nav"],
                        item["estimate"],
                        item["market_price"],
                        item["premium"],
                        item["tracking_error"],
                        item["tracking_error_as_of"],
                        item["tracking_error_source_url"],
                        item["tracking_error_stale"],
                        item["source_time"],
                    ]
                )
        return output.getvalue()

    def restore_data(self, payload: dict[str, Any]) -> dict[str, int]:
        if payload.get("format") != "fire-qdii-backup-v1":
            raise ValueError("不支持的备份格式")
        restored = {"assets": 0, "funds": 0, "snapshots": 0, "alerts": 0}
        for row in payload.get("asset_snapshots", []):
            values = {
                "snapshot_date": row["snapshot_date"],
                "note": row.get("note", ""),
            }
            for key in ASSET_KEYS:
                values[key] = from_cents(row.get(f"{key}_cents")) or 0
            self.save_asset_snapshot(values)
            restored["assets"] += 1
        for row in payload.get("fund_watches", []):
            self.upsert_fund(
                {
                    **row,
                    "channel_daily_limit": from_cents(
                        row.get("channel_daily_limit_cents")
                    ),
                }
            )
            if not row.get("active", 1):
                self.deactivate_fund(row["fund_code"])
            restored["funds"] += 1
        with self.connect() as connection:
            for row in payload.get("fund_snapshots", []):
                columns = [
                    "fund_code",
                    "business_date",
                    "estimate",
                    "nav",
                    "estimate_error",
                    "market_price",
                    "iopv",
                    "premium",
                    "premium_basis",
                    "tracking_error",
                    "tracking_error_source_url",
                    "tracking_error_as_of",
                    "tracking_error_method",
                    "tracking_error_stale",
                    "purchase_status",
                    "daily_limit_cents",
                    "fund_scale_cents",
                    "fund_scale_source_url",
                    "fund_manager",
                    "manager_qdii_quota_usd_cents",
                    "qdii_quota_date",
                    "qdii_quota_source_url",
                    "source_time",
                    "source",
                    "stale",
                    "corrected",
                    "correction_note",
                    "raw_json",
                ]
                connection.execute(
                    f"""
                    INSERT INTO fund_snapshots({", ".join(columns)})
                    VALUES ({", ".join("?" for _ in columns)})
                    """,
                    [row.get(column) for column in columns],
                )
                restored["snapshots"] += 1
            for row in payload.get("alerts", []):
                connection.execute(
                    """
                    INSERT OR IGNORE INTO alerts(
                        fund_code, title, message, event_type,
                        dedupe_key, created_at, read_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        row["fund_code"],
                        row["title"],
                        row["message"],
                        row["event_type"],
                        row["dedupe_key"],
                        row["created_at"],
                        row.get("read_at"),
                    ),
                )
                restored["alerts"] += 1
        return restored
