from pathlib import Path

from fastapi import APIRouter, HTTPException, Request

from smart_house_hunting.config.loader import (
    ConfigError,
    load_config_document,
    read_config_text,
    replace_config_text,
    save_config_document,
)
from smart_house_hunting.config.models import ApplicationConfig, ConfigText

router = APIRouter(prefix="/api/settings", tags=["settings"])


def _config_path(request: Request) -> Path:
    return request.app.state.config_path


@router.get("")
async def get_settings(request: Request) -> ApplicationConfig:
    try:
        return load_config_document(_config_path(request))
    except ConfigError as error:
        raise HTTPException(status_code=500, detail=str(error)) from error


@router.put("")
async def update_settings(update: ApplicationConfig, request: Request) -> ApplicationConfig:
    try:
        return save_config_document(_config_path(request), update)
    except ConfigError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@router.get("/yaml")
async def get_settings_yaml(request: Request) -> ConfigText:
    try:
        return ConfigText(content=read_config_text(_config_path(request)))
    except ConfigError as error:
        raise HTTPException(status_code=500, detail=str(error)) from error


@router.put("/yaml")
async def update_settings_yaml(update: ConfigText, request: Request) -> ConfigText:
    try:
        return ConfigText(content=replace_config_text(_config_path(request), update.content))
    except ConfigError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
