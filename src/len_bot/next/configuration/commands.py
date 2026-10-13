"""Host commands typed in a scene (``/help``, ``/status`` ...), switched in the root configuration."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator

from .types import STRICT

CommandName = Literal["help", "id", "status", "chat", "quiet", "resume", "reset", "model", "limit", "角色"]


class CommandSettings(BaseModel):
    model_config = STRICT

    # Off: every message, commands included, reaches the conversation as before.
    enabled: bool = True
    # Commands turned off one by one; their text then reaches the conversation as an ordinary message.
    disabled: list[CommandName] = Field(default_factory=list)
    # On: a group's owner and admins may also use /chat on|off and /reset there. Off (the default): only
    # the bot's owners and global admins may, as when the switch and a new context were panel actions.
    group_managers_chat_reset: bool = False

    @field_validator("disabled")
    @classmethod
    def distinct(cls, values: list[str]) -> list[str]:
        if len(values) != len(set(values)):
            raise ValueError("disabled commands must not repeat")
        return values
