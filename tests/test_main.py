from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from smart_house_hunting.main import create_app


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.mark.anyio
async def test_health() -> None:
    transport = ASGITransport(app=create_app())

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "name": "smart-house-hunting",
        "version": "0.1.0",
    }


@pytest.mark.anyio
async def test_serves_built_frontend_and_keeps_unknown_api_as_404(tmp_path: Path) -> None:
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<main>Smart House Hunting</main>", encoding="utf-8")
    transport = ASGITransport(app=create_app(dist))

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        root = await client.get("/")
        unknown_api = await client.get("/api/missing")

    assert root.status_code == 200
    assert "Smart House Hunting" in root.text
    assert unknown_api.status_code == 404
