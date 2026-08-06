from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator

from fastapi import APIRouter, Header, HTTPException, Request, status
from fastapi.responses import StreamingResponse

from smart_house_hunting.config.loader import ConfigError
from smart_house_hunting.jobs.manager import TERMINAL_STATUSES, ScanManager, ScanStartError
from smart_house_hunting.jobs.models import (
    ScanStatusResponse,
    ScanView,
    StartScanRequest,
    StartScanResponse,
)

router = APIRouter(prefix="/api/scans", tags=["scans"])


def _manager(request: Request) -> ScanManager:
    return request.app.state.scan_manager


@router.get("/status")
async def get_scan_status(request: Request) -> ScanStatusResponse:
    return _manager(request).status()


@router.post("", status_code=status.HTTP_202_ACCEPTED)
async def start_scan(payload: StartScanRequest, request: Request) -> StartScanResponse:
    try:
        return await _manager(request).start(force_refresh=payload.force_refresh)
    except ScanStartError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except ConfigError as error:
        raise HTTPException(status_code=500, detail=str(error)) from error


@router.get("/{job_id}")
async def get_scan(job_id: int, request: Request) -> ScanView:
    job = _manager(request).job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Scan not found")
    return job


@router.get("/{job_id}/events")
async def scan_events(
    job_id: int,
    request: Request,
    last_event_id: int = Header(default=0, alias="Last-Event-ID"),
) -> StreamingResponse:
    manager = _manager(request)
    if manager.job(job_id) is None:
        raise HTTPException(status_code=404, detail="Scan not found")

    async def stream() -> AsyncIterator[str]:
        cursor = last_event_id
        while True:
            if await request.is_disconnected():
                return
            events = manager.events_after(job_id, cursor)
            for event in events:
                cursor = event.id
                data = json.dumps(
                    {
                        "id": event.id,
                        "event_type": event.event_type,
                        "payload": event.payload,
                    },
                    separators=(",", ":"),
                )
                yield f"id: {event.id}\ndata: {data}\n\n"
            job = manager.job(job_id)
            if job is None or (job.status in TERMINAL_STATUSES and not events):
                return
            if not events:
                yield ": keepalive\n\n"
            await asyncio.sleep(0.25)

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
