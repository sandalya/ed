"""Завантажує тест-кейси з JSON файлів (блоками або всі)."""
import json
import logging
from pathlib import Path
from typing import Optional
from config import SUITES_DIR

log = logging.getLogger("ed.suites.loader")


def load_block(bot_name: str, block_name: str) -> list:
    """Завантажити один блок за назвою.
    load_block("insilver", "pricing") → шукає *_pricing.json у blocks/
    """
    blocks_dir = SUITES_DIR / bot_name / "blocks"
    for f in sorted(blocks_dir.glob("*.json")):
        name_part = f.stem.split("_", 1)[-1] if "_" in f.stem else f.stem
        if name_part == block_name:
            return _load_json(f)
    log.error(f"Block '{block_name}' not found in {blocks_dir}")
    return []


def load_all_blocks(bot_name: str) -> list:
    """Завантажити всі блоки для бота, в порядку префіксів."""
    blocks_dir = SUITES_DIR / bot_name / "blocks"
    if not blocks_dir.exists():
        log.error(f"Blocks dir not found: {blocks_dir}")
        return []
    cases = []
    for f in sorted(blocks_dir.glob("*.json")):
        cases.extend(_load_json(f))
    log.info(f"Loaded {len(cases)} total cases from {blocks_dir}")
    return cases


def load_scenario(bot_name: str, scenario_name: str) -> list:
    """Завантажити сценарій — послідовність блоків."""
    scenario_path = SUITES_DIR / bot_name / "scenarios" / f"{scenario_name}.json"
    if not scenario_path.exists():
        log.error(f"Scenario not found: {scenario_path}")
        return []
    with open(scenario_path, "r", encoding="utf-8") as f:
        scenario = json.load(f)
    cases = []
    for block_name in scenario.get("blocks", []):
        block_cases = load_block(bot_name, block_name)
        cases.extend(block_cases)
    log.info(f"Scenario '{scenario_name}': {len(cases)} cases from {len(scenario['blocks'])} blocks")
    return cases


def load_suite(filename: str) -> list:
    """Зворотня сумісність — завантажити старий flat JSON."""
    path = SUITES_DIR / filename
    if not path.exists():
        log.error(f"Suite not found: {path}")
        return []
    return _load_json(path)


def _load_json(path: Path) -> list:
    """Завантажити JSON, пропустити disabled кейси (id починається на _)."""
    with open(path, "r", encoding="utf-8") as f:
        cases = json.load(f)
    active = [c for c in cases if not c.get("id", "").startswith("_")]
    skipped = len(cases) - len(active)
    if skipped:
        log.info(f"  {path.name}: {len(active)} active, {skipped} disabled")
    else:
        log.info(f"  {path.name}: {len(active)} cases")
    return active


def filter_cases(
    cases: list,
    category: Optional[str] = None,
    tags: Optional[list] = None,
    edge_cases_only: bool = False,
    exclude_tags: Optional[list] = None,
) -> list:
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
