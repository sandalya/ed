---
project: ed
updated: 2026-04-23
---

# WARM — Ed (QA agent)

## Триярусна пам'ять — структура проекту

```yaml
last_touched: 2026-04-23
tags: [infrastructure, memory]
status: active
```

HOT.md (~60 рядків, переписується щосесії), WARM.md (~400 рядків, інкрементальні), COLD.md (append-only архів). Оновлення через `chkp ed`. Rule Zero у MEMORY.md. Ініціалізовано 2026-04-23.

## Призначення

```yaml
last_touched: 2026-04-23
tags: [purpose, philosophy]
status: active
```

Ed — автоматизований QA-агент для тестування ботів Саші (насамперед InSilver, але працює з будь-яким TG-ботом). **Ключова філософія Саші:** "не тестити руками". Ed звільняє від ручного клацання в Telegram — кожну фічу, регресію, баг-фікс можна повторити автоматично. Чим повніше покриття Ed — тим менше ручної роботи і тим швидше можна коммітити зміни впевнено.

## Ed-first policy

```yaml
last_touched: 2026-04-23
tags: [policy, workflow]
status: active
```

Будь-який функціональний тест бота (UI, діалог, тригери, callback кнопок, рендер повідомлень, воронки, handoff) — ЗАВЖДИ через Ed. Якщо у Ed-suites немає відповідного блоку — ≤30 хв на додання → додати і прогнати; >30 хв → попередити Сашу і запропонувати ручний тест. Виключення — тільки для інфраструктурних перевірок (systemd, файли, shell).

## Ed v2 — архітектура

```yaml
last_touched: 2026-04-23
tags: [architecture, v2]
status: active
```

Апгрейд з v1 на v2 з повною підтримкою багатокрокових тестів. Компоненти: `runner/engine.py`, `runner/assertions.py`, `runner/router.py`. Транспорти: `TelegramTransport` (реальний Telegram API через Telethon) + direct transport (прямий виклик бота). Вибір — через `--transport direct/telegram`. `MULTI_MESSAGE_DELAY` відкалібрований для стабільної обробки послідовних повідомлень.

## click_intent — семантичний вибір кнопок

```yaml
last_touched: 2026-04-23
tags: [click_intent, haiku]
status: active
```

Замість жорсткого string-match по label кнопки — `click_intent` використовує Haiku для семантичного підбору. Наприклад, на крок "вибрати варіант з золотом" Ed знайде правильну кнопку навіть якщо в ній написано "Жовте золото 585°" чи "Au 14k". Результати кешуються (intent → button_id), threshold впевненості 0.7. Знижує крихкість тестів при зміні тексту кнопок у боті.

## Assertions (11+ типів)

```yaml
last_touched: 2026-04-23
tags: [assertions]
status: active
```

`assertions.py` підтримує: `text_contains`, `text_not_contains`, `text_matches` (regex), `has_buttons`, `button_count`, `button_text_contains`, `has_photos`, `photo_count`, `response_time`, `no_error`, `price_in_range`, `admin_received`, `no_bot_response`, `order_saved`. `admin_received` резолвиться через `engine._resolve_admin_assertions` — перевіряє що handoff-повідомлення дійшло до адмін-чата (наприклад `ADMIN_VERIFY_CHAT_ID=8627781342` для InSilver).

## Actions

```yaml
last_touched: 2026-04-23
tags: [actions]
status: active
```

Підтримувані дії в тестах: `send` (текст), `click` (по button_id), `photo` (УВАГА: `photo`, а не `send_photo`), `wait` (затримка), `click_intent` (семантичний клік). `reset_before` у блоці читає `reset_command` з `config/bots.yaml` — автоматичний ресет стану бота перед тестом.

## Блоки тестів (InSilver)

```yaml
last_touched: 2026-04-23
tags: [test-blocks, insilver]
status: active
```

- `07_prompt_guardrails` — зелений.
- `09_handoff` — зелений (переписано з admin_received + text_contains замість Haiku judge).
- `10_order_funnel` — відомі баги: intent cache трохи плутається на послідовних кроках, кнопка "Інше" не завжди обирається правильно. Активна робота.

Знайдені реальні баги InSilver через Ed: суржик у відповідях, malformed detail блоки.

## Таймінги запуску

```yaml
last_touched: 2026-04-23
tags: [timing, ux]
status: active
```

Перед кожним запуском Ed — попередження про очікуваний час. Правила: smoke / один кейс ~10-20 сек; один блок з 5-6 кейсів ~5-7 хв (Haiku judge); повна регресія 9 блоків ~30-60 хв. Бачити реальну тривалість можна у `reports/history/run_*.json` (поле `duration`, в секундах: 432с, 962с тощо).

## НІКОЛИ не пайпити вивід Ed

```yaml
last_touched: 2026-04-23
tags: [gotcha]
status: active
```

`python3 main.py run ... | grep ...` — НЕ РОБИТИ. Pipe робить stderr не-TTY → tqdm вимикає прогрес-бар, і замість зручного візуалу — тиша або хаос. Запускати чистою командою. Результати FAILED шукати у повному звіті в кінці або у `reports/history/run_*.json`. Те саме стосується обгорток типу `run_test.sh` — якщо там є grep, прибрати.

## Документація — головний відкритий пункт

```yaml
last_touched: 2026-04-23
tags: [docs, priority]
status: todo
```

Ключова задача на найближчі сесії — написати справжню документацію Ed. Мотивація Саші: "щоб ми нічого не забували і тільки покращували функціонал". Без доки кожна нова сесія починається з переспрашування "а як там assertions" / "а як працює click_intent". Очікуваний контент: як писати тести (YAML формат), довідник assertions, довідник actions, як click_intent обирає кнопку, як додати новий блок, як переключати transport, troubleshooting частих помилок.

## Ключові рішення

```yaml
last_touched: 2026-04-23
tags: [decisions]
status: active
```

Ed-first policy (а не "руками потім додамо"). click_intent > hard match (стійкість до змін у UI). Два transport режими (direct — швидко, telegram — реалістично). Assertions замість Haiku-judge там де можна (детермінізм > гнучкість). JSON-формат блоків (`09_handoff.json`, `10_order_funnel.json`) — з явним списком assertions.

## Open questions

Як структурувати доку Ed — один README.md чи окремі md-файли по розділах (assertions / actions / click_intent / transport / writing-tests). Вирішувати на сесії коли будемо писати доку.
