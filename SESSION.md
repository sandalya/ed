# SESSION — 2026-04-19 21:59

## Проект
ed

## Що зробили
спроєктували reference_fidelity suite для перевірки що Еббі не копіює композицію референсів; код не писали

## Наступний крок
реалізувати 6 кроків послідовно (див. контекст)

## Контекст
зміни в abby-v2 вже застосовані і працюють (text-only reference mode). Для Ed лишається: (1) в runner додати підтримку поля reference_image в JSON-кейсі — виклик send_photo замість send_message, ~15хв; (2) в telegram transport _build_response зберігати bytes першого згенерованого фото в BotResponse.generated_image_bytes через msg.download_media(bytes=True), додати поле в base.py як Optional з default None, ~15хв; (3) в judge/evaluator.py зробити vision-режим: якщо в evaluate() передано reference_bytes+generated_bytes — формувати content як список блоків [image(reference, label='REFERENCE'), image(generated, label='GENERATED'), text(prompt)], розширити JUDGE_SYSTEM_PROMPT секцією про оцінку композиційна_схожість vs стильова_схожість, ~40хв; (4) створити judge/rubrics/reference_fidelity.py з 3 критеріями: does_not_copy_composition(weight=3.0), preserves_mood_palette_lighting(weight=1.5), generates_requested_subject_not_reference_subject(weight=2.0), ~10хв; (5) створити suites/data/abby/blocks/06_reference_fidelity.json з 3 кейсами: casino-ref→'сцена з книжкою' (перевірка: немає карт/фішок), bar-ref→'натюрморт з вазою' (перевірка: немає чоловіків/тераси), casino-ref→'щось в цьому настрої' (перевірка: композиція інша але темний фон+warm glow збережені), ~10хв; (6) референс-файли: папка /home/sashok/.openclaw/workspace/ed/suites/data/abby/refs/ — Сашко скине casino_collage.jpg (колаж з 7 варіаціями казино-композицій, вже був у чаті з Клодом) та bar_collage.jpg через WinSCP, 3-й синтетичний згенерувати через Gemini. ВАЖЛИВО: Sasha хоче Sonnet або Opus як judge (Haiku vision слабке). Тестування тільки через telegram transport (direct не підтримує photo). Загальний обсяг ~1-1.5 год. Абсолютно не починати код без цього контексту — Sasha прийде сам і попросить продовжити.
