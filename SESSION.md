# SESSION — 2026-04-18 15:10

## Проект
ed

## Що зробили
Повний перформанс-реворк: роутер direct/telegram per-case + parallel direct (Sem=5, дефолт) + async judge через asyncio.to_thread (критичне — без цього фальшивий паралелізм) + reset_conversation fire-and-forget /cancel (зекономило 90с на reset) + prompt caching на judge-рубриці (ephemeral, 86% дешевше input на Sonnet/insilver). Результати: abby 3m50s→1m41s (2.3x), insilver 34 кейсів ~10хв→355s (Sonnet judge). Direct-гілка сама 7x швидша через справжній паралелізм.

## Наступний крок
Головне: Ed готовий до інтенсивних прогонів insilver з --parallel 10. Відкрите: Abby 400 Bad Request регресія в abby-v2/core/ai.py (messages.1.content.0 неправильний формат) — блокує більшість direct-кейсів. Insilver знайдено 14 критичних багів у order_funnel (length_other, coating_other, comment_flow, cancel_mid_flow) і handoff_human_request — це для Vlad-сесії.

## Контекст
8 commits на main: router.py + evaluator max_retries=8 → main.py auto+parallel → engine.py per-case routing + Semaphore → evaluator asyncio.to_thread (без цього Semaphore було декорацією, judge блокував event loop) → loader block naming fix → telegram /cancel no-wait → prompt caching на рубриці з cache metrics в логах. Tier 4 API: 4K RPM Sonnet/Haiku/Opus, Batch 4K/min, паралелізм можна сміло 10-20. Розміри рубрик: ABBY 525 tok, INSILVER 622 tok — caching активний тільки на Sonnet (system разом >1024). ed_bot.log треба додати в .gitignore.
