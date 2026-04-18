#!/usr/bin/env python3
"""Ed — QA Agent for Telegram bots.

Usage:
  python main.py run [--transport telegram|direct] [--judge haiku|sonnet|opus]
                     [--suite insilver_seeds.json] [--category pricing]
                     [--budget 2.0] [--notify]

  python main.py generate [--suite insilver_seeds.json] [--variations 5]

  python main.py report [--file run_2026-04-15.json]

Examples:
  # Швидкий тест через direct, суддя Haiku
  python main.py run --transport direct --judge haiku

  # Повний e2e через Telegram, суддя Sonnet, звіт в ТГ
  python main.py run --transport telegram --judge sonnet --notify

  # Тільки pricing
  python main.py run --category pricing

  # Генерувати варіації
  python main.py generate --variations 5
"""
import argparse
import asyncio
import json
import logging
import sys

from config import (
    BASE_DIR, JUDGE_MODELS, MAX_COST_PER_RUN,
    REPORTS_DIR, SUITES_DIR, REPORT_CHAT_ID,
    TELEGRAM_API_ID, TELEGRAM_API_HASH, TELEGRAM_PHONE, SESSION_PATH,
)
from suites.loader import load_suite, load_block, load_all_blocks, load_scenario, filter_cases
from suites.generator import expand_suite
from judge.evaluator import Evaluator
from judge.rubrics.insilver import INSILVER_RUBRIC
from judge.rubrics.abby import ABBY_RUBRIC
from judge.rubrics.garcia import GARCIA_RUBRIC
from runner.engine import TestRunner
from reports.formatter import format_terminal_report, format_telegram_report, format_verbose_report

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.FileHandler(BASE_DIR / "ed.log"),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger("ed.main")


def build_transports(cli_choice: str, bot: str = "insilver") -> dict:
    """Створює словник транспортів відповідно до cli_choice.

    cli_choice="auto"     -> {"direct": ..., "telegram": ...}
    cli_choice="direct"   -> {"direct": ...}
    cli_choice="telegram" -> {"telegram": ...}
    """
    from transports.direct import DirectTransport
    from transports.telegram import TelegramTransport
    from config import TARGET_BOTS

    bot_username = TARGET_BOTS.get(bot, TARGET_BOTS["insilver"])
    transports = {}
    if cli_choice in ("auto", "direct"):
        transports["direct"] = DirectTransport(bot_name=bot)
    if cli_choice in ("auto", "telegram"):
        transports["telegram"] = TelegramTransport(bot_username=bot_username)
    if not transports:
        raise ValueError(f"Unknown transport: {cli_choice}")
    return transports


def get_transport(name: str, bot: str = "insilver"):
    """DEPRECATED: use build_transports(). Kept for backward compat."""
    ts = build_transports(name, bot)
    return ts[name]


async def send_telegram_notification(message: str):
    from telethon import TelegramClient
    client = TelegramClient(SESSION_PATH, TELEGRAM_API_ID, TELEGRAM_API_HASH)
    await client.start(phone=TELEGRAM_PHONE)
    await client.send_message(REPORT_CHAT_ID, message, parse_mode="md")
    await client.disconnect()
    log.info("Telegram notification sent")


async def cmd_run(args):
    bot = getattr(args, 'bot', None) or 'insilver'

    # Режим 3: ad-hoc seed з --seed флагу
    if getattr(args, 'seed', None):
        from suites.generator import generate_variations
        seed_case = {
            "id": "adhoc_01",
            "category": "adhoc",
            "message": args.seed,
            "context": "Ad-hoc seed від оркестратора",
            "tags": ["adhoc"],
            "edge_case": False,
            "conversation": False,
            "expected_behavior": {"should_respond_in_ukrainian": True, "should_be_relevant": True},
        }
        variations_count = getattr(args, 'variations', 5)
        variations = generate_variations(seed_case, count=variations_count, model="claude-haiku-4-5-20251001")
        cases = [seed_case] + [
            {**seed_case, "id": f"adhoc_var_{i+1}", "message": v, "tags": ["adhoc", "variation"]}
            for i, v in enumerate(variations)
        ]
        log.info(f"Ad-hoc: 1 seed + {len(variations)} variations = {len(cases)} cases")
    elif getattr(args, 'block', None):
        cases = []
        for block_name in args.block:
            cases.extend(load_block(bot, block_name))
    elif getattr(args, 'scenario', None):
        cases = load_scenario(bot, args.scenario)
    else:
        # Спробувати нову block-структуру, fallback на старий flat файл
        new_cases = load_all_blocks(bot)
        if new_cases:
            cases = new_cases
        else:
            suite_file = getattr(args, 'suite', None) or "insilver_seeds.json"
            cases = load_suite(suite_file)
        if not cases:
            log.error("No test cases found")
            sys.exit(1)

    if args.category:
        cases = filter_cases(cases, category=args.category)
    if args.edge_only:
        cases = filter_cases(cases, edge_cases_only=True)
    if not cases:
        log.error("No test cases after filtering")
        sys.exit(1)

    transports = build_transports(args.transport, bot=bot)
    judge_model = JUDGE_MODELS.get(args.judge, JUDGE_MODELS["sonnet"])
    if bot == "abby":
        rubric = ABBY_RUBRIC
    elif bot == "garcia":
        rubric = GARCIA_RUBRIC
    else:
        rubric = INSILVER_RUBRIC
    evaluator = Evaluator(rubric=rubric, model=judge_model)
    runner = TestRunner(
        transports=transports,
        evaluator=evaluator,
        max_cost=args.budget,
        cli_transport=args.transport,
        parallel=args.parallel,
    )

    log.info(f"Running {len(cases)} tests via {args.transport} (parallel={args.parallel}), judge: {args.judge}")
    result = await runner.run_suite(cases, bot_name=args.bot)

    # --verbose: повні транскрипти фейлів
    if getattr(args, 'verbose', False):
        print(format_verbose_report(result))
    else:
        print(format_terminal_report(result))

    if args.notify and REPORT_CHAT_ID:
        tg_report = format_telegram_report(result)
        await send_telegram_notification(tg_report)


async def cmd_generate(args):
    suite_file = args.suite or "insilver_seeds.json"
    seeds = load_suite(suite_file)
    if not seeds:
        log.error(f"No seeds in {suite_file}")
        sys.exit(1)

    expanded = expand_suite(seeds, variations_per_seed=args.variations)

    output_file = suite_file.replace("seeds", "suite")
    output_path = SUITES_DIR / output_file
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(expanded, f, ensure_ascii=False, indent=2)

    print(f"✅ {len(seeds)} seeds → {len(expanded)} cases")
    print(f"   Saved: {output_path}")


def cmd_blocks(args):
    """Показати список блоків і кількість кейсів."""
    import json as _json
    bot = getattr(args, 'bot', None) or 'insilver'
    blocks_dir = SUITES_DIR / bot / "blocks"
    if not blocks_dir.exists():
        print(f"No blocks dir: {blocks_dir}")
        sys.exit(1)

    print(f"\n\U0001f4e6 Blocks for {bot}:")
    total = 0
    for f in sorted(blocks_dir.glob("*.json")):
        with open(f, "r", encoding="utf-8") as fh:
            cases = _json.load(fh)
        active = [c for c in cases if not c.get("id", "").startswith("_")]
        disabled = len(cases) - len(active)
        total += len(active)
        status = f" ({disabled} disabled)" if disabled else ""
        print(f"  {f.stem:30s} — {len(active)} cases{status}")
    print(f"\n  Total: {total} active cases")

    archived_dir = SUITES_DIR / bot / "archived"
    if archived_dir.exists():
        archived = list(archived_dir.glob("*.json"))
        if archived:
            print(f"\n\U0001f4c1 Archived: {', '.join(f.stem for f in archived)}")

    scenarios_dir = SUITES_DIR / bot / "scenarios"
    if scenarios_dir.exists():
        for f in sorted(scenarios_dir.glob("*.json")):
            with open(f, "r", encoding="utf-8") as fh:
                scenario = _json.load(fh)
            blocks = scenario.get("blocks", [])
            arrow = ' → '.join(blocks)
            print(f"\n\U0001f3ac Scenario '{f.stem}': {arrow}")


def cmd_report(args):
    if args.file:
        report_path = REPORTS_DIR / args.file
    else:
        reports = sorted(REPORTS_DIR.glob("run_*.json"), reverse=True)
        if not reports:
            print("No reports found")
            sys.exit(1)
        report_path = reports[0]

    with open(report_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    # --case <id> --full: показати один кейс повністю
    if getattr(args, 'case', None):
        case_result = next(
            (r for r in data["results"] if r["test_case"]["id"] == args.case), None
        )
        if not case_result:
            print(f"❌ Case '{args.case}' не знайдено")
            print(f"Доступні: {[r['test_case']['id'] for r in data['results']]}")
            sys.exit(1)
        tc = case_result["test_case"]
        resp = case_result["bot_response"]
        judge = case_result["judge_result"]
        verdict = judge["overall_verdict"]
        icon = {"✅":"pass","⚠️":"warn","❌":"fail"}.get(verdict, "💥")
        print(f"\n{'='*60}")
        print(f"📄 {args.case} — {verdict.upper()}")
        print(f"{'='*60}")
        print(f"\n💬 ПИТАННЯ:\n{tc.get('message', '')}")
        print(f"\n🤖 ВІДПОВІДЬ БОТА ({resp.get('response_time',0):.1f}s):\n{resp.get('text') or '[порожньо]'}")
        print(f"\n🧐 СУДДЯ:\n{judge['summary']}")
        print("\n📋 КРИТЕРІЇ:")
        for cr in judge.get("criteria", []):
            cr_icon = {"✅":"pass","⚠️ ":"warn","❌":"fail"}.get(cr["verdict"], "💥")
            icon2 = "✅" if cr["verdict"]=="pass" else ("⚠️ " if cr["verdict"]=="warn" else "❌")
            print(f"  {icon2} {cr['name']}: {cr['reason']}")
        if judge.get("critical_issues"):
            print("\n🚨 КРИТИЧНІ:")
            for ci in judge["critical_issues"]:
                print(f"  • {ci}")
        return

    s = data["summary"]
    print(f"\n📄 {report_path.name} | {data['timestamp']}")
    print(f"✅ {s['passed']} | ⚠️  {s['warned']} | ❌ {s['failed']} | 💥 {s['errors']} | Rate: {s['pass_rate']}")
    print(f"💰 ${data['total_cost_usd']} | Judge: {data['judge_model']}")

    if data.get("critical_failures"):
        print("\n🚨 Critical:")
        for cf in data["critical_failures"]:
            print(f"  • {cf}")


def main():
    parser = argparse.ArgumentParser(description="Ed — QA Agent")
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_p = subparsers.add_parser("run", help="Run test suite")
    run_p.add_argument("--transport", choices=["auto", "telegram", "direct"], default="auto")
    run_p.add_argument("--parallel", type=int, default=5, help="Parallel direct cases (1=sequential). Telegram always sequential.")
    run_p.add_argument("--judge", choices=["haiku", "sonnet", "opus"], default="sonnet")
    run_p.add_argument("--bot", default="insilver", help="Bot name (insilver, garcia, etc)")
    run_p.add_argument("--block", action="append", help="Run specific block(s). Repeatable: --block pricing --block catalog")
    run_p.add_argument("--scenario", help="Run a scenario (sequence of blocks)")
    run_p.add_argument("--suite", help="Legacy: flat suite JSON filename")
    run_p.add_argument("--category", help="Filter by category")
    run_p.add_argument("--edge-only", action="store_true", dest="edge_only")
    run_p.add_argument("--budget", type=float, default=MAX_COST_PER_RUN)
    run_p.add_argument("--notify", action="store_true", help="Send report to TG")
    run_p.add_argument("--verbose", action="store_true", help="Full transcripts for failed cases")
    run_p.add_argument("--seed", help="Ad-hoc seed message (generates variations automatically)")
    run_p.add_argument("--variations", type=int, default=5, help="Variations for --seed")

    gen_p = subparsers.add_parser("generate", help="Generate variations from expand fields")
    gen_p.add_argument("--bot", default="insilver")
    gen_p.add_argument("--block", help="Generate for specific block")
    gen_p.add_argument("--suite", help="Legacy: flat suite file")
    gen_p.add_argument("--variations", type=int, default=5)
    gen_p.add_argument("--seed", help="Ad-hoc seed message to generate variations for")

    blocks_p = subparsers.add_parser("blocks", help="List blocks and scenarios")
    blocks_p.add_argument("--bot", default="insilver")

    rep_p = subparsers.add_parser("report", help="Show report")
    rep_p.add_argument("--file", help="Specific report file")
    rep_p.add_argument("--case", help="Show specific case by ID")
    rep_p.add_argument("--full", action="store_true", help="Full case details")

    args = parser.parse_args()

    if args.command == "run":
        asyncio.run(cmd_run(args))
    elif args.command == "generate":
        asyncio.run(cmd_generate(args))
    elif args.command == "blocks":
        cmd_blocks(args)
    elif args.command == "report":
        cmd_report(args)


if __name__ == "__main__":
    main()
