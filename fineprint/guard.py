"""Instruction-like text aimed at an AI tool, inside an uploaded document. Decided in code, before any card
is shown: a flagged document gets a warning and every term is marked "check this yourself".

Kept narrow so ordinary policy language ("The Company shall not...") never fires.
"""
import re

_PATTERNS = [
    r"\bignore (?:all |any |the )?(?:previous|prior|above|earlier|other) (?:instructions|rules|text)\b",
    r"\b(?:system|developer) (?:prompt|message|instruction)s?\b",
    r"\b(?:AI|A\.I\.|assistant|chatbot|language model|LLM|GPT|ChatGPT|Gemini|Claude|model)\b[^.\n]{0,40}\b(?:must|should|shall|will)\b[^.\n]{0,20}\b(?:report|answer|say|state|output|respond|record|extract|classify|treat|consider)\b",
    r"\b(?:note|instruction|message)s? (?:to|for) (?:the )?(?:AI|assistant|model|reader bot|chatbot|LLM)\b",
    r"\bif you are an? (?:AI|assistant|language model|bot)\b",
    r"\byou are (?:an? )?(?:AI|assistant|language model|chatbot)\b",
    r"\b(?:respond|reply|answer) (?:only )?with\b[^.\n]{0,30}\b(?:json|no limit|not found)\b",
]
_RX = [re.compile(p, re.I) for p in _PATTERNS]


def find_injection(pages: list[str]) -> tuple[int, str] | None:
    """(page number, matched text) of the first instruction aimed at an AI, or None."""
    for n, text in enumerate(pages, 1):
        flat = re.sub(r"\s+", " ", text or "")
        for rx in _RX:
            m = rx.search(flat)
            if m:
                return n, m.group(0)[:120]
    return None
