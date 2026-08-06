from __future__ import annotations

import gzip
import json

import httpx

from smart_house_hunting.sources.payloads import save_response_payload


def test_saves_complete_response_payload_and_safe_metadata(tmp_path) -> None:
    body = b"<html><body>complete sanitized payload</body></html>"
    response = httpx.Response(
        200,
        content=body,
        headers={"content-type": "text/html", "set-cookie": "must-not-be-retained"},
        request=httpx.Request("GET", "https://example.invalid/public-listing"),
    )

    payload_path = save_response_payload("fixture", response, root=tmp_path)
    metadata_path = payload_path.with_suffix("").with_suffix(".json")

    assert gzip.decompress(payload_path.read_bytes()) == body
    metadata = json.loads(metadata_path.read_text())
    assert metadata["status_code"] == 200
    assert metadata["url"] == "https://example.invalid/public-listing"
    assert "set-cookie" not in metadata
    assert payload_path.stat().st_mode & 0o777 == 0o600
