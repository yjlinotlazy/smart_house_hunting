from pathlib import Path

from fastapi import APIRouter, HTTPException, Request

from smart_house_hunting.config.loader import ConfigError, load_config, update_search_config
from smart_house_hunting.config.models import (
    ConfigUpdate,
    PublicApplicationConfig,
    to_public_config,
)

router = APIRouter(prefix="/api/config", tags=["config"])


def _config_path(request: Request) -> Path:
    return request.app.state.config_path


@router.get("")
async def get_config(request: Request) -> PublicApplicationConfig:
    try:
        return to_public_config(load_config(_config_path(request)))
    except ConfigError as error:
        raise HTTPException(status_code=500, detail=str(error)) from error


@router.put("")
async def update_config(update: ConfigUpdate, request: Request) -> PublicApplicationConfig:
    try:
        config = update_search_config(_config_path(request), update)
        return to_public_config(config)
    except ConfigError as error:
        raise HTTPException(status_code=500, detail=str(error)) from error
