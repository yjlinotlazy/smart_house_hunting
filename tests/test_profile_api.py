from pathlib import Path

import pytest
import yaml
from httpx import ASGITransport, AsyncClient

from smart_house_hunting.main import create_app


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def create_config(tmp_path: Path) -> Path:
    config = yaml.safe_load(Path("config.example.yaml").read_text(encoding="utf-8"))
    config["profile_file"] = str(tmp_path / "private" / "profile.yaml")
    config["search"]["municipalities"] = ["Belmont", "Newton"]
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
    return path


@pytest.mark.anyio
async def test_profile_and_public_config_round_trip(tmp_path: Path) -> None:
    app = create_app(config_path=create_config(tmp_path))
    transport = ASGITransport(app=app)
    profile = {
        "family": "local household context",
        "must_have": "three bedrooms",
        "good_to_have": "morning light",
        "finance": {
            "current_annual_gross_income": "100",
            "minimum_future_annual_gross_income": "80",
            "annual_travel_spending": "10",
            "down_payment": {"mode": "percent", "value": "20"},
        },
    }

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        initial = await client.get("/api/profile")
        saved = await client.put("/api/profile", json=profile)
        reloaded = await client.get("/api/profile")
        public_config = await client.get("/api/config")

    assert initial.status_code == 200
    assert not initial.json()["exists"]
    assert initial.json()["profile"]["finance"]["down_payment"] == {
        "mode": "percent",
        "value": "20",
    }
    assert saved.status_code == 200
    assert saved.json()["profile"]["finance"]["down_payment"] == {
        "mode": "percent",
        "value": "20",
    }
    assert reloaded.json()["profile"] == saved.json()["profile"]
    assert public_config.json()["search"]["municipalities"] == ["Belmont", "Newton"]
    assert "api_key" not in public_config.text
