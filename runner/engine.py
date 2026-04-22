"""Test runner — оркеструє повний прогін тестів."""
import asyncio
import json
import logging
import subprocess
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional
import re

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
    def __init__(
        self,
        transports: dict | None = None,
        evaluator: Evaluator = None,
        max_cost: float = MAX_COST_PER_RUN,
        cli_transport: str = "auto",
        parallel: int = 1,
        transport: BaseTransport | None = None,  # backward compat
    ):
        # Backward compat: якщо переданий одиничний transport — загорнути в dict
        if transport is not None and transports is None:
            tname = "telegram" if type(transport).__name__ == "TelegramTransport" else "direct"
            transports = {tname: transport}
            cli_transport = tname
        if not transports:
            raise ValueError("TestRunner: must provide transports dict or transport")
        self.transports = transports
        self.cli_transport = cli_transport
        self.parallel = max(1, parallel)
        self.evaluator = evaluator
        self.max_cost = max_cost
        self._results: list = []
        # self.transport — використовується в _resolve_intent; вказуємо на telegram
        # якщо він є (бо click_intent можливий тільки через telegram), інакше на direct
        self.transport = transports.get("telegram") or transports.get("direct")

    async def run_suite(self, cases: list, reset_between_tests: bool = True, bot_name: str | None = None) -> RunResult:
        from runner.router import pick_transport, split_by_transport

        start_time = time.time()
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")

        # Роутинг: визначаємо який транспорт потрібен для кожного кейса
        groups = split_by_transport(cases, self.cli_transport)
        n_direct = len(groups["direct"])
        n_telegram = len(groups["telegram"])
        log.info(
            f"Starting: {len(cases)} cases "
            f"(routed: {n_direct} direct, {n_telegram} telegram), "
            f"parallel={self.parallel}, judge: {self.evaluator.model}"
        )

        # Конектимо лише транспорти які реально використовуються І доступні
        active_transports = {}
        for tname in ("direct", "telegram"):
            if groups[tname] and tname in self.transports:
                await self.transports[tname].connect()
                active_transports[tname] = self.transports[tname]
            elif groups[tname] and tname not in self.transports:
                log.error(
                    f"Router requires {tname} for {len(groups[tname])} cases but "
                    f"--transport={self.cli_transport} excluded it. Skipping those cases."
                )
                groups[tname] = []

        passed = warned = failed = errors = 0
        critical_failures = []
        self._results = []

        # Лічильник прогресу для логів (спільний для паралельних)
        self._progress = {"done": 0, "total": n_direct + len(groups["telegram"])}

        # --- Direct гілка: паралельно якщо parallel >= 2, інакше послідовно ---
        if groups["direct"]:
            direct_transport = active_transports["direct"]
            if self.parallel >= 2:
                sem = asyncio.Semaphore(self.parallel)
                async def run_one_direct(case):
                    async with sem:
                        return await self._run_single_case(case, direct_transport, bot_name)
                direct_results = await asyncio.gather(
                    *[run_one_direct(c) for c in groups["direct"]],
                    return_exceptions=True,
                )
            else:
                direct_results = []
                for case in groups["direct"]:
                    try:
                        direct_results.append(await self._run_single_case(case, direct_transport, bot_name))
                    except Exception as e:
                        direct_results.append(e)
            for case, outcome in zip(groups["direct"], direct_results):
                self._accumulate(case, outcome, critical_failures)
                if isinstance(outcome, Exception):
                    errors += 1
                else:
                    verdict = outcome["verdict"]
                    if verdict == "pass": passed += 1
                    elif verdict == "warn": warned += 1
                    elif verdict == "fail": failed += 1
                    elif verdict == "error": errors += 1

        # --- Telegram гілка: завжди послідовно ---
        if groups["telegram"]:
            telegram_transport = active_transports["telegram"]
            for i, case in enumerate(groups["telegram"]):
                if self.evaluator.total_cost >= self.max_cost:
                    log.warning(f"Budget exceeded: ${self.evaluator.total_cost:.2f} >= ${self.max_cost:.2f}. Stopping at {i}/{len(groups['telegram'])}.")
                    break

                log.info(f"[tg {i+1}/{n_telegram}] {case['id']}")

                # --- reset_before: shell hook ---
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
                first_step_is_start = bool(
                    case.get("steps") and
                    len(case["steps"]) > 0 and
                    case["steps"][0].get("action") == "send" and
                    case["steps"][0].get("text", "").strip() == "/start"
                )
                if needs_reset and not first_step_is_start:
                    await telegram_transport.reset_conversation()
                    await asyncio.sleep(1)

                assertion_results = []
                if case.get("steps"):
                    bot_response, step_responses, assertion_results = await self._run_steps(case, telegram_transport)
                elif case.get("conversation"):
                    bot_response = await self._run_conversation_legacy(case, telegram_transport)
                    step_responses = []
                    if case.get("assertions"):
                        assertion_results = run_assertions(case["assertions"], bot_response)
                else:
                    bot_response = await telegram_transport.send_message(case["message"])
                    step_responses = []
                    if case.get("assertions"):
                        assertion_results = run_assertions(case["assertions"], bot_response)

                assertion_results = await self._resolve_admin_assertions(case, assertion_results, telegram_transport)
                assertion_failed = any(not ar.passed for ar in assertion_results)
                if assertion_failed:
                    for ar in assertion_results:
                        if not ar.passed:
                            critical_failures.append(
                                f"{case['id']}: assertion {ar.name} failed — expected={ar.expected}, actual={ar.actual}"
                            )

                pinned_text, pinned_buttons = await self._maybe_fetch_pinned(case, telegram_transport)
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
                        "pinned_text": pinned_text,
                        "pinned_buttons": pinned_buttons,
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

        # Disconnect тільки активні транспорти
        for tname, t in active_transports.items():
            try:
                await t.disconnect()
            except Exception as e:
                log.warning(f"disconnect {tname} error: {e}")
        duration = time.time() - start_time
        run_result = RunResult(
            timestamp=timestamp, total_cases=len(cases),
            passed=passed, warned=warned, failed=failed, errors=errors,
            critical_failures=critical_failures, results=self._results,
            judge_model=self.evaluator.model, total_cost=self.evaluator.total_cost,
            duration=duration, transport_type="+".join(sorted(active_transports.keys())) if active_transports else type(self.transport).__name__,
        )
        self._save_report(run_result, timestamp)
        return run_result


    async def _maybe_fetch_pinned(self, case: dict, transport) -> tuple:
        """
        Якщо case очікує перевірку pinned (must_have_pinned=true або задано pinned_must_contain /
        pinned_must_be_empty) — тягне pinned message з transport.
        Повертає (pinned_text, pinned_buttons). Без потреби — ("", []).
        """
        expected = case.get("expected_behavior", {})
        needs_pinned = (
            expected.get("must_have_pinned") is True
            or "pinned_must_contain" in expected
            or expected.get("pinned_must_be_empty") is True
        )
        if not needs_pinned:
            return ("", [])
        if not hasattr(transport, "get_pinned_message"):
            return ("", [])
        import asyncio
        # Дати боту час обробити auto-refresh hook
        await asyncio.sleep(0.8)
        try:
            return await transport.get_pinned_message()
        except Exception as e:
            import logging
            logging.getLogger("ed.runner").warning(f"fetch pinned failed: {e}")
            return ("", [])

    async def _resolve_admin_assertions(self, case: dict, assertion_results: list, transport) -> list:
        """Перехоплює admin_received assertions (які assertions.py мітить як __pending__)
        і виконує їх через transport.get_admin_messages()."""
        # Збираємо всі admin_received assertions з case (global + steps)
        admin_asserts = []
        for a in case.get("assertions", []) or []:
            if a.get("type") == "admin_received":
                admin_asserts.append(a)
        for step in case.get("steps", []) or []:
            for a in step.get("assertions", []) or []:
                if a.get("type") == "admin_received":
                    admin_asserts.append(a)
        if not admin_asserts:
            return assertion_results
        # Готуємо транспорт (для fallback-кейсів де transport=None)
        if transport is None:
            return assertion_results
        # Знаходимо pending-результати та замінюємо їх
        pending_idx = [i for i, r in enumerate(assertion_results)
                       if r.name == "admin_received" and "__pending__" in (r.message or "")]
        # Виконуємо admin перевірки (одна на всі — читаємо один раз, матчимо по черзі)
        try:
            # Максимальний timeout серед усіх — один читаємо раз
            max_timeout = max(float(a.get("within_seconds", 3)) for a in admin_asserts)
            max_count = max(int(a.get("count", 5)) for a in admin_asserts)
            admin_msgs = await transport.get_admin_messages(count=max_count, timeout=max_timeout)
        except Exception as e:
            from runner.assertions import AssertionResult
            for i in pending_idx:
                assertion_results[i] = AssertionResult(
                    name="admin_received", passed=False,
                    expected="admin messages readable",
                    actual=f"transport error: {e}",
                )
            return assertion_results
        # Помилка конфіга
        if admin_msgs and isinstance(admin_msgs[0], dict) and admin_msgs[0].get("error"):
            from runner.assertions import AssertionResult
            for i in pending_idx:
                assertion_results[i] = AssertionResult(
                    name="admin_received", passed=False,
                    expected="ADMIN_VERIFY_CHAT_ID configured",
                    actual=admin_msgs[0]["error"],
                )
            return assertion_results
        # Для кожного pending — матчимо відповідну admin_asserts[k]
        from runner.assertions import AssertionResult
        for k, idx in enumerate(pending_idx):
            if k >= len(admin_asserts):
                break
            a = admin_asserts[k]
            expected_text = a.get("text_contains", "")
            expected_buttons = a.get("has_buttons")
            # Шукаємо повідомлення яке матчить
            matched_msg = None
            for msg in admin_msgs:
                if expected_text and expected_text.lower() not in msg.get("text", "").lower():
                    continue
                if expected_buttons is True and not msg.get("buttons"):
                    continue
                matched_msg = msg
                break
            if matched_msg:
                assertion_results[idx] = AssertionResult(
                    name="admin_received", passed=True,
                    expected=f"admin msg with '{expected_text}'" if expected_text else "admin msg received",
                    actual=f"matched: {matched_msg.get('text', '')[:80]}",
                )
            else:
                assertion_results[idx] = AssertionResult(
                    name="admin_received", passed=False,
                    expected=f"admin msg with '{expected_text}'" if expected_text else "admin msg received",
                    actual=f"no match in last {len(admin_msgs)} admin messages",
                )
        return assertion_results

    async def _run_steps(self, case: dict, transport=None):
        transport = transport or self.transport
        step_responses = []
        all_texts = []
        all_assertion_results = []

        for step in case.get("steps", []):
            action = step.get("action", "send")

            if action == "send":
                text = step.get("text", "")
                if text.startswith("/"):
                    response = await transport.send_command(text)
                else:
                    response = await transport.send_message(text)
                all_texts.append(f"USER: {text}")
            elif action == "click":
                button_text = step.get("button_text", "")
                button_data = step.get("button_data", "")
                response = await transport.click_button(
                    button_text=button_text, button_data=button_data
                )
                all_texts.append(f"CLICK: {button_text or button_data}")
            elif action == "photo":
                photo_path = step.get("path", "")
                caption = step.get("caption", "")
                response = await transport.send_photo(photo_path, caption=caption)
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
                btn_index = await self._resolve_intent(intent, last_msg, transport)
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
                    response = await transport.click_button(button_text=btn_text)
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

    async def _run_conversation_legacy(self, case: dict, transport=None) -> BotResponse:
        transport = transport or self.transport
        all_texts = []
        last_response = None
        for msg in case.get("messages", []):
            response = await transport.send_message(msg["text"])
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


    @staticmethod
    def _normalize_for_match(s: str) -> str:
        """Прибирає emoji, пунктуацію, пробіли; повертає lowercase. Для string-matching."""
        # Remove emoji and symbols (broad unicode ranges)
        s = re.sub(
            r"[\U0001F300-\U0001FAFF\U00002600-\U000027BF\U0001F000-\U0001F2FF"
            r"\u2190-\u21FF\u2300-\u23FF\u2B00-\u2BFF\uFE00-\uFE0F]",
            "", s
        )
        # Remove punctuation and whitespace, keep letters/digits
        s = re.sub(r"[^\w]", "", s, flags=re.UNICODE)
        return s.lower().strip()

    async def _resolve_intent(self, intent: str, last_bot_message: str, transport) -> int | None:
        """Знаходить кнопку за intent. Стратегія: exact→substring→Haiku (тільки якщо неоднозначно)."""
        import anthropic
        from config import INTENT_CONFIDENCE_THRESHOLD, INTENT_LOGS_DIR
        from telethon.tl.types import ReplyInlineMarkup

        # Collect buttons from last bot messages
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

        intent_norm = self._normalize_for_match(intent)
        buttons_norm = [self._normalize_for_match(b) for b in button_texts]

        # === Layer 2: exact normalized match ===
        exact_matches = [i for i, bn in enumerate(buttons_norm) if bn == intent_norm]
        if len(exact_matches) == 1:
            idx = exact_matches[0]
            log.info(f"  [intent exact] '{intent}' -> [{idx}] '{button_texts[idx]}' (normalized match)")
            return idx
        elif len(exact_matches) > 1:
            log.warning(f"  [intent exact] ambiguous: {len(exact_matches)} buttons match '{intent}', falling back to Haiku")

        # === Layer 3: substring match ===
        if not exact_matches:
            substr_matches = [i for i, bn in enumerate(buttons_norm) if intent_norm and intent_norm in bn]
            if len(substr_matches) == 1:
                idx = substr_matches[0]
                log.info(f"  [intent substr] '{intent}' -> [{idx}] '{button_texts[idx]}' (substring match)")
                return idx
            elif len(substr_matches) > 1:
                log.warning(f"  [intent substr] ambiguous: {len(substr_matches)} buttons contain '{intent}', falling back to Haiku")

        # === Layer 4: Haiku (strict string matcher) ===
        cache_key = hashlib.md5(f"{intent}|{'|'.join(sorted(button_texts))}".encode()).hexdigest()
        INTENT_LOGS_DIR.mkdir(parents=True, exist_ok=True)
        cache_file = INTENT_LOGS_DIR / f"cache_{cache_key}.json"
        if cache_file.exists():
            cached = _json.loads(cache_file.read_text())
            log.info(f"  [intent cache] '{intent}' -> index={cached['index']} ({cached['reason']})")
            return cached["index"]

        formatted = "\n".join(f"[{i}] {t}" for i, t in enumerate(button_texts))
        system = """You are a STRING MATCHER for a QA test runner.
Your ONLY job: find the button whose visible text (ignoring emoji, punctuation, and spacing) most closely matches or contains the TARGET STRING.
DO NOT interpret what a user would want to do.
DO NOT consider whether the action makes logical sense in context.
DO NOT use the bot's previous message to infer intent.
This is pure text matching — like fuzzy string search.
Respond ONLY with JSON (no markdown): {"index": <int>, "confidence": <0.0-1.0>, "reason": "<short reason in Ukrainian>"}
confidence=1.0 for exact match, 0.8-0.9 for clear substring/fuzzy, <0.6 if genuinely ambiguous."""
        user = f"TARGET STRING: {intent}\n\nBUTTONS:\n{formatted}"

        log_entry = {"intent": intent, "buttons": button_texts, "layer": "haiku"}
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
                if raw.startswith("```"):
                    raw = "\n".join(
                        line for line in raw.splitlines()
                        if not line.strip().startswith("```")
                    ).strip()
                log.info(f"  [intent haiku raw] {raw[:200]}")
                parsed = _json.loads(raw)
                index = int(parsed["index"])
                confidence = float(parsed["confidence"])
                reason = parsed.get("reason", "")
                if 0 <= index < len(button_texts):
                    break
                log.warning(f"_resolve_intent: out-of-range index {index}, attempt {attempt+1}")
            else:
                log_entry["error"] = "out-of-range after 2 attempts"
                (INTENT_LOGS_DIR / f"fail_{cache_key}.json").write_text(_json.dumps(log_entry, ensure_ascii=False, indent=2))
                return None

            log.info(f"  [intent haiku] '{intent}' -> [{index}] '{button_texts[index]}' conf={confidence:.2f} ({reason})")
            log_entry.update({"index": index, "confidence": confidence, "reason": reason})
            if confidence < INTENT_CONFIDENCE_THRESHOLD:
                log.warning(f"  [intent] confidence {confidence:.2f} < threshold {INTENT_CONFIDENCE_THRESHOLD}")
                log_entry["error"] = f"low confidence: {confidence}"
                (INTENT_LOGS_DIR / f"fail_{cache_key}.json").write_text(_json.dumps(log_entry, ensure_ascii=False, indent=2))
                return None

            cache_file.write_text(_json.dumps({"index": index, "confidence": confidence, "reason": reason}, ensure_ascii=False))
            return index

        except Exception as e:
            log.error(f"_resolve_intent haiku error: {e}")
            log_entry["error"] = str(e)
            (INTENT_LOGS_DIR / f"error_{cache_key}.json").write_text(_json.dumps(log_entry, ensure_ascii=False, indent=2))
            return None


    async def _run_single_case(self, case: dict, transport, bot_name: str | None):
        """Виконує один кейс через заданий транспорт. Повертає dict з verdict+results або Exception."""
        if self.evaluator.total_cost >= self.max_cost:
            return {"verdict": "skip", "reason": "budget"}

        log.info(f"[direct] {case['id']}")

        # reset_before для direct теж
        if case.get("reset_before") and bot_name:
            from config import BOTS_CONFIG
            reset_cmd = BOTS_CONFIG.get(bot_name, {}).get("reset_command")
            if reset_cmd:
                try:
                    await asyncio.to_thread(
                        subprocess.run, reset_cmd, shell=True,
                        capture_output=True, text=True, timeout=30
                    )
                except Exception as e:
                    log.warning(f"  [reset_before direct] {e}")

        needs_reset = case.get("conversation") or case.get("reset_before", False)
        first_step_is_start = bool(
            case.get("steps") and
            len(case["steps"]) > 0 and
            case["steps"][0].get("action") == "send" and
            case["steps"][0].get("text", "").strip() == "/start"
        )
        if needs_reset and not first_step_is_start:
            await transport.reset_conversation()

        assertion_results = []
        if case.get("steps"):
            bot_response, _step_responses, assertion_results = await self._run_steps(case, transport)
        elif case.get("conversation"):
            bot_response = await self._run_conversation_legacy(case, transport)
            if case.get("assertions"):
                assertion_results = run_assertions(case["assertions"], bot_response)
        else:
            bot_response = await transport.send_message(case["message"])
            if case.get("assertions"):
                assertion_results = run_assertions(case["assertions"], bot_response)

        assertion_failed = any(not ar.passed for ar in assertion_results)

        pinned_text, pinned_buttons = await self._maybe_fetch_pinned(case, transport)
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
                "pinned_text": pinned_text,
                "pinned_buttons": pinned_buttons,
            },
        )

        verdict = "error" if judge_result.error else (
            "fail" if assertion_failed else judge_result.overall_verdict
        )
        verdict_label = "FAIL(assertion)" if assertion_failed else judge_result.overall_verdict.upper()
        log.info(f"  → [{case['id']}] {verdict_label} ({judge_result.summary[:60]})")

        return {
            "verdict": verdict,
            "case": case,
            "bot_response": bot_response,
            "assertion_results": assertion_results,
            "judge_result": judge_result,
            "assertion_failed": assertion_failed,
        }

    def _accumulate(self, case: dict, outcome, critical_failures: list):
        """Записує результат кейса в self._results + оновлює critical_failures."""
        if isinstance(outcome, Exception):
            log.error(f"  {case['id']} raised: {outcome}")
            self._results.append({
                "test_case": case,
                "bot_response": {"text": "", "response_time": 0, "has_photos": False,
                                 "photo_count": 0, "has_buttons": False, "button_texts": [],
                                 "error": str(outcome)},
                "assertions": [],
                "judge_result": {"overall_verdict": "error", "summary": f"Exception: {outcome}",
                                 "criteria": [], "critical_issues": [str(outcome)], "cost": 0.0},
            })
            critical_failures.append(f"{case['id']}: exception {outcome}")
            return
        if outcome.get("verdict") == "skip":
            return

        ar = outcome["assertion_results"]
        jr = outcome["judge_result"]
        if outcome["assertion_failed"]:
            for a in ar:
                if not a.passed:
                    critical_failures.append(
                        f"{case['id']}: assertion {a.name} failed — expected={a.expected}, actual={a.actual}"
                    )
        if jr.overall_verdict == "fail" and jr.critical_issues:
            critical_failures.extend(f"{case['id']}: {issue}" for issue in jr.critical_issues)

        br = outcome["bot_response"]
        self._results.append({
            "test_case": case,
            "bot_response": {
                "text": br.text, "response_time": br.response_time,
                "has_photos": br.has_photos, "photo_count": br.photo_count,
                "has_buttons": br.has_buttons, "button_texts": br.button_texts,
                "error": br.error,
            },
            "assertions": [
                {"name": a.name, "passed": a.passed, "expected": a.expected, "actual": a.actual}
                for a in ar
            ],
            "judge_result": {
                "overall_verdict": "fail" if outcome["assertion_failed"] else jr.overall_verdict,
                "summary": jr.summary,
                "criteria": [
                    {"name": cr.name, "verdict": cr.verdict, "reason": cr.reason}
                    for cr in jr.criteria_results
                ],
                "critical_issues": jr.critical_issues,
                "cost": jr.judge_cost,
            },
        })

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
