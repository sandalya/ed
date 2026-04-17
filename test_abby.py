"""Тест Еббі через Telethon — надсилає промпт з референсом і чекає відповідь."""
import asyncio
import time
import sys
sys.path.insert(0, '/home/sashok/.openclaw/workspace/ed')

from telethon import TelegramClient, events
from config import TELEGRAM_API_ID, TELEGRAM_API_HASH, TELEGRAM_PHONE, SESSION_PATH

ABBY_BOT = "@abby_ksu_bot"
REFERENCE_IMAGE = "/home/sashok/.openclaw/media/inbound/file_120---989cf397-1660-477d-9f27-2e322055c8c6.jpg"
PROMPT = "Згенеруй зображення у такому ж стилі і кольорах розміром 1050 * 350, на тему «форми заробітку в інтернеті для бразильців». Використай наступні елементи: ноутбук, телефон, значки грошей, криптовалют, графіки. Створи красиву композицію"

TIMEOUT = 60

async def test():
    client = TelegramClient(SESSION_PATH, TELEGRAM_API_ID, TELEGRAM_API_HASH)
    await client.start(phone=TELEGRAM_PHONE)

    bot = await client.get_entity(ABBY_BOT)
    print(f"Connected to {ABBY_BOT}")

    responses = []
    done = asyncio.Event()

    @client.on(events.NewMessage(from_users=bot.id))
    async def on_reply(event):
        responses.append(event.message)
        # Чекаємо ще 5 секунд на додаткові повідомлення
        done.set()

    # Надсилаємо фото + текст
    print(f"Sending reference image + prompt...")
    await client.send_file(bot, REFERENCE_IMAGE, caption=PROMPT)
    start = time.time()

    try:
        await asyncio.wait_for(done.wait(), timeout=TIMEOUT)
        await asyncio.sleep(5)  # чекаємо додаткові повідомлення
    except asyncio.TimeoutError:
        print(f"Timeout {TIMEOUT}s — бот не відповів")
        await client.disconnect()
        return

    elapsed = time.time() - start
    print(f"\nОтримано {len(responses)} повідомлень за {elapsed:.1f}s:")
    for i, msg in enumerate(responses):
        if msg.text:
            print(f"  [{i+1}] TEXT: {msg.text[:200]}")
        if msg.media:
            print(f"  [{i+1}] MEDIA: {type(msg.media).__name__}")

    await client.disconnect()

asyncio.run(test())
