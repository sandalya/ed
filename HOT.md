---
project: ed
updated: 2026-04-23
---

# HOT — Ed (QA agent)

## Now

Ed використовується активно для тестування InSilver (блок `10_order_funnel` має відомі баги — intent cache і кнопка "Інше"). Блоки `07_prompt_guardrails` і `09_handoff` — зелені. Міграція на триярусну пам'ять проекту — саме зараз.

## Last done

**2026-04-23** — Ініціалізовано HOT/WARM/COLD/MEMORY через `chkp --init ed`. До того: Ed v2 стабільно прожив через кілька тестових сесій на InSilver, assertions.py розширено до 11+ типів, `click_intent` (Haiku-based семантичний вибір кнопок) відпрацьовує з кешем + threshold 0.7.

## Next

1. Створити **справжню документацію Ed** — як писати тести, які assertions доступні, як працює `click_intent`, як додавати нові блоки. Найважливіша задача наступних сесій (цитата Саші: "щоб ми нічого не забували і тільки покращували функціонал").
2. Продовжити роботу над блоком `10_order_funnel` — дофіксити баги intent cache і кнопки "Інше".
3. Мігрувати Garcia, потім Abby-v2 у цій же сесії.

## Blockers

Немає.

## Active branches

- **ed-репо** (`main`): стан гілки — уточнити (`cd ed && git status`).

## Open questions

- Як структурувати Ed docs — один великий README, чи окремі md-файли для assertions / actions / click_intent / transport / writing-tests?

## Reminders

- Workspace: `/home/sashok/.openclaw/workspace/ed/`
- **Ed-first policy**: будь-який функціональний тест бота — через Ed, не руками. Якщо немає блоку — ≤30 хв додати, >30 хв — попередити.
- **Таймінги перед запуском**: smoke ~10-20 сек; 1 блок ~5-7 хв; повна регресія 9 блоків ~30-60 хв. Формат: "⏱️ Орієнтовно N хв".
- **Ніколи не пайпити вивід Ed** (`| grep ...`) — ламає tqdm прогрес-бар. Результати шукати у ED QA REPORT або `reports/history/run_*.json`.
- API keys маскувати до 4 символів.
- Checkpoint: `chkp ed "done" "next" "context"`
