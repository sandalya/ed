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
    has_buttons: bool = False
    button_texts: list = field(default_factory=list)
    raw_messages: list = field(default_factory=list)
    error: Optional[str] = None


class BaseTransport(ABC):
    """Абстрактний transport для спілкування з ботом."""

    @abstractmethod
    async def connect(self):
        """Підключитись до каналу."""
        ...

    @abstractmethod
    async def send_message(self, text: str) -> BotResponse:
        """Відправити повідомлення боту і отримати відповідь."""
        ...

    @abstractmethod
    async def send_command(self, command: str) -> BotResponse:
        """Відправити команду (/start, /help, etc)."""
        ...

    @abstractmethod
    async def disconnect(self):
        """Відключитись."""
        ...

    async def reset_conversation(self):
        """Скинути контекст розмови (опціонально)."""
        pass
