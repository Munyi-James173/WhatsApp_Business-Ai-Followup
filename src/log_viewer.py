"""
src/log_viewer.py
Pretty-prints the audit log in real time.
Usage: tail -f logs/audit.jsonl | python -m src.log_viewer
       python -m src.log_viewer --file logs/audit.jsonl --last 50
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime


ACTION_COLORS = {
    "analysis_complete":    "\033[36m",   # cyan
    "follow_up_scheduled":  "\033[33m",   # yellow
    "follow_up_sent":       "\033[32m",   # green
    "follow_up_suppressed": "\033[90m",   # dark gray
    "inbound_message":      "\033[37m",   # white
    "error":                "\033[31m",   # red
}
RESET = "\033[0m"


def render(line: str) -> str:
    try:
        ev = json.loads(line)
    except json.JSONDecodeError:
        return line

    action = ev.get("action", "unknown")
    color  = ACTION_COLORS.get(action, "")
    ts     = ev.get("ts", "")[:19].replace("T", " ")
    tid    = ev.get("thread_id", "?")[-10:]

    parts = [f"{color}[{ts}] {action:<28} thread=…{tid}"]

    if action == "analysis_complete":
        parts.append(
            f"  follow_up={ev['needs_follow_up']}  conf={ev['confidence']:.2f}"
            f"  stage={ev.get('stage')}  reason={ev.get('reasoning','')[:60]}"
        )
    elif action == "follow_up_scheduled":
        parts.append(f"  send_at={ev.get('scheduled_for','')[:16]}  stage={ev.get('stage')}")
    elif action == "follow_up_sent":
        parts.append(f"  msg_id={ev.get('provider_message_id')}  msg={ev.get('message','')[:60]}")
    elif action == "follow_up_suppressed":
        parts.append(f"  reason={ev.get('reason')}")
    elif action == "error":
        parts.append(f"  {ev.get('error','')[:80]}")

    return "\n".join(parts) + RESET


def stream_stdin():
    for line in sys.stdin:
        line = line.strip()
        if line:
            print(render(line))
            sys.stdout.flush()


def tail_file(path: str, last: int):
    with open(path) as fh:
        lines = fh.readlines()
    for line in lines[-last:]:
        print(render(line.strip()))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--file", help="Log file path (reads from stdin if omitted)")
    parser.add_argument("--last", type=int, default=50, help="Show last N entries")
    args = parser.parse_args()

    if args.file:
        tail_file(args.file, args.last)
    else:
        stream_stdin()
