# Will My Policy Pay?

Health insurance fine print, explained before you need it. A free tool for Indian families: pick a
health policy or upload its PDF, and see the terms that decide what a claim pays (room-rent limit,
co-payment, sub-limits, waiting periods) in plain English, each with the exact words and page from
the insurer's own document. A bill simulator then shows, line by line, what a hospital bill would
pay and why.

- Live: https://will-my-policy-pay.onrender.com
- Product requirements: [docs/PRD.md](docs/PRD.md)
- Status: built and live. Release run 1 was blocked (3.3% of facts wrong against a 2% bar); on review,
  3 of its 5 wrong facts were answer-key mistakes. Release run 2, on fresh documents, is next (see Results).

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

- **14 real documents**, policy wordings, customer information sheets and prospectuses from 10
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
| v3, 2 reads + checks | gemini-3.5-flash | 92% | 3.5% | 5% |
| **v3 + exemption and shared-ceiling checks (frozen)** | gemini-3.5-flash | **91%** | **0%** | 9% |

What the dev runs showed:

- **The checks are the product.** The same two reads without verification showed 7 wrong facts;
  with the checks, 1. The catch is withheld facts, which version 2 of the prompt cut from 25% to 7%
  by asking for the words that set each value.
- **A summary that lists a benefit doesn't state its limit.** The worst early error called ambulance
  cover "up to your sum insured" from a line that only said "Expenses incurred towards Ambulance".
  A "no limit" answer now needs words that say so.
- **"None" has to be said of everyone.** Version 3 on all 5 documents showed 3 wrong facts. Two read
  "no co-payment" from sentences that only exempt some people ("will not apply for those insured persons
  who have entered the policy before attaining 61 years of age"; "Insured paying premium as per Zone I
  can avail treatment in ... Zone IV without copayment"). One took a ceiling shared by several covers
  ("Our maximum liability collectively for ... would not exceed the hospitalization Sum Insured") as
  AYUSH's own limit, when the AYUSH clause sets a lower one. Two code checks now send such quotes to
  "check this yourself": all 3 wrong facts and 1 correct one (Bajaj's ambulance cover rests on the
  same shared ceiling). Re-scored from the same cached answers, with no new model calls.
- **The lite models aren't good enough here.** Both read "up to 1% of SI or actual, whichever is
  lower" as a menu of two options, and called a premium discount a bonus. The extraction uses
  gemini-3.5-flash, whose free tier allows 20 requests a day.
- **The labeller makes mistakes too.** Run 1 found a cumulative bonus clause (Bajaj, page 22) that I
  had missed while labelling; the dev label was corrected. Held-out labels are never changed after a run.

### Held-out set (9 documents, 152 facts): the release run

Run once on the frozen configuration (prompt v3, gemini-3.5-flash, two reads, every check above) on
9 October 2026: [eval/results/holdout_run1.log](eval/results/holdout_run1.log).

| Run | Correct | Wrong | Withheld |
| --- | --- | --- | --- |
| 1 read, no checks | 90.8% | 3.9% (6) | 5.3% |
| 2 reads, no checks | 93.4% | 3.9% (6) | 2.6% |
| **2 reads + checks (what ships)** | **91.4%** (139) | **3.3%** (5) | 5.3% (8) |

**Release gate: blocked.** Correct facts pass (91.4% against 85%); wrong facts fail (3.3% against 2%:
5 of 152, where 3 would pass). Every value shown had its quote found on the cited page, and the bill
simulator matches all 25 hand-worked bills.

The 5 wrong facts, on review (the score above stands, because held-out labels never change after a run):

- **Two answers wider than the answer key.** ICICI Lombard Elevate (H06) and SBI Arogya Supreme (H09):
  the specific-illness waiting period shown as 3 and 24 months, joining the 24-month clause with a
  separate 90-day wait for hypertension, diabetes and heart conditions. The guide counted only the
  specific-illness clause, yet for a buyer with diabetes the 90 days is real.
- **Three mistakes in my answer key.** H08's deductible is an optional "Aggregate Deductible" cover
  ("can be opted only at inception"), and rule 2 says the base plan then has none, as the model said.
  H09's "Sum Insured Refill" (100%) is item C.18 of the base covers, which the key missed. H08's AYUSH
  limit: the plan table on page 61 gives every plan "AYUSH Treatment: Covered upto sum insured", and the
  model quoted that row; the key had used only the wording on page 7, which leaves the sub-limit to the
  policy schedule.

So none of the 5 is a clear model error. My first write-up of this run called the AYUSH answer the
error this product exists to prevent, read from a cell that never names AYUSH; that was wrong, and the
check I drafted from it (an item's quote must name the item) cost 4 correct dev answers and caught
nothing, so it was dropped.

### Version 2: the answer-key rules, then a fresh release run

These 9 documents have now been seen, so they joined the dev set with the corrections above and a
wider definition of the specific-illness waiting period: the Excl02 clause plus any other wait the
exclusions set for named illnesses. Both are logged in [data/LABEL_GUIDE.md](data/LABEL_GUIDE.md);
`labels_holdout.json` keeps the key release run 1 was scored against. The system itself is unchanged.

| Dev, v2 answer keys (14 documents, 237 facts) | Correct | Wrong | Withheld |
| --- | --- | --- | --- |
| 2 reads + checks, re-scored from the cached answers | 92.8% | 0.4% (1) | 6.8% |

The one wrong fact is SBI's 15-day wait for COVID-19, which the model leaves out of the list.

### Release run 2: 9 fresh documents (pending)

Frozen before any labelling (`51ac132`): Go Digit, IFFCO Tokio, National (Mediclaim Plus), Kotak, Liberty
(Health Prime Connect and the Health Connect Supra super top-up), Galaxy Health, Bajaj (Health Guard)
and SBI (Arogya Plus); five of the insurers are new to the project. The answer key was written under the
v2 rules before any model read them (`26e6d75`): 141 scored facts, 80 stated and 61 "not stated", with
12 plan-dependent terms skipped. At 141 facts the 2% bar allows 2 wrong. It runs once on 10 October 2026,
on the unchanged system.

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

## Deploy

The Docker image serves the app on `$PORT` (default 8000) and needs one secret, `GEMINI_API_KEY`,
ideally from its own Google project so the free daily requests aren't shared.

[render.yaml](render.yaml) deploys it on Render's free plan in Singapore, the closest region to India.
Use a workspace of its own: free instance hours (750 a month) are counted per workspace, and the scam
checker's always-on service uses its workspace's hours.

- **Staying awake.** The free plan sleeps after 15 minutes without inbound traffic. The app pings its
  own public URL every 10 minutes (`KEEP_AWAKE`, on by default on Render; `off` turns it off), which
  uses about 744 of the 750 hours a month. `/healthz` never calls the model, so the pings cost no quota.
- `/healthz` reports the deployed commit and whether keep-awake is on.
- `/api/stats` is protected by a generated `STATS_TOKEN` (send it as `X-Stats-Token`).
- Hugging Face Spaces was the first choice, but since 2026 new free accounts can't create Docker
  Spaces on free hardware.

The ready-made cards ship in the image (`data/catalogue.json`), so they work with no API key; only
uploads call Gemini.

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
