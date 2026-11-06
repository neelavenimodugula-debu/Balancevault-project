# AI prompt and verification log

Entries are written as the work happens. Each must say what was requested, what the tool returned, what was specifically wrong or risky, what was done to correct/check it, and identify the commit containing that correction. Future entries are intentionally not prefilled.

## 2026-11-06: Day 1 project bootstrap

- **Asked:** Set up LedgerLine for a six-day build in the existing `d:\LedgerLine` workspace with Python 3.13, FastAPI, PostgreSQL, tests, integrity documentation, and a daily Git workflow; scaffold only the first day's work.
- **Produced:** The project setup helper refused with “The user has not opened a valid workspace folder,” despite this VS Code session being rooted at `d:\LedgerLine` and containing the configured `.venv`. The initial manual starter is a health-only FastAPI app plus one HTTP test; it does not implement any money behavior.
- **Wrong or risky:** Treating the visible workspace as unavailable would have blocked the requested setup. Also, a passing health test proves only that the API/test harness starts; it says nothing about ledger integrity.
- **Correction and check:** Created the starter directly in the actual workspace, ignored `.venv`, and ran `python -m pytest -q` (1 passed). Integrity work remains open and is tracked in `THREATS.md`; no money-safety claim is made from this check.
- **Commit containing the correction:** `00af2659fc0f04640b9163fef01df95b045b114f` (local commit; add the GitHub permalink after the remote is configured).

## Entry template for future work

Add a dated section after the relevant work is completed. Do not copy a planned prompt and describe it as completed.

- **Asked:**
- **Produced:**
- **Wrong or risky:**
- **Correction and check:**
- **Commit containing the correction:**