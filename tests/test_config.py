from pathlib import Path

import yaml

from smart_house_hunting.config.loader import load_config, update_search_config
from smart_house_hunting.config.models import ConfigUpdate, to_public_config


def test_example_config_is_valid_and_public_view_contains_no_provider_secrets() -> None:
    config = load_config(Path("config.example.yaml"))

    public = to_public_config(config).model_dump(mode="json")

    assert public["server"]["port"] == 7004
    assert public["search"]["included_property_types"] == ["single_family"]
    assert public["search"]["minimum_bedrooms"] == "0"
    assert public["search"]["minimum_bathrooms"] == "0"
    assert public["search"]["maximum_price"] == "2000000"
    assert config.finance.default_down_payment_percent == 20
    assert public["llm"]["default_provider"] == "google"
    assert "api_key_env" not in str(public)
    assert "base_url" not in str(public)


def test_update_search_preserves_private_provider_configuration(tmp_path: Path) -> None:
    source = yaml.safe_load(Path("config.example.yaml").read_text(encoding="utf-8"))
    source["profile_file"] = str(tmp_path / "profile.yaml")
    config_path = tmp_path / "config.yaml"
    config_path.write_text(yaml.safe_dump(source, sort_keys=False), encoding="utf-8")

    updated = update_search_config(
        config_path, ConfigUpdate(municipalities=["Belmont", "newton", "BELMONT"])
    )
    persisted = yaml.safe_load(config_path.read_text(encoding="utf-8"))

    assert updated.search.municipalities == ["Belmont", "newton"]
    assert persisted["llm"]["providers"]["google"]["api_key_env"] == "GOOGLE_API_KEY"
    assert config_path.stat().st_mode & 0o777 == 0o600
