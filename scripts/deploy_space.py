"""Publish the app to a Hugging Face Docker Space.

    python -m scripts.deploy_space --dry-run   # build the Space folder and list it; nothing is uploaded
    python -m scripts.deploy_space             # create the Space if needed and upload (pip install huggingface_hub)

Needs a Hugging Face write token in HF_TOKEN (or a cached `hf auth login`). The Space is
HF_SPACE if set, otherwise <your username>/will-my-policy-pay. GitHub Actions runs this on every
push to main that changes the app (.github/workflows/deploy-space.yml).

The Space gets only what the Docker image needs, plus a README holding the Space settings
(sdk: docker, app_port: 8000). GEMINI_API_KEY is added once as a secret in the Space's settings;
the ready-made cards work without it, only uploads call Gemini.
"""
import argparse
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
REPO = "https://github.com/AKSHAYKUMARDHAR/Will-My-Policy-Pay"
SPACE_NAME = "will-my-policy-pay"
# Everything the Dockerfile copies
FILES = ["Dockerfile", "requirements.txt", "data/catalogue.json", "data/documents.json"]
DIRS = ["fineprint", "api", "web"]

README = """---
title: "Will My Policy Pay?"
emoji: 🩺
colorFrom: blue
colorTo: green
sdk: docker
app_port: 8000
pinned: false
short_description: Health insurance fine print, quoted and checked
---

# Will My Policy Pay?

Indian health insurance fine print, explained before a claim. Every limit is quoted with its page
from the insurer's own document, and a bill simulator shows what a hospital bill would actually pay.

This Space is deployed automatically from [GitHub]({repo}) (commit `{short}`), where the code,
the PRD and the evaluation on 14 real policy documents live.
"""


def commit() -> str:
    sha = os.getenv("GITHUB_SHA")
    if not sha:
        sha = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True).stdout.strip()
    return sha or "unknown"


def stage(dest: pathlib.Path, sha: str) -> list[str]:
    for rel in FILES:
        (dest / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / rel, dest / rel)
    for rel in DIRS:
        shutil.copytree(ROOT / rel, dest / rel, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    # The running app reports its commit at /healthz, so the live version can be checked
    dockerfile = (dest / "Dockerfile").read_text(encoding="utf-8")
    dockerfile = dockerfile.replace("\nCMD ", f"\nENV GIT_COMMIT={sha}\nCMD ", 1)
    (dest / "Dockerfile").write_text(dockerfile, encoding="utf-8", newline="\n")
    (dest / "README.md").write_text(README.format(repo=REPO, short=sha[:7]), encoding="utf-8", newline="\n")
    return sorted(p.relative_to(dest).as_posix() for p in dest.rglob("*") if p.is_file())


def app_url(space_id: str) -> str:
    return "https://" + space_id.lower().replace("/", "-").replace("_", "-").replace(".", "-") + ".hf.space"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)
    sha = commit()
    with tempfile.TemporaryDirectory() as tmp:
        dest = pathlib.Path(tmp)
        files = stage(dest, sha)
        if args.dry_run:
            print("\n".join(files))
            print(f"{len(files)} files would be uploaded (commit {sha[:7]})")
            return 0

        from huggingface_hub import HfApi

        api = HfApi(token=os.getenv("HF_TOKEN") or None)
        space_id = os.getenv("HF_SPACE") or f"{api.whoami()['name']}/{SPACE_NAME}"
        api.create_repo(space_id, repo_type="space", space_sdk="docker", exist_ok=True)
        # delete_patterns removes files the app no longer ships; .gitattributes is always kept
        api.upload_folder(repo_id=space_id, repo_type="space", folder_path=dest, delete_patterns="*",
                          commit_message=f"Deploy {sha[:7]} from GitHub")
    print(f"Uploaded {len(files)} files (commit {sha[:7]}) to https://huggingface.co/spaces/{space_id}")
    print(f"The app builds in a few minutes at {app_url(space_id)}")
    print("Uploads need GEMINI_API_KEY as a secret in the Space's Settings > Variables and secrets.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
