from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from sqlalchemy import delete, select

from smart_house_hunting.db.engine import create_session_factory, create_sqlite_engine
from smart_house_hunting.db.migration import initialize_database
from smart_house_hunting.db.models import PropertyEvent, ScanJob
from smart_house_hunting.services.history import backfill_property_events
from smart_house_hunting.services.ingest import ingest_candidate
from smart_house_hunting.sources import NormalizedListing


def listing(price: str, status: str) -> NormalizedListing:
    return NormalizedListing(
        source="redfin",
        source_listing_id="history-one",
        url="https://example.invalid/history-one",
        street_address="10 Example Rd",
        municipality="Belmont",
        price=Decimal(price),
        status=status,
        bedrooms=Decimal("3"),
        bathrooms=Decimal("2"),
        living_area_sqft=1800,
        lot_size_sqft=Decimal("10000"),
        facts={"property_type": "single_family", "year_built": 1940},
    )


def test_history_events_are_deterministic_and_unchanged_scans_add_nothing(
    tmp_path: Path,
) -> None:
    engine = create_sqlite_engine(tmp_path / "app.db")
    initialize_database(engine, tmp_path / "app.db")
    sessions = create_session_factory(engine)
    started = datetime(2026, 8, 5, 12, tzinfo=UTC)

    inputs = [
        listing("900000", "active"),
        listing("850000", "off_market"),
        listing("850000", "off_market"),
        listing("850000", "active"),
        listing("840000", "sold"),
    ]
    for index, candidate in enumerate(inputs):
        with sessions.begin() as session:
            scan = ScanJob(status="running", config_fingerprint="a" * 64)
            session.add(scan)
            session.flush()
            ingest_candidate(
                session,
                scan_job=scan,
                candidate=candidate,
                configured_municipalities=["Belmont"],
                observed_at=started + timedelta(days=index),
            )

    with sessions() as session:
        events = session.scalars(
            select(PropertyEvent).order_by(PropertyEvent.occurred_at, PropertyEvent.id)
        ).all()
        event_types = [event.event_type for event in events]
        fingerprints = [event.event_fingerprint for event in events]

    assert event_types == [
        "first_seen",
        "price_change",
        "status_change",
        "delisted",
        "status_change",
        "relisted",
        "price_change",
        "status_change",
        "sold",
    ]
    assert len(fingerprints) == len(set(fingerprints))

    with sessions.begin() as session:
        session.execute(delete(PropertyEvent))
        assert backfill_property_events(session) == 9
        assert backfill_property_events(session) == 0
    engine.dispose()
