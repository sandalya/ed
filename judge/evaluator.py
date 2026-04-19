"""AI Judge — оцінює відповідь бота по рубриці."""
import json
import logging
import anthropic
import asyncio
from dataclasses import dataclass, field
from typing import Optional
from config import ANTHROPIC_API_KEY, JUDGE_MODEL, MODEL_COSTS
from .rubrics.base import Rubric

log = logging.getLogger("ed.judge")

client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY, max_retries=8, timeout=60.0)

JUDGE_SYSTEM_PROMPT = """Ти — Ed, суворий QA-тестувальник Telegram-ботів. Твоя робота — знаходити проблеми, а не підтверджувати що все добре.

Тобі дають:
1. Тест-кейс — що написав "клієнт" боту
2. Відповідь бота
3. Рубрику з критеріями оцінки

Оціни КОЖЕН критерій рубрики. Для кожного критерію дай:
- verdict: "pass" | "warn" | "fail"
- reason: коротке пояснення (1-2 речення) ЧОМУ такий вердикт

Правила:
- "pass" — критерій виконаний повністю
- "warn" — є зауваження, але не критично
- "fail" — критерій порушений

Будь СУВОРИМ. Краще зайвий warn ніж пропущений fail.
НЕ давай pass всьому підряд — це означає що ти не працюєш.

Відповідай ТІЛЬКИ валідним JSON (без markdown, без пояснень поза JSON):
{
  "criteria_results": [
    {"name": "criterion_name", "verdict": "pass|warn|fail", "reason": "пояснення"}
  ],
  "overall_verdict": "pass|warn|fail",
  "summary": "загальний коментар 1-2 речення",
  "critical_issues": ["список критичних проблем, якщо є"]
}"""


@dataclass
class CriterionResult:
    name: str
    verdict: str
    reason: str
    weight: float = 1.0
    critical: bool = False


@dataclass
class JudgeResult:
    test_id: str
    overall_verdict: str
    summary: str
    criteria_results: list = field(default_factory=list)
    critical_issues: list = field(default_factory=list)
    judge_model: str = ""
    judge_cost: float = 0.0
    error: Optional[str] = None


class Evaluator:
    """AI Judge для оцінки відповідей бота."""

    def __init__(self, rubric: Rubric, model: str = ""):
        self.rubric = rubric
        self.model = model or JUDGE_MODEL
        self._total_cost = 0.0

    @property
    def total_cost(self) -> float:
        return self._total_cost

    async def evaluate(self, test_case: dict, bot_response_text: str, bot_response_meta: dict = None) -> JudgeResult:
        meta = bot_response_meta or {}
        user_prompt = self._build_user_prompt(test_case, bot_response_text, meta)

        try:
            rubric_block = self.rubric.to_judge_prompt()
            response = await asyncio.to_thread(
                client.messages.create,
                model=self.model,
                max_tokens=1500,
                system=[
                    {"type": "text", "text": JUDGE_SYSTEM_PROMPT},
                    {"type": "text", "text": rubric_block, "cache_control": {"type": "ephemeral"}},
                ],
                messages=[{"role": "user", "content": user_prompt}],
            )

            usage = response.usage
            costs = MODEL_COSTS.get(self.model, {"input": 3.0, "output": 15.0})
            cache_read = getattr(usage, "cache_read_input_tokens", 0) or 0
            cache_write = getattr(usage, "cache_creation_input_tokens", 0) or 0
            cost = (
                usage.input_tokens * costs["input"] / 1_000_000
                + cache_read * costs["input"] * 0.1 / 1_000_000
                + cache_write * costs["input"] * 1.25 / 1_000_000
                + usage.output_tokens * costs["output"] / 1_000_000
            )
            if cache_read or cache_write:
                import logging
                logging.getLogger("ed.judge").info(
                    f"cache: read={cache_read} write={cache_write} in={usage.input_tokens} out={usage.output_tokens}"
                )
            self._total_cost += cost

            text = response.content[0].text.strip()
            if text.startswith("```"):
                text = text.split("\n", 1)[1] if "\n" in text else text[3:]
            if text.endswith("```"):
                text = text[:-3]
            text = text.strip()

            data = json.loads(text)
            return self._parse_result(test_case["id"], data, cost)

        except json.JSONDecodeError as e:
            log.error(f"Judge JSON parse error for {test_case['id']}: {e}")
            return JudgeResult(test_id=test_case["id"], overall_verdict="error",
                               summary="Judge returned invalid JSON", judge_model=self.model, error=str(e))
        except Exception as e:
            log.error(f"Judge error for {test_case['id']}: {e}")
            return JudgeResult(test_id=test_case["id"], overall_verdict="error",
                               summary=f"Judge error: {e}", judge_model=self.model, error=str(e))

    def _build_user_prompt(self, test_case: dict, bot_response: str, meta: dict) -> str:
        # rubric вже в system (cache_control)

        meta_lines = []
        if meta.get("response_time"):
            meta_lines.append(f"Час відповіді: {meta['response_time']:.1f}с")
        if meta.get("has_photos"):
            photo_count = meta.get("photo_count", 1)
            meta_lines.append(f"Бот надіслав {photo_count} фото")
        btn_texts = meta.get("button_texts", [])
        if btn_texts:
            meta_lines.append(
                f"Inline-кнопки Telegram (під повідомленням): {len(btn_texts)} шт. — "
                f"{', '.join(btn_texts)}"
            )
            meta_lines.append(
                "ВАЖЛИВО: кнопки не з'являються В ТЕКСТІ відповіді. Вони прикріплені до "
                "повідомлення як InlineKeyboardMarkup. Факт їхньої наявності ≠ їх згадування в тексті."
            )
        else:
            meta_lines.append("Inline-кнопок немає")
        pinned_text = meta.get("pinned_text", "")
        pinned_buttons = meta.get("pinned_buttons", [])
        if pinned_text or pinned_buttons:
            meta_lines.append("")
            meta_lines.append("📌 Закріплене повідомлення (pinned) у чаті:")
            meta_lines.append("--- pinned_text ---")
            meta_lines.append(pinned_text or "(порожньо)")
            meta_lines.append("--- /pinned_text ---")
            if pinned_buttons:
                meta_lines.append(f"Кнопки у pinned: {', '.join(pinned_buttons)}")
        meta_str = "\n".join(meta_lines) if meta_lines else "немає"

        expected = test_case.get("expected_behavior", {})
        expected_lines = []
        for key, val in expected.items():
            readable = key.replace("_", " ").replace("should ", "")
            if isinstance(val, bool):
                expected_lines.append(f"- {'МАЄ' if val else 'НЕ МАЄ'}: {readable}")
            elif isinstance(val, list):
                if val:
                    items = ", ".join(f"'{x}'" for x in val)
                    expected_lines.append(f"- {readable}: {items}")
                else:
                    expected_lines.append(f"- {readable}: (порожньо — критерій не активний)")
            elif isinstance(val, (int, float)):
                expected_lines.append(f"- {readable}: {val}")
            else:
                expected_lines.append(f"- {readable}: {val}")
        expected_str = "\n".join(expected_lines) if expected_lines else "немає"

        return f"""## Тест-кейс
**ID:** {test_case['id']}
**Категорія:** {test_case.get('category', 'unknown')}
**Контекст:** {test_case.get('context', 'немає')}

**Повідомлення клієнта:**
{test_case.get('message', '')}

**Очікувана поведінка:**
{expected_str}

---

## Відповідь бота
{bot_response if bot_response else '[ПОРОЖНЯ ВІДПОВІДЬ]'}

---

## Мета-інформація
{meta_str}

---

Оціни відповідь бота по КОЖНОМУ критерію рубрики. JSON only."""

    def _parse_result(self, test_id: str, data: dict, cost: float) -> JudgeResult:
        criteria_results = []
        for cr in data.get("criteria_results", []):
            rubric_criterion = next(
                (c for c in self.rubric.criteria if c.name == cr["name"]), None)
            criteria_results.append(CriterionResult(
                name=cr["name"], verdict=cr.get("verdict", "error"),
                reason=cr.get("reason", ""),
                weight=rubric_criterion.weight if rubric_criterion else 1.0,
                critical=rubric_criterion.critical if rubric_criterion else False,
            ))

        return JudgeResult(
            test_id=test_id, overall_verdict=data.get("overall_verdict", "error"),
            summary=data.get("summary", ""), criteria_results=criteria_results,
            critical_issues=data.get("critical_issues", []),
            judge_model=self.model, judge_cost=cost,
        )
