from pathlib import Path

import pytest
import yaml
from httpx import ASGITransport, AsyncClient

from smart_house_hunting.main import create_app


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.mark.anyio
async def test_config_text_round_trip_and_validation(tmp_path: Path) -> None:
    raw = (
        Path("config.example.yaml")
        .read_text(encoding="utf-8")
        .replace(
            '"<private-profile-directory>/house_profile.yaml"',
            '"private/profile.yaml"',
        )
    )
    config_path = tmp_path / "config.yaml"
    config_path.write_text(raw, encoding="utf-8")
    app = create_app(config_path=config_path, database_path=tmp_path / "app.db")

    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client,
    ):
        loaded = await client.get("/api/settings/yaml")
        changed = loaded.json()["content"].replace(
            "maximum_price: 2000000", "maximum_price: 2100000"
        )
        saved = await client.put("/api/settings/yaml", json={"content": changed})
        invalid = await client.put(
            "/api/settings/yaml",
            json={"content": changed.replace("mortgage_years: 30", "mortgage_years: 15")},
        )
        structured = await client.get("/api/settings")
        structured_body = structured.json()
        structured_body["search"]["included_property_types"] = ["single_family", "condo"]
        structured_saved = await client.put("/api/settings", json=structured_body)

    assert loaded.status_code == 200
    assert saved.status_code == 200
    assert (
        yaml.safe_load(config_path.read_text(encoding="utf-8"))["search"]["maximum_price"]
        == "2100000"
    )
    assert invalid.status_code == 422
    assert "finance.mortgage_years" in invalid.json()["detail"]
    assert structured_saved.status_code == 200
    assert structured_saved.json()["search"]["included_property_types"] == [
        "single_family",
        "condo",
    ]
    assert config_path.stat().st_mode & 0o777 == 0o600
