"""Минимальные pydantic-модели Telegram Update (нужен только нам подмножество полей).

Назначение:
- валидация входа webhook → 400 на невалидный JSON;
- типизированный доступ в обработчике вместо `isinstance(msg, dict)` и `.get()`.

extra="ignore" — Telegram добавляет новые поля; мы их просто пропускаем.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict


class TgUser(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: int
    is_bot: bool | None = None
    first_name: str | None = None
    last_name: str | None = None
    username: str | None = None
    language_code: str | None = None


class TgChat(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: int
    type: str | None = None


class TgVoice(BaseModel):
    model_config = ConfigDict(extra="ignore")
    file_id: str
    duration: int | None = None
    mime_type: str | None = None
    file_size: int | None = None


class TgAudio(BaseModel):
    model_config = ConfigDict(extra="ignore")
    file_id: str
    duration: int | None = None
    mime_type: str | None = None
    file_size: int | None = None
    title: str | None = None


class TgMessage(BaseModel):
    model_config = ConfigDict(extra="ignore")
    message_id: int | None = None
    date: int | None = None
    from_user: TgUser | None = None  # заполняется вручную из ключа "from"
    chat: TgChat | None = None
    text: str | None = None
    caption: str | None = None
    voice: TgVoice | None = None
    audio: TgAudio | None = None

    @classmethod
    def from_raw(cls, raw: dict[str, Any]) -> "TgMessage":
        """Telegram шлёт поле `from`, а Pydantic не может использовать его как имя атрибута."""
        data = dict(raw)
        if "from_user" not in data and "from" in data:
            data["from_user"] = data.pop("from")
        return cls.model_validate(data)


class TgUpdate(BaseModel):
    """Update с любым из сообщений: message, edited_message, channel_post, business_message."""

    model_config = ConfigDict(extra="ignore")
    update_id: int
    message: TgMessage | None = None
    edited_message: TgMessage | None = None
    channel_post: TgMessage | None = None
    business_message: TgMessage | None = None

    @classmethod
    def from_raw(cls, raw: dict[str, Any]) -> "TgUpdate":
        data = dict(raw)
        for key in ("message", "edited_message", "channel_post", "business_message"):
            if key in data and isinstance(data[key], dict):
                # Переименуем from → from_user в каждом сообщении
                data[key] = dict(data[key])
                if "from" in data[key] and "from_user" not in data[key]:
                    data[key]["from_user"] = data[key].pop("from")
        return cls.model_validate(data)

    def primary_message(self) -> TgMessage | None:
        return self.message or self.business_message or self.edited_message or self.channel_post
