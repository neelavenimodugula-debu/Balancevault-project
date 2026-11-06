# AI prompt and verification log

Entries are written as the work happens. Each must say what was requested, what the tool returned, what was specifically wrong or risky, what was done to correct/check it, and identify the commit containing that correction. Future entries are intentionally not prefilled.

## 2026-11-06: Day 1 project bootstrap

- **Asked:** Set up LedgerLine for a six-day build in the existing `d:\LedgerLine` workspace with Python 3.13, FastAPI, PostgreSQL, tests, integrity documentation, and a daily Git workflow; scaffold only the first day's work.
- **Produced:** The project setup helper refused with “The user has not opened a valid workspace folder,” despite this VS Code session being rooted at `d:\LedgerLine` and containing the configured `.venv`. The initial manual starter is a health-only FastAPI app plus one HTTP test; it does not implement any money behavior.
- **Wrong or risky:** Treating the visible workspace as unavailable would have blocked the requested setup. Also, a passing health test proves only that the API/test harness starts; it says nothing about ledger integrity.
- **Correction and check:** Created the starter directly in the actual workspace, ignored `.venv`, and ran `python -m pytest -q` (1 passed). Integrity work remains open and is tracked in `THREATS.md`; no money-safety claim is made from this check.
- **Commit containing the correction:** `00af2659fc0f04640b9163fef01df95b045b114f` (local commit; add the GitHub permalink after the remote is configured).

## 2026-11-06: Dashboard and schema foundation

- **Asked:** Build the project to match the supplied LedgerLine dashboard reference and continue implementing the project rather than leaving only instructions.
- **Produced:** A dark responsive dashboard with sample accounts, activity, role preview, navigation, and non-posting account/transfer forms; SQLAlchemy schema foundations for users, accounts, journal transactions, entries, idempotency records, and audit events; and HTTP/schema tests.
- **Wrong or risky:** The first Users & roles view handler rendered role cards and then immediately overwrote them with account cards. The interface could also be mistaken for a live ledger if the sample-only status was not prominent. The schema alone does not provide authorization, transaction-level money movement, append-only enforcement, or concurrency safety.
- **Correction and check:** Fixed view rendering; labeled the figures and forms as preview-only; verified the dashboard at desktop and mobile widths; ran `pytest -q` (4 passed), Ruff, and `node --check`. Docker Compose is installed but Docker Desktop's engine is unavailable, so no PostgreSQL migration or race behavior has been validated. Those integrity controls remain open in `THREATS.md`.
- **Commit containing the correction:** `5a0d2e3e6ca6ab596f6589360ebc8641683753e7` (implementation commit; repository permalink will be recorded after push).

## Entry template for future work

Add a dated section after the relevant work is completed. Do not copy a planned prompt and describe it as completed.

- **Asked:**
- **Produced:**
- **Wrong or risky:**
- **Correction and check:**
- **Commit containing the correction:**