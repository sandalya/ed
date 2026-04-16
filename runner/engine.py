"""Test runner — оркеструє повний прогін тестів."""
import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from config import MAX_COST_PER_RUN, REPORTS_DIR
from transports.base import BaseTransport, BotResponse
from judge.evaluator import Evaluator, JudgeResult

log = logging.getLogger("ed.runner")

BETWEEN_TESTS_DELAY = 2


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

    async def run_suite(self, cases: list, reset_between_tests: bool = True) -> RunResult:
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

            # Reset тільки для conversation тестів або якщо явно запитано
            needs_reset = case.get("conversation") or case.get("reset_before", False)
            if reset_between_tests and needs_reset:
                await self.transport.reset_conversation()
                await asyncio.sleep(1)

            if case.get("conversation"):
                bot_response = await self._run_conversation(case)
            else:
                bot_response = await self.transport.send_message(case["message"])

            judge_result = await self.evaluator.evaluate(
                test_case=case,
                bot_response_text=bot_response.text,
                bot_response_meta={
                    "response_time": bot_response.response_time,
                    "has_photos": bot_response.has_photos,
                    "has_buttons": bot_response.has_buttons,
                    "button_texts": bot_response.button_texts,
                    "error": bot_response.error,
                },
            )

            if judge_result.error:
                errors += 1
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
                    "has_buttons": bot_response.has_buttons,
                    "button_texts": bot_response.button_texts,
                    "error": bot_response.error,
                },
                "judge_result": {
                    "overall_verdict": judge_result.overall_verdict,
                    "summary": judge_result.summary,
                    "criteria": [
                        {"name": cr.name, "verdict": cr.verdict, "reason": cr.reason}
                        for cr in judge_result.criteria_results
                    ],
                    "critical_issues": judge_result.critical_issues,
                    "cost": judge_result.judge_cost,
                },
            })

            log.info(f"  → {judge_result.overall_verdict.upper()} ({judge_result.summary[:60]})")
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

    async def _run_conversation(self, case: dict) -> BotResponse:
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
            has_buttons=last_response.has_buttons if last_response else False,
            button_texts=last_response.button_texts if last_response else [],
        )

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
