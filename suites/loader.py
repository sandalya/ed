"""Завантажує тест-кейси з JSON файлів."""
import json
import logging
from typing import Optional
from config import SUITES_DIR

log = logging.getLogger("ed.suites.loader")


def load_suite(filename: str) -> list:
    """Завантажити тест-suite з файлу."""
    path = SUITES_DIR / filename
    if not path.exists():
        log.error(f"Suite not found: {path}")
        return []
    with open(path, "r", encoding="utf-8") as f:
        cases = json.load(f)
    log.info(f"Loaded {len(cases)} test cases from {filename}")
    return cases


def filter_cases(
    cases: list,
    category: Optional[str] = None,
    tags: Optional[list] = None,
    edge_cases_only: bool = False,
    exclude_tags: Optional[list] = None,
) -> list:
    """Фільтрувати кейси по категорії, тегах, edge_case."""
    result = cases
    if category:
        result = [c for c in result if c.get("category") == category]
    if tags:
        result = [c for c in result if any(t in c.get("tags", []) for t in tags)]
    if edge_cases_only:
        result = [c for c in result if c.get("edge_case", False)]
    if exclude_tags:
        result = [c for c in result if not any(t in c.get("tags", []) for t in exclude_tags)]
    log.info(f"Filtered: {len(result)} cases (from {len(cases)})")
    return result
