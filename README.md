# LedgerLine

A secure financial transaction platform with an immutable ledger, account management, idempotent transfers and AI-assisted anomaly detection.

LedgerLine is an integrity-first money movement service. The current implementation is still in progress; the dashboard is a sample-only preview and no real money movement is enabled.

## Six-day build sequence

Keep each day's work small enough to test and commit. Add a dated entry to `PROMPTS.md` as work happens, including an actual mistake or a specific verification that caught a risky assumption. Do not write future entries in advance.

### Day 1: Foundation and threat model

- Establish the Python package, test runner, Git ignore rules, and `/health` endpoint.
- Record the planned integrity model and known threats before implementing money movement.
- Check: `python -m pytest -q`.
- Commit: `Day 1: bootstrap FastAPI service` (done locally as `00af265`).

### Day 2: PostgreSQL schema and identity

- Add PostgreSQL Compose configuration, environment-based settings, SQLAlchemy models, and Alembic migrations.
- Model users and roles, accounts and ownership, immutable journal transactions, postings, idempotency records, and audit events.
- Store all amounts as integer minor units (paise); do not use floating-point currency.
- Add an administrator, account-holder, and auditor policy, then implement password hashing and authenticated API requests.
- Check: migration-up/down or migration-forward tests, role tests, and database constraint tests against PostgreSQL.
- Commit: `Day 2: add database schema and authentication`.

### Day 3: Money movement

- Implement deposits, withdrawals, and transfers through one service layer; do not let routes update balances directly.
- Use double-entry postings. Each journal transaction must sum to zero; external deposits and withdrawals post against a clearing account.
- Within one PostgreSQL transaction, lock affected accounts in stable ID order, verify authorization and funds, write postings, and update any cached balances.
- Check: unit/integration tests for balance changes, conservation, insufficient funds, and a forced failure proving a transfer cannot partially commit.
- Commit: `Day 3: implement atomic money movements`.

### Day 4: Idempotency and adversarial concurrency

- Require an idempotency key for every money-moving request. Enforce uniqueness in PostgreSQL, bind the key to the actor and request payload, return the original result for an identical retry, and reject key reuse with a different payload.
- Exercise simultaneous withdrawals and duplicate transfers using multiple database connections against PostgreSQL, not SQLite or mocked locks.
- Deploy a staging version early and run the same adversarial checks against it.
- Check: race tests assert exactly one winner when funds only cover one withdrawal, and exactly one posting set after concurrent duplicate requests.
- Commit: `Day 4: enforce idempotency and race safety`.

### Day 5: Authorization, statements, and audit integrity

- Enforce account ownership and role checks in the service layer on every request.
- Add account balances and statements with running balances, actor, timestamps, successful postings, and refused attempts.
- Separate refused-attempt auditing from a rolled-back money transaction so a decline remains recorded.
- Protect posted ledger rows with database permissions and append-only database rules; application checks alone are not sufficient.
- Check: cross-account access tests, auditor read-only tests, denied-attempt tests, and tests that update/delete attempts against posted ledger rows are rejected.
- Commit: `Day 5: add statements and audit protections`.

### Day 6: User experience, deployment, and hand-in

- Add a small usable interface for login, account overview, transfer submission, and statements; the API remains the authority for all money decisions.
- Add safe seed data, clean-clone setup instructions, API permission/money-effect documentation, and production configuration without committing secrets.
- Deploy the final service, run the attack checklist against the live URL, record the five-minute demo, and write the final implementation/gaps summary.
- Check: full test suite, clean deployment smoke test, and manual replay/overdraft/ownership/tamper checks.
- Commit: `Day 6: prepare release and demo`.

## Run locally

Python 3.13 is configured for this workspace. From the repository root in PowerShell:

```powershell
python -m pip install -e ".[dev]"
python -m pytest -q
python -m uvicorn ledgerline.main:app --reload
```

Open `http://127.0.0.1:8000/` for the dashboard preview, `http://127.0.0.1:8000/health` for the health check, and `http://127.0.0.1:8000/docs` for the generated API docs. The account and activity figures are sample-only; preview forms do not post money. PostgreSQL-backed routes will require the database setup that is scheduled for Day 2.

## Daily GitHub workflow

The private GitHub repository is [neelavenimodugula-debu/LedgerLine-project](https://github.com/neelavenimodugula-debu/LedgerLine-project). The local `main` branch tracks the `origin` remote. At the end of each day, review, commit, and push the tested changes:

```powershell
git status
git add README.md THREATS.md PROMPTS.md pyproject.toml src tests
git diff --cached
git commit -m "Day N: describe the tested change"
git push
```

Replace `N` and the message with the actual day's work. Never stage `.env`, credentials, deployment secrets, or `.venv`. Keep `PROMPTS.md` entries tied to real prompts, observed output, a specific correction/check, and the commit that contains the correction. Use the full GitHub commit URL in each entry.

## Integrity design (planned, not yet implemented)

- PostgreSQL is the source of truth. SQLite is not a substitute for the row-locking and concurrency tests.
- Transfers will lock both accounts in a deterministic order, check available funds, write balanced postings, and update any cached balances within one database transaction.
- Idempotency will be enforced by a database uniqueness constraint and a request-payload fingerprint, not by an in-memory cache.
- Statements will be derived from append-only postings and audit events. A reconciliation check will compare account balances with ledger totals.
- Any cached balance is a projection updated atomically with the postings; it is not allowed to become a second independent source of truth.
- The administrator may create accounts and perform explicitly attributed external funding/adjustment operations; an account holder may debit only owned accounts; an auditor may read but never move money. Exact endpoint rules will be documented before those routes are exposed.

These are decisions to implement and test, not claims that the current preview moves money. See `THREATS.md` for the open risks.
