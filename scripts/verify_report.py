"""Tiny PASS/FAIL report accumulator shared by verify.py and
verify_checks.py — split into its own module only to avoid a circular
import between the two (verify.py orchestrates, verify_checks.py runs
the checks, both need to write to the same report)."""

from __future__ import annotations


class Report:
    def __init__(self) -> None:
        self.failures: list[str] = []

    def check(self, label: str, ok: bool, detail: str = "") -> None:
        mark = "PASS" if ok else "FAIL"
        print(f"[{mark}] {label}" + (f" — {detail}" if detail else ""))
        if not ok:
            self.failures.append(label)

    def info(self, line: str) -> None:
        print(line)
