"""Форматує звіт для терміналу і Telegram."""
from runner.engine import RunResult


def format_terminal_report(result: RunResult) -> str:
    lines = [
        "", "=" * 60,
        f" ED QA REPORT — {result.timestamp}",
        "=" * 60, "",
        f" Transport: {result.transport_type}",
        f" Judge: {result.judge_model}",
        f" Duration: {result.duration:.0f}s",
        f" Cost: ${result.total_cost:.4f}", "",
        f" TOTAL: {result.total_cases}",
        f" ✅ PASS:  {result.passed}",
        f" ⚠️  WARN:  {result.warned}",
        f" ❌ FAIL:  {result.failed}",
        f" 💥 ERROR: {result.errors}", "",
    ]

    if result.critical_failures:
        lines.append(" 🚨 CRITICAL FAILURES:")
        for cf in result.critical_failures:
            lines.append(f"   • {cf}")
        lines.append("")

    lines.append("-" * 60)
    for r in result.results:
        case_id = r["test_case"]["id"]
        verdict = r["judge_result"]["overall_verdict"]
        summary = r["judge_result"]["summary"]
        icon = {"pass": "✅", "warn": "⚠️ ", "fail": "❌", "error": "💥"}.get(verdict, "💥")
        lines.append(f" {icon} {case_id}")
        lines.append(f"    {summary[:80]}")
        for cr in r["judge_result"].get("criteria", []):
            if cr["verdict"] in ("fail", "warn"):
                cr_icon = "❌" if cr["verdict"] == "fail" else "⚠️ "
                lines.append(f"    {cr_icon} {cr['name']}: {cr['reason'][:60]}")

    lines.extend(["", "=" * 60])
    return "\n".join(lines)


def format_verbose_report(result: RunResult) -> str:
    """Детальний звіт для LLM-оркестратора: питання → відповідь → вердикт."""
    lines = [
        "", "=" * 70,
        f" ED VERBOSE REPORT — {result.timestamp}",
        "=" * 70, "",
    ]
    for r in result.results:
        case = r["test_case"]
        resp = r["bot_response"]
        judge = r["judge_result"]
        verdict = judge["overall_verdict"]
        icon = {"pass": "✅", "warn": "⚠️ ", "fail": "❌", "error": "💥"}.get(verdict, "💥")

        lines.append(f"{icon} [{case['id']}] {verdict.upper()}")
        lines.append(f"  ПИТАННЯ: {case.get('message', '')[:200]}")
        lines.append(f"  ВІДПОВІДЬ: {(resp.get('text') or '[порожньо]')[:400]}")
        if resp.get('error'):
            lines.append(f"  ERROR: {resp['error']}")
        lines.append(f"  СУДДЯ: {judge['summary']}")
        for cr in judge.get("criteria", []):
            if cr["verdict"] in ("fail", "warn"):
                cr_icon = "❌" if cr["verdict"] == "fail" else "⚠️ "
                lines.append(f"    {cr_icon} {cr['name']}: {cr['reason']}")
        if judge.get("critical_issues"):
            for ci in judge["critical_issues"]:
                lines.append(f"    🚨 {ci}")
        lines.append("")

    lines.append("=" * 70)
    return "\n".join(lines)


def format_telegram_report(result: RunResult) -> str:
    if result.failed > 0 or result.critical_failures:
        status = "🔴"
    elif result.warned > 0:
        status = "🟡"
    else:
        status = "🟢"

    model_short = result.judge_model.split("-")[1] if "-" in result.judge_model else result.judge_model

    lines = [
        f"{status} **Ed QA Report**",
        f"📅 {result.timestamp}", "",
        f"✅ Pass: {result.passed} | ⚠️ Warn: {result.warned} | ❌ Fail: {result.failed}",
        f"🤖 Judge: {model_short}",
        f"💰 ${result.total_cost:.3f} | ⏱ {result.duration:.0f}s",
    ]

    if result.critical_failures:
        lines.extend(["", "🚨 **Critical:**"])
        for cf in result.critical_failures[:5]:
            lines.append(f"• {cf[:80]}")

    failed_tests = [r for r in result.results if r["judge_result"]["overall_verdict"] == "fail"]
    if failed_tests:
        lines.extend(["", "❌ **Failed:**"])
        for ft in failed_tests[:5]:
            lines.append(f"• `{ft['test_case']['id']}`: {ft['judge_result']['summary'][:60]}")

    return "\n".join(lines)
