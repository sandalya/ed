"""AI-генерація варіацій тест-кейсів з seed'ів."""
import json
import logging
import anthropic
from config import ANTHROPIC_API_KEY

log = logging.getLogger("ed.suites.generator")

client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

VARIATION_PROMPT = """Ти генеруєш варіації тестових повідомлень для QA-тестування Telegram-бота ювелірної майстерні.

Оригінальне повідомлення: "{message}"
Категорія: {category}
Контекст: {context}

Згенеруй {count} варіацій цього повідомлення. Кожна варіація має:
1. Зберігати той самий INTENT (що клієнт хоче)
2. Але відрізнятись формулюванням

Типи варіацій (розподіли рівномірно):
- Перефразування українською (інші слова, той самий зміст)
- Російською мовою (клієнти часто пишуть російською)
- З помилками/сленгом ("скока стоит", "чо по цене")
- Короткі/телеграфні ("ціна бісмарк 50см")
- З emoji ("Привіт! 👋 Покажіть каталог 💍")
- CAPS або змішаний регістр

Відповідай ТІЛЬКИ валідним JSON масивом рядків, без пояснень:
["варіація 1", "варіація 2", ...]"""


def generate_variations(seed_case: dict, count: int = 5, model: str = "claude-haiku-4-5-20251001") -> list:
    """Згенерувати варіації для одного seed кейсу."""
    try:
        response = client.messages.create(
            model=model,
            max_tokens=1000,
            messages=[{
                "role": "user",
                "content": VARIATION_PROMPT.format(
                    message=seed_case["message"],
                    category=seed_case.get("category", "general"),
                    context=seed_case.get("context", ""),
                    count=count,
                ),
            }],
        )
        text = response.content[0].text.strip()
        variations = json.loads(text)
        if isinstance(variations, list):
            log.info(f"Generated {len(variations)} variations for {seed_case['id']}")
            return variations
    except Exception as e:
        log.error(f"Failed to generate variations for {seed_case['id']}: {e}")
    return []


def expand_suite(seeds: list, variations_per_seed: int = 5, model: str = "claude-haiku-4-5-20251001") -> list:
    """Розширити seed suite варіаціями."""
    expanded = list(seeds)

    for seed in seeds:
        if seed.get("conversation") or seed.get("category") == "injection":
            continue

        variations = generate_variations(seed, variations_per_seed, model)
        for i, var_text in enumerate(variations):
            var_case = {
                **seed,
                "id": f"{seed['id']}_var_{i+1}",
                "message": var_text,
                "tags": seed.get("tags", []) + ["generated", "variation"],
                "source_seed": seed["id"],
            }
            expanded.append(var_case)

    log.info(f"Expanded: {len(seeds)} seeds → {len(expanded)} total")
    return expanded
