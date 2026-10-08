"""Check an answer key against the policy documents: every quoted label must appear on its cited page.

    python -m eval.check_labels data/labels_holdout.json

Quotes are compared on letters and digits only (after Unicode NFKC), because text extracted from
PDFs often loses or adds spaces ("specifiedinPolicySchedule") and turns "fi" into a ligature.
"""
import json
import pathlib
import re
import sys
import unicodedata

from pypdf import PdfReader

ROOT = pathlib.Path(__file__).resolve().parent.parent
FIELDS = ["room_rent", "icu", "copay", "copay_senior", "deductible", "initial_waiting_days", "ped_waiting_months",
          "specific_waiting_months", "maternity", "pre_hosp_days", "post_hosp_days", "cataract", "restoration", "ncb",
          "ambulance", "modern_treatments", "ayush"]
UNSCORED = ("not_stated", "skip")


def compact(s: str) -> str:
    return re.sub(r"[^0-9a-z]", "", unicodedata.normalize("NFKC", s or "").lower())


def page_texts(doc_id: str) -> dict[int, str]:
    reader = PdfReader(str(ROOT / "data" / "pdfs" / f"{doc_id}.pdf"))
    return {i: compact(p.extract_text() or "") for i, p in enumerate(reader.pages, 1)}


def check(path: str) -> int:
    data = json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
    bad = total = 0
    for doc in data["documents"]:
        pages = page_texts(doc["id"])
        labels = doc["labels"]
        for field in FIELDS:
            if field not in labels:
                print(f"  {doc['id']}: missing {field}")
                bad += 1
        for field, lab in labels.items():
            if field not in FIELDS:
                print(f"  {doc['id']}.{field}: unknown field")
                bad += 1
            if lab["value"] in UNSCORED:
                continue
            total += 1
            q, p = compact(lab.get("quote", "")), lab.get("page")
            if len(q) < 12 or p not in pages or q not in pages[p]:
                where = [n for n, t in pages.items() if len(q) >= 12 and q in t]
                print(f"  {doc['id']}.{field}: quote not on page {p} (found on {where}): {lab.get('quote', '')[:70]!r}")
                bad += 1
        stated = sum(1 for v in labels.values() if v["value"] not in UNSCORED)
        print(f"  {doc['id']}: {stated} stated, {sum(1 for v in labels.values() if v['value'] == 'not_stated')} not stated, "
              f"{sum(1 for v in labels.values() if v['value'] == 'skip')} skipped")
    print(f"{total} quoted labels, {bad} problems")
    return bad


if __name__ == "__main__":
    sys.exit(1 if check(sys.argv[1]) else 0)
