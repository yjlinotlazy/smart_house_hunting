from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from sqlalchemy import func, select

from smart_house_hunting import __version__
from smart_house_hunting.api.analysis import router as analysis_router
from smart_house_hunting.api.config import router as config_router
from smart_house_hunting.api.exports import router as exports_router
from smart_house_hunting.api.finance import router as finance_router
from smart_house_hunting.api.maps import router as maps_router
from smart_house_hunting.api.profile import router as profile_router
from smart_house_hunting.api.properties import router as properties_router
from smart_house_hunting.api.scans import router as scans_router
from smart_house_hunting.api.settings import router as settings_router
from smart_house_hunting.config.loader import default_config_path, load_config
from smart_house_hunting.db.engine import (
    create_session_factory,
    create_sqlite_engine,
    default_database_path,
)
from smart_house_hunting.db.migration import initialize_database
from smart_house_hunting.db.models import Listing, ListingState, Property, ScanJob
from smart_house_hunting.jobs.manager import ScanManager
from smart_house_hunting.logging_security import install_redaction
from smart_house_hunting.services.history import backfill_property_events
from smart_house_hunting.sources.base import SourceAdapter

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_FRONTEND_DIST = PROJECT_ROOT / "frontend" / "dist"


def create_app(
    frontend_dist: Path | None = None,
    config_path: Path | None = None,
    database_path: Path | None = None,
    source_adapters: list[SourceAdapter] | None = None,
    maps_client_factory=None,
    llm_provider_factory=None,
) -> FastAPI:
    """Create the API and attach a production frontend build when available."""
    selected_database_path = database_path or default_database_path()

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        config = load_config(application.state.config_path)
        engine = create_sqlite_engine(selected_database_path)
        initialize_database(engine, selected_database_path)
        level = getattr(logging, config.logging.level.upper(), logging.INFO)
        application_logger = logging.getLogger("smart_house_hunting")
        uvicorn_logger = logging.getLogger("uvicorn.error")
        uvicorn_handlers = uvicorn_logger.handlers or logging.getLogger("uvicorn").handlers
        application_logger.disabled = False
        application_logger.setLevel(level)
        if uvicorn_handlers:
            install_redaction(list(uvicorn_handlers))
            application_logger.handlers = list(uvicorn_handlers)
            application_logger.propagate = False
        application_logger.info(
            "application logging configured level=%s", logging.getLevelName(level)
        )
        application.state.database_engine = engine
        application.state.session_factory = create_session_factory(engine)
        with application.state.session_factory.begin() as session:
            backfilled_events = backfill_property_events(session)
            properties = session.scalar(select(func.count(Property.id))) or 0
            listings = session.scalar(select(func.count(Listing.id))) or 0
            states = session.scalar(select(func.count(ListingState.id))) or 0
            scans = session.scalar(select(func.count(ScanJob.id))) or 0
            source_rows = session.execute(
                select(Listing.source, func.count(Listing.id))
                .group_by(Listing.source)
                .order_by(Listing.source)
            ).all()
        source_counts = ",".join(f"{source}:{count}" for source, count in source_rows) or "none"
        application_logger.info(
            "database inventory properties=%s listings=%s states=%s scans=%s sources=%s",
            properties,
            listings,
            states,
            scans,
            source_counts,
        )
        if backfilled_events:
            application_logger.info("listing history backfilled events=%s", backfilled_events)
        manager = ScanManager(
            application.state.session_factory,
            application.state.config_path,
            adapters=source_adapters,
        )
        application.state.scan_manager = manager
        manager.recover_interrupted()
        try:
            yield
        finally:
            await manager.shutdown()
            engine.dispose()

    app = FastAPI(title="Smart House Hunting", version=__version__, lifespan=lifespan)
    app.state.config_path = config_path or default_config_path()
    app.state.maps_client_factory = maps_client_factory
    app.state.llm_provider_factory = llm_provider_factory
    dist = frontend_dist if frontend_dist is not None else DEFAULT_FRONTEND_DIST

    app.include_router(config_router)
    app.include_router(analysis_router)
    app.include_router(finance_router)
    app.include_router(exports_router)
    app.include_router(maps_router)
    app.include_router(profile_router)
    app.include_router(properties_router)
    app.include_router(scans_router)
    app.include_router(settings_router)

    @app.get("/api/health", tags=["system"])
    async def health() -> dict[str, str]:
        return {
            "status": "ok",
            "name": "smart-house-hunting",
            "version": __version__,
        }

    assets = dist / "assets"
    if assets.is_dir():
        app.mount("/assets", StaticFiles(directory=assets), name="frontend-assets")

    @app.get("/{path:path}", include_in_schema=False)
    async def frontend(path: str) -> Response:
        if path.startswith("api/"):
            raise HTTPException(status_code=404, detail="API endpoint not found")

        index = dist / "index.html"
        if index.is_file():
            return HTMLResponse(index.read_text(encoding="utf-8"))

        return JSONResponse(
            {
                "name": "smart-house-hunting",
                "message": "Frontend build not found. Run Vite or build the frontend.",
            }
        )

    return app


app = create_app()


def run() -> None:
    """Run the localhost production server with project defaults."""
    uvicorn.run(
        "smart_house_hunting.main:app",
        port=7004,
        reload=False,
    )
