"""Read a policy document twice and keep only what both reads agree on and the document proves.

For each term:
- both reads say the document doesn't state it          -> "not_found"
- the reads disagree, or one is malformed                 -> "check" (both quotes are kept for the user)
- they agree, and a quote is found in the PDF text and
  contains the numbers the value relies on                -> "shown"
- they agree but no quote can be verified                 -> "check"
A document with text aimed at AI tools is flagged, and every term becomes "check".
"""
import asyncio
from dataclasses import dataclass, field

from . import config
from .guard import find_injection
from .llm import LLMError, Provider, QuotaExhausted
from .prompts import user_message
from .terms import KEYS, canonical, same, value_numbers
from .text import compact, is_scanned, locate, numbers_in, pdf_pages, supports, words_support


@dataclass
class TermResult:
    key: str
    status: str                       # shown | not_found | check
    value: str | None = None          # canonical value when shown
    quote: str = ""
    page: int | None = None
    reason: str = ""                  # why "check": reads_disagree | quote_not_found | number_not_in_quote | words_not_in_quote | malformed | no_answer | document_flagged
    candidates: list = field(default_factory=list)   # [(canonical, quote, page)] from each read, for "check"


@dataclass
class Extraction:
    terms: dict
    pages: int
    flagged: tuple | None = None      # (page, text) of an instruction aimed at AI tools
    scanned: bool = False
    reads: list = field(default_factory=list)
    errors: list = field(default_factory=list)
    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0


class UnreadableDocument(Exception):
    """No text layer: quotes could not be checked, so nothing would be shown."""


def _verify(value: str, quote: str, cited, pages: list[str]) -> tuple[int | None, str]:
    page = locate(quote, pages, cited if isinstance(cited, int) else None)
    if page is None:
        return None, "quote_not_found"
    if value.startswith("options:"):
        import re
        option_numbers = [float(n) for n in re.findall(r"\d+(?:\.\d+)?", value[8:]) if float(n) != 0]
        if option_numbers and not (numbers_in(quote) & set(option_numbers)):
            return None, "number_not_in_quote"
        return page, ""
    q = compact(quote)
    implied_full = value == "100" and "suminsured" in q and any(w in q for w in ("restor", "reinstat", "recharg", "reset", "refill"))
    if not implied_full and not supports(quote, value_numbers(value)):
        return None, "number_not_in_quote"
    category = value.split(",")[0]
    if not words_support(quote, category):
        return None, "words_not_in_quote"
    return page, ""


def merge(key: str, reads: list[dict], pages: list[str]) -> TermResult:
    answers = [(canonical(key, r.get(key) or {}), (r.get(key) or {}).get("quote", ""), (r.get(key) or {}).get("page")) for r in reads]
    if not answers:
        return TermResult(key, "check", reason="no_answer")
    values = [a[0] for a in answers]
    if any(v is None for v in values):
        return TermResult(key, "check", reason="malformed", candidates=answers)
    if all(v == "not_stated" for v in values):
        return TermResult(key, "not_found")
    if not all(same(values[0], v) for v in values[1:]):
        return TermResult(key, "check", reason="reads_disagree", candidates=answers)
    reason = ""
    for value, quote, cited in answers:
        page, reason = _verify(value, quote, cited, pages)
        if page:
            return TermResult(key, "shown", value=values[0], quote=quote, page=page)
    return TermResult(key, "check", reason=reason, candidates=answers)


async def run_extraction(pdf: bytes, provider: Provider, *, sum_insured: int, age: int, runs: int | None = None) -> Extraction:
    pages = pdf_pages(pdf)
    if is_scanned(pages):
        raise UnreadableDocument("This PDF has no text layer (it looks scanned), so its quotes can't be checked.")
    out = Extraction(terms={}, pages=len(pages), flagged=find_injection(pages))
    prompt = user_message(sum_insured, age)
    n = runs or config.RUNS

    async def one():
        out.calls += 1
        try:
            data, usage = await provider.extract(pdf, prompt)
        except QuotaExhausted:
            raise
        except LLMError as e:
            out.errors.append(str(e)[:200])
            return None
        out.input_tokens += usage.get("input_tokens", 0)
        out.output_tokens += usage.get("output_tokens", 0)
        return data if isinstance(data, dict) else None

    reads = [r for r in await asyncio.gather(*[one() for _ in range(n)]) if r]
    out.reads = reads
    for key in KEYS:
        result = merge(key, reads, pages)
        if out.flagged and result.status == "shown":
            result = TermResult(key, "check", reason="document_flagged", candidates=[(result.value, result.quote, result.page)])
        out.terms[key] = result
    return out
