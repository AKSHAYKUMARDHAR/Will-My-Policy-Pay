"""Score the extraction against an answer key, through the same code path the app uses.

    python -m eval.run_eval dev                      # build/tune on the dev documents (answers cached)
    python -m eval.run_eval holdout --gate           # the release run, once, on the frozen held-out set
    python -m eval.run_eval dev --offline            # recompute from cached answers, no model calls

Versions, all from the same cached model answers:
    1 read           one read, quote checked              (what a single call would give)
    2 reads, no check   both reads agree, quotes not checked  (what the quote check removes)
    2 reads + check  both agree AND the quote is in the PDF with the value's numbers (shipped)

Every model answer is cached in eval/cache/ keyed by model, prompt hash, document hash, request and
read index, so re-runs cost nothing and an interrupted run resumes.
"""
import argparse
import asyncio
import collections
import datetime as dt
import hashlib
import json
import pathlib
import sys

from fineprint import config
from fineprint.extract import TermResult, merge, run_extraction
from fineprint.llm import GeminiProvider, LLMError, Provider, QuotaExhausted
from fineprint.prompts import PROMPT_VERSION, prompt_hash
from fineprint.terms import KEYS, canonical, same
from fineprint.text import pdf_pages

ROOT = pathlib.Path(__file__).resolve().parent.parent
CACHE = ROOT / "eval" / "cache"
RESULTS = ROOT / "eval" / "results"
AGE = 40


class CachingProvider(Provider):
    """The n-th call with the same document and request returns the n-th cached answer."""

    def __init__(self, inner: Provider | None, model: str, offline: bool):
        self.inner, self.model, self.name, self.offline = inner, model, "cached", offline
        CACHE.mkdir(parents=True, exist_ok=True)
        self.path = CACHE / f"{model}__{PROMPT_VERSION}-{prompt_hash()}.jsonl"
        self.cache = {}
        if self.path.exists():
            for line in self.path.read_text(encoding="utf-8").splitlines():
                r = json.loads(line)
                self.cache[(r["key"], r["idx"])] = r
        self.counters = collections.Counter()
        self.new_calls = 0
        self.lock = asyncio.Lock()

    async def extract(self, pdf: bytes, user: str):
        key = hashlib.sha1(hashlib.sha256(pdf).digest() + user.encode()).hexdigest()[:16]
        async with self.lock:
            idx = self.counters[key]
            self.counters[key] += 1
        if (key, idx) in self.cache:
            r = self.cache[(key, idx)]
            return r["out"], r["usage"]
        if self.offline or self.inner is None:
            raise LLMError("not cached (offline)")
        out, usage = await self.inner.extract(pdf, user)
        rec = {"key": key, "idx": idx, "out": out, "usage": usage, "at": dt.datetime.now().isoformat(timespec="seconds")}
        async with self.lock:
            self.cache[(key, idx)] = rec
            self.new_calls += 1
            with self.path.open("a", encoding="utf-8", newline="\n") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        return out, usage


def score(label: str, result: TermResult) -> str:
    """correct | wrong | withheld | skip, per data/LABEL_GUIDE.md."""
    if label == "skip":
        return "skip"
    if label == "not_stated":
        return "correct" if result.status == "not_found" else ("wrong" if result.status == "shown" else "withheld")
    if result.status == "shown":
        return "correct" if same(result.value, label) else "wrong"
    return "withheld"


def unchecked(key: str, reads: list[dict]) -> TermResult:
    """Two reads agreeing, without any quote check: what the verification step protects against."""
    values = [canonical(key, r.get(key) or {}) for r in reads]
    if not values or any(v is None for v in values):
        return TermResult(key, "check", reason="malformed")
    if all(v == "not_stated" for v in values):
        return TermResult(key, "not_found")
    if all(same(values[0], v) for v in values[1:]):
        return TermResult(key, "shown", value=values[0])
    return TermResult(key, "check", reason="reads_disagree")


def summarise(rows: list[dict]) -> dict:
    c = collections.Counter(r["score"] for r in rows if r["score"] != "skip")
    n = sum(c.values())
    stated = [r for r in rows if r["label"] not in ("not_stated", "skip")]
    pct = (lambda k: round(100 * c[k] / n, 1) if n else None)
    return {"facts": n, "correct": c["correct"], "wrong": c["wrong"], "withheld": c["withheld"],
            "correct_pct": pct("correct"), "wrong_pct": pct("wrong"), "withheld_pct": pct("withheld"),
            "stated_facts": len(stated),
            "stated_shown_correct": sum(1 for r in stated if r["score"] == "correct")}


GATE = [
    ("Wrong facts shown <= 2% of labelled facts", lambda s: s["wrong_pct"] is not None and s["wrong_pct"] <= 2.0),
    ("Correct facts >= 85% of labelled facts", lambda s: s["correct_pct"] is not None and s["correct_pct"] >= 85.0),
]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("split", choices=["dev", "holdout"])
    ap.add_argument("--docs", help="comma-separated document ids")
    ap.add_argument("--model", default=config.GEMINI_MODEL)
    ap.add_argument("--offline", action="store_true")
    ap.add_argument("--gate", action="store_true")
    ap.add_argument("--note", default="")
    args = ap.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8")

    labels = json.loads((ROOT / "data" / f"labels_{args.split}.json").read_text(encoding="utf-8"))
    manifest = {d["id"]: d for d in json.loads((ROOT / "data" / "documents.json").read_text(encoding="utf-8"))["documents"]}
    docs = [d for d in labels["documents"] if not args.docs or d["id"] in args.docs.split(",")]
    inner = None if args.offline else GeminiProvider(model=args.model)
    provider = CachingProvider(inner, args.model, args.offline)

    async def go():
        out, stopped = {}, False
        for doc in docs:
            pdf = (ROOT / "data" / "pdfs" / f"{doc['id']}.pdf").read_bytes()
            provider.counters.clear()
            try:
                ex = await run_extraction(pdf, provider, sum_insured=doc["assumed"]["sum_insured"], age=AGE, runs=2)
            except QuotaExhausted as e:
                print(f"  stopped: {e}", file=sys.stderr)
                stopped = True
                break
            out[doc["id"]] = (ex, pdf_pages(pdf))
            print(f"  {doc['id']}: {sum(1 for t in ex.terms.values() if t.status == 'shown')} shown, "
                  f"{len(ex.reads)} reads, {ex.input_tokens:,} in / {ex.output_tokens:,} out tokens"
                  + (f", errors {ex.errors}" if ex.errors else ""), file=sys.stderr, flush=True)
        return out, stopped

    extractions, stopped = asyncio.run(go())
    versions = {"1 read": [], "2 reads, no check": [], "2 reads + check": []}
    for doc in docs:
        if doc["id"] not in extractions:
            continue
        ex, pages = extractions[doc["id"]]
        for key in KEYS:
            label = doc["labels"][key]["value"]
            shipped = ex.terms[key]
            one = merge(key, ex.reads[:1], pages) if ex.reads else TermResult(key, "check", reason="no_answer")
            loose = unchecked(key, ex.reads)
            for name, res in (("1 read", one), ("2 reads, no check", loose), ("2 reads + check", shipped)):
                versions[name].append({"doc": doc["id"], "term": key, "label": label, "status": res.status,
                                       "value": res.value, "reason": res.reason, "score": score(label, res),
                                       "quote": res.quote, "page": res.page, "candidates": res.candidates})

    print(f"\n{args.split}: {len(extractions)}/{len(docs)} documents, model {args.model}, prompt {PROMPT_VERSION}-{prompt_hash()}"
          + ("  (INCOMPLETE: stopped on quota)" if stopped else ""))
    print(f"{'version':20} {'facts':>5} | {'correct':>8} {'wrong':>6} {'withheld':>9} | {'correct%':>8} {'wrong%':>7}")
    summary = {}
    for name, rows in versions.items():
        s = summarise(rows)
        summary[name] = s
        print(f"{name:20} {s['facts']:>5} | {s['correct']:>8} {s['wrong']:>6} {s['withheld']:>9} | {s['correct_pct']!s:>8} {s['wrong_pct']!s:>7}")

    shipped = versions["2 reads + check"]
    by_term = collections.defaultdict(collections.Counter)
    for r in shipped:
        by_term[r["term"]][r["score"]] += 1
    print("\nby term (2 reads + check): correct / wrong / withheld")
    print("  " + "  ".join(f"{k}: {c['correct']}/{c['wrong']}/{c['withheld']}" for k, c in by_term.items()))
    reasons = collections.Counter(r["reason"] for r in shipped if r["status"] == "check")
    print(f"why withheld: {dict(reasons)}")

    wrong = [r for r in shipped if r["score"] == "wrong"]
    if wrong:
        print("\nWrong facts shown:")
        for r in wrong:
            print(f"  {r['doc']}.{r['term']}: shown {r['value']!r}, label {r['label']!r}, p{r['page']}: {r['quote'][:110]!r}")
    withheld = [r for r in shipped if r["score"] == "withheld"]
    if withheld:
        print("\nWithheld facts:")
        for r in withheld:
            print(f"  {r['doc']}.{r['term']} [{r['reason']}] label {r['label']!r}: " +
                  " | ".join(f"{c[0]!r} p{c[2]}" for c in r["candidates"])[:200])
    if args.gate:
        print("\nRelease gate (PRD):")
        for name, check in GATE:
            print(f"  [{'PASS' if check(summary['2 reads + check']) else 'FAIL'}] {name}")

    RESULTS.mkdir(parents=True, exist_ok=True)
    tokens = (sum(e.input_tokens for e, _ in extractions.values()), sum(e.output_tokens for e, _ in extractions.values()))
    with (RESULTS / "runs.jsonl").open("a", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps({"at": dt.datetime.now().isoformat(timespec="seconds"), "split": args.split, "docs": list(extractions),
                            "complete": not stopped and len(extractions) == len(docs), "model": args.model,
                            "prompt": f"{PROMPT_VERSION}-{prompt_hash()}", "new_calls": provider.new_calls,
                            "input_tokens": tokens[0], "output_tokens": tokens[1], "note": args.note, "versions": summary},
                           ensure_ascii=False) + "\n")
    with (RESULTS / f"decisions_{args.split}.jsonl").open("w", encoding="utf-8", newline="\n") as f:
        for r in shipped:
            f.write(json.dumps({k: r[k] for k in ("doc", "term", "label", "status", "value", "reason", "score", "page", "quote")},
                               ensure_ascii=False) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
