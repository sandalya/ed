"""Base transport interface."""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class BotResponse:
    """Відповідь бота на тестове повідомлення."""
    text: str
    response_time: float
    has_photos: bool = False
    photo_count: int = 0
    has_buttons: bool = False
    button_texts: list = field(default_factory=list)
    button_data: list = field(default_factory=list)
    raw_messages: list = field(default_factory=list)
    error: Optional[str] = None
    all_texts: list = field(default_factory=list)
    caption_texts: list = field(default_factory=list)
    pinned_text: str = ""
    pinned_buttons: list = field(default_factory=list)


class BaseTransport(ABC):
    """Абстрактний transport для спілкування з ботом."""

    @abstractmethod
    async def connect(self):
        ...

    @abstractmethod
    async def send_message(self, text: str) -> BotResponse:
        ...

    @abstractmethod
    async def send_command(self, command: str) -> BotResponse:
        ...

    @abstractmethod
    async def disconnect(self):
        ...

    async def reset_conversation(self):
        """Скинути контекст розмови."""
        pass

    async def click_button(self, button_text: str = "", button_data: str = "") -> BotResponse:
        """Натиснути inline кнопку. Шукає по тексту або callback_data."""
        raise NotImplementedError("Transport не підтримує click_button")

    async def send_photo(self, photo_path: str, caption: str = "") -> BotResponse:
        """Надіслати фото боту."""
        raise NotImplementedError("Transport не підтримує send_photo")

    async def get_admin_messages(self, count: int = 1, timeout: float = 10) -> list:
        """Отримати останні повідомлення в адмін-чаті."""
        raise NotImplementedError("Transport не підтримує get_admin_messages")
