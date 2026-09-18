from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import distinct, func, select
from sqlalchemy.orm import Session, joinedload, selectinload, sessionmaker

from smart_house_hunting.config.loader import load_config
from smart_house_hunting.db.models import (
    Listing,
    ScanJob,
    ScanObservation,
    ScanProgressEvent,
    ScanSourceRun,
)
from smart_house_hunting.jobs.models import (
    ScanStatusResponse,
    ScanView,
    SourceRunView,
    StartScanResponse,
)
from smart_house_hunting.services.comparables import refresh_sold_comparables
from smart_house_hunting.services.ingest import IngestCounters, ingest_candidate
from smart_house_hunting.sources import (
    NormalizedListing,
    RealtorSourceAdapter,
    RedfinSourceAdapter,
    ScanRequest,
    SourceAdapter,
    ZillowSourceAdapter,
)

ACTIVE_STATUSES = ("queued", "running")
SUCCESS_STATUSES = ("success", "partial_success")
TERMINAL_STATUSES = ("partial_success", "success", "failed", "interrupted")
logger = logging.getLogger(__name__)


class ScanStartError(RuntimeError):
    pass


def _now() -> datetime:
    return datetime.now(UTC)


def _utc(value: datetime | None) -> datetime | None:
    if value is None or value.tzinfo is not None:
        return value
    return value.replace(tzinfo=UTC)


def _view(job: ScanJob) -> ScanView:
    return ScanView(
        id=job.id,
        status=job.status,
        created_at=_utc(job.created_at),
        started_at=_utc(job.started_at),
        completed_at=_utc(job.completed_at),
        counters=job.counters,
        error_summary=job.error_summary,
        source_runs=[
            SourceRunView(
                source=run.source,
                status=run.status,
                started_at=_utc(run.started_at),
                completed_at=_utc(run.completed_at),
                counters=run.counters,
                error_summary=run.error_summary,
            )
            for run in sorted(job.source_runs, key=lambda item: item.source)
        ],
    )


class ScanManager:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        config_path: Path,
        adapters: Sequence[SourceAdapter] | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._config_path = config_path
        self._custom_adapters = adapters is not None
        self._adapters = (
            list(adapters)
            if adapters is not None
            else [RedfinSourceAdapter(), ZillowSourceAdapter(), RealtorSourceAdapter()]
        )
        self._start_lock = asyncio.Lock()
        self._tasks: dict[int, asyncio.Task[None]] = {}

    def recover_interrupted(self) -> int:
        recovered = 0
        with self._session_factory.begin() as session:
            jobs = session.scalars(
                select(ScanJob)
                .options(selectinload(ScanJob.source_runs))
                .where(ScanJob.status.in_(ACTIVE_STATUSES))
            ).all()
            for job in jobs:
                job.status = "interrupted"
                job.completed_at = _now()
                job.error_summary = "Server restarted before the scan completed"
                for run in job.source_runs:
                    if run.status in ACTIVE_STATUSES:
                        run.status = "failed"
                        run.completed_at = _now()
                        run.error_summary = "Server restarted before the source completed"
                self._event(session, job.id, "interrupted", {"reason": "server_restart"})
                recovered += 1
        return recovered

    async def shutdown(self) -> None:
        tasks = list(self._tasks.values())
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def start(self, *, force_refresh: bool = False) -> StartScanResponse:
        async with self._start_lock:
            config = load_config(self._config_path)
            if not config.search.municipalities:
                raise ScanStartError("Configure at least one Massachusetts city or town")
            adapters = self._enabled_adapters(config)
            if not adapters:
                raise ScanStartError("Enable at least one listing source")
            fingerprint = self._fingerprint(config, adapters)
            with self._session_factory.begin() as session:
                active = session.scalar(
                    select(ScanJob)
                    .options(selectinload(ScanJob.source_runs))
                    .where(ScanJob.status.in_(ACTIVE_STATUSES))
                    .order_by(ScanJob.id.desc())
                )
                if active is not None:
                    return StartScanResponse(job=_view(active), reused_active=True)

                job = ScanJob(
                    status="queued",
                    config_fingerprint=fingerprint,
                    created_at=_now(),
                    counters={},
                )
                job.source_runs = [
                    ScanSourceRun(
                        source=adapter.name,
                        status="queued",
                        parser_version=adapter.parser_version,
                        counters={},
                    )
                    for adapter in adapters
                ]
                session.add(job)
                session.flush()
                self._event(
                    session,
                    job.id,
                    "queued",
                    {"sources": len(adapters), "force_refresh": force_refresh},
                )
                job_id = job.id
                response = StartScanResponse(job=_view(job), reused_active=False)

            logger.info(
                "scan queued job_id=%s sources=%s towns=%s force_refresh=%s",
                job_id,
                ",".join(adapter.name for adapter in adapters),
                ",".join(config.search.municipalities),
                force_refresh,
            )

            task = asyncio.create_task(
                self._run(job_id, adapters, force_refresh=force_refresh),
                name=f"scan-{job_id}",
            )
            self._tasks[job_id] = task
            task.add_done_callback(lambda _task: self._tasks.pop(job_id, None))
            return response

    def status(self) -> ScanStatusResponse:
        with self._session_factory() as session:
            base = select(ScanJob).options(selectinload(ScanJob.source_runs))
            latest = session.scalar(base.order_by(ScanJob.id.desc()))
            success = session.scalar(
                base.where(ScanJob.status.in_(SUCCESS_STATUSES)).order_by(ScanJob.id.desc())
            )
            active = session.scalar(
                base.where(ScanJob.status.in_(ACTIVE_STATUSES)).order_by(ScanJob.id.desc())
            )
            return ScanStatusResponse(
                latest_attempt=_view(latest) if latest else None,
                last_success=_view(success) if success else None,
                active_job=_view(active) if active else None,
            )

    def job(self, job_id: int) -> ScanView | None:
        with self._session_factory() as session:
            job = session.scalar(
                select(ScanJob)
                .options(selectinload(ScanJob.source_runs))
                .where(ScanJob.id == job_id)
            )
            return _view(job) if job else None

    def events_after(self, job_id: int, event_id: int) -> list[ScanProgressEvent]:
        with self._session_factory() as session:
            return list(
                session.scalars(
                    select(ScanProgressEvent)
                    .where(
                        ScanProgressEvent.scan_job_id == job_id,
                        ScanProgressEvent.id > event_id,
                    )
                    .order_by(ScanProgressEvent.id)
                ).all()
            )

    async def _run(
        self,
        job_id: int,
        adapters: Sequence[SourceAdapter],
        *,
        force_refresh: bool,
    ) -> None:
        try:
            config = load_config(self._config_path)
            base_request = ScanRequest(
                municipalities=config.search.municipalities,
                included_property_types=config.search.included_property_types,
                minimum_bedrooms=config.search.minimum_bedrooms,
                minimum_bathrooms=config.search.minimum_bathrooms,
                maximum_price=config.search.maximum_price,
                retain_source_payloads=config.logging.retain_source_payloads,
                force_refresh=force_refresh,
            )
            self._set_job_running(job_id)
            logger.info("scan started job_id=%s", job_id)
            successes = 0
            failures = 0
            total_candidates = 0
            sold_records_total = 0
            ingest_totals = IngestCounters()
            for adapter in adapters:
                source_name = adapter.name
                source_counters = IngestCounters()
                emitted: set[tuple[str, str]] = set()
                self._set_source_running(job_id, source_name)
                logger.info("source started job_id=%s source=%s", job_id, source_name)
                request = base_request.model_copy(
                    update={"tracked_listings": self._tracked_listings(source_name)}
                )

                async def progress(
                    event_type: str,
                    payload: dict[str, object],
                    source: str = source_name,
                ) -> None:
                    with self._session_factory.begin() as session:
                        self._event(
                            session,
                            job_id,
                            "source_progress",
                            {"source": source, "step": event_type, **payload},
                        )

                async def on_candidate(
                    candidate: NormalizedListing,
                    emitted_for_source: set[tuple[str, str]] = emitted,
                    counters_for_source: IngestCounters = source_counters,
                ) -> None:
                    nonlocal total_candidates
                    key = (candidate.source, candidate.source_listing_id)
                    if key in emitted_for_source:
                        return
                    counters = self._ingest_candidates(
                        job_id,
                        [candidate],
                        config.search.municipalities,
                    )
                    emitted_for_source.add(key)
                    total_candidates += 1
                    counters_for_source.add(counters)
                    ingest_totals.add(counters)
                    logger.info(
                        "candidate persisted job_id=%s source=%s listing_id=%s "
                        "properties_created=%s states_created=%s",
                        job_id,
                        candidate.source,
                        candidate.source_listing_id,
                        counters.properties_created,
                        counters.states_created,
                    )

                try:
                    candidates = await adapter.scan(request, progress, on_candidate)
                    for candidate in candidates:
                        await on_candidate(candidate)
                    sold_scanner = getattr(adapter, "scan_sold", None)
                    if callable(sold_scanner):
                        sold_candidates = await sold_scanner(request, progress)
                        for sold_candidate in sold_candidates:
                            self._ingest_candidates(
                                job_id,
                                [sold_candidate],
                                config.search.municipalities,
                            )
                            sold_records_total += 1
                        logger.info(
                            "sold records persisted job_id=%s source=%s count=%s",
                            job_id,
                            source_name,
                            len(sold_candidates),
                        )
                except Exception as error:
                    failures += 1
                    detail = str(error).strip().replace("\n", " ")[:300]
                    summary = f"Source scan failed ({type(error).__name__})"
                    if detail:
                        summary += f": {detail}"
                    source_status = "partial_failed" if source_counters.candidates else "failed"
                    logger.exception(
                        "source %s job_id=%s source=%s persisted=%s error_type=%s error=%s",
                        source_status,
                        job_id,
                        source_name,
                        source_counters.candidates,
                        type(error).__name__,
                        detail or "(no message)",
                    )
                    self._finish_source(
                        job_id,
                        source_name,
                        source_status,
                        source_counters.as_dict(),
                        summary,
                    )
                else:
                    successes += 1
                    logger.info(
                        "source completed job_id=%s source=%s candidates=%s",
                        job_id,
                        source_name,
                        source_counters.candidates,
                    )
                    self._finish_source(
                        job_id,
                        source_name,
                        "success",
                        source_counters.as_dict(),
                        None,
                    )

            with self._session_factory.begin() as session:
                comparable_count = refresh_sold_comparables(
                    session,
                    municipalities=config.search.municipalities,
                    retrieved_at=_now(),
                )
            logger.info("sold comparables refreshed job_id=%s count=%s", job_id, comparable_count)

            if successes and failures:
                status = "partial_success"
            elif successes:
                status = "success"
            elif total_candidates:
                status = "partial_success"
            else:
                status = "failed"
            with self._session_factory.begin() as session:
                job = session.get(ScanJob, job_id)
                if job is None:
                    return
                job.status = status
                job.completed_at = _now()
                unique_properties = session.scalar(
                    select(func.count(distinct(Listing.property_id)))
                    .join(ScanObservation, ScanObservation.listing_id == Listing.id)
                    .where(ScanObservation.scan_job_id == job_id)
                )
                job.counters = {
                    "sources_succeeded": successes,
                    "sources_failed": failures,
                    "sold_comparables": comparable_count,
                    "sold_records": sold_records_total,
                    "candidates": total_candidates,
                    "properties": unique_properties or 0,
                    **ingest_totals.as_dict(),
                }
                job.error_summary = f"{failures} source(s) failed" if failures else None
                self._event(session, job_id, "completed", {"status": status})
                logger.info(
                    "scan completed job_id=%s status=%s candidates=%s properties=%s "
                    "sources_succeeded=%s sources_failed=%s",
                    job_id,
                    status,
                    total_candidates,
                    unique_properties or 0,
                    successes,
                    failures,
                )
        except asyncio.CancelledError:
            self._interrupt(job_id, "Server stopped before the scan completed")
            raise
        except Exception as error:
            logger.exception(
                "scan crashed job_id=%s error_type=%s error=%s",
                job_id,
                type(error).__name__,
                str(error).strip().replace("\n", " ")[:300] or "(no message)",
            )
            self._interrupt(
                job_id,
                f"Scan failed ({type(error).__name__})",
                status="failed",
            )

    def _set_job_running(self, job_id: int) -> None:
        with self._session_factory.begin() as session:
            job = session.get(ScanJob, job_id)
            if job is None:
                return
            job.status = "running"
            job.started_at = _now()
            self._event(session, job_id, "running", {})

    def _set_source_running(self, job_id: int, source: str) -> None:
        with self._session_factory.begin() as session:
            run = session.scalar(
                select(ScanSourceRun).where(
                    ScanSourceRun.scan_job_id == job_id,
                    ScanSourceRun.source == source,
                )
            )
            if run is None:
                return
            run.status = "running"
            run.started_at = _now()
            self._event(session, job_id, "source_started", {"source": source})

    def _finish_source(
        self,
        job_id: int,
        source: str,
        status: str,
        counters: dict[str, int] | int,
        error: str | None,
    ) -> None:
        with self._session_factory.begin() as session:
            run = session.scalar(
                select(ScanSourceRun).where(
                    ScanSourceRun.scan_job_id == job_id,
                    ScanSourceRun.source == source,
                )
            )
            if run is None:
                return
            run.status = status
            run.completed_at = _now()
            run.counters = {"candidates": counters} if isinstance(counters, int) else counters
            run.error_summary = error
            self._event(
                session,
                job_id,
                "source_completed",
                {"source": source, "status": status, **run.counters},
            )

    def _ingest_candidates(
        self,
        job_id: int,
        candidates,
        configured_municipalities: list[str],
    ) -> IngestCounters:
        totals = IngestCounters()
        observed_at = _now()
        with self._session_factory.begin() as session:
            job = session.get(ScanJob, job_id)
            if job is None:
                raise RuntimeError("Scan job disappeared during ingestion")
            for candidate in candidates:
                totals.add(
                    ingest_candidate(
                        session,
                        scan_job=job,
                        candidate=candidate,
                        configured_municipalities=configured_municipalities,
                        observed_at=observed_at,
                    )
                )
        return totals

    def _interrupt(self, job_id: int, reason: str, status: str = "interrupted") -> None:
        logger.warning("scan interrupted job_id=%s status=%s reason=%s", job_id, status, reason)
        with self._session_factory.begin() as session:
            job = session.get(ScanJob, job_id)
            if job is None or job.status in TERMINAL_STATUSES:
                return
            job.status = status
            job.completed_at = _now()
            job.error_summary = reason
            runs = session.scalars(
                select(ScanSourceRun).where(
                    ScanSourceRun.scan_job_id == job_id,
                    ScanSourceRun.status.in_(ACTIVE_STATUSES),
                )
            ).all()
            for run in runs:
                run.status = "failed"
                run.completed_at = _now()
                run.error_summary = reason
            self._event(session, job_id, status, {"reason": reason})

    @staticmethod
    def _event(session: Session, job_id: int, event_type: str, payload: dict[str, object]) -> None:
        session.add(
            ScanProgressEvent(
                scan_job_id=job_id,
                event_type=event_type,
                payload=payload,
                created_at=_now(),
            )
        )

    def _enabled_adapters(self, config) -> list[SourceAdapter]:
        if self._custom_adapters:
            return list(self._adapters)
        enabled = {
            "redfin": config.sources.redfin.enabled,
            "zillow": config.sources.zillow.enabled,
            "realtor": config.sources.realtor.enabled,
        }
        return [
            adapter
            for adapter in self._adapters
            if enabled.get(adapter.name.removeprefix("fixture-"), False)
        ]

    def _tracked_listings(self, source: str) -> list[NormalizedListing]:
        tracked: list[NormalizedListing] = []
        with self._session_factory() as session:
            listings = session.scalars(
                select(Listing)
                .options(joinedload(Listing.property), selectinload(Listing.states))
                .where(Listing.source == source)
            ).all()
            for listing in listings:
                latest = max(listing.states, key=lambda state: state.created_at, default=None)
                if latest is not None and latest.facts.get("record_kind") == "sold_comparable":
                    continue
                property_record = listing.property
                tracked.append(
                    NormalizedListing(
                        source=source,
                        source_listing_id=listing.source_listing_id,
                        url=listing.url,
                        street_address=property_record.street_address,
                        unit_number=property_record.unit_number,
                        municipality=property_record.municipality,
                        state=property_record.state,
                        postal_code=property_record.postal_code,
                        latitude=property_record.latitude,
                        longitude=property_record.longitude,
                        parcel_id=property_record.parcel_id,
                        price=latest.price if latest else None,
                        status=latest.status if latest else None,
                        bedrooms=latest.bedrooms if latest else None,
                        bathrooms=latest.bathrooms if latest else None,
                        living_area_sqft=latest.living_area_sqft if latest else None,
                        lot_size_sqft=latest.lot_size_sqft if latest else None,
                        property_tax_annual=latest.property_tax_annual if latest else None,
                        hoa_monthly=latest.hoa_monthly if latest else None,
                        description=latest.description if latest else None,
                        facts=latest.facts if latest else {},
                        source_updated_at=latest.source_updated_at if latest else None,
                        last_observed_at=listing.last_seen_at,
                    )
                )
        return tracked

    def _fingerprint(self, config, adapters: Sequence[SourceAdapter]) -> str:
        payload = {
            "state": config.search.state,
            "municipalities": [town.casefold() for town in config.search.municipalities],
            "included_property_types": config.search.included_property_types,
            "minimum_bedrooms": str(config.search.minimum_bedrooms),
            "minimum_bathrooms": str(config.search.minimum_bathrooms),
            "maximum_price": str(config.search.maximum_price),
            "sources": config.sources.model_dump(mode="json"),
            "adapters": [adapter.name for adapter in adapters],
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        return hashlib.sha256(encoded).hexdigest()
