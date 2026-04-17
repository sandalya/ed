"""Assertion engine — конкретні перевірки без AI Judge."""
import re
import logging
from dataclasses import dataclass
from typing import Optional

log = logging.getLogger("ed.assertions")


@dataclass
class AssertionResult:
    name: str
    passed: bool
    expected: str
    actual: str
    message: str = ""


def run_assertions(assertions: list, bot_response, step_responses: list = None) -> list:
    """Виконати список assertions для відповіді бота."""
    results = []
    for a in assertions:
        result = _run_one(a, bot_response, step_responses)
        results.append(result)
    return results


def _run_one(assertion: dict, response, step_responses: list = None) -> AssertionResult:
    a_type = assertion["type"]

    target = response
    if assertion.get("step") is not None and step_responses:
        step_idx = assertion["step"]
        if 0 <= step_idx < len(step_responses):
            target = step_responses[step_idx]
        else:
            return AssertionResult(
                name=a_type, passed=False,
                expected=f"step {step_idx}", actual=f"only {len(step_responses)} steps",
                message=f"Step index {step_idx} out of range",
            )

    try:
        if a_type == "has_photos":
            expected = assertion.get("value", True)
            return AssertionResult(
                name="has_photos", passed=target.has_photos == expected,
                expected=str(expected), actual=str(target.has_photos),
            )

        elif a_type == "photo_count":
            op = assertion.get("op", "gte")
            value = assertion["value"]
            actual = target.photo_count
            passed = _compare(actual, op, value)
            return AssertionResult(
                name="photo_count", passed=passed,
                expected=f"{op} {value}", actual=str(actual),
            )

        elif a_type == "text_contains":
            pattern = assertion["value"]
            full_text = target.text
            if assertion.get("case_insensitive", True):
                passed = pattern.lower() in full_text.lower()
            else:
                passed = pattern in full_text
            return AssertionResult(
                name="text_contains", passed=passed,
                expected=f"contains '{pattern}'",
                actual=full_text[:200] if not passed else "found",
            )

        elif a_type == "text_not_contains":
            pattern = assertion["value"]
            full_text = target.text
            if assertion.get("case_insensitive", True):
                passed = pattern.lower() not in full_text.lower()
            else:
                passed = pattern not in full_text
            return AssertionResult(
                name="text_not_contains", passed=passed,
                expected=f"NOT contains '{pattern}'",
                actual="not found" if passed else f"found in: {full_text[:200]}",
            )

        elif a_type == "text_matches":
            pattern = assertion["value"]
            passed = bool(re.search(pattern, target.text, re.IGNORECASE))
            return AssertionResult(
                name="text_matches", passed=passed,
                expected=f"matches /{pattern}/",
                actual=target.text[:200] if not passed else "matched",
            )

        elif a_type == "has_buttons":
            expected = assertion.get("value", True)
            return AssertionResult(
                name="has_buttons", passed=target.has_buttons == expected,
                expected=str(expected), actual=str(target.has_buttons),
            )

        elif a_type == "button_text_contains":
            pattern = assertion["value"]
            found = any(pattern.lower() in b.lower() for b in target.button_texts)
            return AssertionResult(
                name="button_text_contains", passed=found,
                expected=f"button with '{pattern}'",
                actual=str(target.button_texts) if not found else "found",
            )

        elif a_type == "button_count":
            op = assertion.get("op", "gte")
            value = assertion["value"]
            actual = len(target.button_texts)
            passed = _compare(actual, op, value)
            return AssertionResult(
                name="button_count", passed=passed,
                expected=f"{op} {value}", actual=str(actual),
            )

        elif a_type == "response_time":
            op = assertion.get("op", "lte")
            value = assertion["value"]
            actual = target.response_time
            passed = _compare(actual, op, value)
            return AssertionResult(
                name="response_time", passed=passed,
                expected=f"{op} {value}s", actual=f"{actual:.1f}s",
            )

        elif a_type == "no_error":
            passed = target.error is None
            return AssertionResult(
                name="no_error", passed=passed,
                expected="no error", actual=target.error or "no error",
            )

        elif a_type == "price_in_range":
            prices = re.findall(r'(\d[\d\s]*\d)\s*(?:грн|₴)', target.text)
            if not prices:
                prices = re.findall(r'(?:₴|грн)\s*(\d[\d\s]*\d)', target.text)
            if not prices:
                return AssertionResult(
                    name="price_in_range", passed=False,
                    expected=f"{assertion.get('min', 0)}-{assertion.get('max', 99999)} грн",
                    actual="no price found in text",
                )
            price_str = prices[0].replace(" ", "").replace("\u00a0", "")
            price = float(price_str)
            min_price = assertion.get("min", 0)
            max_price = assertion.get("max", 999999)
            passed = min_price <= price <= max_price
            return AssertionResult(
                name="price_in_range", passed=passed,
                expected=f"{min_price}-{max_price} грн",
                actual=f"{price} грн",
            )

        elif a_type == "admin_received":
            return AssertionResult(
                name="admin_received", passed=True,
                expected="admin check", actual="deferred to engine",
                message="Checked in engine.py",
            )

        else:
            return AssertionResult(
                name=a_type, passed=False,
                expected="known assertion type", actual=a_type,
                message=f"Unknown assertion type: {a_type}",
            )

    except Exception as e:
        return AssertionResult(
            name=a_type, passed=False,
            expected="no exception", actual=str(e),
            message=f"Assertion error: {e}",
        )


def _compare(actual, op: str, value) -> bool:
    if op == "eq":
        return actual == value
    elif op == "gte":
        return actual >= value
    elif op == "lte":
        return actual <= value
    elif op == "gt":
        return actual > value
    elif op == "lt":
        return actual < value
    return False
