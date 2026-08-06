from __future__ import annotations

import gzip
import hashlib
import json
import logging
import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path

import httpx

logger = logging.getLogger(__name__)


def default_payload_root() -> Path:
    data_home = os.environ.get("XDG_DATA_HOME")
    root = Path(data_home).expanduser() if data_home else Path.home() / ".local" / "share"
    return root / "smart_house_hunting" / "source_payloads"


def save_response_payload(
    source: str,
    response: httpx.Response,
    *,
    root: Path | None = None,
) -> Path:
    retrieved_at = datetime.now(UTC)
    content_hash = hashlib.sha256(response.content).hexdigest()
    payload_root = root or default_payload_root()
    source_root = payload_root / source
    directory = source_root / retrieved_at.strftime("%Y-%m-%d")
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    for private_directory in (payload_root, source_root, directory):
        os.chmod(private_directory, 0o700)
    stem = (
        f"{retrieved_at.strftime('%Y%m%dT%H%M%S.%fZ')}_{response.status_code}_{content_hash[:16]}"
    )
    payload_path = directory / f"{stem}.body.gz"
    metadata_path = directory / f"{stem}.json"
    _atomic_bytes(payload_path, gzip.compress(response.content, compresslevel=6))
    metadata = {
        "source": source,
        "url": str(response.url),
        "status_code": response.status_code,
        "retrieved_at": retrieved_at.isoformat(),
        "content_type": response.headers.get("content-type"),
        "sha256": content_hash,
        "payload_file": payload_path.name,
    }
    _atomic_bytes(
        metadata_path,
        json.dumps(metadata, sort_keys=True, separators=(",", ":")).encode(),
    )
    return payload_path


def retain_response_payload(source: str, response: httpx.Response, *, enabled: bool) -> None:
    if not enabled:
        return
    try:
        path = save_response_payload(source, response)
    except OSError:
        logger.exception(
            "source payload save failed source=%s status=%s",
            source,
            response.status_code,
        )
    else:
        logger.info(
            "source payload saved source=%s status=%s file=%s",
            source,
            response.status_code,
            path.name,
        )


def _atomic_bytes(path: Path, content: bytes) -> None:
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
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
    except OSError:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
        raise
