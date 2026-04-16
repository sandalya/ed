"""Direct transport — викликає ask_ai() напряму без Telegram."""
import logging
import sys
import time
from .base import BaseTransport, BotResponse

log = logging.getLogger("ed.transport.direct")

INSILVER_PATH = "/home/sashok/.openclaw/workspace/insilver-v3"


class DirectTransport(BaseTransport):
    """Викликає ask_ai() напряму — без Telegram."""

    def __init__(self, bot_path: str = INSILVER_PATH):
        self.bot_path = bot_path
        self._ask_ai = None
        self._history: list = []

    async def connect(self):
        if self.bot_path not in sys.path:
            sys.path.insert(0, self.bot_path)
        from core.ai import ask_ai
        self._ask_ai = ask_ai
        log.info(f"Direct transport ready, bot: {self.bot_path}")

    async def send_message(self, text: str) -> BotResponse:
        start_time = time.time()
        try:
            reply = await self._ask_ai(
                user_id=999999,
                message=text,
                history=self._history,
            )
            elapsed = time.time() - start_time

            self._history.append({"role": "user", "content": text})
            self._history.append({"role": "assistant", "content": reply})
            self._history = self._history[-20:]

            return BotResponse(text=reply, response_time=elapsed)
        except Exception as e:
            elapsed = time.time() - start_time
            return BotResponse(text="", response_time=elapsed, error=str(e))

    async def send_command(self, command: str) -> BotResponse:
        return BotResponse(
            text="", response_time=0,
            error="Direct transport не підтримує команди. Використай Telegram transport.",
        )

    async def reset_conversation(self):
        self._history.clear()
        log.info("Direct transport: history cleared")

    async def disconnect(self):
        self._history.clear()
        log.info("Direct transport disconnected")
