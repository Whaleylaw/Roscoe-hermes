from run_agent import normalize_legacy_compression_config


def test_legacy_compression_summary_config_maps_to_auxiliary_compression():
    config = {
        "compression": {
            "summary_model": "gpt-5.4-mini",
            "summary_provider": "openrouter",
            "summary_base_url": "https://openrouter.ai/api/v1",
        },
        "auxiliary": {
            "compression": {
                "provider": "auto",
                "model": "",
                "base_url": "",
            },
        },
    }

    mapped = normalize_legacy_compression_config(config)

    assert mapped == ["model", "provider", "base_url"]
    assert config["auxiliary"]["compression"]["model"] == "gpt-5.4-mini"
    assert config["auxiliary"]["compression"]["provider"] == "openrouter"
    assert config["auxiliary"]["compression"]["base_url"] == "https://openrouter.ai/api/v1"


def test_legacy_compression_summary_config_does_not_override_explicit_auxiliary():
    config = {
        "compression": {
            "summary_model": "gpt-5.4-mini",
            "summary_provider": "openrouter",
            "summary_base_url": "https://openrouter.ai/api/v1",
        },
        "auxiliary": {
            "compression": {
                "provider": "custom",
                "model": "custom-summary",
                "base_url": "http://localhost:1234/v1",
            },
        },
    }

    mapped = normalize_legacy_compression_config(config)

    assert mapped == []
    assert config["auxiliary"]["compression"]["model"] == "custom-summary"
    assert config["auxiliary"]["compression"]["provider"] == "custom"
    assert config["auxiliary"]["compression"]["base_url"] == "http://localhost:1234/v1"
