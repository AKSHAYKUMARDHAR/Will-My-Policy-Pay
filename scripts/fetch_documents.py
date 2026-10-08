"""Download the policy documents listed in data/documents.json and check each one's SHA-256.

    python -m scripts.fetch_documents            # fetch what's missing into data/pdfs/, verify all
    python -m scripts.fetch_documents --freeze   # (maintainer) write hashes and page counts into the manifest

The documents are the insurers' own public PDFs, so they are fetched from their published URLs
rather than redistributed in this repo. A hash mismatch means the insurer changed the file; the
eval results apply to the hashed version only.
"""
import argparse
import hashlib
import json
import os
import pathlib
import sys

import httpx

ROOT = pathlib.Path(__file__).resolve().parent.parent
MANIFEST = ROOT / "data" / "documents.json"
PDFS = ROOT / "data" / "pdfs"
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) will-my-policy-pay/1.0"}


def sha256(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load() -> dict:
    return json.loads(MANIFEST.read_text(encoding="utf-8"))


def save(manifest: dict) -> None:
    with open(MANIFEST, "w", encoding="utf-8", newline="\n") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
        f.write("\n")


def fetch(doc: dict) -> pathlib.Path:
    path = PDFS / f"{doc['id']}.pdf"
    if not path.exists():
        r = httpx.get(doc["url"], follow_redirects=True, timeout=float(os.getenv("FETCH_TIMEOUT", "120")), headers=UA)
        r.raise_for_status()
        if not r.content.startswith(b"%PDF"):
            raise ValueError(f"{doc['id']}: the URL did not return a PDF")
        path.write_bytes(r.content)
    return path


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--freeze", action="store_true")
    args = ap.parse_args(argv)
    PDFS.mkdir(parents=True, exist_ok=True)
    manifest = load()
    bad = 0
    for doc in manifest["documents"]:
        try:
            path = fetch(doc)
        except (httpx.HTTPError, ValueError) as e:
            print(f"  {doc['id']}: download failed: {e}")
            bad += 1
            continue
        digest = sha256(path)
        if args.freeze:
            from pypdf import PdfReader
            doc["sha256"], doc["pages"] = digest, len(PdfReader(str(path)).pages)
        elif digest != doc.get("sha256"):
            print(f"  {doc['id']}: hash differs from the frozen version (the insurer may have updated the file)")
            bad += 1
            continue
        print(f"  {doc['id']}: ok ({doc['split']})")
    if args.freeze:
        save(manifest)
    print(f"{len(manifest['documents']) - bad}/{len(manifest['documents'])} documents ready in {PDFS}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
