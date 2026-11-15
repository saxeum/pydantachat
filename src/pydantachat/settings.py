"""Application configuration.

Everything except secrets lives in `config.json`:

- `default_provider` / `default_model` / `default_thinking` — what to run.
- `providers.<name>.models` — the models that may be requested, each with the
  thinking control it really offers (`thinking.levels`, `thinking.can_disable`).
- `tracing.endpoint` / `tracing.service_name` — where spans are exported.

Secrets are API keys and nothing else, and they only ever come from the
environment (`.env`) under the same names Pydantic AI itself reads:
`DEEPSEEK_API_KEY`, `OPENAI_API_KEY`, `OPENROUTER_API_KEY`, i.e.
`<PROVIDER>_API_KEY` for whatever provider is selected.
"""

import json
import os
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import cast

from dotenv import load_dotenv
from pydantic import BaseModel, Field, ValidationError, model_validator
from pydantic_ai.settings import ModelSettings, ThinkingLevel

load_dotenv()

DEFAULT_CONFIG_PATH = Path("config.json")


class ConfigError(ValueError):
    """The configuration is missing, or forbids what was asked for."""


def thinking_label(thinking: ThinkingLevel | None) -> str:
    if thinking is None:
        return "provider default"
    if isinstance(thinking, bool):
        return "enabled" if thinking else "disabled"
    return str(thinking)


@dataclass(frozen=True)
class ModelConfig:
    """A fully resolved provider/model/thinking triple."""

    provider: str
    model: str
    thinking: ThinkingLevel | None = None

    def validate(self) -> None:
        """Raise if the provider or model is missing."""
        if not self.provider or not self.model:
            raise ConfigError(
                "Set default_provider and default_model in config.json, "
                "or pass --provider and --model."
            )

    @property
    def model_id(self) -> str:
        self.validate()
        return f"{self.provider}:{self.model}"

    @property
    def model_settings(self) -> ModelSettings | None:
        if self.thinking is None:
            return None
        return ModelSettings(thinking=self.thinking)

    @property
    def api_key_env(self) -> str:
        if not self.provider:
            return ""
        return f"{self.provider.upper().replace('-', '_')}_API_KEY"

    @property
    def has_api_key(self) -> bool:
        return bool(self.api_key_env and os.getenv(self.api_key_env))


class ThinkingConfig(BaseModel):
    """A model's thinking control.

    `levels` are the effort levels it accepts. `can_disable` says whether
    thinking can actually be turned off: many models reason always-on, and
    Pydantic AI then quietly sends the lowest effort instead, which would let
    "off" be recorded as a measurement it never was.
    """

    levels: list[ThinkingLevel] = Field(default_factory=list)
    can_disable: bool = False


class ModelCapabilities(BaseModel):
    """What one model accepts; thinking support varies model by model."""

    thinking: ThinkingConfig = Field(default_factory=ThinkingConfig)


class ProviderConfig(BaseModel):
    """The models the app may request from one provider."""

    models: dict[str, ModelCapabilities] = Field(min_length=1)


class TracingConfig(BaseModel):
    """OTel export target; `endpoint` is the OTLP base URL, e.g.
    `http://localhost:6006` for Phoenix. Unset means no tracing."""

    endpoint: str | None = None
    service_name: str = "pydantachat"


class Settings(BaseModel):
    """Contents of `config.json`, validated as one unit."""

    default_provider: str
    default_model: str
    default_thinking: ThinkingLevel | None = None
    providers: dict[str, ProviderConfig]
    tracing: TracingConfig = Field(default_factory=TracingConfig)

    @model_validator(mode="after")
    def _defaults_are_allowed(self) -> Settings:
        # Fails at load time rather than on the first request.
        self.resolve()
        return self

    def resolve(
        self,
        provider: str | None = None,
        model: str | None = None,
        thinking: ThinkingLevel | None = None,
    ) -> ModelConfig:
        """Return an allowed model, overriding the defaults where given.

        `thinking=None` means "use the configured default" when the default
        model itself is selected, and "send no thinking setting" for any other
        model. Pass `False` to ask for thinking to be off.
        """
        provider = provider or self.default_provider
        provider_config = self.providers.get(provider)
        if provider_config is None:
            known = ", ".join(sorted(self.providers)) or "none"
            raise ConfigError(
                f"Provider {provider!r} is not configured in config.json "
                f"(known: {known})."
            )

        if model is None:
            if provider != self.default_provider:
                allowed = ", ".join(provider_config.models)
                raise ConfigError(
                    f"No model given for {provider!r}; pass one of: {allowed}."
                )
            model = self.default_model

        capabilities = provider_config.models.get(model)
        if capabilities is None:
            allowed = ", ".join(provider_config.models) or "none"
            raise ConfigError(
                f"Model {model!r} is not allowed for {provider!r} (allowed: {allowed})."
            )

        if thinking is None and (provider, model) == (
            self.default_provider,
            self.default_model,
        ):
            thinking = self.default_thinking
        if thinking is not None:
            self._check_thinking(provider, model, thinking, capabilities.thinking)

        return ModelConfig(provider=provider, model=model, thinking=thinking)

    @staticmethod
    def _check_thinking(
        provider: str,
        model: str,
        thinking: ThinkingLevel,
        config: ThinkingConfig,
    ) -> None:
        levels = ", ".join(thinking_label(level) for level in config.levels) or "none"
        if thinking is False:
            if not config.can_disable:
                raise ConfigError(
                    f"Thinking cannot be disabled for {provider}:{model}: it "
                    f"always reasons (levels: {levels})."
                )
            return
        if thinking is True:
            if not config.levels and not config.can_disable:
                raise ConfigError(f"{provider}:{model} has no thinking setting.")
            return
        if thinking not in config.levels:
            raise ConfigError(
                f"Thinking {thinking!r} is not allowed for {provider}:{model} "
                f"(allowed: {levels})."
            )

    @property
    def model(self) -> ModelConfig:
        return self.resolve()

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> Settings:
        try:
            return cls.model_validate(data)
        except ValidationError as exc:
            raise ConfigError(f"config.json is invalid:\n{exc}") from exc

    @classmethod
    def from_file(cls, path: Path | str = DEFAULT_CONFIG_PATH) -> Settings:
        path = Path(path)
        try:
            data = json.loads(path.read_text())
        except FileNotFoundError as exc:
            raise ConfigError(
                f"Config file not found: {path}. Run from the project root or "
                "pass --config."
            ) from exc
        except json.JSONDecodeError as exc:
            raise ConfigError(f"{path} is not valid JSON: {exc}") from exc
        try:
            return cls.model_validate(data)
        except ValidationError as exc:
            raise ConfigError(f"{path} is invalid:\n{exc}") from exc


@cache
def get_settings() -> Settings:
    """The app's configuration, loaded once from `config.json`."""
    return Settings.from_file()


def thinking_from_cli(value: str | None) -> ThinkingLevel | None:
    """Coerce a `--thinking` argument; None keeps the configured default."""
    if value is None:
        return None
    lowered = value.strip().lower()
    if lowered == "true":
        return True
    if lowered == "false":
        return False
    return cast(ThinkingLevel, lowered)
