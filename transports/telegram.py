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

RESPONSE_TIMEOUT = 90  # Garcia з search_products може відповідати 60+ секунд
MULTI_MESSAGE_DELAY = 2.0
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
        self._last_messages: list = []  # для click_button

    async def connect(self):
        await self.client.start(phone=TELEGRAM_PHONE)
        self._bot_entity = await self.client.get_entity(self.bot_username)
        log.info(f"Connected, target bot: {self.bot_username}")

        @self.client.on(events.NewMessage(from_users=self._bot_entity.id))
        async def on_bot_message(event):
            self._responses.append(event.message)
            self._response_event.set()

        @self.client.on(events.MessageEdited(from_users=self._bot_entity.id))
        async def on_bot_edit(event):
            # Для FSM-флоу на edit_message_text (flashcards, exam)
            # Замінюємо існуюче повідомлення з тим самим id на нову версію,
            # або додаємо як нове якщо не знайдено.
            edited = event.message
            replaced = False
            for i, m in enumerate(self._responses):
                if getattr(m, "id", None) == edited.id:
                    self._responses[i] = edited
                    replaced = True
                    break
            if not replaced:
                self._responses.append(edited)
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
        self._last_messages = list(self._responses)
        return self._build_response(elapsed)

    def _build_response(self, elapsed: float) -> BotResponse:
        texts = []
        all_texts = []
        caption_texts = []
        has_photos = False
        photo_count = 0
        has_buttons = False
        button_texts = []
        button_data = []
        raw = []

        for msg in self._responses:
            if msg.raw_text:
                texts.append(msg.raw_text)
                all_texts.append(msg.raw_text)
            if isinstance(msg.media, MessageMediaPhoto):
                has_photos = True
                photo_count += 1
                if msg.message:  # caption
                    caption_texts.append(msg.message)
                    if msg.message not in all_texts:
                        all_texts.append(msg.message)
            if isinstance(msg.reply_markup, ReplyInlineMarkup):
                has_buttons = True
                for row in msg.reply_markup.rows:
                    for btn in row.buttons:
                        button_texts.append(btn.text)
                        if hasattr(btn, "data") and btn.data:
                            bd = btn.data.decode("utf-8") if isinstance(btn.data, bytes) else str(btn.data)
                            button_data.append(bd)
            raw.append({
                "text": msg.raw_text or "",
                "has_photo": isinstance(msg.media, MessageMediaPhoto),
                "caption": msg.message if isinstance(msg.media, MessageMediaPhoto) else "",
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
            photo_count=photo_count,
            has_buttons=has_buttons,
            button_texts=button_texts,
            button_data=button_data,
            raw_messages=raw,
            all_texts=all_texts,
            caption_texts=caption_texts,
        )

    async def click_button(self, button_text: str = "", button_data: str = "") -> BotResponse:
        """Натиснути inline кнопку з останньої відповіді бота."""
        if not self._last_messages:
            return BotResponse(text="", response_time=0, error="No previous messages with buttons")

        target_msg = None
        target_btn = None

        for msg in reversed(self._last_messages):
            if not isinstance(msg.reply_markup, ReplyInlineMarkup):
                continue
            for row in msg.reply_markup.rows:
                for btn in row.buttons:
                    if button_text and btn.text == button_text:
                        if not hasattr(btn, "data"):
                            continue
                        target_msg = msg
                        target_btn = btn
                        break
                    if button_data and hasattr(btn, "data"):
                        bd = btn.data.decode("utf-8") if isinstance(btn.data, bytes) else str(btn.data)
                        if bd == button_data or bd.startswith(button_data):
                            target_msg = msg
                            target_btn = btn
                            break
                if target_btn:
                    break
            if target_btn:
                break

        if not target_btn:
            search = button_text or button_data
            available = []
            for msg in self._last_messages:
                if isinstance(msg.reply_markup, ReplyInlineMarkup):
                    for row in msg.reply_markup.rows:
                        for btn in row.buttons:
                            available.append(btn.text)
            return BotResponse(
                text="", response_time=0,
                error=f"Button \'{search}\' not found. Available: {available}",
            )

        self._responses.clear()
        self._response_event.clear()

        start_time = time.time()
        await target_msg.click(data=target_btn.data)
        log.info(f"Clicked button: \'{target_btn.text}\'")

        try:
            await asyncio.wait_for(
                self._response_event.wait(), timeout=RESPONSE_TIMEOUT,
            )
        except asyncio.TimeoutError:
            return BotResponse(
                text="", response_time=RESPONSE_TIMEOUT,
                error=f"Timeout after clicking \'{target_btn.text}\'",
            )

        while True:
            last_count = len(self._responses)
            await asyncio.sleep(MULTI_MESSAGE_DELAY)
            if len(self._responses) == last_count:
                break

        elapsed = time.time() - start_time
        self._last_messages = list(self._responses)
        return self._build_response(elapsed)

    async def send_photo(self, photo_path: str, caption: str = "") -> BotResponse:
        """Надіслати фото боту."""
        self._responses.clear()
        self._response_event.clear()

        start_time = time.time()
        await self.client.send_file(self._bot_entity, photo_path, caption=caption)
        log.info(f"Sent photo: {photo_path}")

        try:
            await asyncio.wait_for(
                self._response_event.wait(), timeout=RESPONSE_TIMEOUT,
            )
        except asyncio.TimeoutError:
            return BotResponse(
                text="", response_time=RESPONSE_TIMEOUT,
                error="Timeout: бот не відповів на фото",
            )

        while True:
            last_count = len(self._responses)
            await asyncio.sleep(MULTI_MESSAGE_DELAY)
            if len(self._responses) == last_count:
                break

        elapsed = time.time() - start_time
        self._last_messages = list(self._responses)
        return self._build_response(elapsed)

    async def get_admin_messages(self, count: int = 1, timeout: float = 5) -> list:
        """Читає останні повідомлення з адмін-чату (ADMIN_VERIFY_CHAT_ID)."""
        from config import ADMIN_VERIFY_CHAT_ID

        if not ADMIN_VERIFY_CHAT_ID:
            return [{"error": "ADMIN_VERIFY_CHAT_ID not set in .env"}]

        await asyncio.sleep(timeout)

        entity = await self.client.get_entity(ADMIN_VERIFY_CHAT_ID)
        messages = await self.client.get_messages(entity, limit=count)

        result = []
        for msg in messages:
            result.append({
                "text": msg.raw_text or "",
                "has_photo": isinstance(msg.media, MessageMediaPhoto),
                "buttons": [
                    b.text
                    for row in (msg.reply_markup.rows if isinstance(msg.reply_markup, ReplyInlineMarkup) else [])
                    for b in row.buttons
                ],
                "date": msg.date.isoformat() if msg.date else "",
            })
        return result

    async def reset_conversation(self, include_start: bool = True):
        # /cancel відправляємо fire-and-forget (деякі боти не відповідають на нього,
        # і тоді send_command висить RESPONSE_TIMEOUT секунд). Відповідь тут не потрібна.
        await self.client.send_message(self._bot_entity, "/cancel")
        log.info("Sent: /cancel (no wait)")
        await asyncio.sleep(0.5)
        if include_start:
            # /start відправляємо нормально — очікуємо welcome-повідомлення
            await self.send_command("/start")
            await asyncio.sleep(1)
            log.info("Conversation reset via /cancel + /start")
        else:
            log.info("Conversation reset via /cancel only (test starts with /start)")


    async def get_pinned_message(self) -> tuple:
        """
        Повертає (raw_text, [button_texts]) закріпленого повідомлення у чаті з ботом.
        Якщо немає — ("", []).
        """
        from telethon.tl.functions.messages import GetHistoryRequest
        from telethon.tl.types import ReplyInlineMarkup
        try:
            full = await self.client.get_entity(self._bot_entity)
            # Отримуємо messages з фільтром pinned
            from telethon.tl.types import InputMessagesFilterPinned
            pinned_msgs = await self.client.get_messages(
                self._bot_entity, limit=1, filter=InputMessagesFilterPinned
            )
            if not pinned_msgs:
                return ("", [])
            msg = pinned_msgs[0]
            text = msg.raw_text or ""
            buttons = []
            if isinstance(msg.reply_markup, ReplyInlineMarkup):
                for row in msg.reply_markup.rows:
                    for btn in row.buttons:
                        buttons.append(btn.text)
            return (text, buttons)
        except Exception as e:
            import logging
            logging.getLogger("ed.transport.telegram").warning(f"get_pinned_message failed: {e}")
            return ("", [])

    async def disconnect(self):
        await self.client.disconnect()
        log.info("Disconnected from Telegram")
