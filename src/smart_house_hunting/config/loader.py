from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from smart_house_hunting.config.models import ApplicationConfig, ConfigUpdate


class ConfigError(RuntimeError):
    """Raised when local configuration cannot be loaded or saved safely."""


def default_config_path() -> Path:
    config_home = os.environ.get("XDG_CONFIG_HOME")
    root = Path(config_home).expanduser() if config_home else Path.home() / ".config"
    return root / "smart_house_hunting" / "config.yaml"


def _read_raw(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise ConfigError("Application configuration does not exist")
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as error:
        raise ConfigError("Application configuration could not be read") from error
    if not isinstance(data, dict):
        raise ConfigError("Application configuration must be a YAML mapping")
    return data


def load_config(path: Path | None = None) -> ApplicationConfig:
    config_path = path or default_config_path()
    config = load_config_document(config_path)

    if not config.profile_file.is_absolute():
        config.profile_file = (config_path.parent / config.profile_file).resolve()
    else:
        config.profile_file = config.profile_file.expanduser()
    return config


def load_config_document(path: Path) -> ApplicationConfig:
    try:
        config = ApplicationConfig.model_validate(_read_raw(path))
    except ValidationError as error:
        raise ConfigError("Application configuration is invalid") from error
    return config


def save_config_document(path: Path, config: ApplicationConfig) -> ApplicationConfig:
    _atomic_yaml_write(path, config.model_dump(mode="json"))
    return load_config_document(path)


def read_config_text(path: Path) -> str:
    if not path.is_file():
        raise ConfigError("Application configuration does not exist")
    try:
        return path.read_text(encoding="utf-8")
    except OSError as error:
        raise ConfigError("Application configuration could not be read") from error


def replace_config_text(path: Path, content: str) -> str:
    try:
        raw = yaml.safe_load(content)
    except yaml.YAMLError as error:
        raise ConfigError("Configuration is not valid YAML") from error
    if not isinstance(raw, dict):
        raise ConfigError("Application configuration must be a YAML mapping")
    try:
        ApplicationConfig.model_validate(raw)
    except ValidationError as error:
        issues = "; ".join(
            f"{'.'.join(str(part) for part in issue['loc'])}: {issue['msg']}"
            for issue in error.errors(include_input=False)
        )
        raise ConfigError(f"Application configuration is invalid: {issues}") from error
    normalized = content if content.endswith("\n") else f"{content}\n"
    _atomic_text_write(path, normalized)
    return normalized


def update_search_config(path: Path, update: ConfigUpdate) -> ApplicationConfig:
    raw = _read_raw(path)
    search = raw.setdefault("search", {})
    if not isinstance(search, dict):
        raise ConfigError("Search configuration is invalid")
    search["municipalities"] = update.municipalities

    try:
        validated = ApplicationConfig.model_validate(raw)
    except ValidationError as error:
        raise ConfigError("Updated application configuration is invalid") from error

    _atomic_yaml_write(path, validated.model_dump(mode="json"))
    return load_config(path)


def _atomic_yaml_write(path: Path, data: dict[str, Any]) -> None:
    serialized = yaml.safe_dump(data, sort_keys=False, allow_unicode=True)
    _atomic_text_write(path, serialized)


def _atomic_text_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary = Path(handle.name)
            os.chmod(temporary, 0o600)
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        os.chmod(path, 0o600)
    except OSError as error:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
        raise ConfigError("Application configuration could not be saved") from error
