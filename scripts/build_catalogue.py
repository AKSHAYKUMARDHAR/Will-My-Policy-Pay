"""Build data/catalogue.json: ready-made cards for the documents in data/documents.json, from cached
model answers (the same answers the eval scored), so serving the catalogue costs no model calls.

Every card is reviewed against the hand-written answer key before it is published: a value the key
contradicts, or one the key can't settle (a plan-dependent term), is shown as "check this yourself"
with the readings, never as a value. Uploads get no such review; the site says so.

    python -m scripts.build_catalogue                       # the current prompt's cache for the default model
    python -m scripts.build_catalogue --cache eval/cache/gemini-3.5-flash__v2-b011b82d.jsonl
"""
import argparse
import asyncio
import json
import pathlib
import sys

from eval.run_eval import AGE, CACHE, CachingProvider
from fineprint import config
from fineprint.card import extraction_to_json
from fineprint.extract import TermResult, run_extraction
from fineprint.llm import LLMError
from fineprint.terms import same

ROOT = pathlib.Path(__file__).resolve().parent.parent


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default=config.GEMINI_MODEL)
    ap.add_argument("--cache", help="a specific cache file (default: the current prompt's)")
    args = ap.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8")

    provider = CachingProvider(None, args.model, offline=True)
    if args.cache:
        provider.path = pathlib.Path(args.cache)
        provider.cache = {}
        for line in provider.path.read_text(encoding="utf-8").splitlines():
            r = json.loads(line)
            provider.cache[(r["key"], r["idx"])] = r
    manifest = json.loads((ROOT / "data" / "documents.json").read_text(encoding="utf-8"))["documents"]
    keys = {}   # the answer key for every labelled document (dev includes the run-1 set since v2)
    for split in ("dev", "holdout2"):
        for d in json.loads((ROOT / "data" / f"labels_{split}.json").read_text(encoding="utf-8"))["documents"]:
            keys[d["id"]] = d

    def review(doc_id: str, ex) -> list[str]:
        """Turn every shown value the answer key contradicts or can't settle into 'check this yourself'."""
        changed = []
        labels = keys[doc_id]["labels"] if doc_id in keys else None
        for key, t in list(ex.terms.items()):
            if t.status != "shown":
                continue
            label = labels[key]["value"] if labels else None
            if label is None or label == "skip" or not same(t.value, label):
                reason = "review_disagrees" if label not in (None, "skip") else "review_unsettled"
                ex.terms[key] = TermResult(key, "check", reason=reason, candidates=[(t.value, t.quote, t.page)])
                changed.append(key)
        return changed

    async def go():
        entries = []
        for doc in manifest:
            pdf_path = ROOT / "data" / "pdfs" / f"{doc['id']}.pdf"
            if not pdf_path.exists():
                print(f"  {doc['id']}: PDF missing (run python -m scripts.fetch_documents)")
                continue
            provider.counters.clear()
            si = keys[doc["id"]]["assumed"]["sum_insured"] if doc["id"] in keys else 500000
            ex = await run_extraction(pdf_path.read_bytes(), provider, sum_insured=si, age=AGE, runs=2)
            if len(ex.reads) < 2:
                print(f"  {doc['id']}: skipped, {len(ex.reads)} cached reads")
                continue
            changed = review(doc["id"], ex)
            entries.append({**{k: doc[k] for k in ("id", "insurer", "product", "doc_type", "uin", "url", "source")},
                            "sum_insured": si, "reviewed": changed, "extraction": extraction_to_json(ex)})
            shown = sum(1 for t in ex.terms.values() if t.status == "shown")
            print(f"  {doc['id']}: {doc['product']} ({shown} terms shown"
                  + (f"; review turned {', '.join(changed)} into 'check yourself'" if changed else "") + ")")
        return entries

    try:
        entries = asyncio.run(go())
    except LLMError as e:
        print(f"stopped: {e}")
        return 1
    out = {"model": args.model, "cache": provider.path.name, "entries": entries}
    with open(ROOT / "data" / "catalogue.json", "w", encoding="utf-8", newline="\n") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
        f.write("\n")
    print(f"{len(entries)} catalogue entries -> data/catalogue.json (from {provider.path.name})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
