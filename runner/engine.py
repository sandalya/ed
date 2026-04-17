"""Test runner — оркеструє повний прогін тестів."""
import asyncio
import json
import logging
import subprocess
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from config import MAX_COST_PER_RUN, REPORTS_DIR
from transports.base import BaseTransport, BotResponse
from judge.evaluator import Evaluator, JudgeResult
import hashlib
import json as _json
from pathlib import Path
from runner.assertions import run_assertions, AssertionResult

log = logging.getLogger("ed.runner")

BETWEEN_TESTS_DELAY = 0.3


@dataclass
class RunResult:
    timestamp: str
    total_cases: int
    passed: int
    warned: int
    failed: int
    errors: int
    critical_failures: list
    results: list
    judge_model: str
    total_cost: float
    duration: float
    transport_type: str


class TestRunner:
    def __init__(self, transport: BaseTransport, evaluator: Evaluator, max_cost: float = MAX_COST_PER_RUN):
        self.transport = transport
        self.evaluator = evaluator
        self.max_cost = max_cost
        self._results: list = []

    async def run_suite(self, cases: list, reset_between_tests: bool = True, bot_name: str | None = None) -> RunResult:
        start_time = time.time()
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        log.info(f"Starting: {len(cases)} cases, judge: {self.evaluator.model}")
        await self.transport.connect()
        passed = warned = failed = errors = 0
        critical_failures = []
        self._results = []

        for i, case in enumerate(cases):
            if self.evaluator.total_cost >= self.max_cost:
                log.warning(f"Budget exceeded: ${self.evaluator.total_cost:.2f} >= ${self.max_cost:.2f}. Stopping at {i}/{len(cases)}.")
                break

            log.info(f"[{i+1}/{len(cases)}] {case['id']}")

            # --- reset_before: shell hook перед кейсом ---
            if case.get("reset_before") and bot_name:
                from config import BOTS_CONFIG
                reset_cmd = BOTS_CONFIG.get(bot_name, {}).get("reset_command")
                if reset_cmd:
                    log.info(f"  [reset_before] {reset_cmd[:80]}...")
                    try:
                        result = await asyncio.to_thread(
                            subprocess.run, reset_cmd, shell=True,
                            capture_output=True, text=True, timeout=30
                        )
                        if result.returncode != 0:
                            log.warning(f"  [reset_before] exit={result.returncode} stderr={result.stderr[:200]}")
                        else:
                            log.info(f"  [reset_before] ok")
                    except subprocess.TimeoutExpired:
                        log.error(f"  [reset_before] TIMEOUT after 30s")
                    except Exception as e:
                        log.error(f"  [reset_before] error: {e}")
                else:
                    log.warning(f"  [reset_before] no reset_command configured for bot={bot_name}")

            needs_reset = case.get("conversation") or case.get("reset_before", False)
            # Не шлемо /start якщо перший крок тесту вже є /start
            first_step_is_start = bool(
                case.get("steps") and
                len(case["steps"]) > 0 and
                case["steps"][0].get("action") == "send" and
                case["steps"][0].get("text", "").strip() == "/start"
            )
            if needs_reset and not first_step_is_start:
                await self.transport.reset_conversation()
                await asyncio.sleep(1)

            assertion_results = []
            if case.get("steps"):
                bot_response, step_responses, assertion_results = await self._run_steps(case)
            elif case.get("conversation"):
                bot_response = await self._run_conversation_legacy(case)
                step_responses = []
                if case.get("assertions"):
                    assertion_results = run_assertions(case["assertions"], bot_response)
            else:
                bot_response = await self.transport.send_message(case["message"])
                step_responses = []
                if case.get("assertions"):
                    assertion_results = run_assertions(case["assertions"], bot_response)

            assertion_failed = any(not ar.passed for ar in assertion_results)
            if assertion_failed:
                for ar in assertion_results:
                    if not ar.passed:
                        critical_failures.append(
                            f"{case['id']}: assertion {ar.name} failed — expected={ar.expected}, actual={ar.actual}"
                        )

            judge_result = await self.evaluator.evaluate(
                test_case=case,
                bot_response_text=bot_response.text,
                bot_response_meta={
                    "response_time": bot_response.response_time,
                    "has_photos": bot_response.has_photos,
                    "photo_count": bot_response.photo_count,
                    "has_buttons": bot_response.has_buttons,
                    "button_texts": bot_response.button_texts,
                    "error": bot_response.error,
                },
            )

            if judge_result.error:
                errors += 1
            elif assertion_failed:
                failed += 1
            elif judge_result.overall_verdict == "pass":
                passed += 1
            elif judge_result.overall_verdict == "warn":
                warned += 1
            elif judge_result.overall_verdict == "fail":
                failed += 1
                if judge_result.critical_issues:
                    critical_failures.extend(
                        f"{case['id']}: {issue}" for issue in judge_result.critical_issues
                    )

            self._results.append({
                "test_case": case,
                "bot_response": {
                    "text": bot_response.text,
                    "response_time": bot_response.response_time,
                    "has_photos": bot_response.has_photos,
                    "photo_count": bot_response.photo_count,
                    "has_buttons": bot_response.has_buttons,
                    "button_texts": bot_response.button_texts,
                    "error": bot_response.error,
                },
                "assertions": [
                    {"name": ar.name, "passed": ar.passed, "expected": ar.expected, "actual": ar.actual}
                    for ar in assertion_results
                ],
                "judge_result": {
                    "overall_verdict": "fail" if assertion_failed else judge_result.overall_verdict,
                    "summary": judge_result.summary,
                    "criteria": [
                        {"name": cr.name, "verdict": cr.verdict, "reason": cr.reason}
                        for cr in judge_result.criteria_results
                    ],
                    "critical_issues": judge_result.critical_issues,
                    "cost": judge_result.judge_cost,
                },
            })

            verdict_label = "FAIL(assertion)" if assertion_failed else judge_result.overall_verdict.upper()
            log.info(f"  → {verdict_label} ({judge_result.summary[:60]})")
            await asyncio.sleep(BETWEEN_TESTS_DELAY)

        await self.transport.disconnect()
        duration = time.time() - start_time
        run_result = RunResult(
            timestamp=timestamp, total_cases=len(cases),
            passed=passed, warned=warned, failed=failed, errors=errors,
            critical_failures=critical_failures, results=self._results,
            judge_model=self.evaluator.model, total_cost=self.evaluator.total_cost,
            duration=duration, transport_type=type(self.transport).__name__,
        )
        self._save_report(run_result, timestamp)
        return run_result

    async def _run_steps(self, case: dict):
        step_responses = []
        all_texts = []
        all_assertion_results = []

        for step in case.get("steps", []):
            action = step.get("action", "send")

            if action == "send":
                text = step.get("text", "")
                if text.startswith("/"):
                    response = await self.transport.send_command(text)
                else:
                    response = await self.transport.send_message(text)
                all_texts.append(f"USER: {text}")
            elif action == "click":
                button_text = step.get("button_text", "")
                button_data = step.get("button_data", "")
                response = await self.transport.click_button(
                    button_text=button_text, button_data=button_data
                )
                all_texts.append(f"CLICK: {button_text or button_data}")
            elif action == "photo":
                photo_path = step.get("path", "")
                caption = step.get("caption", "")
                response = await self.transport.send_photo(photo_path, caption=caption)
                all_texts.append(f"PHOTO: {photo_path}")
            elif action == "wait":
                await asyncio.sleep(step.get("seconds", 2))
                continue
            elif action == "click_intent":
                intent = step.get("intent", "")
                last_msg = step.get("_last_bot_text", "")
                # Беремо текст останнього повідомлення бота з попереднього кроку
                if step_responses:
                    last_msg = step_responses[-1].text
                btn_index = await self._resolve_intent(intent, last_msg, self.transport)
                if btn_index is None:
                    response = BotResponse(
                        text="", response_time=0,
                        error=f"click_intent failed: low confidence or no match for intent='{intent}'"
                    )
                else:
                    # Натискаємо по індексу через button_texts
                    if step_responses and btn_index < len(step_responses[-1].button_texts):
                        btn_text = step_responses[-1].button_texts[btn_index]
                    else:
                        btn_text = ""
                    response = await self.transport.click_button(button_text=btn_text)
                all_texts.append(f"CLICK_INTENT: {intent} -> {btn_text if btn_index is not None else 'FAILED'}")
            else:
                log.warning(f"Unknown step action: {action}")
                continue

            all_texts.append(f"BOT: {response.text[:300]}")
            step_responses.append(response)

            if step.get("assertions"):
                step_ar = run_assertions(step["assertions"], response)
                all_assertion_results.extend(step_ar)
                for ar in step_ar:
                    icon = "✅" if ar.passed else "❌"
                    log.info(f"    {icon} [{action}] {ar.name}: {ar.actual}")

            await asyncio.sleep(step.get("delay", BETWEEN_TESTS_DELAY))

        if case.get("assertions") and step_responses:
            last = step_responses[-1]
            combined = BotResponse(
                text="\n\n".join(all_texts),
                response_time=sum(r.response_time for r in step_responses),
                has_photos=any(r.has_photos for r in step_responses),
                photo_count=sum(r.photo_count for r in step_responses),
                has_buttons=last.has_buttons,
                button_texts=last.button_texts,
            )
            global_ar = run_assertions(case["assertions"], combined, step_responses)
            all_assertion_results.extend(global_ar)

        last = step_responses[-1] if step_responses else BotResponse(text="", response_time=0)
        combined = BotResponse(
            text="\n\n".join(all_texts),
            response_time=sum(r.response_time for r in step_responses),
            has_photos=any(r.has_photos for r in step_responses),
            photo_count=sum(r.photo_count for r in step_responses),
            has_buttons=last.has_buttons,
            button_texts=last.button_texts,
        )
        return combined, step_responses, all_assertion_results

    async def _run_conversation_legacy(self, case: dict) -> BotResponse:
        all_texts = []
        last_response = None
        for msg in case.get("messages", []):
            response = await self.transport.send_message(msg["text"])
            all_texts.append(f"USER: {msg['text']}")
            all_texts.append(f"BOT: {response.text}")
            last_response = response
            if msg.get("wait_for_response", True):
                await asyncio.sleep(BETWEEN_TESTS_DELAY)
        return BotResponse(
            text="\n\n".join(all_texts),
            response_time=last_response.response_time if last_response else 0,
            has_photos=last_response.has_photos if last_response else False,
            photo_count=last_response.photo_count if last_response else 0,
            has_buttons=last_response.has_buttons if last_response else False,
            button_texts=last_response.button_texts if last_response else [],
        )


    async def _resolve_intent(self, intent: str, last_bot_message: str, transport) -> int | None:
        """Викликає Haiku щоб вибрати кнопку по семантичному інтенту."""
        import anthropic
        from config import INTENT_CONFIDENCE_THRESHOLD, INTENT_LOGS_DIR
        from telethon.tl.types import ReplyInlineMarkup

        button_texts = []
        if hasattr(transport, "_last_messages"):
            for msg in transport._last_messages:
                if hasattr(msg, "reply_markup") and isinstance(msg.reply_markup, ReplyInlineMarkup):
                    for row in msg.reply_markup.rows:
                        for btn in row.buttons:
                            button_texts.append(btn.text)

        if not button_texts:
            log.warning(f"_resolve_intent: no buttons for intent='{intent}'")
            return None

        cache_key = hashlib.md5(f"{intent}|{'|'.join(sorted(button_texts))}".encode()).hexdigest()
        INTENT_LOGS_DIR.mkdir(parents=True, exist_ok=True)
        cache_file = INTENT_LOGS_DIR / f"cache_{cache_key}.json"
        if cache_file.exists():
            cached = _json.loads(cache_file.read_text())
            log.info(f"  [intent cache] '{intent}' -> index={cached['index']} ({cached['reason']})")
            return cached["index"]

        formatted = "\n".join(f"[{i}] {t}" for i, t in enumerate(button_texts))
        system = """Ти — вибиральник кнопок для QA-агента.
Відповідай ЛИШЕ JSON без markdown: {"index": <число>, "confidence": <0.0-1.0>, "reason": "<5-10 слів українською>"}
index — з наданого списку. confidence=1.0 точний збіг, 0.7-0.9 семантичний, <0.6 неоднозначно."""

        user = f"Повідомлення бота:\n{last_bot_message[:500]}\n\nКнопки:\n{formatted}\n\nМета: {intent}"
        log_entry = {"intent": intent, "buttons": button_texts, "last_bot_message": last_bot_message[:200]}

        try:
            client = anthropic.Anthropic()
            for attempt in range(2):
                resp = client.messages.create(
                    model="claude-haiku-4-5-20251001",
                    max_tokens=150,
                    temperature=0,
                    system=system,
                    messages=[{"role": "user", "content": user}],
                )
                raw = resp.content[0].text.strip()
                # Прибираємо markdown фенси якщо Haiku загорнув у ```json ... ```
                if raw.startswith("```"):
                    raw = "\n".join(
                        line for line in raw.splitlines()
                        if not line.strip().startswith("```")
                    ).strip()
                log.info(f"  [intent raw cleaned] {raw[:200]}")
                parsed = _json.loads(raw)
                index = int(parsed["index"])
                confidence = float(parsed["confidence"])
                reason = parsed.get("reason", "")
                if 0 <= index < len(button_texts):
                    break
                log.warning(f"_resolve_intent: out-of-range index {index}, attempt {attempt+1}")
            else:
                log_entry["error"] = f"out-of-range after 2 attempts"
                (INTENT_LOGS_DIR / f"fail_{cache_key}.json").write_text(_json.dumps(log_entry, ensure_ascii=False, indent=2))
                return None

            log.info(f"  [intent] '{intent}' -> [{index}] '{button_texts[index]}' conf={confidence:.2f} ({reason})")
            log_entry.update({"index": index, "confidence": confidence, "reason": reason})

            if confidence < INTENT_CONFIDENCE_THRESHOLD:
                log.warning(f"  [intent] confidence {confidence:.2f} < threshold {INTENT_CONFIDENCE_THRESHOLD}")
                log_entry["error"] = f"low confidence: {confidence}"
                (INTENT_LOGS_DIR / f"fail_{cache_key}.json").write_text(_json.dumps(log_entry, ensure_ascii=False, indent=2))
                return None

            cache_file.write_text(_json.dumps({"index": index, "confidence": confidence, "reason": reason}, ensure_ascii=False))
            return index

        except Exception as e:
            log.error(f"_resolve_intent error: {e}")
            log_entry["error"] = str(e)
            (INTENT_LOGS_DIR / f"error_{cache_key}.json").write_text(_json.dumps(log_entry, ensure_ascii=False, indent=2))
            return None

    def _save_report(self, result: RunResult, timestamp: str):
        REPORTS_DIR.mkdir(parents=True, exist_ok=True)
        report_path = REPORTS_DIR / f"run_{timestamp}.json"
        report_data = {
            "timestamp": result.timestamp,
            "summary": {
                "total": result.total_cases,
                "passed": result.passed, "warned": result.warned,
                "failed": result.failed, "errors": result.errors,
                "pass_rate": f"{result.passed / max(result.total_cases, 1) * 100:.0f}%",
            },
            "judge_model": result.judge_model,
            "transport": result.transport_type,
            "total_cost_usd": round(result.total_cost, 4),
            "duration_seconds": round(result.duration, 1),
            "critical_failures": result.critical_failures,
            "results": result.results,
        }
        with open(report_path, "w", encoding="utf-8") as f:
            json.dump(report_data, f, ensure_ascii=False, indent=2)
        log.info(f"Report saved: {report_path}")
