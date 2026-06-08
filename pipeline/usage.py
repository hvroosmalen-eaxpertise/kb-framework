"""Token-usage accounting for Claude calls across the pipeline.

Every ``call_claude()`` (in ingest.py and query.py) reports its usage here. Records
append to ``<logs>/token_usage.jsonl`` — one JSON object per call — so totals are
exact even across process boundaries (bootstrap spawns query.py as subprocesses).

Wiring:
- A script calls :func:`configure` once in ``main()`` with its KB ``logs`` dir. That
  also exports ``KB_LOGS_DIR`` so child processes write to the *same* file.
- :func:`reset` truncates the log for a fresh session (bootstrap uses this so a
  "from-scratch" run yields a clean tally).
- An ``atexit`` hook prints this process's running total.

CLI — tally an existing log without re-running the pipeline::

    python usage.py --kb <path-to-kb>      # reads <kb>/logs/token_usage.jsonl
    python usage.py --logs <path-to-logs>
"""

import os
import json
import atexit
import datetime
from pathlib import Path

LOG_NAME = "token_usage.jsonl"

# Process-local running total (one process = one ingest/query invocation).
_totals = {"calls": 0, "input_tokens": 0, "output_tokens": 0}


def _logs_dir() -> Path:
    return Path(os.environ.get("KB_LOGS_DIR", "logs"))


def configure(logs_dir) -> None:
    """Point accounting at ``logs_dir`` and propagate it to child processes."""
    os.environ["KB_LOGS_DIR"] = str(Path(logs_dir).resolve())


def reset() -> None:
    """Start a fresh session: truncate the usage log and the in-process counters."""
    _totals.update(calls=0, input_tokens=0, output_tokens=0)
    path = _logs_dir() / LOG_NAME
    if path.exists():
        path.unlink()


def record(model: str, usage, label: str = "") -> tuple[int, int]:
    """Account one Claude call. ``usage`` is the SDK's ``message.usage`` object."""
    it = int(getattr(usage, "input_tokens", 0) or 0)
    ot = int(getattr(usage, "output_tokens", 0) or 0)
    _totals["calls"] += 1
    _totals["input_tokens"] += it
    _totals["output_tokens"] += ot

    rec = {
        "ts": datetime.datetime.now().isoformat(timespec="seconds"),
        "label": label,
        "model": model,
        "input_tokens": it,
        "output_tokens": ot,
    }
    d = _logs_dir()
    d.mkdir(parents=True, exist_ok=True)
    with open(d / LOG_NAME, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec) + "\n")
    return it, ot


def totals() -> dict:
    return dict(_totals)


def tally(logs_dir) -> dict:
    """Read a usage log and group totals by label and model. For the CLI/reporting."""
    path = Path(logs_dir) / LOG_NAME
    out = {"calls": 0, "input_tokens": 0, "output_tokens": 0, "by_label": {}}
    if not path.exists():
        return out
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            r = json.loads(line)
        except json.JSONDecodeError:
            continue
        it, ot = int(r.get("input_tokens", 0)), int(r.get("output_tokens", 0))
        out["calls"] += 1
        out["input_tokens"] += it
        out["output_tokens"] += ot
        b = out["by_label"].setdefault(
            r.get("label") or "(unlabeled)",
            {"calls": 0, "input_tokens": 0, "output_tokens": 0},
        )
        b["calls"] += 1
        b["input_tokens"] += it
        b["output_tokens"] += ot
    return out


def format_tally(t: dict) -> str:
    lines = ["Token usage", "===========",
             f"{'stage':<20}{'calls':>7}{'input':>12}{'output':>12}{'total':>12}",
             "-" * 63]
    for label, b in sorted(t["by_label"].items(),
                           key=lambda kv: -(kv[1]["input_tokens"] + kv[1]["output_tokens"])):
        tot = b["input_tokens"] + b["output_tokens"]
        lines.append(f"{label:<20}{b['calls']:>7}{b['input_tokens']:>12,}"
                     f"{b['output_tokens']:>12,}{tot:>12,}")
    grand = t["input_tokens"] + t["output_tokens"]
    lines.append("-" * 63)
    lines.append(f"{'TOTAL':<20}{t['calls']:>7}{t['input_tokens']:>12,}"
                 f"{t['output_tokens']:>12,}{grand:>12,}")
    return "\n".join(lines)


@atexit.register
def _print_summary() -> None:
    if _totals["calls"]:
        grand = _totals["input_tokens"] + _totals["output_tokens"]
        print(f"[usage] {_totals['calls']} Claude calls | "
              f"in={_totals['input_tokens']:,} out={_totals['output_tokens']:,} "
              f"total={grand:,} tokens")


def main() -> None:
    import argparse
    p = argparse.ArgumentParser(description="Tally pipeline token usage.")
    p.add_argument("--kb", help="KB root (reads <kb>/logs/token_usage.jsonl)")
    p.add_argument("--logs", help="logs dir directly")
    args = p.parse_args()
    if args.logs:
        logs = Path(args.logs)
    elif args.kb:
        logs = Path(args.kb) / "logs"
    else:
        logs = _logs_dir()
    print(format_tally(tally(logs)))


if __name__ == "__main__":
    main()
