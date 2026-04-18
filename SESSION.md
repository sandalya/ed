# SESSION — 2026-04-18 13:26

## Проект
ed

## Що зробили
Автомат роутер direct/telegram + parallel direct (Sem=5) + async judge через asyncio.to_thread + reset_conversation fire-and-forget /cancel. Результат на abby: 3m50s→1m41s (2.3x). На самій direct-гілці: 63s→9s (7x паралелізм заробив нарешті).

## Наступний крок
Протестувати insilver (27/34 direct) з --parallel 5-10 — очікуваний приріст ще кращий. Окремо на потім: Abby 400 Bad Request регресія в abby-v2/core/ai.py (messages.1.content.0 неправильний формат — блокує майже всі direct-кейси, FAIL замість PASS). Опційно: prompt caching на judge-рубриках для +10-20%.

## Контекст
6 commits на main: router.py + evaluator max_retries=8 → main.py --transport auto (default) + --parallel → engine.py per-case routing + Semaphore → evaluator asyncio.to_thread (КРИТИЧНО для паралелізму — був sync виклик в async-функції) → loader block naming fix (--block smoke і --block 01_smoke обидва працюють) → telegram reset_conversation no-wait /cancel. Tier 4 API: 4K RPM Sonnet/Haiku/Opus, паралелізм можна підняти до 10-20 без страху 429. ed_bot.log треба додати в .gitignore.
