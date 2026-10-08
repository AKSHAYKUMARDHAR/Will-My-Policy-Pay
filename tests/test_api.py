"""API: catalogue, upload (scripted model), simulator, feedback and stats. No network."""
import importlib
import json
import pathlib

import pytest
from fastapi.testclient import TestClient

from fineprint.llm import FakeProvider, QuotaExhausted
from fineprint.terms import KEYS

ROOT = pathlib.Path(__file__).resolve().parent.parent
D01 = ROOT / "data" / "pdfs" / "D01.pdf"


def answer(**terms):
    out = {k: {"found": False} for k in KEYS}
    out.update(terms)
    return out


ROOM = {"found": True, "kind": "no_limit", "quote": "Room Rent and ICU expenses actually incurred", "page": 2}


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("LOG_PATH", str(tmp_path / "events.jsonl"))
    monkeypatch.delenv("STATS_TOKEN", raising=False)
    import fineprint.config
    importlib.reload(fineprint.config)
    import api.main
    main = importlib.reload(api.main)
    main.provider = FakeProvider([answer(room_rent=ROOM)])
    return TestClient(main.app), main


def test_simulate_returns_lines_and_totals(client):
    c, _ = client
    r = c.post("/api/simulate", json={"calc": {"room": "percent_si:1", "icu": "percent_si:2"}, "sum_insured": 500000, "age": 40,
                                      "bill": {"days": 5, "room_rate": 8000, "doctor_ot": 120000, "medicines": 60000,
                                               "diagnostics": 20000, "implants": 100000}})
    assert r.status_code == 200
    body = r.json()
    assert (body["insurer"], body["you"], body["saving_if_within_limit"]) == (280000, 60000, 60000)


def test_simulate_rejects_bad_input(client):
    c, _ = client
    assert c.post("/api/simulate", json={"calc": {}, "sum_insured": 5, "bill": {}}).status_code == 422


@pytest.mark.skipif(not D01.exists(), reason="run python -m scripts.fetch_documents first")
def test_upload_reads_and_logs_no_text(client):
    c, main = client
    r = c.post("/api/upload", files={"file": ("policy.pdf", D01.read_bytes(), "application/pdf")}, data={"sum_insured": "500000", "age": "40"})
    assert r.status_code == 200
    card = r.json()
    room = next(t for g in card["groups"] for t in g["terms"] if t["key"] == "room_rent")
    assert room["status"] == "shown" and room["page"] == 2 and card["calc"]["room"] == "no_limit"
    log = pathlib.Path(main.config.LOG_PATH).read_text(encoding="utf-8")
    assert "actually incurred" not in log and json.loads(log.splitlines()[-1])["source"] == "upload"
    # the same document again is served from the cache, without new model calls
    calls = main.provider.calls
    c.post("/api/upload", files={"file": ("policy.pdf", D01.read_bytes(), "application/pdf")}, data={"sum_insured": "500000", "age": "40"})
    assert main.provider.calls == calls


def test_upload_rejects_non_pdf(client):
    c, _ = client
    r = c.post("/api/upload", files={"file": ("x.pdf", b"hello", "application/pdf")}, data={"sum_insured": "500000", "age": "40"})
    assert r.status_code == 422


@pytest.mark.skipif(not D01.exists(), reason="run python -m scripts.fetch_documents first")
def test_upload_quota_message(client):
    c, main = client
    main.provider = FakeProvider([QuotaExhausted("daily")])
    r = c.post("/api/upload", files={"file": ("p.pdf", D01.read_bytes(), "application/pdf")}, data={"sum_insured": "750000", "age": "40"})
    assert r.status_code == 503 and "tomorrow" in r.json()["detail"]


def test_feedback_and_stats(client):
    c, _ = client
    assert c.post("/api/feedback", json={"event": "learned_yes", "card_id": "abc"}).status_code == 200
    assert c.post("/api/feedback", json={"event": "nonsense"}).status_code == 422
    stats = c.get("/api/stats").json()
    assert stats["surprises_found"] == 1 and stats["learned_rate_pct"] == 100.0


def test_catalogue_card_when_present(client):
    c, main = client
    if not main.catalogue:
        pytest.skip("no catalogue built")
    entry = next(iter(main.catalogue))
    card = c.get(f"/api/card/{entry}").json()
    assert card["groups"] and "calc" in card and card["meta"]["insurer"]
    assert c.get("/api/card/nope").status_code == 404


def test_keep_awake_setting(monkeypatch):
    import fineprint.config as cfg
    monkeypatch.setenv("RENDER_EXTERNAL_URL", "https://x.onrender.com/")
    monkeypatch.setenv("KEEP_AWAKE", "auto")
    assert importlib.reload(cfg).KEEP_AWAKE_URL == "https://x.onrender.com"
    monkeypatch.setenv("KEEP_AWAKE", "off")
    assert importlib.reload(cfg).KEEP_AWAKE_URL == ""
    monkeypatch.delenv("RENDER_EXTERNAL_URL")
    monkeypatch.setenv("KEEP_AWAKE", "auto")
    assert importlib.reload(cfg).KEEP_AWAKE_URL == ""
