"""Telegram Bot API transport settings (long polling), independent of host and scene assembly."""

from __future__ import annotations

from urllib.parse import urlsplit

from pydantic import BaseModel, Field, field_validator

from .types import STRICT


class TelegramSettings(BaseModel):
    model_config = STRICT

    # From @BotFather; never logged or shown by the panel.
    bot_token: str = Field(min_length=1, repr=False)
    # A self-hosted Bot API server or a reverse proxy may replace the public one.
    api_base: str = "https://api.telegram.org"
    # Long polling: how long one getUpdates waits for new messages on the server side.
    poll_timeout_seconds: int = Field(default=25, ge=0, le=50)
    # Every other request, and the extra time a poll may take beyond its own timeout.
    request_timeout_seconds: float = Field(default=15.0, gt=0, le=300, allow_inf_nan=False)

    @field_validator("bot_token")
    @classmethod
    def plain_token(cls, value: str) -> str:
        if any(char.isspace() or char == "/" for char in value):
            raise ValueError("bot_token must be the token text from BotFather")
        return value

    @field_validator("api_base")
    @classmethod
    def http_base(cls, value: str) -> str:
        parts = urlsplit(value)
        if parts.scheme not in {"http", "https"} or not parts.netloc or parts.query or parts.fragment:
            raise ValueError("api_base must be an http(s) URL without query or fragment")
        return value.rstrip("/")
