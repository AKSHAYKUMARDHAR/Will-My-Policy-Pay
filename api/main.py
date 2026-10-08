"""FastAPI service: the catalogue, uploads, the bill simulator and feedback, plus the static web app.

    uvicorn api.main:app --reload            # http://localhost:8000

GET  /api/catalogue          ready-made cards for public policy documents
GET  /api/card/{id}          one catalogue card
POST /api/upload             a policy PDF -> card (read twice by the model; nothing is stored)
POST /api/simulate           a hospital bill -> what the policy pays, line by line
POST /api/feedback           learned something / decision changed / a term is wrong
GET  /api/stats              usage metrics from the event log (optional STATS_TOKEN)
GET  /healthz

Privacy: uploaded PDFs are read in memory and discarded. The event log holds no document text,
only which card, the sum insured band, the counts of terms shown and the feedback.
"""
import asyncio
import hashlib
import json
import os
import pathlib
import time
import uuid
from collections import OrderedDict, defaultdict
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, File, Form, Header, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from fineprint import config
from fineprint.calculator import Bill, Terms, simulate
from fineprint.card import build_card, extraction_from_json
from fineprint.extract import UnreadableDocument, run_extraction
from fineprint.llm import QuotaExhausted, get_provider

ROOT = pathlib.Path(__file__).resolve().parent.parent
WEB = ROOT / "web"
CATALOGUE_PATH = ROOT / "data" / "catalogue.json"


def load_catalogue() -> dict:
    if not CATALOGUE_PATH.exists():
        return {}
    data = json.loads(CATALOGUE_PATH.read_text(encoding="utf-8"))
    return {e["id"]: e for e in data["entries"]}


class Events:
    """JSONL event log with no document text."""

    def __init__(self, path: str):
        self.path = pathlib.Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def add(self, event: dict) -> None:
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps({"ts": round(time.time(), 3), **event}, ensure_ascii=False) + "\n")

    def all(self) -> list[dict]:
        if not self.path.exists():
            return []
        return [json.loads(line) for line in self.path.read_text(encoding="utf-8").splitlines() if line.strip()]


class RateLimiter:
    def __init__(self, per_hour: int):
        self.per_hour, self.hits = per_hour, defaultdict(list)

    def allow(self, key: str) -> bool:
        now = time.time()
        self.hits[key] = [t for t in self.hits[key] if now - t < 3600]
        if len(self.hits[key]) >= self.per_hour:
            return False
        self.hits[key].append(now)
        return True


class CardCache(OrderedDict):
    """Uploads of the same document and inputs reuse the card instead of spending model calls."""

    def __init__(self, size: int = 64):
        super().__init__()
        self.size = size

    def put(self, key, value):
        self[key] = value
        self.move_to_end(key)
        while len(self) > self.size:
            self.popitem(last=False)


async def keep_awake(url: str, every_s: float) -> None:
    async with httpx.AsyncClient(timeout=30) as client:
        while True:
            await asyncio.sleep(every_s)
            try:
                await client.get(f"{url}/healthz")
            except httpx.HTTPError:
                pass


@asynccontextmanager
async def lifespan(_app):
    url = config.KEEP_AWAKE_URL
    task = asyncio.create_task(keep_awake(url, 60 * config.KEEP_AWAKE_MINUTES)) if url else None
    yield
    if task:
        task.cancel()


app = FastAPI(title="Will My Policy Pay?", docs_url="/api/docs", openapi_url="/api/openapi.json", lifespan=lifespan)
provider = get_provider()
catalogue = load_catalogue()
events = Events(config.LOG_PATH)
limiter = RateLimiter(config.RATE_LIMIT_PER_HOUR)
cards = CardCache()


def client_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for")
    return fwd.split(",")[0].strip() if fwd else (request.client.host if request.client else "unknown")


def si_band(si: int) -> str:
    return "under 5L" if si < 500000 else "5-10L" if si <= 1000000 else "above 10L"


@app.get("/api/catalogue")
async def get_catalogue():
    return [{"id": e["id"], "insurer": e["insurer"], "product": e["product"], "doc_type": e["doc_type"],
             "sum_insured": e["sum_insured"]} for e in catalogue.values()]


@app.get("/api/card/{entry_id}")
async def get_card(entry_id: str, age: int = 40):
    e = catalogue.get(entry_id)
    if not e:
        raise HTTPException(404, "No such policy in the catalogue.")
    ex = extraction_from_json(e["extraction"])
    meta = {k: e[k] for k in ("id", "insurer", "product", "doc_type", "uin", "url", "source")}
    card = build_card(ex, sum_insured=e["sum_insured"], age=age, meta=meta)
    card["card_id"] = uuid.uuid4().hex[:12]
    events.add({"type": "card", "card_id": card["card_id"], "source": "catalogue", "entry": entry_id, **card["counts"]})
    return card


@app.post("/api/upload")
async def upload(request: Request, file: UploadFile = File(...), sum_insured: int = Form(500000), age: int = Form(40)):
    if provider is None:
        raise HTTPException(503, "Reading your own document isn't available right now. Try a policy from the list.")
    if not limiter.allow(client_ip(request)):
        raise HTTPException(429, "Too many uploads from this connection. Please try again in an hour.")
    if not (50000 <= sum_insured <= 50000000) or not (0 <= age <= 100):
        raise HTTPException(422, "Check the sum insured and age.")
    data = await file.read()
    if not data.startswith(b"%PDF"):
        raise HTTPException(422, "Please upload a PDF of your policy wording or customer information sheet.")
    if len(data) > config.MAX_PDF_BYTES:
        raise HTTPException(413, "That PDF is too large. Please upload one under 15 MB.")
    key = hashlib.sha256(data + f"|{sum_insured}|{age}".encode()).hexdigest()
    card = cards.get(key)
    if card is None:
        try:
            ex = await run_extraction(data, provider, sum_insured=sum_insured, age=age)
        except UnreadableDocument as e:
            raise HTTPException(422, str(e) + " Try the policy's text PDF from the insurer's website.")
        except QuotaExhausted:
            raise HTTPException(503, "Today's free reading capacity is used up. Please try again tomorrow, or open a policy from the list.")
        if ex.pages > config.MAX_PDF_PAGES:
            raise HTTPException(413, "That document is too long to read here.")
        card = build_card(ex, sum_insured=sum_insured, age=age, meta={"product": file.filename or "Your policy", "doc_type": "upload"})
        cards.put(key, card)
    card = {**card, "card_id": uuid.uuid4().hex[:12]}
    events.add({"type": "card", "card_id": card["card_id"], "source": "upload", "si_band": si_band(sum_insured), **card["counts"]})
    return card


class SimulateRequest(BaseModel):
    calc: dict
    sum_insured: int = Field(ge=10000, le=100000000)
    age: int = Field(40, ge=0, le=110)
    bill: dict
    card_id: str | None = Field(None, max_length=32)


BILL_FIELDS = set(Bill.__dataclass_fields__)


@app.post("/api/simulate")
async def simulate_bill(req: SimulateRequest):
    try:
        bill = Bill(**{k: v for k, v in req.bill.items() if k in BILL_FIELDS})
        c = req.calc
        terms = Terms(req.sum_insured, c.get("room"), c.get("icu"), float(c.get("copay") or 0), c.get("copay_senior"),
                      req.age, float(c.get("deductible") or 0), c.get("cataract"))
        r = simulate(bill, terms)
    except (TypeError, ValueError) as e:
        raise HTTPException(422, f"Check the bill amounts: {e}")
    events.add({"type": "simulate", "card_id": req.card_id})
    return {"lines": [{"item": l.item, "billed": l.billed, "pays": l.pays, "you": l.you, "reason": l.reason} for l in r.lines],
            "adjustments": [{"item": a, "amount": b, "reason": c} for a, b, c in r.adjustments],
            "billed": r.billed, "insurer": r.insurer, "you": r.you, "caveats": r.caveats,
            "saving_if_within_limit": r.saving_if_within_limit, "room_limit_rate": r.room_limit_rate}


FEEDBACK = {"learned_yes", "learned_no", "decision_changed", "term_wrong", "shared"}


class Feedback(BaseModel):
    event: str
    card_id: str | None = Field(None, max_length=32)
    term: str | None = Field(None, max_length=40)
    note: str | None = Field(None, max_length=200)


@app.post("/api/feedback")
async def feedback(f: Feedback):
    if f.event not in FEEDBACK:
        raise HTTPException(422, "Unknown event.")
    events.add({"type": "feedback", "event": f.event, "card_id": f.card_id, "term": f.term, "note": (f.note or "")[:200]})
    return {"ok": True}


@app.get("/api/stats")
async def stats(x_stats_token: str | None = Header(None)):
    token = os.getenv("STATS_TOKEN")
    if token and x_stats_token != token:
        raise HTTPException(401, "Stats need a token.")
    ev = events.all()
    cards_ = [e for e in ev if e["type"] == "card"]
    fb = [e for e in ev if e["type"] == "feedback"]
    learned = sum(1 for e in fb if e["event"] == "learned_yes")
    asked = sum(1 for e in fb if e["event"] in ("learned_yes", "learned_no"))
    return {"cards": len(cards_), "uploads": sum(1 for e in cards_ if e.get("source") == "upload"),
            "simulations": sum(1 for e in ev if e["type"] == "simulate"),
            "surprises_found": learned, "learned_rate_pct": round(100 * learned / asked, 1) if asked else None,
            "decisions_changed": sum(1 for e in fb if e["event"] == "decision_changed"),
            "terms_reported_wrong": sum(1 for e in fb if e["event"] == "term_wrong"),
            "shares": sum(1 for e in fb if e["event"] == "shared")}


@app.get("/healthz")
async def healthz():
    return {"ok": True, "model": getattr(provider, "model", None), "catalogue": len(catalogue),
            "commit": os.getenv("RENDER_GIT_COMMIT", "")[:7] or None,
            "keep_awake": bool(config.KEEP_AWAKE_URL)}


@app.get("/")
async def index():
    return FileResponse(WEB / "index.html")


app.mount("/", StaticFiles(directory=WEB), name="web")
