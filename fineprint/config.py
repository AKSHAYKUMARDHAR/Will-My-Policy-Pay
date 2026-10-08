"""Settings, read once from the environment (a local .env file is loaded if present)."""
import os
import pathlib

from dotenv import load_dotenv

load_dotenv(pathlib.Path(__file__).resolve().parent.parent / ".env")


def _float(name: str, default: str) -> float:
    return float(os.getenv(name, default))


def _int(name: str, default: str) -> int:
    return int(os.getenv(name, default))


GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.5-flash")
GEMINI_RPM = _float("GEMINI_RPM", "8")
TEMPERATURE = _float("TEMPERATURE", "1.0")          # two independent reads must agree, so they shouldn't be identical copies
RUNS = _int("RUNS", "2")                            # reads per document; a term is shown only when they agree

MAX_PDF_BYTES = _int("MAX_PDF_BYTES", "15000000")
MAX_PDF_PAGES = _int("MAX_PDF_PAGES", "150")
RATE_LIMIT_PER_HOUR = _int("RATE_LIMIT_PER_HOUR", "6")   # uploads per IP per hour
LOG_PATH = os.getenv("LOG_PATH", "data/logs/events.jsonl")
