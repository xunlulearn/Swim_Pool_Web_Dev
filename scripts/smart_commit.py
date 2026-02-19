from __future__ import annotations

import argparse
import re
import subprocess
import sys
import time
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
GIT_DIR = PROJECT_ROOT / ".git"
INDEX_LOCK = GIT_DIR / "index.lock"
LOCK_WAIT_TIMEOUT_SECONDS = 45
STALE_LOCK_SECONDS = 300
CONVENTIONAL_RE = re.compile(r"^[a-z]+\([^)]+\): .+")
DEFAULT_MESSAGE = "chore(repo): update project files"


def run(cmd: list[str], capture: bool = False) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        cwd=PROJECT_ROOT,
        text=True,
        capture_output=capture,
        check=False,
    )


def ensure_git_repo() -> None:
    result = run(["git", "rev-parse", "--is-inside-work-tree"], capture=True)
    if result.returncode != 0 or result.stdout.strip() != "true":
        print("[ERROR] Current directory is not a git work tree.")
        raise SystemExit(1)


def wait_for_index_lock() -> None:
    start = time.time()
    warned = False
    while INDEX_LOCK.exists():
        try:
            age = time.time() - INDEX_LOCK.stat().st_mtime
        except OSError:
            age = 0

        if age >= STALE_LOCK_SECONDS:
            try:
                INDEX_LOCK.unlink()
                print("[WARN] Removed stale .git/index.lock (older than 5 minutes).")
                return
            except OSError:
                pass

        elapsed = time.time() - start
        if elapsed > LOCK_WAIT_TIMEOUT_SECONDS:
            print("[ERROR] .git/index.lock is still present. Another git process may be running.")
            print("[ERROR] Close other git processes and retry.")
            raise SystemExit(1)

        if not warned:
            print("[INFO] Waiting for .git/index.lock to be released...")
            warned = True
        time.sleep(1)


def validate_message(message: str) -> None:
    if not CONVENTIONAL_RE.match(message):
        print("[ERROR] Invalid commit message.")
        print("[ERROR] Required format: type(scope): description")
        print(f"[ERROR] Example: {DEFAULT_MESSAGE}")
        raise SystemExit(1)


def ensure_changes_staged() -> bool:
    add_result = run(["git", "add", "-A"])
    if add_result.returncode != 0:
        print("[ERROR] git add failed.")
        raise SystemExit(add_result.returncode)

    diff_result = run(["git", "diff", "--cached", "--quiet"])
    if diff_result.returncode == 0:
        print("[INFO] No staged changes. Nothing to commit.")
        return False
    return True


def current_branch() -> str:
    branch_result = run(["git", "rev-parse", "--abbrev-ref", "HEAD"], capture=True)
    if branch_result.returncode != 0:
        print("[ERROR] Cannot determine current branch.")
        raise SystemExit(branch_result.returncode)
    return branch_result.stdout.strip()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Safe git stage/commit/push workflow for Windows and cross-platform shells."
    )
    parser.add_argument(
        "message",
        nargs="?",
        default=DEFAULT_MESSAGE,
        help='Commit message in "type(scope): description" format.',
    )
    parser.add_argument(
        "--no-push",
        action="store_true",
        help="Create commit locally without pushing to origin.",
    )
    args = parser.parse_args()

    ensure_git_repo()
    validate_message(args.message)
    wait_for_index_lock()

    if not ensure_changes_staged():
        return 0

    commit_result = run(["git", "commit", "-m", args.message])
    if commit_result.returncode != 0:
        print("[ERROR] git commit failed.")
        return commit_result.returncode

    if args.no_push:
        print("[OK] Commit created (push skipped by --no-push).")
        return 0

    branch = current_branch()
    push_result = run(["git", "push", "-u", "origin", branch])
    if push_result.returncode != 0:
        print("[ERROR] git push failed.")
        return push_result.returncode

    print(f"[OK] Pushed to origin/{branch}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
