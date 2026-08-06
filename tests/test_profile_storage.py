from datetime import date
from decimal import Decimal
from pathlib import Path

import yaml

from smart_house_hunting.profile.models import HouseholdProfile
from smart_house_hunting.profile.storage import ProfileStore


def profile(family: str) -> HouseholdProfile:
    return HouseholdProfile(family=family)


def test_missing_profile_returns_safe_defaults(tmp_path: Path) -> None:
    stored, exists, version = ProfileStore(tmp_path / "profile.yaml").read()

    assert not exists
    assert stored.family == ""
    assert stored.finance.down_payment.mode == "amount"
    assert len(version) == 64


def test_missing_profile_uses_configured_down_payment_default(tmp_path: Path) -> None:
    stored, exists, _ = ProfileStore(
        tmp_path / "profile.yaml", default_down_payment_percent=Decimal("20")
    ).read()

    assert not exists
    assert stored.finance.down_payment.mode == "percent"
    assert stored.finance.down_payment.value == Decimal("20")


def test_save_is_atomic_private_and_backed_up_at_most_once_per_day(tmp_path: Path) -> None:
    path = tmp_path / "private" / "profile.yaml"
    store = ProfileStore(path)
    first_day = date(2026, 8, 5)

    _, first_backup = store.save(profile("first"), local_date=first_day)
    _, second_backup = store.save(profile("second"), local_date=first_day)
    _, third_backup = store.save(profile("third"), local_date=first_day)

    backup = path.parent / "backups" / "profile.2026-08-05.yaml"
    backup_data = yaml.safe_load(backup.read_text(encoding="utf-8"))

    assert not first_backup
    assert second_backup
    assert not third_backup
    assert backup_data["family"] == "first"
    assert path.stat().st_mode & 0o777 == 0o600
    assert not list(path.parent.glob("*.tmp"))

    _, next_day_backup = store.save(profile("fourth"), local_date=date(2026, 8, 6))
    next_backup = path.parent / "backups" / "profile.2026-08-06.yaml"

    assert next_day_backup
    assert yaml.safe_load(next_backup.read_text(encoding="utf-8"))["family"] == "third"
