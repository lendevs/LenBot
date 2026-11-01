"""Telegram and Feishu connection settings, independent of host and scene assembly."""

from __future__ import annotations

import re
from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, Field, field_validator, model_validator

from .types import STRICT


def _https_base(value: str) -> str:
    parts = urlsplit(value)
    if (parts.scheme not in {"http", "https"} or not parts.netloc or parts.username is not None
            or parts.password is not None or parts.query or parts.fragment):
        raise ValueError("must be an HTTP(S) URL without credentials, query or fragment")
    return value.rstrip("/")


def _proxy(value: str | None) -> str | None:
    if value is not None and (urlsplit(value).scheme not in {"http", "https"} or not urlsplit(value).netloc):
        raise ValueError("proxy must be an http or https URL")
    return value


class TelegramSettings(BaseModel):
    model_config = STRICT

    bot_id: str = Field(description="Bot 账号，telegram:<数字 ID>，即令牌冒号前的数字。")
    bot_token: str = Field(repr=False, description="BotFather 给出的令牌。")
    api_url: str = Field(default="https://api.telegram.org", description="Bot API 地址；自建 Bot API 服务时修改。")
    proxy: str | None = Field(default=None, description="访问 Bot API 的 HTTP 代理，例如 http://127.0.0.1:7890。")
    poll_timeout_seconds: int = Field(default=30, ge=1, le=50, strict=True)
    request_timeout_seconds: float = Field(default=15.0, gt=0, allow_inf_nan=False)

    @field_validator("bot_token")
    @classmethod
    def valid_token(cls, value: str) -> str:
        if re.fullmatch(r"[1-9][0-9]*:[A-Za-z0-9_-]{20,}", value) is None:
            raise ValueError("bot_token must be <bot id>:<secret> as issued by BotFather")
        return value

    @field_validator("api_url")
    @classmethod
    def valid_api_url(cls, value: str) -> str:
        return _https_base(value)

    @field_validator("proxy")
    @classmethod
    def valid_proxy(cls, value: str | None) -> str | None:
        return _proxy(value)

    @model_validator(mode="after")
    def bot_matches_token(self) -> TelegramSettings:
        if self.bot_id != "telegram:" + self.bot_token.split(":", 1)[0]:
            raise ValueError("bot_id must be telegram:<the number before the colon in bot_token>")
        return self


FEISHU_DOMAINS = {"feishu": "https://open.feishu.cn", "lark": "https://open.larksuite.com"}


class FeishuSettings(BaseModel):
    model_config = STRICT

    bot_id: str = Field(description="机器人账号，feishu:<open_id>，连接测试时由机器人信息接口取得。")
    app_id: str = Field(description="企业自建应用的 App ID。")
    app_secret: str = Field(repr=False, description="企业自建应用的 App Secret。")
    domain: Literal["feishu", "lark"] = Field(default="feishu", description="飞书或国际版 Lark。")
    request_timeout_seconds: float = Field(default=15.0, gt=0, allow_inf_nan=False)

    @field_validator("bot_id")
    @classmethod
    def valid_bot(cls, value: str) -> str:
        if re.fullmatch(r"feishu:ou_[A-Za-z0-9]+", value) is None:
            raise ValueError("bot_id must be feishu:ou_<open_id>")
        return value

    @field_validator("app_id")
    @classmethod
    def valid_app(cls, value: str) -> str:
        if re.fullmatch(r"cli_[A-Za-z0-9]+", value) is None:
            raise ValueError("app_id must look like cli_xxx")
        return value

    @field_validator("app_secret")
    @classmethod
    def valid_secret(cls, value: str) -> str:
        if not value or any(character.isspace() for character in value):
            raise ValueError("app_secret must be nonempty without whitespace")
        return value

    @property
    def base_url(self) -> str:
        return FEISHU_DOMAINS[self.domain]
