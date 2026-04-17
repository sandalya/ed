"""Telegram transport via Telethon userbot."""
import asyncio
import logging
import time
from telethon import TelegramClient, events
from telethon.tl.types import (
    MessageMediaPhoto,
    ReplyInlineMarkup,
)
from .base import BaseTransport, BotResponse
from config import (
    TELEGRAM_API_ID, TELEGRAM_API_HASH, TELEGRAM_PHONE,
    SESSION_PATH, TARGET_BOT_USERNAME,
)

log = logging.getLogger("ed.transport.telegram")

RESPONSE_TIMEOUT = 30
MULTI_MESSAGE_DELAY = 0.8  # змінюй тут для відкату
BETWEEN_MESSAGES_DELAY = 2


class TelegramTransport(BaseTransport):
    """Спілкується з ботом через Telegram як справжній юзер."""

    def __init__(self, bot_username: str = ""):
        self.bot_username = bot_username or TARGET_BOT_USERNAME
        self.client = TelegramClient(
            SESSION_PATH, TELEGRAM_API_ID, TELEGRAM_API_HASH,
        )
        self._responses: list = []
        self._response_event = asyncio.Event()
        self._bot_entity = None

    async def connect(self):
        await self.client.start(phone=TELEGRAM_PHONE)
        self._bot_entity = await self.client.get_entity(self.bot_username)
        log.info(f"Connected, target bot: {self.bot_username}")

        @self.client.on(events.NewMessage(from_users=self._bot_entity.id))
        async def on_bot_message(event):
            self._responses.append(event.message)
            self._response_event.set()

    async def send_message(self, text: str) -> BotResponse:
        return await self._send_and_collect(text)

    async def send_command(self, command: str) -> BotResponse:
        if not command.startswith("/"):
            command = f"/{command}"
        return await self._send_and_collect(command)

    async def _send_and_collect(self, text: str) -> BotResponse:
        self._responses.clear()
        self._response_event.clear()

        # Telethon не може відправити порожнє повідомлення
        if not text or not text.strip():
            return BotResponse(
                text="", response_time=0,
                error="Cannot send empty message via Telegram",
            )

        start_time = time.time()
        await self.client.send_message(self._bot_entity, text)
        log.info(f"Sent: {text[:80]}")

        try:
            await asyncio.wait_for(
                self._response_event.wait(), timeout=RESPONSE_TIMEOUT,
            )
        except asyncio.TimeoutError:
            return BotResponse(
                text="", response_time=RESPONSE_TIMEOUT,
                error=f"Timeout: бот не відповів за {RESPONSE_TIMEOUT}с",
            )

        while True:
            last_count = len(self._responses)
            await asyncio.sleep(MULTI_MESSAGE_DELAY)
            if len(self._responses) == last_count:
                break
        elapsed = time.time() - start_time
        return self._build_response(elapsed)

    def _build_response(self, elapsed: float) -> BotResponse:
        texts = []
        has_photos = False
        has_buttons = False
        button_texts = []
        raw = []

        for msg in self._responses:
            if msg.text:
                texts.append(msg.text)
            if isinstance(msg.media, MessageMediaPhoto):
                has_photos = True
            if isinstance(msg.reply_markup, ReplyInlineMarkup):
                has_buttons = True
                for row in msg.reply_markup.rows:
                    for btn in row.buttons:
                        button_texts.append(btn.text)
            raw.append({
                "text": msg.text or "",
                "has_photo": isinstance(msg.media, MessageMediaPhoto),
                "buttons": [
                    b.text
                    for row in (msg.reply_markup.rows if isinstance(msg.reply_markup, ReplyInlineMarkup) else [])
                    for b in row.buttons
                ],
            })

        return BotResponse(
            text="\n\n".join(texts),
            response_time=elapsed,
            has_photos=has_photos,
            has_buttons=has_buttons,
            button_texts=button_texts,
            raw_messages=raw,
        )

    async def reset_conversation(self):
        await self.send_command("/start")
        await asyncio.sleep(1)
        log.info("Conversation reset via /start")

    async def disconnect(self):
        await self.client.disconnect()
        log.info("Disconnected from Telegram")
