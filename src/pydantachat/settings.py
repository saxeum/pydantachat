"""Runtime configuration loaded from `.env` or the environment."""

import os
from dataclasses import dataclass
from typing import cast

from dotenv import load_dotenv
from pydantic_ai.settings import ModelSettings, ThinkingLevel

load_dotenv()

_THINKING_LEVELS = {"minimal", "low", "medium", "high", "xhigh", "max"}


def thinking_from_env() -> ThinkingLevel | None:
    raw = os.getenv("THINKING_LEVEL", "").strip()
    if not raw:
        return None
    value = raw.lower()
    if value == "true":
        return True
    if value == "false":
        return False
    if value in _THINKING_LEVELS:
        return cast(ThinkingLevel, value)
    raise ValueError(
        "THINKING_LEVEL must be true, false, or one of "
        f"{', '.join(sorted(_THINKING_LEVELS))}; got {raw!r}"
    )


@dataclass(frozen=True)
class ModelConfig:
    provider: str
    model: str
    thinking: ThinkingLevel | None = None

    def validate(self) -> None:
        """Raise if the provider or model is missing."""
        if not self.provider or not self.model:
            raise ValueError("Set PROVIDER and MODEL in .env to build the agent.")

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


@dataclass(frozen=True)
class Settings:
    model: ModelConfig

    @classmethod
    def from_env(cls) -> Settings:
        return cls(
            model=ModelConfig(
                provider=os.getenv("PROVIDER", "").strip(),
                model=os.getenv("MODEL", "").strip(),
                thinking=thinking_from_env(),
            )
        )


settings = Settings.from_env()
