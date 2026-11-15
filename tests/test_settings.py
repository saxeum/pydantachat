"""Tests for `config.json`: loading, defaults, and the allow-lists."""

import json
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError
from pydantic_ai.models import infer_model

from pydantachat.evals import thinking_from_cli
from pydantachat.settings import ConfigError, Settings, thinking_label

CONFIG: dict[str, Any] = {
    "default_provider": "acme",
    "default_model": "acme-model",
    "default_thinking": "low",
    "providers": {
        "acme": {
            "models": {
                "acme-model": {"thinking": {"levels": ["low", "high"]}},
                "acme-small": {"thinking": {"levels": ["minimal"]}},
                "acme-plain": {},
                "acme-off": {"thinking": {"levels": ["low"], "can_disable": True}},
            }
        },
        "other": {"models": {"other-model": {}}},
    },
    "tracing": {"endpoint": None, "service_name": "tests"},
}


def settings(**overrides: Any) -> Settings:
    return Settings.model_validate({**CONFIG, **overrides})


def test_settings_resolves_configured_defaults() -> None:
    config = settings().model

    assert config.model_id == "acme:acme-model"
    assert config.thinking == "low"
    assert config.model_settings == {"thinking": "low"}


def test_settings_without_thinking_uses_provider_default() -> None:
    config = settings(default_thinking=None).model

    assert config.thinking is None
    assert config.model_settings is None


def test_settings_rejects_unknown_default_provider() -> None:
    with pytest.raises(ValidationError, match="Provider 'missing' is not configured"):
        settings(default_provider="missing")


def test_settings_rejects_disallowed_default_model() -> None:
    with pytest.raises(ValidationError, match="Model 'nope' is not allowed"):
        settings(default_model="nope")


def test_settings_rejects_disallowed_default_thinking() -> None:
    with pytest.raises(ValidationError, match="Thinking 'medium' is not allowed"):
        settings(default_thinking="medium")


def test_settings_requires_at_least_one_model() -> None:
    with pytest.raises(ValidationError, match="at least 1 item"):
        settings(providers={"acme": {"models": {}}})


def test_resolve_applies_overrides() -> None:
    config = settings().resolve(model="acme-small", thinking="minimal")

    assert config.model_id == "acme:acme-small"
    assert config.thinking == "minimal"


def test_resolve_rejects_unknown_provider() -> None:
    with pytest.raises(ConfigError, match="Provider 'nope' is not configured"):
        settings().resolve(provider="nope")


def test_resolve_rejects_disallowed_model() -> None:
    with pytest.raises(ConfigError, match="Model 'other-model' is not allowed"):
        settings().resolve(model="other-model")


def test_resolve_rejects_disallowed_thinking() -> None:
    with pytest.raises(
        ConfigError, match="Thinking 'minimal' is not allowed for acme:acme-model"
    ):
        settings().resolve(thinking="minimal")


def test_thinking_levels_are_per_model() -> None:
    # Same provider: 'minimal' is allowed on acme-small but not on acme-model.
    assert settings().resolve(model="acme-small", thinking="minimal").thinking == (
        "minimal"
    )

    with pytest.raises(
        ConfigError, match="Thinking 'minimal' is not allowed for acme:acme-model"
    ):
        settings().resolve(model="acme-model", thinking="minimal")


def test_model_without_thinking_support_refuses_any_level() -> None:
    with pytest.raises(
        ConfigError, match="Thinking 'low' is not allowed for acme:acme-plain"
    ):
        settings().resolve(model="acme-plain", thinking="low")

    with pytest.raises(ConfigError, match="acme:acme-plain has no thinking setting"):
        settings().resolve(model="acme-plain", thinking=True)


def test_default_thinking_applies_to_the_default_model_only() -> None:
    assert settings().resolve().thinking == "low"
    assert settings().resolve(model="acme-small").thinking is None


def test_resolve_requires_a_model_for_a_non_default_provider() -> None:
    with pytest.raises(ConfigError, match="No model given for 'other'"):
        settings().resolve(provider="other")


def test_resolve_can_disable_thinking_when_the_model_allows_it() -> None:
    config = settings().resolve(model="acme-off", thinking=False)

    assert config.thinking is False
    assert config.model_settings == {"thinking": False}


def test_resolve_rejects_disabling_thinking_on_an_always_on_model() -> None:
    with pytest.raises(
        ConfigError,
        match="Thinking cannot be disabled for acme:acme-model: it always reasons",
    ):
        settings().resolve(thinking=False)


def test_settings_rejects_a_default_that_tries_to_disable_thinking() -> None:
    with pytest.raises(ValidationError, match="Thinking cannot be disabled"):
        settings(default_thinking=False)


def test_api_key_env_is_provider_specific(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ACME_API_KEY", "test-key")

    config = settings().model

    assert config.api_key_env == "ACME_API_KEY"
    assert config.has_api_key


def test_has_no_api_key_when_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ACME_API_KEY", raising=False)

    assert not settings().model.has_api_key


def test_tracing_is_off_by_default() -> None:
    tracing = Settings.model_validate({**CONFIG, "tracing": {}}).tracing

    assert tracing.endpoint is None
    assert tracing.service_name == "pydantachat"


def test_settings_from_file(tmp_path: Path) -> None:
    path = tmp_path / "config.json"
    path.write_text(json.dumps(CONFIG))

    assert Settings.from_file(path).model.model_id == "acme:acme-model"


def test_settings_from_file_missing(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="Config file not found"):
        Settings.from_file(tmp_path / "absent.json")


def test_settings_from_file_invalid_json(tmp_path: Path) -> None:
    path = tmp_path / "config.json"
    path.write_text("{not json")

    with pytest.raises(ConfigError, match="not valid JSON"):
        Settings.from_file(path)


def test_thinking_from_cli() -> None:
    assert thinking_from_cli("HIGH") == "high"
    assert thinking_from_cli("true") is True
    assert thinking_from_cli("false") is False
    assert thinking_from_cli(None) is None


def test_thinking_label() -> None:
    assert thinking_label(None) == "provider default"
    assert thinking_label(True) == "enabled"
    assert thinking_label(False) == "disabled"
    assert thinking_label("high") == "high"


_REPO_CONFIG = json.loads(
    (Path(__file__).resolve().parents[1] / "config.json").read_text()
)


@pytest.mark.parametrize(
    ("provider", "model"),
    [
        (provider, model)
        for provider, provider_config in _REPO_CONFIG["providers"].items()
        for model in provider_config["models"]
    ],
)
def test_shipped_config_matches_the_model_thinking_profile(
    provider: str, model: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`can_disable` is a claim about the model; keep it honest.

    pydantic-ai treats `thinking=False` on a model that always reasons as
    "use the lowest effort", so a wrong claim here would let an "off" run be
    recorded while the model was still thinking.
    """
    monkeypatch.setenv(f"{provider.upper().replace('-', '_')}_API_KEY", "test-key")

    profile = infer_model(f"{provider}:{model}").profile or {}
    declared = _REPO_CONFIG["providers"][provider]["models"][model].get("thinking", {})

    assert declared.get("can_disable", False) is not profile.get(
        "thinking_always_enabled", False
    )
