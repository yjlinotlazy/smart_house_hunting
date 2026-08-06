from __future__ import annotations

import fcntl
import hashlib
import json
import os
import shutil
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from smart_house_hunting.profile.models import HouseholdProfile


class ProfileStorageError(RuntimeError):
    """Raised when the private profile cannot be read or saved safely."""


class ProfileStore:
    def __init__(self, path: Path, *, default_down_payment_percent: Decimal | None = None) -> None:
        self.path = path.expanduser()
        self.default_down_payment_percent = default_down_payment_percent

    def read(self) -> tuple[HouseholdProfile, bool, str]:
        if not self.path.exists():
            profile = HouseholdProfile()
            if self.default_down_payment_percent is not None:
                profile.finance.down_payment.mode = "percent"
                profile.finance.down_payment.value = self.default_down_payment_percent
            return profile, False, profile_hash(profile)
        try:
            raw = yaml.safe_load(self.path.read_text(encoding="utf-8"))
            profile = HouseholdProfile.model_validate(raw or {})
        except (OSError, yaml.YAMLError, ValidationError) as error:
            raise ProfileStorageError("Household profile could not be read") from error
        return profile, True, profile_hash(profile)

    def save(
        self, profile: HouseholdProfile, *, local_date: date | None = None
    ) -> tuple[str, bool]:
        today = local_date or date.today()
        self._ensure_parent()
        with self._lock():
            backup_created = self._backup_once(today)
            self._atomic_write(profile)
        return profile_hash(profile), backup_created

    def _ensure_parent(self) -> None:
        try:
            existed = self.path.parent.exists()
            self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            if not existed:
                os.chmod(self.path.parent, 0o700)
        except OSError as error:
            raise ProfileStorageError("Household profile directory could not be created") from error

    @contextmanager
    def _lock(self) -> Iterator[None]:
        lock_path = self.path.parent / f".{self.path.name}.lock"
        try:
            with lock_path.open("a", encoding="utf-8") as handle:
                os.chmod(lock_path, 0o600)
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
                yield
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        except OSError as error:
            raise ProfileStorageError("Household profile lock failed") from error

    def _backup_once(self, today: date) -> bool:
        if not self.path.is_file():
            return False
        backup_dir = self.path.parent / "backups"
        suffix = self.path.suffix or ".yaml"
        backup = backup_dir / f"{self.path.stem}.{today.isoformat()}{suffix}"
        if backup.exists():
            return False
        try:
            backup_dir.mkdir(mode=0o700, exist_ok=True)
            shutil.copy2(self.path, backup)
            os.chmod(backup, 0o600)
        except OSError as error:
            raise ProfileStorageError("Daily household profile backup failed") from error
        return True

    def _atomic_write(self, profile: HouseholdProfile) -> None:
        temporary: Path | None = None
        data = profile.model_dump(mode="json")
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=self.path.parent,
                prefix=f".{self.path.name}.",
                suffix=".tmp",
                delete=False,
            ) as handle:
                temporary = Path(handle.name)
                os.chmod(temporary, 0o600)
                yaml.safe_dump(data, handle, sort_keys=False, allow_unicode=True)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.path)
            os.chmod(self.path, 0o600)
        except OSError as error:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
            raise ProfileStorageError("Household profile could not be saved") from error


def profile_hash(profile: HouseholdProfile) -> str:
    canonical: dict[str, Any] = profile.model_dump(mode="json")
    encoded = json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()
