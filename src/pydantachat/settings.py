"""Application configuration.

Everything except secrets lives in `config.json`:

- `default_provider` / `default_model` / `default_thinking` — what to run.
- `providers.<provider>.models.<model>.thinking` — the effort levels that
  model accepts, and whether it can stop reasoning at all.
- `tracing.endpoint` / `tracing.service_name` — where spans are exported.

Secrets are API keys and nothing else, read from the environment (`.env`) under
the names Pydantic AI itself uses, i.e. `<PROVIDER>_API_KEY`.
"""

import json
import os
from dataclasses import dataclass
from functools import cache
from pathlib import Path

from dotenv import load_dotenv
from pydantic import BaseModel, Field, ValidationError, model_validator
from pydantic_ai.settings import ModelSettings, ThinkingLevel

# The providers read their key from the environment themselves, so the one
# thing `.env` has to do is put it there.
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
    """A resolved provider/model/thinking triple that `config.json` allows."""

    provider: str
    model: str
    thinking: ThinkingLevel | None = None

    @property
    def model_id(self) -> str:
        return f"{self.provider}:{self.model}"

    @property
    def model_settings(self) -> ModelSettings | None:
        if self.thinking is None:
            return None
        return ModelSettings(thinking=self.thinking)

    @property
    def api_key_env(self) -> str:
        return f"{self.provider.upper().replace('-', '_')}_API_KEY"

    @property
    def has_api_key(self) -> bool:
        return bool(os.getenv(self.api_key_env))


class ThinkingConfig(BaseModel):
    """What a model's thinking control really offers.

    `levels` are the effort levels it accepts; `can_disable` says whether
    thinking can actually be stopped. A model that always reasons takes its
    lowest effort when asked for `False`, so refusing the request is how "off"
    stays honest.
    """

    levels: list[ThinkingLevel] = Field(default_factory=list)
    can_disable: bool = False

    def check(self, label: str, thinking: ThinkingLevel) -> None:
        """Raise unless this model can be asked for `thinking`."""
        levels = ", ".join(thinking_label(level) for level in self.levels) or "none"
        if thinking is False and not self.can_disable:
            raise ConfigError(
                f"Thinking cannot be disabled for {label}: it always reasons "
                f"(levels: {levels})."
            )
        if thinking is True and not self.levels and not self.can_disable:
            raise ConfigError(f"{label} has no thinking setting.")
        if thinking not in (True, False, *self.levels):
            raise ConfigError(
                f"Thinking {thinking!r} is not allowed for {label} (allowed: {levels})."
            )


class ModelSpec(BaseModel):
    """One allowed model. Thinking support varies model by model, so the
    allow-lists live here rather than on the provider."""

    thinking: ThinkingConfig = Field(default_factory=ThinkingConfig)


class ProviderConfig(BaseModel):
    """The models the app may request from one provider."""

    models: dict[str, ModelSpec] = Field(min_length=1)


class TracingConfig(BaseModel):
    """OTel export target; `endpoint` is the OTLP base URL (`null` turns
    tracing off), e.g. `http://localhost:6006` for Phoenix."""

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
        self.resolve()  # fail at load, not on the first request
        return self

    @property
    def model(self) -> ModelConfig:
        return self.resolve()

    def resolve(
        self,
        provider: str | None = None,
        model: str | None = None,
        thinking: ThinkingLevel | None = None,
    ) -> ModelConfig:
        """Return an allowed model, overriding the defaults where given.

        `thinking=None` keeps the configured default when the default model is
        selected, and sends no thinking setting for any other model. Pass
        `False` to ask for thinking to be off.
        """
        provider = provider or self.default_provider
        provider_config = self.providers.get(provider)
        if provider_config is None:
            known = ", ".join(sorted(self.providers)) or "none"
            raise ConfigError(
                f"Provider {provider!r} is not configured in config.json "
                f"(known: {known})."
            )
        models = provider_config.models

        if model is None:
            if provider != self.default_provider:
                raise ConfigError(
                    f"No model given for {provider!r}; "
                    f"pass one of: {', '.join(models)}."
                )
            model = self.default_model

        spec = models.get(model)
        if spec is None:
            raise ConfigError(
                f"Model {model!r} is not allowed for {provider!r} "
                f"(allowed: {', '.join(models) or 'none'})."
            )

        if thinking is None and (provider, model) == (
            self.default_provider,
            self.default_model,
        ):
            thinking = self.default_thinking
        if thinking is not None:
            spec.thinking.check(f"{provider}:{model}", thinking)

        return ModelConfig(provider, model, thinking)

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


@dataclass(frozen=True)
class AuthConfig:
    """Google OIDC and session settings. All of it is secret or deployment
    specific, so it comes from the environment, never from `config.json`."""

    google_client_id: str
    google_client_secret: str
    session_secret: str
    allowed_emails: frozenset[str]
    app_base_url: str

    @property
    def https(self) -> bool:
        return self.app_base_url.startswith("https")

    @property
    def redirect_uri(self) -> str:
        return f"{self.app_base_url}/auth"

    def is_allowed(self, email: str | None) -> bool:
        """Fail closed: an empty allowlist admits nobody.

        zuchat's `is_allowed` treats an empty list as "any Google account", which
        is fine for a static page and wrong for endpoints that spend money.
        """
        return bool(email) and email.lower() in self.allowed_emails

    @classmethod
    def from_env(cls) -> AuthConfig:
        required = {
            name: os.getenv(name, "").strip()
            for name in (
                "GOOGLE_CLIENT_ID",
                "GOOGLE_CLIENT_SECRET",
                "SESSION_SECRET",
                "ALLOWED_EMAILS",
            )
        }
        missing = [name for name, value in required.items() if not value]
        if missing:
            raise ConfigError(f"Set {', '.join(missing)} in .env to serve the API.")

        emails = frozenset(
            email.strip().lower()
            for email in required["ALLOWED_EMAILS"].split(",")
            if email.strip()
        )
        if not emails:
            raise ConfigError(
                "ALLOWED_EMAILS lists no addresses; the API fails closed rather "
                "than let any Google account spend money."
            )

        return cls(
            google_client_id=required["GOOGLE_CLIENT_ID"],
            google_client_secret=required["GOOGLE_CLIENT_SECRET"],
            session_secret=required["SESSION_SECRET"],
            allowed_emails=emails,
            app_base_url=os.getenv("APP_BASE_URL", "http://localhost:8000").rstrip("/"),
        )


@cache
def get_auth() -> AuthConfig:
    """The auth configuration, loaded once from the environment."""
    return AuthConfig.from_env()
