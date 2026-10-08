# Will My Policy Pay?

Health insurance fine print, explained before you need it. A free tool for Indian families: pick a
health policy or upload its PDF, and see the terms that decide what a claim pays (room-rent limit,
co-payment, sub-limits, waiting periods) in plain English, each with the exact words and page from
the insurer's own document. A bill simulator then shows, line by line, what a hospital bill would
pay and why.

- Product requirements: [docs/PRD.md](docs/PRD.md)
- Status: built; the held-out release run is scheduled after the dev confirmation run (see Results).

Built with Claude Code, after my [UPI Triage Agent](https://github.com/AKSHAYKUMARDHAR/UPI-Triage-Agent)
and [Is This a Scam?](https://github.com/AKSHAYKUMARDHAR/Is-This-A-Scam). This time the evaluation
runs on **real, public policy documents**, not test data I wrote.

## How it works

**The model reads; code checks, explains and calculates.**

```
 policy PDF ──► text of every page (pypdf)          injection guard (code): text aimed at AI tools
     │                                                 flags the document; nothing is shown unchecked
     ├──► Gemini reads the PDF twice (tables and columns as printed), returns 17 terms as
     │    structured values, each with an exact quote and page number
     ▼
 for each term:  both reads agree?  ── no ──►  "Check this one yourself" (both quotes shown)
                     │ yes
                 quote found on the page (letters and digits match, '...' passages one by one)?
                 every number of the value written in the quote?   ("36 months" must say 36)
                 a "no limit" quoted with words that say so?         ("up to the Sum Insured")
                     │ all yes                                 │ any no ──► "Check this one yourself"
                     ▼
                 shown, with a fixed plain-English explanation written once in code
                 (both reads say the document doesn't state it ──► "Not found in this document")

 bill simulator (code only): room cap ─► proportionate deduction with IRDAI's exemptions ─► ICU cap
   ─► non-medical items ─► cataract sub-limit ─► deductible ─► co-payment ─► sum insured
```

| Part | What it does | File |
| --- | --- | --- |
| Terms | The 17 terms, canonical values, fixed explanations in plain English | [fineprint/terms.py](fineprint/terms.py) |
| Extraction | Prompt, two reads, merge, quote and number checks | [fineprint/prompts.py](fineprint/prompts.py), [fineprint/extract.py](fineprint/extract.py), [fineprint/text.py](fineprint/text.py) |
| Calculator | Deterministic bill simulator with IRDAI's proportionate-deduction rules | [fineprint/calculator.py](fineprint/calculator.py) |
| Card | What the page shows for each term, including "not found" and "check yourself" | [fineprint/card.py](fineprint/card.py) |
| API and app | FastAPI, vanilla JS page, catalogue, uploads, simulator, grievance letter | [api/](api/), [web/](web/) |
| Eval | Answer keys, label checker, scorer comparing 1 read / 2 reads / 2 reads + checks | [eval/](eval/), [data/](data/) |

## Evaluation design

- **14 real documents**, policy wordings, customer information sheets and prospectuses from 9
  insurers, frozen in git ([data/documents.json](data/documents.json), commit `e0f3e83`) before any
  prompt existed: 5 dev documents to build on, 9 held-out documents run once for the release gate.
  The manifest pins each file's URL, UIN and SHA-256; [scripts/fetch_documents.py](scripts/fetch_documents.py)
  downloads them (they are not redistributed here).
- **Answer keys written from the documents** before any model read them: 153 held-out facts
  (commit `c3a1703`) and 85 dev facts, each with the exact quote and page, which
  `python -m eval.check_labels` verifies against the PDFs. The rules are in
  [data/LABEL_GUIDE.md](data/LABEL_GUIDE.md); the main one is "only what the document says":
  silence is "not stated", because a policy schedule can still set a limit the wording doesn't.
- **Scoring**: correct, **wrong** (a value shown that the document doesn't support: the error that
  hurts), or withheld ("not found" or "check this yourself" where the document does state a value).
- **Release gate** (PRD): wrong facts ≤ 2%, correct ≥ 85% of labelled facts, every shown fact
  quoted and verified, the calculator matches all 25 hand-worked bills (it does), no value from an
  injected document shown unchecked.

## Results

### Dev set (5 documents, 85 facts): used to build the prompt

| Run | Model | Correct | Wrong | Withheld |
| --- | --- | --- | --- | --- |
| v1, 2 reads, no checks | gemini-3.5-flash | 88% | **8.2%** | 4% |
| v1, 2 reads + checks | gemini-3.5-flash | 74% | 1.2% | 25% |
| v2, 2 reads + checks (4 of 5 documents) | gemini-3.5-flash | 91% | 1.5% | 7% |
| v2, 2 reads + checks | gemini-3.1-flash-lite | 75% | 7.1% | 18% |
| v3, 2 reads + checks | gemini-3.5-flash-lite | 80% | 8.2% | 12% |

What the dev runs showed:

- **The checks are the product.** The same two reads without verification showed 7 wrong facts;
  with the checks, 1. The catch is withheld facts, which version 2 of the prompt reduced from 21 to 5
  by asking for the words that set each value.
- **A summary that lists a benefit doesn't state its limit.** The worst early error called ambulance
  cover "up to your sum insured" from a line that only said "Expenses incurred towards Ambulance".
  A "no limit" answer now needs words that say so.
- **The lite models aren't good enough here.** Both read "up to 1% of SI or actual, whichever is
  lower" as a menu of two options, and called a premium discount a bonus. The extraction uses
  gemini-3.5-flash, whose free tier allows 20 requests a day.
- **The labeller makes mistakes too.** Run 1 found a cumulative bonus clause (Bajaj, page 22) that I
  had missed while labelling; the dev label was corrected. Held-out labels are never changed after a run.

### Held-out set (9 documents, 152 facts): the release run

Pending: runs once on the frozen configuration after the version 3 confirmation run on dev.

## Run it locally

Python 3.12.

```bash
python -m venv .venv
.venv\Scripts\activate                       # Windows; source .venv/bin/activate elsewhere
pip install -r requirements.txt
copy .env.example .env                       # add a free GEMINI_API_KEY for uploads
python -m scripts.fetch_documents            # the 14 policy PDFs, hash-checked
uvicorn api.main:app --reload                # http://localhost:8000
python -m pytest -q                          # 45 tests, no API key needed
```

```bash
python -m eval.check_labels data/labels_holdout.json     # every answer-key quote is on its page
python -m eval.run_eval dev --offline                    # re-score the dev set from cached answers
python -m scripts.build_catalogue                        # ready-made cards from cached answers
```

## API

| Method | Path | What it does |
| --- | --- | --- |
| GET | `/api/catalogue` | ready-made cards for public policy documents |
| GET | `/api/card/{id}` | one card: terms with values, explanations, quotes and pages |
| POST | `/api/upload` | a policy PDF (multipart `file`, `sum_insured`, `age`) → a card; nothing is stored |
| POST | `/api/simulate` | `{calc, sum_insured, age, bill}` → lines, adjustments, totals, saving |
| POST | `/api/feedback` | `learned_yes`, `learned_no`, `decision_changed`, `term_wrong`, `shared` |
| GET | `/api/stats` | the PRD's metrics from the event log (no document text is logged) |

## Read these results honestly

- The documents are real, but the answer keys are mine, written from the documents; a second
  labeller is part of the plan. Dev and held-out share some insurers (New India, Star, Tata) but no product.
- 152 held-out facts make the 2% bar a minimum: 3 wrong facts would pass, and the true rate could still
  be higher.
- Five documents come from a public mirror run by an advisory firm and two from partner-bank
  copies; the UIN and hash pin the exact version either way.

## Project structure

```
fineprint/  terms, text and quote checks, prompt, Gemini provider, extraction, card, calculator, guard
api/        FastAPI app
web/        index.html, styles.css, app.js (English only)
data/       documents.json (frozen manifest), labels_dev.json, labels_holdout.json, LABEL_GUIDE.md, catalogue.json
eval/       run_eval.py, check_labels.py, cache/ (model answers), results/
scripts/    fetch_documents.py, build_catalogue.py, render_prd.py
tests/      calculator (25 hand-worked bills), extraction safeguards, API
docs/       PRD.md and PRD.html
```
