# SESSION — 2026-04-18 15:20

## Проект
ed

## Що зробили
Повний перформанс-реворк Ed: роутер direct/telegram per-case + parallel direct (Sem=5 дефолт) + async judge через asyncio.to_thread + reset_conversation fire-and-forget /cancel + prompt caching на judge-рубриці (ephemeral). Abby 3m50s→1m41s (2.3x), insilver 34 кейсів ~10хв→355s. Direct-гілка сама 7x через справжній паралелізм. Оновлений docstring main.py з прикладами auto + parallel, argparse help коректний.

## Наступний крок
Готово для інтенсивних прогонів insilver (--parallel 10, Sonnet judge). Відкрите: Abby 400 Bad Request регресія в abby-v2/core/ai.py (messages.1.content.0 — неправильний формат), блокує direct-кейси. Insilver знайдено 14 критичних багів: order_funnel (length_other, coating_other, comment_flow, cancel_mid_flow), handoff_human_request, measurement_help_01 — для Vlad-сесії.

## Контекст
9 commits на main: router.py + evaluator max_retries=8 → main.py auto+parallel → engine.py per-case routing + Semaphore → evaluator asyncio.to_thread (КРИТИЧНО — без цього Semaphore декорація, judge блокував event loop) → loader block naming fix → telegram /cancel no-wait → prompt caching з cache metrics → main.py docstring update. Tier 4 API: 4K RPM Sonnet/Haiku/Opus, Batch 4K/min. Рубрики: ABBY 525 tok, INSILVER 622 tok — caching активний тільки на Sonnet бо system block з JUDGE_SYSTEM_PROMPT разом >1024. ed_bot.log треба додати в .gitignore.
