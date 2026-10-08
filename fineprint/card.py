"""Turn an extraction into the fine-print card the page shows: fixed explanations, the quote and page
behind every value, and the terms the bill simulator needs."""
from dataclasses import asdict

from .extract import Extraction, TermResult
from .terms import BY_KEY, KEYS, WATCH, describe, lakh

GROUPS = [
    ("What can cut your claim", ["room_rent", "icu", "copay", "copay_senior", "deductible", "cataract"]),
    ("Waiting periods", ["initial_waiting_days", "ped_waiting_months", "specific_waiting_months", "maternity"]),
    ("What else is covered", ["pre_hosp_days", "post_hosp_days", "restoration", "ncb", "ambulance", "modern_treatments", "ayush"]),
]

WHY_CHECK = {
    "reads_disagree": "Two independent readings of the document gave different answers.",
    "quote_not_found": "We couldn't find the supporting words in the document.",
    "number_not_in_quote": "The words we found don't contain this number.",
    "words_not_in_quote": "The words we found don't clearly say this.",
    "exemption_not_none": "The words we found exempt some people (by age or city zone) rather than say there is none for everyone.",
    "shared_ceiling": "The words we found set one overall limit for several covers, not a limit for this one.",
    "malformed": "We couldn't read this term reliably.",
    "no_answer": "We couldn't read this term.",
    "document_flagged": "This document contains text aimed at AI tools, so nothing is shown without your own check.",
}


def term_view(t: TermResult, si: float, age: int, summary_doc: bool) -> dict:
    meta = BY_KEY[t.key]
    view = {"key": t.key, "name": meta.name, "status": t.status}
    if t.status == "shown":
        d = describe(t.key, t.value, si, age)
        view.update(value=d["value"], meaning=d["meaning"], watch=d["watch"] and t.key in WATCH or d["watch"],
                    quote=t.quote, page=t.page, canonical=t.value)
    elif t.status == "not_found":
        view.update(value="Not found in this document",
                    meaning=("Summaries often leave this out. " if summary_doc else "") +
                            "Your policy schedule or your insurer can confirm it.", watch=False)
    else:
        view.update(value="Check this one yourself", meaning=WHY_CHECK.get(t.reason, "We couldn't confirm this."), watch=False,
                    candidates=[{"quote": q, "page": p} for _, q, p in t.candidates if q][:2])
    return view


def calc_terms(terms: dict) -> dict:
    """The values the bill simulator uses; None where the card couldn't confirm one."""
    def shown(key):
        t = terms[key]
        return t.value if t.status == "shown" else None
    copay = shown("copay")
    deductible = shown("deductible")
    return {"room": shown("room_rent"), "icu": shown("icu"), "copay": float(copay) if copay and not copay.startswith("options") else 0.0,
            "copay_senior": shown("copay_senior"), "deductible": float(deductible) if deductible and not deductible.startswith("options") else 0.0,
            "cataract": shown("cataract")}


def build_card(ex: Extraction, *, sum_insured: int, age: int, meta: dict | None = None) -> dict:
    meta = meta or {}
    summary_doc = meta.get("doc_type") in ("CIS", "prospectus", "brochure")
    views = {k: term_view(ex.terms[k], sum_insured, age, summary_doc) for k in KEYS}
    watch = [v for v in views.values() if v.get("watch")]
    order = ["room_rent", "copay_senior", "copay", "deductible", "cataract", "icu", "ped_waiting_months", "ambulance", "modern_treatments", "ayush"]
    top = sorted(watch, key=lambda v: order.index(v["key"]) if v["key"] in order else 99)[:3]
    return {
        "meta": {**meta, "pages": ex.pages, "sum_insured": sum_insured, "sum_insured_text": lakh(sum_insured), "age": age},
        "flagged": {"page": ex.flagged[0], "text": ex.flagged[1]} if ex.flagged else None,
        "watch_outs": [{"key": v["key"], "name": v["name"], "value": v["value"]} for v in top],
        "groups": [{"title": title, "terms": [views[k] for k in keys]} for title, keys in GROUPS],
        "calc": calc_terms(ex.terms),
        "counts": {"shown": sum(1 for v in views.values() if v["status"] == "shown"),
                   "not_found": sum(1 for v in views.values() if v["status"] == "not_found"),
                   "check": sum(1 for v in views.values() if v["status"] == "check")},
    }


def extraction_to_json(ex: Extraction) -> dict:
    """What the catalogue stores: the merged terms only (no raw model output)."""
    return {"pages": ex.pages, "flagged": ex.flagged,
            "terms": {k: {**asdict(t), "candidates": [list(c) for c in t.candidates]} for k, t in ex.terms.items()}}


def extraction_from_json(data: dict) -> Extraction:
    terms = {k: TermResult(**{**v, "candidates": [tuple(c) for c in v.get("candidates", [])]}) for k, v in data["terms"].items()}
    return Extraction(terms=terms, pages=data["pages"], flagged=tuple(data["flagged"]) if data.get("flagged") else None)
