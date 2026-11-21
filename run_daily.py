#!/usr/bin/env python3
"""Daily runner: pull, build, commit and push if the page changed, write a heartbeat.

Heartbeat file: ~/.proactive-heartbeat/petition-feed, plain `key: value` lines
(timestamp, status, cost_usd, details). status is `success` when every source
parsed and the push (if any) worked, `partial` when some sources failed (their
last good items stay on the page), `failed` when nothing could be built or the
push failed. Anything but success surfaces in the owner's system view.
"""
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent
BEAT = Path.home() / ".proactive-heartbeat" / "petition-feed"


def run(*cmd):
    return subprocess.run(cmd, cwd=REPO, capture_output=True, text=True, timeout=300)


def beat(status, details):
    BEAT.parent.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+0000")
    BEAT.write_text(f"timestamp: {ts}\nstatus: {status}\ncost_usd: 0\ndetails: {details}\n")


def main():
    pull = run("git", "pull", "--ff-only", "-q")
    if pull.returncode:
        beat("failed", f"git-pull rc={pull.returncode} {pull.stderr.strip()[:160]}")
        return 1
    b = run(sys.executable, "build.py")
    try:
        summary = json.loads(b.stdout.strip().splitlines()[-1])
    except Exception:
        summary = {}
    src = " ".join(f"{k}={v}" for k, v in summary.get("sources", {}).items())
    info = f"sources=[{src}] shown={summary.get('shown')} new={summary.get('new')} nj={summary.get('nj')}"
    if b.returncode == 1 or not summary:
        beat("failed", f"build rc={b.returncode} {info} {b.stderr.strip()[-160:]}")
        return 1
    run("git", "add", "index.html", "state/items.json")
    if run("git", "diff", "--cached", "--quiet").returncode:
        c = run("git", "commit", "-q", "-m", f"Daily refresh {datetime.now().date().isoformat()}")
        p = run("git", "push", "-q")
        if c.returncode or p.returncode:
            beat("failed", f"push rc={p.returncode} commit rc={c.returncode} {info} {p.stderr.strip()[:160]}")
            return 1
        info += " pushed=yes"
    else:
        info += " pushed=no-change"
    beat("success" if b.returncode == 0 else "partial", info)
    return 0 if b.returncode == 0 else 2


if __name__ == "__main__":
    sys.exit(main())
