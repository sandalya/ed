"""Direct transport — викликає бота напряму без Telegram."""
import logging
import sys
import time
from .base import BaseTransport, BotResponse

log = logging.getLogger("ed.transport.direct")

BOT_PATHS = {
    "insilver": "/home/sashok/.openclaw/workspace/insilver-v3",
    "abby": "/home/sashok/.openclaw/workspace/abby-v2",
    "garcia": "/home/sashok/.openclaw/workspace/garcia",
}


class DirectTransport(BaseTransport):
    """Викликає бота напряму — без Telegram."""

    def __init__(self, bot_name: str = "insilver"):
        self.bot_name = bot_name
        self.bot_path = BOT_PATHS.get(bot_name, BOT_PATHS["insilver"])
        self._ask_fn = None
        self._brain = None
        self._history: list = []

    async def connect(self):
        if self.bot_path not in sys.path:
            sys.path.insert(0, self.bot_path)

        if self.bot_name == "garcia":
            from modules.brain import GarciaBrain
            self._brain = GarciaBrain()
            log.info(f"Direct transport ready, bot: garcia (GarciaBrain)")
        else:
            from core.ai import ask_ai
            self._ask_fn = ask_ai
            log.info(f"Direct transport ready, bot: {self.bot_path}")

    async def send_message(self, text: str) -> BotResponse:
        start_time = time.time()
        try:
            if self._brain:
                reply = self._brain.run(text)
            else:
                reply = await self._ask_fn(
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
            error="Direct transport does not support commands. Use Telegram transport.",
        )

    async def reset_conversation(self):
        self._history.clear()
        if self._brain:
            self._brain.reset_history()
        log.info("Direct transport: history cleared")

    async def disconnect(self):
        self._history.clear()
        if self._brain:
            self._brain.reset_history()
        log.info("Direct transport disconnected")
