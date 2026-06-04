"""
Rebuild the MkDocs wiki and commit changes to Git.

Usage:
    python rebuild.py --kb <path-to-kb>
"""

import argparse
import datetime
import subprocess
import sys
from pathlib import Path


def log_change(logs_dir: Path, message: str):
    timestamp = datetime.datetime.now().isoformat(timespec="seconds")
    entry = f"{timestamp} {message}\n"
    change_log = logs_dir / "changes.log"
    with open(change_log, "a", encoding="utf-8") as f:
        f.write(entry)
    print(entry.strip())


def run(cmd: list, cwd: Path) -> subprocess.CompletedProcess:
    result = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    if result.stdout:
        print(result.stdout.strip())
    if result.stderr:
        print(result.stderr.strip(), file=sys.stderr)
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--kb", required=True)
    parser.add_argument("--no-git", action="store_true", help="Skip git commit/push")
    args = parser.parse_args()

    kb_root  = Path(args.kb).resolve()
    logs_dir = kb_root / "logs"
    logs_dir.mkdir(exist_ok=True)

    # 1. Build wiki
    log_change(logs_dir, "BUILD_START")
    result = run(["mkdocs", "build", "--clean"], cwd=kb_root)
    if result.returncode != 0:
        log_change(logs_dir, "BUILD_FAILED")
        sys.exit(1)
    log_change(logs_dir, "BUILD_OK")

    if args.no_git:
        return

    # 2. Stage and commit
    run(["git", "add", "docs/", "logs/"], cwd=kb_root)

    # Check if there is anything to commit
    status = run(["git", "status", "--porcelain"], cwd=kb_root)
    if not status.stdout.strip():
        log_change(logs_dir, "NO_CHANGES — nothing to commit")
        return

    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    commit_msg = f"ingest: wiki rebuild {timestamp}"
    run(["git", "commit", "-m", commit_msg], cwd=kb_root)
    log_change(logs_dir, f"COMMITTED: {commit_msg}")

    # 3. Push
    push = run(["git", "push"], cwd=kb_root)
    if push.returncode == 0:
        log_change(logs_dir, "PUSHED to remote")
    else:
        log_change(logs_dir, "PUSH_FAILED — check remote config")


if __name__ == "__main__":
    main()
