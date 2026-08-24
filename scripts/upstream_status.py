#!/usr/bin/env python3
"""Report pinned, absorbed, classified-review, local, and remote upstream commits."""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
UPSTREAM = ROOT / "upstreams" / "ai-berkshire"
LOCK_PATH = ROOT / "sources.lock.json"


def git(*args: str, check: bool = True) -> str:
    completed = subprocess.run(
        ["git", *args],
        cwd=UPSTREAM,
        text=True,
        capture_output=True,
        check=False,
    )
    if check and completed.returncode != 0:
        raise ValueError(completed.stderr.strip() or completed.stdout.strip())
    return completed.stdout.strip()


def category(path: str) -> str:
    if path.startswith("skills/") or path.startswith("codex-skills/"):
        return "skills"
    if path.startswith("tools/") or path.startswith("scripts/"):
        return "tools"
    if path.startswith("tests/"):
        return "tests"
    if path.startswith("reports/") or path.startswith("data/") or path.startswith("assets/"):
        return "excluded-content"
    if path.endswith(".md"):
        return "documentation"
    return "other"


def build_status(fetch: bool) -> dict[str, Any]:
    lock = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    entry = next(item for item in lock["upstreams"] if item["id"] == "ai-berkshire")
    if not (UPSTREAM / ".git").exists() and not UPSTREAM.is_dir():
        raise ValueError("AI Berkshire submodule is not initialized")
    if fetch:
        git("fetch", "--quiet", "origin", "main")
    local = git("rev-parse", "HEAD")
    remote = git("rev-parse", "origin/main")
    reviewed = entry["reviewed_commit"]
    reviews = entry.get("reviews", [])
    review_baseline = reviews[-1]["through_commit"] if reviews else reviewed
    changed_files = (
        [] if remote == review_baseline else git("diff", "--name-only", f"{review_baseline}..{remote}").splitlines()
    )
    categories: dict[str, int] = {}
    for path in changed_files:
        key = category(path)
        categories[key] = categories.get(key, 0) + 1
    if local != entry["pinned_commit"]:
        state = "submodule_mismatch"
    elif remote != review_baseline:
        state = "review_required"
    else:
        state = "current"
    return {
        "schema": "money-craft.upstream-status.v1",
        "state": state,
        "fetched": fetch,
        "pinned_commit": entry["pinned_commit"],
        "reviewed_commit": reviewed,
        "review_baseline_commit": review_baseline,
        "absorbed_commit": entry["absorbed_commit"],
        "local_commit": local,
        "remote_commit": remote,
        "changed_file_count": len(changed_files),
        "changed_categories": categories,
        "changed_files": changed_files,
        "automatic_merge": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fetch", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    try:
        payload = build_status(args.fetch)
    except (OSError, ValueError, json.JSONDecodeError, KeyError) as exc:
        payload = {"schema": "money-craft.upstream-status.v1", "state": "error", "error": str(exc)}
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 1
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload["state"] == "current" else 2


if __name__ == "__main__":
    raise SystemExit(main())
