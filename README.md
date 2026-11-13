# BalanceVault

A secure financial transaction platform with an immutable, cryptographically hash-chained double-entry ledger, account management, idempotent money movement, Redis-based rate limiting, and role-based access control.

BalanceVault is built with an integrity-first architecture in Python 3.13, FastAPI, SQLAlchemy 2.0, PostgreSQL, and Redis.

---

## 1. System Architecture

```
                      +---------------------------------------+
                      |       Web Dashboard / REST Client      |
                      +---------------------------------------+
                                          |  HTTPS / JWT Bearer
                                          v
                      +---------------------------------------+
                      |         FastAPI Application           |
                      |  - JWT Authentication & RBAC Guards   |
                      |  - Pydantic Input Validation          |
                      |  - Redis Sliding-Window Rate Limiter  |
                      |  - Idempotency Middleware             |
                      +---------------------------------------+
                                          |
                +-------------------------+-------------------------+
                |                                                   |
                v                                                   v
  +---------------------------+                       +---------------------------+
  |    Financial Ledger Engine|                       |       Redis Service       |
  |  - Double-Entry Postings  |                       |  - Rate Limit Counters    |
  |  - Deterministic Ordering |                       |  - Distributed Sliding    |
  |  - Conditional Updates    |                       |    Window Keys            |
  |  - SHA-256 Hash Chaining  |                       +---------------------------+
  |  - Rollback / Refusal Log |
  +---------------------------+
                |
                v
  +---------------------------------------------------------------+
  |                      PostgreSQL Database                      |
  |  - Check Constraints (nonnegative balances)                   |
  |  - Unique Constraints (actor + idempotency key)               |
  |  - Foreign Key Constraints (ON DELETE RESTRICT)               |
  |  - Append-Only Hardened Rules (No UPDATE/DELETE on entries)   |
  +---------------------------------------------------------------+
```

---

## 2. BalanceVault Challenge Compliance

### A. Financial Integrity
1. **Double-Entry Accounting**: Every financial operation creates a `JournalTransaction` and at least two balanced `LedgerEntry` postings.
2. **Balanced Postings**: For every journal transaction, the sum of all entry amounts is strictly zero (`sum(entry.amount_minor) == 0`). External deposits and withdrawals post against a system clearing account (`SYSTEM_CLEARING`).
3. **Atomic Processing**: All ledger mutations, balance updates, idempotency records, and audit events execute within a single database transaction. Failure at any point triggers an immediate rollback.
4. **Idempotency Protection**: Scoped to `(actor_user_id, key)`. Computes a SHA-256 canonical payload fingerprint. Identical replays return the cached response; key re-use with a modified payload returns `409 Conflict`.
5. **Concurrency & Deadlock Safety**: Involved accounts are locked in deterministic order (sorted by UUID). Balances are updated via atomic conditional SQL statements:
   ```sql
   UPDATE accounts SET balance_minor = balance_minor + :amount
   WHERE id = :id AND (balance_minor + :amount >= 0 OR is_system_account = true);
   ```
6. **Overdraft Prevention**: Strict non-negative balance checks are enforced at both application and database constraint levels.
7. **Append-Only Audit Ledger**: Completed and refused attempts are logged in `audit_events`. Refused operations are recorded in an independent transaction so declines cannot disappear if the financial transaction rolls back.
8. **Hash-Chained Ledger Verification**: Every `LedgerEntry` contains `prev_hash`, `entry_sequence`, and `entry_hash` (`SHA-256(prev_hash:seq:journal:account:amount:balance_after)`). The `/ledger/verify` endpoint walks the entire chain from genesis to detect tampering.
9. **Proper Rollback**: Injected failures leave zero partial state.

### B. Account Management & Authentication
1. **User Registration & Onboarding**: `POST /auth/register` creates an account. Public registration is restricted strictly to `UserRole.ACCOUNT_HOLDER`.
2. **Account Management**: `POST /accounts` allows creating customer accounts; `GET /accounts` and `GET /accounts/{id}` enforce ownership isolation.
3. **Authentication**: `POST /auth/login` validates credentials and returns a signed JWT access token.
4. **Password Hashing**: Passwords hashed with **Argon2** (`pwdlib[argon2]`).
5. **Session/Token Handling**: JWT Bearer tokens with configurable expiration and claims (`sub`, `email`, `role`).
6. **Input Validation**: Strict Pydantic models validate integer minor units (paise), RFC-compliant emails, and UUIDs.

### C. Role-Based Access Control (RBAC)
1. **Roles**: `admin`, `account_holder`, `auditor`.
2. **Backend Enforcement**: FastAPI dependencies (`require_roles(...)`) protect every route.
3. **User Isolation**: Account holders can only view and transfer from accounts they own (`owner_user_id == current_user.id`).
4. **Privilege Escalation Prevention**: Role parameters in public registration are rejected; first admin is created via an explicit CLI bootstrap script.
5. **Auditor & Admin Separation**: Auditors have read-only access to statements, audit logs, and reconciliation; only administrators and account holders can initiate transfers.

### D. Database & Infrastructure
1. **PostgreSQL**: Primary production database utilizing psycopg3 binary driver.
2. **Alembic Migrations**: Full declarative migration suite (`alembic.ini`, `alembic/versions/001_initial_schema.py`).
3. **Redis Rate Limiting**: Distributed sliding-window rate limiting with in-memory fallback.
4. **Bootstrap Script**: `src/balancevault/bootstrap.py` initializes the first admin from environment variables safely.
5. **Database Roles**: `scripts/init_db_roles.sql` provides separated `balancevault_migrator` (DDL owner) and `balancevault_app` (runtime user with NO UPDATE/DELETE on ledger entries).
6. **Environment Configuration**: `pydantic-settings` validates environment variables and requires private production secrets.

### E. Health Checks & Deployment
1. **Application Health**: `GET /health` returns `{"status": "ok"}`.
2. **Database Health**: `GET /health/db` tests database connectivity with `SELECT 1`.
3. **Redis Health**: `GET /health/redis` pings Redis.
4. **Readiness Probe**: `GET /ready` returns readiness status for orchestrators.
5. **Production Docker**: `Dockerfile` (multi-stage non-root container) and `docker-compose.yml`.

---

## 3. API Reference

| Endpoint | Method | Role | Description |
| :--- | :--- | :--- | :--- |
| `/health` | `GET` | Public | Application health check |
| `/health/db` | `GET` | Public | Database connectivity health check |
| `/health/redis` | `GET` | Public | Redis connectivity health check |
| `/ready` | `GET` | Public | Readiness probe |
| `/docs` | `GET` | Public | Swagger Interactive API Documentation |
| `/redoc` | `GET` | Public | ReDoc Technical API Reference |
| `/auth/register` | `POST` | Public | Register new account holder |
| `/auth/login` | `POST` | Public | Authenticate user & retrieve JWT / HttpOnly cookie |
| `/auth/logout` | `POST` | Public | Log out user & clear session cookies |
| `/auth/me` | `GET` | Authenticated | Get current authenticated user profile & role |
| `/users` | `GET` | Admin | List all registered workspace users |
| `/users/auditors` | `POST` | Admin | Provision a new auditor or promote account holder |
| `/users/{id}/role` | `PATCH` | Admin | Promote or update a user's assigned role |
| `/accounts` | `POST` | Admin, Holder | Create a new ledger account |
| `/accounts` | `GET` | Authenticated | List accessible accounts |
| `/accounts/{id}`| `GET` | Authenticated | Get account details (enforces ownership) |
| `/deposits` | `POST` | Admin, Holder | Execute deposit against clearing account |
| `/withdrawals` | `POST` | Admin, Holder | Execute withdrawal against clearing account |
| `/transfers` | `POST` | Admin, Holder | Execute atomic double-entry transfer |
| `/statements/{id}` | `GET` | Authenticated | View account statements and entry history |
| `/ledger/verify` | `GET` | Admin, Auditor | Verify SHA-256 cryptographic hash-chain |
| `/ledger/reconciliation` | `GET` | Admin, Auditor | Verify system-wide balance conservation (sum=0) |
| `/audit/events` | `GET` | Admin, Auditor | View append-only audit trail |

---

## 4. Quick Start (Local Development)

### Prerequisites
- Python 3.13
- PostgreSQL (or SQLite for automated unit tests)
- Redis (optional for local dev; built-in in-memory fallback enabled)

### Setup & Run
```powershell
# 1. Clone repository
git clone https://github.com/neelavenimodugula-debu/Balancevault-project.git
cd Balancevault-project

# 2. Install dependencies
python -m pip install -e ".[dev]"

# 3. Copy environment configuration
cp .env.example .env

# 4. Bootstrap initial administrator
python -m balancevault.bootstrap

# 5. Run tests
python -m pytest -v

# 6. Start the API & Dashboard
python -m uvicorn balancevault.main:app --reload --port 8000
```

Open:
- Dashboard: [http://localhost:8000/](http://localhost:8000/)
- API Docs: [http://localhost:8000/docs](http://localhost:8000/docs)
- Health check: [http://localhost:8000/health](http://localhost:8000/health)

---

## 5. Production Deployment (Docker Compose)

The complete stack includes PostgreSQL 16, Redis 7, and BalanceVault API with volume persistence and health checks.

```bash
# 1. Configure production environment
cp .env.example .env
# Edit .env with strong production passwords and a private JWT secret

# 2. Build and start services
docker-compose up -d --build

# 3. Apply database migrations
docker-compose exec web alembic upgrade head

# 4. Apply database roles and append-only hardening rules
docker-compose exec -T postgres psql -U balancevault -d balancevault < scripts/init_db_roles.sql

# 5. Check service health
curl -f http://localhost:8000/health
curl -f http://localhost:8000/health/db
curl -f http://localhost:8000/health/redis
curl -f http://localhost:8000/ready
```

---

## 6. Automated Testing Suite

The automated test suite in `tests/` covers all 13 challenge categories:

```powershell
# Run the complete test suite
python -m pytest -v

# Run concurrency and race condition tests
python -m pytest tests/test_concurrency.py -v

# Run code style and lint verification
python -m ruff check src tests
```

### Verified Test Suites (30 automated tests passed):
- **Core Financial & Engine** (`tests/test_balancevault_requirements.py`): 13 passed
- **Auditor Provisioning & RBAC** (`tests/test_auditor_provisioning.py`): 5 passed
- **Frontend Auth & RBAC Workflow** (`tests/test_frontend_auth_and_rbac_workflow.py`): Comprehensive 10-step workflow passed
- **Production Redis & Rate Limiting** (`tests/test_production_rate_limiting.py`): 4 passed
- **Concurrency & Deadlock Prevention** (`tests/test_concurrency.py`): 2 passed
- **Health & OpenAPI Documentation** (`tests/test_health.py`): 3 passed
- **Database Immutability Triggers** (`tests/test_immutability.py`): 1 passed
- **Schema & Minor Unit Compliance** (`tests/test_schema.py`): 2 passed

For detailed launch and environment instructions, see [STARTUP.md](file:///c:/Users/ADMIN/OneDrive/Desktop/sri/Balancevault-project/STARTUP.md).

---

## 7. Demo Video Checklist

When recording the challenge demonstration video (5 minutes):

1. **Dashboard & Overview** (0:00 - 0:45):
   - Open [http://localhost:8000/](http://localhost:8000/).
   - Show dashboard with accounts, balances, and real-time cryptographic verification pill.
2. **Registration & RBAC** (0:45 - 1:30):
   - Register a new account holder. Show role is restricted to `account_holder`.
   - Log in as admin via bootstrap credentials. Show admin privileges.
3. **Atomic Double-Entry Transfer** (1:30 - 2:30):
   - Submit a transfer between accounts.
   - Show both sides of the ledger entry and check `/ledger/reconciliation` (sum equals 0).
4. **Idempotency Protection** (2:30 - 3:15):
   - Re-send request with identical idempotency key. Show identical cached response returned.
   - Modify payload with same key. Show `409 Conflict` rejection.
5. **Overdraft & Rollback Prevention** (3:15 - 3:45):
   - Attempt to withdraw more than available balance. Show `400 Insufficient Funds` rejection.
   - Show audit event logged for refused attempt.
6. **Cryptographic Hash Chain & Tamper Detection** (3:45 - 4:30):
   - Query `/ledger/verify` showing chain valid.
   - Explain cryptographic SHA-256 link from genesis.
7. **Automated Test Run & Health Checks** (4:30 - 5:00):
   - Run `python -m pytest -v` in terminal showing all 30 tests passing.
   - Check `/health/db` and `/health/redis`.
