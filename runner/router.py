"""Transport router — автоматичний вибір direct vs telegram per-case.

Правила (у порядку пріоритету):
1. Явне override в кейсі: "transport": "telegram" | "direct"
2. Multi-step кейс (має "steps") → telegram
3. Кейс має click_intent / click / photo action → telegram
4. Простий кейс (message + expect / assertions) → direct

Використання:
    from runner.router import pick_transport
    tname = pick_transport(case, cli_choice="auto")  # -> "direct" | "telegram"
"""
from typing import Literal

TransportName = Literal["direct", "telegram"]

# Типи step-дій які вимагають telegram транспорту
TELEGRAM_ONLY_ACTIONS = {"click", "click_intent", "photo"}


def pick_transport(case: dict, cli_choice: str = "auto") -> TransportName:
    """Визначає який транспорт використовувати для кейса.

    Args:
        case: Тест-кейс (dict з JSON).
        cli_choice: Значення з --transport ("auto", "direct", "telegram").

    Returns:
        "direct" або "telegram".
    """
    # 1. CLI override — якщо явно задано, слухаємось
    if cli_choice in ("direct", "telegram"):
        return cli_choice

    # 2. Явне override на рівні кейса
    case_transport = case.get("transport")
    if case_transport in ("direct", "telegram"):
        return case_transport

    # 3. Multi-step → telegram (бо steps можуть мати click_intent / photo)
    steps = case.get("steps")
    if steps:
        for step in steps:
            action = step.get("action", "send")
            if action in TELEGRAM_ONLY_ACTIONS:
                return "telegram"
        # steps без telegram-only actions (наприклад, тільки send) — теж
        # залишаємо на telegram, бо multi-step зазвичай перевіряє UX
        return "telegram"

    # 4. Legacy conversation-based → telegram
    if case.get("conversation"):
        return "telegram"

    # 5. Простий кейс (message + assertions/expect) → direct
    return "direct"


def split_by_transport(cases: list, cli_choice: str = "auto") -> dict:
    """Розділяє список кейсів на групи за транспортом.

    Returns:
        {"direct": [...], "telegram": [...]}
    """
    groups = {"direct": [], "telegram": []}
    for case in cases:
        t = pick_transport(case, cli_choice)
        groups[t].append(case)
    return groups
