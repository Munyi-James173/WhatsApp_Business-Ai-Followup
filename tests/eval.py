"""
tests/eval.py
Automated accuracy evaluation against the sample test conversations.

Usage:
  python -m tests.eval                     # run all suites
  python -m tests.eval --suite suppression # only suppression accuracy
  python -m tests.eval --suite drafting    # only message quality checks

The suppression suite tests the ≥90% target.
The drafting suite prints messages for human review and saves to human_eval_sheet.csv.
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import json
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# Ensure project root is on path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.analyser import analyse
from src.db import Message
from src.drafter import draft_message


CONVERSATIONS_DIR = Path(__file__).parent / "conversations"


@dataclass
class EvalCase:
    id: str
    description: str
    expected_needs_follow_up: bool
    expected_stage: str
    messages: list[Message]


def load_cases() -> list[EvalCase]:
    cases = []
    for path in sorted(CONVERSATIONS_DIR.glob("*.json")):
        with open(path) as fh:
            data = json.load(fh)
        messages = [
            Message(
                id=i,
                thread_id=data["id"],
                direction=m["direction"],
                content=m["content"],
                sent_at=datetime.fromisoformat(m["sent_at"].replace("Z", "+00:00")),
            )
            for i, m in enumerate(data["messages"])
        ]
        cases.append(EvalCase(
            id=data["id"],
            description=data["description"],
            expected_needs_follow_up=data["expected_needs_follow_up"],
            expected_stage=data.get("expected_stage", ""),
            messages=messages,
        ))
    return cases


async def run_suppression_suite(cases: list[EvalCase]) -> dict:
    """
    Measures accuracy of the suppression decision:
    - For threads that SHOULD NOT trigger a follow-up, did we correctly suppress?
    - For threads that SHOULD trigger, did we correctly allow?
    """
    print("\n" + "=" * 60)
    print("SUPPRESSION ACCURACY SUITE")
    print("=" * 60)

    total = len(cases)
    correct = 0
    results = []

    for case in cases:
        analysis = await analyse(case.messages)
        predicted = analysis.needs_follow_up
        expected  = case.expected_needs_follow_up
        ok = predicted == expected

        if ok:
            correct += 1

        icon = "✓" if ok else "✗"
        print(f"\n{icon} [{case.id}] {case.description[:60]}")
        print(f"   Expected: follow_up={expected}  |  Got: follow_up={predicted}  confidence={analysis.confidence:.2f}")
        print(f"   Stage: {analysis.stage}  |  Reasoning: {analysis.reasoning[:80]}")

        results.append({
            "id": case.id,
            "expected": expected,
            "predicted": predicted,
            "correct": ok,
            "confidence": analysis.confidence,
            "stage": analysis.stage,
            "reasoning": analysis.reasoning,
        })

    accuracy = correct / total
    print(f"\n{'=' * 60}")
    print(f"RESULT: {correct}/{total} correct — Accuracy: {accuracy:.0%}")
    target_met = accuracy >= 0.90
    status = "✓ PASS (≥90% target met)" if target_met else "✗ FAIL (below 90% target)"
    print(f"Status: {status}")
    print("=" * 60)

    return {"accuracy": accuracy, "correct": correct, "total": total, "cases": results}


async def run_drafting_suite(cases: list[EvalCase]) -> list[dict]:
    """
    For cases where follow-up IS expected, generate messages and
    save them for human review.
    """
    print("\n" + "=" * 60)
    print("DRAFTING QUALITY SUITE  (save to human_eval_sheet.csv)")
    print("=" * 60)

    follow_up_cases = [c for c in cases if c.expected_needs_follow_up]
    rows = []

    for case in follow_up_cases:
        analysis = await analyse(case.messages)
        if not analysis.needs_follow_up:
            print(f"\n  [{case.id}] Analyser suppressed — skipping draft.")
            continue

        message = await draft_message(analysis)
        print(f"\n[{case.id}] {case.description[:55]}")
        print(f"  Stage: {analysis.stage}  Customer: {analysis.customer_name}")
        print(f"  DRAFTED MESSAGE:")
        print(f"  ┌─────────────────────────────────────────")
        for line in message.split("\n"):
            print(f"  │ {line}")
        print(f"  └─────────────────────────────────────────")

        rows.append({
            "case_id": case.id,
            "description": case.description,
            "stage": analysis.stage,
            "drafted_message": message,
            "reviewer_1_human_sounding": "",   # to be filled by colleagues
            "reviewer_2_human_sounding": "",
            "reviewer_3_human_sounding": "",
            "notes": "",
        })

    # Save CSV for human review
    csv_path = Path(__file__).parent / "human_eval_sheet.csv"
    if rows:
        with open(csv_path, "w", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=rows[0].keys())
            writer.writeheader()
            writer.writerows(rows)
        print(f"\n  Saved {len(rows)} messages to {csv_path}")
        print("  → Ask 3 colleagues to fill in reviewer_N_human_sounding (yes/no)")

    return rows


async def main():
    parser = argparse.ArgumentParser(description="Eval suite for WhatsApp AI Follow-Up")
    parser.add_argument("--suite", choices=["suppression", "drafting", "all"], default="all")
    args = parser.parse_args()

    cases = load_cases()
    print(f"Loaded {len(cases)} test cases from {CONVERSATIONS_DIR}")

    if args.suite in ("suppression", "all"):
        await run_suppression_suite(cases)

    if args.suite in ("drafting", "all"):
        await run_drafting_suite(cases)


if __name__ == "__main__":
    asyncio.run(main())
