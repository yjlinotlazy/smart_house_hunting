from fastapi import APIRouter, HTTPException, Request

from smart_house_hunting.config.loader import ConfigError, load_config
from smart_house_hunting.profile.models import (
    HouseholdProfile,
    ProfileReadResponse,
    ProfileSaveResponse,
)
from smart_house_hunting.profile.storage import ProfileStorageError, ProfileStore

router = APIRouter(prefix="/api/profile", tags=["profile"])


def _store(request: Request) -> ProfileStore:
    config = load_config(request.app.state.config_path)
    return ProfileStore(
        config.profile_file,
        default_down_payment_percent=config.finance.default_down_payment_percent,
    )


@router.get("")
async def get_profile(request: Request) -> ProfileReadResponse:
    try:
        profile, exists, version = _store(request).read()
        return ProfileReadResponse(profile=profile, exists=exists, version=version)
    except (ConfigError, ProfileStorageError) as error:
        raise HTTPException(status_code=500, detail=str(error)) from error


@router.put("")
async def save_profile(profile: HouseholdProfile, request: Request) -> ProfileSaveResponse:
    try:
        version, backup_created = _store(request).save(profile)
        return ProfileSaveResponse(
            profile=profile,
            exists=True,
            version=version,
            backup_created=backup_created,
        )
    except (ConfigError, ProfileStorageError) as error:
        raise HTTPException(status_code=500, detail=str(error)) from error
