from __future__ import annotations

import json
import platform
import subprocess
import threading
from datetime import date
from typing import Any

from .database import Database
from .providers import AKShareProvider


def _opened(status: str | None) -> bool:
    return bool(
        status
        and "暂停" not in status
        and ("开放" in status or "限" in status)
    )


def _is_relaxed(
    old_status: str | None,
    new_status: str | None,
    old_limit: float | None,
    new_limit: float | None,
) -> tuple[bool, str | None]:
    if new_limit is not None and new_limit > 0 and (
        old_limit is None or new_limit > old_limit
    ):
        return True, "limit_increased"
    if _opened(new_status) and not _opened(old_status):
        return True, "purchase_reopened"
    return False, None


def _carry_forward(collected: dict[str, Any], previous: dict | None) -> dict:
    if not previous:
        return collected
    carry_fields = (
        "business_date",
        "estimate",
        "nav",
        "estimate_error",
        "market_price",
        "iopv",
        "premium",
        "premium_basis",
        "tracking_error",
        "purchase_status",
        "daily_limit",
    )
    for field in carry_fields:
        if collected.get(field) is None:
            collected[field] = previous.get(field)
    return collected


class SyncService:
    def __init__(
        self,
        database: Database,
        provider: AKShareProvider | None = None,
    ):
        self.database = database
        self.provider = provider or AKShareProvider()
        self.lock = threading.Lock()

    def run(self, mode: str = "full") -> dict[str, Any]:
        if mode not in {"morning", "evening", "full"}:
            raise ValueError("未知同步模式")
        if not self.lock.acquire(blocking=False):
            return {"ok": False, "message": "已有同步任务正在进行"}
        watches = self.database.list_funds()
        run_id = self.database.start_sync_run(mode, len(watches))
        succeeded = 0
        try:
            if not watches:
                self.database.finish_sync_run(run_id, succeeded=0)
                return {"ok": True, "message": "尚未添加关注基金"}

            try:
                collected_by_code = self.provider.collect(watches, mode=mode)
            except Exception as exc:
                collected_by_code = {
                    watch["fund_code"]: {
                        "fund_code": watch["fund_code"],
                        "source_time": self._now(),
                        "source": self.provider.name,
                        "errors": [str(exc)],
                        "raw": {},
                    }
                    for watch in watches
                }

            for watch in watches:
                code = watch["fund_code"]
                previous = self.database.latest_fund_snapshot(code)
                collected = dict(collected_by_code.get(code, {}))
                errors = collected.pop("errors", ["上游未返回该基金"])
                fresh_fields = (
                    "purchase_status",
                    "daily_limit",
                    "estimate",
                    "nav",
                    "market_price",
                    "iopv",
                )
                has_fresh_data = any(
                    collected.get(field) is not None for field in fresh_fields
                )
                collected = _carry_forward(collected, previous)
                collected["fund_code"] = code
                collected["stale"] = not has_fresh_data
                collected.setdefault("source_time", self._now())
                collected.setdefault("source", self.provider.name)
                collected.setdefault("raw", {"errors": errors})
                if errors:
                    collected["raw"] = {
                        **(collected.get("raw") or {}),
                        "errors": errors,
                    }

                new_status = collected.get("purchase_status")
                new_limit = collected.get("daily_limit")
                old_status = previous.get("purchase_status") if previous else None
                old_limit = previous.get("daily_limit") if previous else None
                changed = previous and (
                    new_status != old_status or new_limit != old_limit
                )
                relaxed, event_type = _is_relaxed(
                    old_status, new_status, old_limit, new_limit
                )

                snapshot = self.database.save_fund_snapshot(collected)
                if collected.get("name"):
                    self.database.update_fund_name_if_empty(
                        code, collected["name"]
                    )
                if changed:
                    self.database.record_status_change(
                        code,
                        old_status,
                        new_status,
                        old_limit,
                        new_limit,
                        relaxed,
                    )
                if previous and relaxed and event_type:
                    fund_name = watch.get("name") or collected.get("name") or code
                    title = f"{fund_name} 额度放宽"
                    message = self._alert_message(
                        old_status, new_status, old_limit, new_limit
                    )
                    dedupe_key = "|".join(
                        [
                            code,
                            str(snapshot.get("business_date") or date.today()),
                            event_type,
                            str(old_status),
                            str(new_status),
                            str(old_limit),
                            str(new_limit),
                        ]
                    )
                    created = self.database.create_alert(
                        code=code,
                        title=title,
                        message=message,
                        event_type=event_type,
                        dedupe_key=dedupe_key,
                    )
                    if created and self.database.get_settings()[
                        "notifications_enabled"
                    ]:
                        self._notify(title, message)
                if has_fresh_data:
                    succeeded += 1

            error = None if succeeded else "所有数据源均未返回有效数据"
            self.database.finish_sync_run(
                run_id, succeeded=succeeded, error=error
            )
            if error:
                return {
                    "ok": False,
                    "message": "同步未获得新数据，已保留上一条有效记录",
                }
            return {
                "ok": True,
                "message": f"同步完成：{succeeded}/{len(watches)} 只基金已更新",
            }
        except Exception as exc:
            self.database.finish_sync_run(
                run_id, succeeded=succeeded, error=str(exc)
            )
            raise
        finally:
            self.lock.release()

    @staticmethod
    def _now() -> str:
        from .database import utc_now

        return utc_now()

    @staticmethod
    def _alert_message(
        old_status: str | None,
        new_status: str | None,
        old_limit: float | None,
        new_limit: float | None,
    ) -> str:
        parts = []
        if old_status != new_status:
            parts.append(f"申购状态：{old_status or '未公布'} → {new_status or '未公布'}")
        if old_limit != new_limit:
            old_text = "未公布" if old_limit is None else f"¥{old_limit:,.0f}"
            new_text = "未公布" if new_limit is None else f"¥{new_limit:,.0f}"
            parts.append(f"单日额度：{old_text} → {new_text}")
        return "；".join(parts) or "申购条件已放宽"

    @staticmethod
    def _notify(title: str, message: str) -> None:
        if platform.system() != "Darwin":
            return
        safe_title = json.dumps(title, ensure_ascii=False)
        safe_message = json.dumps(message, ensure_ascii=False)
        script = f"display notification {safe_message} with title {safe_title}"
        try:
            subprocess.run(
                ["osascript", "-e", script],
                check=False,
                timeout=5,
                capture_output=True,
            )
        except (OSError, subprocess.SubprocessError):
            # In-app alerts remain the source of truth.
            return
