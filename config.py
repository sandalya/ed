"""Ed — QA Agent configuration."""
import os
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).parent
load_dotenv(BASE_DIR / ".env")

# --- Telegram (Telethon) ---
TELEGRAM_API_ID = int(os.getenv("TELEGRAM_API_ID", "0"))
TELEGRAM_API_HASH = os.getenv("TELEGRAM_API_HASH", "")
TELEGRAM_PHONE = os.getenv("TELEGRAM_PHONE", "")
SESSION_PATH = str(BASE_DIR / "data" / "telethon_session" / "ed_session")

# --- Target bot ---
TARGET_BOT_USERNAME = os.getenv("TARGET_BOT_USERNAME", "")
ADMIN_VERIFY_CHAT_ID = int(os.getenv("ADMIN_VERIFY_CHAT_ID", "0"))

# --- Anthropic ---
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")

# --- Judge ---
JUDGE_MODELS = {
    "haiku": "claude-haiku-4-5-20251001",
    "sonnet": "claude-sonnet-4-20250514",
    "opus": "claude-opus-4-20250514",
}
JUDGE_MODEL_KEY = os.getenv("JUDGE_MODEL", "sonnet")
JUDGE_MODEL = JUDGE_MODELS.get(JUDGE_MODEL_KEY, JUDGE_MODELS["sonnet"])

# --- Report ---
REPORT_CHAT_ID = int(os.getenv("REPORT_CHAT_ID", "0"))

# --- Budget ---
MAX_COST_PER_RUN = float(os.getenv("MAX_COST_PER_RUN", "2.00"))

# Cost per 1M tokens
MODEL_COSTS = {
    "claude-haiku-4-5-20251001": {"input": 0.80, "output": 4.00},
    "claude-sonnet-4-20250514": {"input": 3.00, "output": 15.00},
    "claude-opus-4-20250514": {"input": 15.00, "output": 75.00},
}

# --- Ed Bot interface ---
ED_BOT_TOKEN = os.getenv("ED_BOT_TOKEN", "")

# --- Paths ---
REPORTS_DIR = BASE_DIR / "reports" / "history"
SUITES_DIR = BASE_DIR / "suites" / "data"

# --- Target bots ---
TARGET_BOTS = {
    "insilver": os.getenv("TARGET_BOT_USERNAME", "@insilver_v3_bot"),
    "abby": "@abby_ksu_bot",
}

# --- click_intent settings ---
INTENT_CONFIDENCE_THRESHOLD = float(os.getenv("INTENT_CONFIDENCE_THRESHOLD", "0.7"))
INTENT_LOGS_DIR = BASE_DIR / "data" / "intent_logs"
