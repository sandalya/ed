"""Базовий формат рубрики для AI Judge."""
from dataclasses import dataclass, field


@dataclass
class RubricCriterion:
    """Один критерій оцінки."""
    name: str
    description: str
    weight: float = 1.0
    critical: bool = False


@dataclass
class Rubric:
    """Набір критеріїв для оцінки відповідей конкретного бота."""
    name: str
    bot_description: str
    criteria: list = field(default_factory=list)

    def to_judge_prompt(self) -> str:
        lines = [
            f"# Рубрика оцінки: {self.name}",
            f"## Бот: {self.bot_description}",
            "",
            "## Критерії оцінки:",
        ]
        for i, c in enumerate(self.criteria, 1):
            critical_mark = " ⚠️ КРИТИЧНИЙ" if c.critical else ""
            lines.append(f"{i}. **{c.name}** (вага: {c.weight}){critical_mark}")
            lines.append(f"   {c.description}")
        return "\n".join(lines)
