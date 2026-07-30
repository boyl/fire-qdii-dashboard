from __future__ import annotations

import json
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Literal
from zoneinfo import ZoneInfo

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from fastapi import FastAPI, HTTPException
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator, model_validator

from .calculations import (
    ASSET_KEYS,
    portfolio_summary,
    stress_portfolio,
    sustainability_runway,
)
from .config import DIST_DIR, TIMEZONE
from .database import Database
from .providers import AKShareProvider
from .sync import SyncService

database = Database()
provider = AKShareProvider()
sync_service = SyncService(database, provider)
scheduler = BackgroundScheduler(timezone=TIMEZONE, daemon=True)


class AssetPayload(BaseModel):
    snapshot_date: str
    cash: float = Field(ge=0)
    short_bond: float = Field(ge=0)
    long_bond: float = Field(ge=0)
    nasdaq100: float = Field(ge=0)
    gold: float = Field(ge=0)
    digital: float = Field(ge=0)
    note: str = Field(default="", max_length=200)

    @field_validator("snapshot_date")
    @classmethod
    def validate_date(cls, value: str) -> str:
        datetime.strptime(value, "%Y-%m-%d")
        return value


class StressPayload(BaseModel):
    scenarios: list[dict[str, Any]] = Field(min_length=1, max_length=12)


class SustainabilityPayload(BaseModel):
    annual_spending: list[float] = Field(min_length=1, max_length=20)
    real_return: float = Field(ge=-100, le=100)
    initial_assets: float | None = Field(default=None, ge=0)

    @field_validator("annual_spending")
    @classmethod
    def validate_spending(cls, values: list[float]) -> list[float]:
        if any(value < 0 for value in values):
            raise ValueError("年度支出不能为负数")
        return values


class SettingsPayload(BaseModel):
    target_equity: float = Field(gt=0, lt=100)
    rebalance_band: float = Field(gt=0, le=40)
    morning_sync: str
    evening_sync: str
    notifications_enabled: bool

    @field_validator("morning_sync", "evening_sync")
    @classmethod
    def validate_time(cls, value: str) -> str:
        datetime.strptime(value, "%H:%M")
        return value

    @model_validator(mode="after")
    def validate_band(self) -> "SettingsPayload":
        if (
            self.target_equity - self.rebalance_band < 0
            or self.target_equity + self.rebalance_band > 100
        ):
            raise ValueError("目标与缓冲带必须落在 0%–100% 之间")
        return self


class FundPayload(BaseModel):
    fund_code: str = Field(pattern=r"^\d{6}$")
    name: str = Field(default="", max_length=80)
    exchange_code: str | None = Field(
        default=None, pattern=r"^\d{6}$"
    )
    category: str = Field(default="QDII", max_length=30)
    benchmark: str | None = Field(default=None, max_length=80)
    channel_daily_limit: float | None = Field(default=None, ge=0)
    limit_channel: str | None = Field(default=None, max_length=80)
    limit_source_url: str | None = Field(default=None, max_length=500)
    limit_effective_date: str | None = Field(
        default=None, pattern=r"^\d{4}-\d{2}-\d{2}$"
    )

    @field_validator(
        "exchange_code",
        "benchmark",
        "limit_channel",
        "limit_source_url",
        "limit_effective_date",
        mode="before",
    )
    @classmethod
    def empty_string_to_none(cls, value: Any) -> Any:
        if isinstance(value, str) and not value.strip():
            return None
        return value


class SyncPayload(BaseModel):
    mode: Literal["morning", "evening", "full"] = "full"


class AlertReadPayload(BaseModel):
    ids: list[int] | None = None


class CorrectionPayload(BaseModel):
    estimate: float | None = Field(default=None, ge=0)
    nav: float | None = Field(default=None, ge=0)
    market_price: float | None = Field(default=None, ge=0)
    daily_limit: float | None = Field(default=None, ge=0)
    fund_scale: float | None = Field(default=None, ge=0)
    manager_qdii_quota_usd: float | None = Field(default=None, ge=0)
    fund_manager: str | None = Field(default=None, max_length=100)
    qdii_quota_date: str | None = Field(default=None, max_length=10)
    purchase_status: str | None = Field(default=None, max_length=50)
    correction_note: str = Field(min_length=2, max_length=300)


def configure_scheduler() -> None:
    settings = database.get_settings()
    scheduler.remove_all_jobs()
    for job_id, mode, value in (
        ("morning-sync", "morning", settings["morning_sync"]),
        ("evening-sync", "evening", settings["evening_sync"]),
    ):
        hour, minute = (int(part) for part in value.split(":"))
        scheduler.add_job(
            sync_service.run,
            CronTrigger(
                day_of_week="mon-fri",
                hour=hour,
                minute=minute,
                timezone=TIMEZONE,
            ),
            args=[mode],
            id=job_id,
            max_instances=1,
            coalesce=True,
            misfire_grace_time=60 * 60 * 4,
            replace_existing=True,
        )

    last_sync = database.last_sync_run()
    today = datetime.now(ZoneInfo(TIMEZONE)).date()
    last_sync_date = (
        datetime.fromisoformat(last_sync["started_at"])
        .astimezone(ZoneInfo(TIMEZONE))
        .date()
        if last_sync
        else None
    )
    if database.list_funds() and (
        not last_sync or last_sync_date != today
    ):
        scheduler.add_job(
            sync_service.run,
            "date",
            run_date=datetime.now() + timedelta(seconds=5),
            args=["full"],
            id="startup-catchup",
            replace_existing=True,
        )


@asynccontextmanager
async def lifespan(_: FastAPI):
    database.initialize()
    configure_scheduler()
    scheduler.start()
    try:
        yield
    finally:
        scheduler.shutdown(wait=False)


app = FastAPI(
    title="FIRE 资产配置与 QDII 记录器",
    version="1.0.0",
    docs_url="/api/docs",
    redoc_url=None,
    lifespan=lifespan,
)


@app.get("/api/settings")
def get_settings():
    return database.get_settings()


@app.put("/api/settings")
def save_settings(payload: SettingsPayload):
    settings = database.update_settings(payload.model_dump())
    configure_scheduler()
    return settings


@app.get("/api/assets")
def list_assets():
    return database.list_asset_snapshots()


@app.post("/api/assets")
def save_assets(payload: AssetPayload):
    return database.save_asset_snapshot(payload.model_dump())


@app.get("/api/assets/history")
def asset_history():
    return database.list_asset_snapshots()


@app.get("/api/portfolio/summary")
def get_portfolio_summary():
    snapshot = database.latest_asset_snapshot()
    settings = database.get_settings()
    amounts = (
        {key: snapshot[key] for key in ASSET_KEYS}
        if snapshot
        else {key: 0 for key in ASSET_KEYS}
    )
    result = portfolio_summary(
        amounts,
        settings["target_equity"],
        settings["rebalance_band"],
    )
    result["snapshot"] = snapshot
    return result


@app.post("/api/portfolio/stress")
def run_stress(payload: StressPayload):
    snapshot = database.latest_asset_snapshot()
    if not snapshot:
        raise HTTPException(status_code=409, detail="请先保存资产快照")
    amounts = {key: snapshot[key] for key in ASSET_KEYS}
    return stress_portfolio(amounts, payload.scenarios)


@app.post("/api/sustainability")
def run_sustainability(payload: SustainabilityPayload):
    initial_assets = payload.initial_assets
    if initial_assets is None:
        snapshot = database.latest_asset_snapshot()
        if not snapshot:
            raise HTTPException(status_code=409, detail="请先保存资产快照")
        initial_assets = sum(snapshot[key] for key in ASSET_KEYS)
    return sustainability_runway(
        initial_assets,
        payload.annual_spending,
        payload.real_return,
    )


@app.get("/api/funds")
def list_funds():
    return database.list_funds()


@app.post("/api/funds")
def add_fund(payload: FundPayload):
    return database.upsert_fund(payload.model_dump())


@app.delete("/api/funds/{code}")
def delete_fund(code: str):
    if not database.deactivate_fund(code):
        raise HTTPException(status_code=404, detail="未找到该基金")
    return {"ok": True}


@app.get("/api/funds/{code}/history")
def fund_history(code: str):
    if not database.get_fund(code):
        raise HTTPException(status_code=404, detail="未找到该基金")
    return database.list_fund_history(code)


@app.patch("/api/funds/{code}/snapshots/{snapshot_id}")
def correct_snapshot(code: str, snapshot_id: int, payload: CorrectionPayload):
    values = payload.model_dump(exclude_unset=True)
    result = database.correct_fund_snapshot(code, snapshot_id, values)
    if not result:
        raise HTTPException(status_code=404, detail="未找到该记录")
    return result


@app.post("/api/sync")
async def sync_funds(payload: SyncPayload):
    result = await run_in_threadpool(sync_service.run, payload.mode)
    return JSONResponse(
        result,
        status_code=200 if result.get("ok") else 503,
    )


@app.get("/api/alerts")
def list_alerts():
    return database.list_alerts()


@app.post("/api/alerts/read")
def read_alerts(payload: AlertReadPayload):
    return {"updated": database.mark_alerts_read(payload.ids)}


@app.get("/api/health")
def health():
    jobs = [
        {
            "id": job.id,
            "next_run": job.next_run_time.isoformat()
            if job.next_run_time
            else None,
        }
        for job in scheduler.get_jobs()
    ]
    return {
        "status": "ok",
        "database": database.health(),
        "provider": provider.name,
        "scheduler_running": scheduler.running,
        "next_jobs": jobs,
        "last_sync": database.last_sync_run(),
    }


@app.get("/api/export/json")
def export_json():
    content = json.dumps(
        database.export_data(), ensure_ascii=False, indent=2
    )
    return Response(
        content=content,
        media_type="application/json",
        headers={
            "Content-Disposition": 'attachment; filename="fire-qdii-backup.json"'
        },
    )


@app.get("/api/export/csv")
def export_csv():
    return Response(
        content="\ufeff" + database.export_csv(),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": 'attachment; filename="fire-qdii-records.csv"'
        },
    )


@app.post("/api/restore")
def restore(payload: dict[str, Any]):
    try:
        restored = database.restore_data(payload)
    except (KeyError, TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True, "restored": restored}


if DIST_DIR.exists():
    assets_dir = DIST_DIR / "assets"
    if assets_dir.exists():
        app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")


@app.get("/{path:path}", include_in_schema=False)
def serve_frontend(path: str):
    requested = (DIST_DIR / path).resolve()
    if (
        path
        and requested.is_relative_to(DIST_DIR.resolve())
        and requested.is_file()
    ):
        return FileResponse(requested)
    index = DIST_DIR / "index.html"
    if not index.exists():
        raise HTTPException(
            status_code=503,
            detail="前端尚未构建，请先运行安装脚本",
        )
    return FileResponse(index)
