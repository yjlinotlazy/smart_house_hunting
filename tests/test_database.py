from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import insert, inspect, select, text
from sqlalchemy.exc import IntegrityError

from smart_house_hunting.db.engine import create_session_factory, create_sqlite_engine
from smart_house_hunting.db.migration import (
    _backup_before_migration,
    initialize_database,
    verify_database_revision,
)
from smart_house_hunting.db.models import (
    Base,
    ListingState,
    PropertyAlias,
    ScanJob,
    ScanObservation,
)
from smart_house_hunting.db.repositories import (
    ListingStateInput,
    get_or_create_listing,
    get_or_create_listing_state,
    get_or_create_property,
    record_observation,
)
from smart_house_hunting.main import create_app


def initialized_database(tmp_path: Path):
    path = tmp_path / "data" / "app.db"
    engine = create_sqlite_engine(path)
    revision = initialize_database(engine, path)
    return path, engine, revision


def test_fresh_database_migrates_with_wal_foreign_keys_and_private_permissions(
    tmp_path: Path,
) -> None:
    path, engine, revision = initialized_database(tmp_path)

    tables = set(inspect(engine).get_table_names())
    with engine.connect() as connection:
        journal_mode = connection.execute(text("PRAGMA journal_mode")).scalar_one()
        foreign_keys = connection.execute(text("PRAGMA foreign_keys")).scalar_one()
        schema_differences = compare_metadata(MigrationContext.configure(connection), Base.metadata)

    assert revision == verify_database_revision(engine)
    assert {
        "alembic_version",
        "properties",
        "property_aliases",
        "property_duplicate_candidates",
        "listings",
        "listing_states",
        "scan_jobs",
        "scan_source_runs",
        "scan_progress_events",
        "scan_observations",
        "property_events",
        "sold_comparables",
        "profile_versions",
        "llm_runs",
        "llm_evaluations",
        "llm_digests",
        "places",
        "nearby_analysis_runs",
        "nearby_search_cache",
        "property_walking_routes",
    } == tables
    assert journal_mode == "wal"
    assert foreign_keys == 1
    assert schema_differences == []
    assert path.stat().st_mode & 0o777 == 0o600

    assert initialize_database(engine, path) == revision
    engine.dispose()


def test_pre_migration_backup_is_private(tmp_path: Path) -> None:
    path, engine, _ = initialized_database(tmp_path)
    with engine.begin() as connection:
        connection.execute(text("UPDATE alembic_version SET version_num = 'older'"))
    backup = _backup_before_migration(engine, path)
    assert backup is not None and backup.is_file()
    assert backup.stat().st_mode & 0o777 == 0o600
    engine.dispose()


def test_database_rejects_orphaned_relationships(tmp_path: Path) -> None:
    _, engine, _ = initialized_database(tmp_path)

    with pytest.raises(IntegrityError), engine.begin() as connection:
        connection.execute(
            insert(PropertyAlias).values(
                property_id=999,
                kind="address",
                normalized_value="orphaned alias",
                confidence=100,
            )
        )

    engine.dispose()


def test_repository_reuses_content_but_records_presence_in_later_scans(tmp_path: Path) -> None:
    _, engine, _ = initialized_database(tmp_path)
    session_factory = create_session_factory(engine)
    observed_at = datetime(2026, 8, 5, 12, tzinfo=UTC)

    with session_factory.begin() as session:
        property_record, property_created = get_or_create_property(
            session,
            alias_kind="address",
            alias_value="example street|example town|ma",
            street_address="Example Street",
            municipality="Example Town",
        )
        same_property, duplicate_property_created = get_or_create_property(
            session,
            alias_kind="address",
            alias_value="example street|example town|ma",
            street_address="Different Input",
            municipality="Example Town",
        )
        listing, listing_created = get_or_create_listing(
            session,
            property_record=property_record,
            source="example",
            source_listing_id="listing-one",
            episode_key="initial",
            url="https://example.invalid/listing-one",
            observed_at=observed_at,
        )
        same_listing, duplicate_listing_created = get_or_create_listing(
            session,
            property_record=property_record,
            source="example",
            source_listing_id="listing-one",
            episode_key="initial",
            url="https://example.invalid/listing-one",
            observed_at=observed_at,
        )
        state_input = ListingStateInput(
            status="active",
            price=Decimal("1000000"),
            facts={"property_type": "single_family"},
        )
        state, state_created = get_or_create_listing_state(
            session, listing=listing, state=state_input
        )
        same_state, duplicate_state_created = get_or_create_listing_state(
            session, listing=listing, state=state_input
        )
        first_scan = ScanJob(status="running", config_fingerprint="a" * 64)
        second_scan = ScanJob(status="running", config_fingerprint="a" * 64)
        session.add_all([first_scan, second_scan])
        session.flush()
        first_observation, first_observation_created = record_observation(
            session,
            scan_job=first_scan,
            listing=listing,
            listing_state=state,
            observed_at=observed_at,
        )
        same_observation, duplicate_observation_created = record_observation(
            session,
            scan_job=first_scan,
            listing=listing,
            listing_state=state,
            observed_at=observed_at,
        )
        _, later_observation_created = record_observation(
            session,
            scan_job=second_scan,
            listing=listing,
            listing_state=state,
            observed_at=observed_at,
        )

        assert property_created and not duplicate_property_created
        assert property_record.id == same_property.id
        assert listing_created and not duplicate_listing_created
        assert listing.id == same_listing.id
        assert state_created and not duplicate_state_created
        assert state.id == same_state.id
        assert first_observation_created and not duplicate_observation_created
        assert first_observation.id == same_observation.id
        assert later_observation_created

    with session_factory() as session:
        assert len(session.scalars(select(ListingState)).all()) == 1
        assert len(session.scalars(select(ScanObservation)).all()) == 2
    engine.dispose()


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.mark.anyio
async def test_application_lifespan_migrates_database_before_serving(tmp_path: Path) -> None:
    path = tmp_path / "startup" / "app.db"
    app = create_app(database_path=path)

    async with app.router.lifespan_context(app):
        assert path.exists()
        assert verify_database_revision(app.state.database_engine)
        assert app.state.session_factory is not None
