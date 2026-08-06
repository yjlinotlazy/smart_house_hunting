from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class StartScanRequest(StrictModel):
    force_refresh: bool = False


class SourceRunView(StrictModel):
    source: str
    status: str
    started_at: datetime | None
    completed_at: datetime | None
    counters: dict[str, object]
    error_summary: str | None


class ScanView(StrictModel):
    id: int
    status: str
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    counters: dict[str, object]
    error_summary: str | None
    source_runs: list[SourceRunView]


class StartScanResponse(StrictModel):
    job: ScanView
    reused_active: bool


class ScanStatusResponse(StrictModel):
    latest_attempt: ScanView | None
    last_success: ScanView | None
    active_job: ScanView | None
