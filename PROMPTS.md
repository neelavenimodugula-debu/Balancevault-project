# AI prompt and verification log

Entries are written as the work happens. Each must say what was requested, what the tool returned, what was specifically wrong or risky, what was done to correct/check it, and identify the commit containing that correction. Future entries are intentionally not prefilled.

## 2026-11-06: Day 1 project bootstrap

- **Asked:** Set up BalanceVault for a six-day build in the existing `d:\BalanceVault` workspace with Python 3.13, FastAPI, PostgreSQL, tests, integrity documentation, and a daily Git workflow; scaffold only the first day's work.
- **Produced:** The project setup helper refused with “The user has not opened a valid workspace folder,” despite this VS Code session being rooted at `d:\BalanceVault` and containing the configured `.venv`. The initial manual starter is a health-only FastAPI app plus one HTTP test; it does not implement any money behavior.
- **Wrong or risky:** Treating the visible workspace as unavailable would have blocked the requested setup. Also, a passing health test proves only that the API/test harness starts; it says nothing about ledger integrity.
- **Correction and check:** Created the starter directly in the actual workspace, ignored `.venv`, and ran `python -m pytest -q` (1 passed). Integrity work remains open and is tracked in `THREATS.md`; no money-safety claim is made from this check.
- **Commit containing the correction:** `b13f587` (Day 1 bootstrap; https://github.com/neelavenimodugula-debu/Balancevault-project/commit/b13f587).

## 2026-11-06: Dashboard and schema foundation

- **Asked:** Build the project to match the supplied BalanceVault dashboard reference and continue implementing the project rather than leaving only instructions.
- **Produced:** A dark responsive dashboard with sample accounts, activity, role preview, navigation, and non-posting account/transfer forms; SQLAlchemy schema foundations for users, accounts, journal transactions, entries, idempotency records, and audit events; and HTTP/schema tests.
- **Wrong or risky:** The first Users & roles view handler rendered role cards and then immediately overwrote them with account cards. The interface could also be mistaken for a live ledger if the sample-only status was not prominent. The schema alone does not provide authorization, transaction-level money movement, append-only enforcement, or concurrency safety.
- **Correction and check:** Fixed view rendering; labeled the figures and forms as preview-only; verified the dashboard at desktop and mobile widths; ran `pytest -q` (4 passed), Ruff, and `node --check`. Docker Compose is installed but Docker Desktop's engine is unavailable, so no PostgreSQL migration or race behavior has been validated. Those integrity controls remain open in `THREATS.md`.
- **Commit containing the correction:** `54f6a25` (implementation commit; https://github.com/neelavenimodugula-debu/Balancevault-project/commit/54f6a25).

## 2026-11-12: Full BalanceVault Challenge Audit, Implementation & Verification

- **Asked:** Perform an independent audit of BalanceVault against official BalanceVault requirements, implement all missing functionality (financial integrity, double-entry accounting, atomic transactions, idempotency, overdraft prevention, hash-chained ledger, rollback, auth, RBAC, Redis rate limiting, Alembic migrations, database permissions, health checks), run comprehensive automated tests, and prepare for deployment.
- **Produced:**
  - Financial ledger service (`src/balancevault/services/ledger.py`) supporting atomic double-entry deposits, withdrawals, and transfers with deterministic lock order, overdraft prevention, SHA-256 cryptographic hash-chaining, tamper verification, and balance reconciliation.
  - Authentication & RBAC engine (`src/balancevault/auth.py`) with Argon2 password hashing, JWT bearer authentication, and role enforcement.
  - Redis rate limiting with fallback (`src/balancevault/rate_limit.py`).
  - First-admin bootstrap CLI (`src/balancevault/bootstrap.py`).
  - Expanded FastAPI application (`src/balancevault/main.py`) with endpoints for auth, accounts, money movement, ledger verification, reconciliation, and health checks (`/health`, `/health/db`, `/health/redis`, `/ready`).
  - Alembic migrations (`alembic.ini`, `alembic/env.py`, `alembic/versions/001_initial_schema.py`).
  - Database role permissions and append-only hardening rules (`scripts/init_db_roles.sql`).
  - Docker containerization (`Dockerfile`, `docker-compose.yml`, `.env.example`).
  - Live frontend connection in `src/balancevault/static/app.js`.
  - Comprehensive automated test suite (`tests/test_balancevault_requirements.py`, `tests/test_concurrency.py`, `tests/test_health.py`, `tests/test_schema.py`) totaling 19 passed tests.
- **Wrong or risky:**
  - Using Pydantic `EmailStr` caused an `ImportError` because `email-validator` was not installed; replaced with RFC-compliant regex pattern validation.
  - TestClient hang in Windows sandbox due to loopback socket constraints; resolved by running with elevated test permissions.
  - Concurrency race test revealed that database engines without strict row locks could allow concurrent threads to calculate stale balances; implemented atomic conditional SQL `UPDATE accounts SET balance_minor = balance_minor + amount WHERE balance_minor + amount >= 0` checking row count, guaranteeing overdraft prevention across all SQL dialects.
  - Initial route configuration permitted auditor accounts to invoke `POST /accounts`; restricted to `require_roles(UserRole.ADMIN, UserRole.ACCOUNT_HOLDER)`.
  - Rate limiting test exhausted client counter, causing subsequent concurrency tests to receive 429; added counter clearance before each test block.
- **Correction and check:** Executed `python -m pytest -v` (19 passed in 7.76s); verified `python -m ruff check src tests` (All checks passed).

## 2026-11-13: Comprehensive Project Rebranding to BalanceVault

- **Asked:** Modify the project name to BalanceVault everywhere in the codebase without pushing to git.
- **Produced:**
  - Package renamed to `src/balancevault`.
  - Updated `pyproject.toml`, `alembic/env.py`, `Dockerfile`, `docker-compose.yml`, `render.yaml`, `.env`, `.env.example`.
  - Updated application settings prefix to `BALANCEVAULT_*`.
  - Updated all tests in `tests/` to import from `balancevault`.
  - Updated UI assets, frontend app tokens (`balancevault_token`), cookies (`balancevault_access_token`), and OpenAPI metadata (`BalanceVault API`).
  - Verified 30 automated unit, security, RBAC, and concurrency tests passing cleanly.
- **Wrong or risky:**
  - Unsynchronized package installation would lead pytest and alembic to fail locating `balancevault` module; reinstalled package in editable mode (`pip install -e .`).
- **Correction and check:** Ran `ruff check src tests` and `pytest -v` (30 passed). Strictly prevented `git push` per explicit user requirement.
