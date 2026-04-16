#!/usr/bin/env python3
"""Ed — Telegram bot interface.

Команди:
  /run          — повний прогін (direct transport, haiku)
  /run tg       — через Telegram transport
  /run pricing  — тільки категорія pricing
  /run edge     — тільки edge cases
  /report       — останній звіт
  /status       — статус системи
  /help         — допомога
"""
import asyncio
import logging
import os
import sys
from pathlib import Path

from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

BASE_DIR = Path(__file__).parent
sys.path.insert(0, str(BASE_DIR))

from config import (
    ED_BOT_TOKEN, JUDGE_MODELS, MAX_COST_PER_RUN,
    REPORTS_DIR, TELEGRAM_API_ID, TELEGRAM_API_HASH,
    TELEGRAM_PHONE, SESSION_PATH, REPORT_CHAT_ID,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.FileHandler(BASE_DIR / "ed_bot.log"),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger("ed.bot")

AUTHORIZED_USERS = {REPORT_CHAT_ID}
_run_lock = asyncio.Lock()


def is_authorized(user_id: int) -> bool:
    return user_id in AUTHORIZED_USERS


async def cmd_help(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update.effective_user.id):
        return
    await update.message.reply_text(
        "🧪 *Ed — QA Agent*\n\n"
        "*Команди:*\n"
        "`/run` — прогін всіх тестів (direct, haiku)\n"
        "`/run tg` — через реальний Telegram\n"
        "`/run pricing` — тільки категорія\n"
        "`/run edge` — тільки edge cases\n"
        "`/run sonnet` — суддя Sonnet (точніше, дорожче)\n"
        "`/report` — останній звіт\n"
        "`/status` — статус системи\n\n"
        "Можна комбінувати: `/run tg pricing sonnet`",
        parse_mode="Markdown"
    )


async def cmd_status(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update.effective_user.id):
        return

    reports = sorted(REPORTS_DIR.glob("run_*.json"), reverse=True)
    last_run = reports[0].stem.replace("run_", "") if reports else "немає"

    import json
    last_cost = "—"
    last_result = "—"
    if reports:
        try:
            with open(reports[0]) as f:
                d = json.load(f)
            s = d["summary"]
            last_cost = f"${d['total_cost_usd']}"
            last_result = f"✅{s['passed']} ⚠️{s['warned']} ❌{s['failed']}"
        except Exception:
            pass

    locked = "🔄 Тест запущено" if _run_lock.locked() else "💤 Вільний"
    await update.message.reply_text(
        f"🧪 *Ed Status*\n\n"
        f"Стан: {locked}\n"
        f"Останній прогін: `{last_run}`\n"
        f"Результат: {last_result}\n"
        f"Вартість: {last_cost}\n"
        f"Звітів збережено: {len(reports)}",
        parse_mode="Markdown"
    )


async def cmd_report(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update.effective_user.id):
        return

    import json
    reports = sorted(REPORTS_DIR.glob("run_*.json"), reverse=True)
    if not reports:
        await update.message.reply_text("Звітів ще немає. Спочатку запусти `/run`", parse_mode="Markdown")
        return

    with open(reports[0]) as f:
        data = json.load(f)

    s = data["summary"]
    if data["summary"]["failed"] > 0 or data.get("critical_failures"):
        status = "🔴"
    elif data["summary"]["warned"] > 0:
        status = "🟡"
    else:
        status = "🟢"

    model_short = data["judge_model"].split("-")[1] if "-" in data["judge_model"] else data["judge_model"]

    lines = [
        f"{status} *Ed QA Report*",
        f"📅 `{data['timestamp']}`\n",
        f"✅ Pass: {s['passed']} | ⚠️ Warn: {s['warned']} | ❌ Fail: {s['failed']}",
        f"🤖 Judge: {model_short} | 💰 ${data['total_cost_usd']} | ⏱ {data['duration_seconds']}s\n",
    ]

    if data.get("critical_failures"):
        lines.append("🚨 *Critical:*")
        for cf in data["critical_failures"][:8]:
            lines.append(f"• {cf[:90]}")
        lines.append("")

    failed = [r for r in data["results"] if r["judge_result"]["overall_verdict"] == "fail"]
    if failed:
        lines.append("❌ *Failed:*")
        for ft in failed[:6]:
            lines.append(f"• `{ft['test_case']['id']}`: {ft['judge_result']['summary'][:70]}")

    warned = [r for r in data["results"] if r["judge_result"]["overall_verdict"] == "warn"]
    if warned:
        lines.append("\n⚠️ *Warned:*")
        for wt in warned[:4]:
            lines.append(f"• `{wt['test_case']['id']}`: {wt['judge_result']['summary'][:70]}")

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def cmd_run(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update.effective_user.id):
        return

    if _run_lock.locked():
        await update.message.reply_text("⏳ Тест вже запущено, зачекай.")
        return

    # Парсимо аргументи
    args = (ctx.args or [])
    transport = "telegram" if "tg" in args else "direct"
    judge_key = "sonnet" if "sonnet" in args else ("opus" if "opus" in args else "haiku")
    category = None
    edge_only = "edge" in args
    block = None
    known = {"tg", "sonnet", "opus", "haiku", "edge"}
    for a in args:
        if a not in known:
            block = a  # перший невідомий аргумент = назва блоку
            break

    judge_model = JUDGE_MODELS.get(judge_key, JUDGE_MODELS["haiku"])

    desc_parts = [f"transport: *{transport}*", f"judge: *{judge_key}*"]
    if block:
        desc_parts.append(f"block: *{block}*")
    if edge_only:
        desc_parts.append("edge cases only")

    await update.message.reply_text(
        f"🚀 Запускаю тести...\n" + " | ".join(desc_parts) + "\n\n"
        f"{'⚠️ Буде ~12 повідомлень до @insilver_v3_bot' if transport == 'telegram' else ''}",
        parse_mode="Markdown"
    )

    async with _run_lock:
        try:
            await _run_tests(update, transport, judge_model, category, edge_only, block)
        except Exception as e:
            log.error(f"Run error: {e}", exc_info=True)
            await update.message.reply_text(f"💥 Помилка: {e}")


async def _run_tests(update: Update, transport_name: str, judge_model: str, category: str, edge_only: bool, block: str = None):
    from suites.loader import load_suite, load_block, load_all_blocks, filter_cases
    from judge.evaluator import Evaluator
    from judge.rubrics.insilver import INSILVER_RUBRIC
    from runner.engine import TestRunner
    from reports.formatter import format_telegram_report

    if block:
        cases = load_block("insilver", block)
    else:
        cases = load_all_blocks("insilver")
        if not cases:
            cases = load_suite("insilver_seeds.json")
    if category:
        cases = filter_cases(cases, category=category)
    if edge_only:
        cases = filter_cases(cases, edge_cases_only=True)

    if not cases:
        await update.message.reply_text("❌ Немає тест-кейсів після фільтрації")
        return

    await update.message.reply_text(f"📋 {len(cases)} кейсів. Починаю...")

    if transport_name == "telegram":
        from transports.telegram import TelegramTransport
        transport = TelegramTransport()
    else:
        sys.path.insert(0, "/home/sashok/.openclaw/workspace/insilver-v3")
        from transports.direct import DirectTransport
        transport = DirectTransport()

    evaluator = Evaluator(rubric=INSILVER_RUBRIC, model=judge_model)
    runner = TestRunner(transport=transport, evaluator=evaluator, max_cost=MAX_COST_PER_RUN)

    result = await runner.run_suite(cases)

    report_text = format_telegram_report(result)
    await update.message.reply_text(report_text, parse_mode="Markdown")


def main():
    if not ED_BOT_TOKEN:
        log.error("ED_BOT_TOKEN не знайдено в .env")
        sys.exit(1)

    # python-telegram-bot потрібен
    try:
        import telegram
    except ImportError:
        log.error("python-telegram-bot не встановлено. Запусти: pip install python-telegram-bot")
        sys.exit(1)

    app = Application.builder().token(ED_BOT_TOKEN).build()
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("start", cmd_help))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("report", cmd_report))
    app.add_handler(CommandHandler("run", cmd_run))

    log.info("Ed bot starting...")
    app.run_polling()


if __name__ == "__main__":
    main()
