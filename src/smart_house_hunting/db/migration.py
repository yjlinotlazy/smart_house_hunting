from __future__ import annotations

import os
import sqlite3
from datetime import datetime
from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import Engine, text

PROJECT_ROOT = Path(__file__).resolve().parents[3]
ALEMBIC_INI = PROJECT_ROOT / "alembic.ini"


class MigrationError(RuntimeError):
    """Raised when the local database schema cannot be verified."""


def alembic_config() -> Config:
    return Config(str(ALEMBIC_INI))


def upgrade_database(engine: Engine) -> None:
    config = alembic_config()
    try:
        with engine.begin() as connection:
            config.attributes["connection"] = connection
            command.upgrade(config, "head")
    except Exception as error:
        raise MigrationError("Database migration failed") from error


def verify_database_revision(engine: Engine) -> str:
    config = alembic_config()
    expected = ScriptDirectory.from_config(config).get_current_head()
    if expected is None:
        raise MigrationError("Database migration head is missing")
    try:
        with engine.connect() as connection:
            current = connection.execute(
                text("SELECT version_num FROM alembic_version")
            ).scalar_one()
    except Exception as error:
        raise MigrationError("Database revision could not be read") from error
    if current != expected:
        raise MigrationError("Database revision is not current")
    return current


def initialize_database(engine: Engine, path: Path) -> str:
    _backup_before_migration(engine, path)
    upgrade_database(engine)
    revision = verify_database_revision(engine)
    if path.exists():
        os.chmod(path, 0o600)
    return revision


def _backup_before_migration(engine: Engine, path: Path) -> Path | None:
    if not path.is_file() or path.stat().st_size == 0:
        return None
    expected = ScriptDirectory.from_config(alembic_config()).get_current_head()
    try:
        with engine.connect() as connection:
            current = connection.execute(
                text("SELECT version_num FROM alembic_version")
            ).scalar_one_or_none()
    except Exception:
        current = None
    if current == expected:
        return None
    backup_dir = path.parent / "backups"
    backup_dir.mkdir(mode=0o700, exist_ok=True)
    backup = backup_dir / f"{path.stem}.pre-migration.{datetime.now().strftime('%Y%m%d-%H%M%S')}.db"
    source = sqlite3.connect(path)
    destination = sqlite3.connect(backup)
    try:
        source.backup(destination)
    finally:
        destination.close()
        source.close()
    os.chmod(backup, 0o600)
    return backup
