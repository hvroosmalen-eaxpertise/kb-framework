"""Everyday pipeline loop: ingest the inbox, then finalise.

Usage:
    python orchestrate.py --kb <path> [--file SRC] [--no-lint] [--deep]
                          [--no-strict] [--no-commit] [--no-push]

Ingest is best-effort per source (failures isolate to pipeline/failed/). The
hard gates are lint and the strict build, enforced by finalize(); a gate failure
aborts before any commit. On a clean run this commits and pushes by default
(use --no-push to hold the commit for review).
"""

import sys
import argparse
import subprocess
from pathlib import Path

import yaml
from dotenv import load_dotenv

import usage
from finalize import finalize


def _ingest(kb_root: Path, framework_path: Path, file_arg) -> int:
    """Run ingest.py over the inbox (or a single --file). Returns its exit code."""
    ingest_script = framework_path / "pipeline" / "ingest.py"
    cmd = [sys.executable, str(ingest_script), "--kb", str(kb_root)]
    if file_arg:
        cmd += ["--file", file_arg]
    return subprocess.run(cmd, cwd=str(kb_root)).returncode


def main():
    parser = argparse.ArgumentParser(description="Ingest the inbox then finalise the KB.")
    parser.add_argument("--kb", required=True)
    parser.add_argument("--file", help="Ingest a single source file (.pdf or .md)")
    parser.add_argument("--no-lint", action="store_true")
    parser.add_argument("--deep", action="store_true")
    parser.add_argument("--no-strict", action="store_true")
    parser.add_argument("--no-commit", action="store_true")
    parser.add_argument("--no-push", action="store_true")
    args = parser.parse_args()

    kb_root = Path(args.kb).resolve()
    load_dotenv(kb_root / ".env")
    cfg_file = kb_root / "config" / "kb.yaml"
    kb_config = yaml.safe_load(cfg_file.read_text(encoding="utf-8")) if cfg_file.exists() else {}
    fw_raw = (kb_config or {}).get("framework_path", "../kb-framework")
    framework_path = (kb_root / fw_raw).resolve()
    usage.configure(kb_root / "logs")

    rc = _ingest(kb_root, framework_path, args.file)
    if rc != 0:
        print("ABORT: ingest — ingest.py exited non-zero", file=sys.stderr)
        sys.exit(rc)

    rc = finalize(kb_root, framework_path, kb_config or {},
                  lint=not args.no_lint, deep=args.deep,
                  strict=not args.no_strict,
                  commit=not args.no_commit, push=not args.no_push)
    sys.exit(rc)


if __name__ == "__main__":
    main()
