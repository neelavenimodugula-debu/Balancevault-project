# LedgerLine – Complete Startup & Deployment Guide

This guide provides end-to-end instructions for launching, configuring, testing, and deploying **LedgerLine** across local environments, Docker, and Render cloud hosting.

---

## 1. System Requirements

- **Python**: 3.13+ (or 3.11+ / 3.12+)
- **PostgreSQL**: 15+ (Local or Cloud-hosted like Neon / Supabase / AWS RDS)
- **Redis**: 7+ (Optional for local development; required for strict distributed multi-instance production rate limiting)
- **Git**: For version control

---

## 2. Local Development Quickstart (Under 2 Minutes)

### Windows (PowerShell)

```powershell
# 1. Clone the repository
git clone https://github.com/neelavenimodugula-debu/Balancevault-project.git
cd Balancevault-project

# 2. Create and activate a Python virtual environment
python -m venv .venv
.\.venv\Scripts\Activate.ps1

# 3. Upgrade pip and install package with development dependencies
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"

# 4. Create your local environment file
Copy-Item .env.example .env

# 5. Apply database migrations to create schema
python -m alembic upgrade head

# 6. Bootstrap the initial Administrator and system accounts
python -m ledgerline.bootstrap

# 7. Start the FastAPI application server
python -m uvicorn ledgerline.main:app --reload --host 127.0.0.1 --port 8000
```

### Linux / macOS (Bash)

```bash
# 1. Clone repository
git clone https://github.com/neelavenimodugula-debu/Balancevault-project.git
cd Balancevault-project

# 2. Create and activate virtual environment
python3 -m venv .venv
source .venv/bin/activate

# 3. Install package
pip install --upgrade pip
pip install -e ".[dev]"

# 4. Copy environment configuration
cp .env.example .env

# 5. Apply migrations
alembic upgrade head

# 6. Bootstrap initial administrator
python -m ledgerline.bootstrap

# 7. Start server
uvicorn ledgerline.main:app --reload --host 127.0.0.1 --port 8000
```

Once started, access:
- **Interactive Web Dashboard**: [http://127.0.0.1:8000/](http://127.0.0.1:8000/)
- **Swagger Interactive API Testing**: [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)
- **ReDoc Technical Reference**: [http://127.0.0.1:8000/redoc](http://127.0.0.1:8000/redoc)
- **Health Check**: [http://127.0.0.1:8000/health](http://127.0.0.1:8000/health)

---

## 3. Cloud Deployment on Render

LedgerLine includes a pre-configured `render.yaml` blueprint and a multi-stage production `Dockerfile`.

### Method 1: Deploying via Render Blueprint (`render.yaml`)
1. In your [Render Dashboard](https://dashboard.render.com/), click **New +** &rarr; **Blueprint**.
2. Connect your GitHub repository: `https://github.com/neelavenimodugula-debu/Balancevault-project.git`.
3. Render reads `render.yaml` and provisions:
   - **`ledgerline-api`** (Python Web Service).
   - **`ledgerline-redis`** (Managed Redis instance).
4. Supply your Neon PostgreSQL connection string in the `LEDGERLINE_DATABASE_URL` prompt.
5. Click **Apply**.

### Method 2: Manual Web Service Deployment
If deploying as a standalone Web Service on Render:
1. Click **New +** &rarr; **Web Service**.
2. Connect your repository.
3. Set the following settings:
   - **Runtime**: `Python`
   - **Build Command**:
     ```bash
     pip install --upgrade pip && pip install . && alembic upgrade head && python -m ledgerline.bootstrap
     ```
   - **Start Command**:
     ```bash
     uvicorn ledgerline.main:app --host 0.0.0.0 --port $PORT
     ```
   - **Health Check Path**: `/health`
4. Add Environment Variables under the **Environment** tab:
   | Key | Value |
   | :--- | :--- |
   | `LEDGERLINE_ENVIRONMENT` | `production` |
   | `LEDGERLINE_DATABASE_URL` | `postgresql://neondb_owner:...@ep-ancient-...aws.neon.tech/neondb?sslmode=require` |
   | `LEDGERLINE_JWT_SECRET` | *(Random 32+ character secret string)* |
   | `LEDGERLINE_ADMIN_EMAIL` | `admin@gmail.com` |
   | `LEDGERLINE_ADMIN_PASSWORD` | `Admin@2026` |
   | `LEDGERLINE_STRICT_REDIS` | `false` *(allows fallback if Redis is unlinked)* |
   | `LEDGERLINE_REDIS_URL` | `redis://localhost:6379/0` *(or your Render/Upstash Redis URL)* |
   | `LEDGERLINE_RATE_LIMIT_PER_MINUTE` | `60` |

---

## 4. Production Docker Deployment

LedgerLine provides a hardened `docker-compose.yml` that boots PostgreSQL 16, Redis 7, and the LedgerLine API container with non-root privileges:

```bash
# 1. Prepare environment configuration
cp .env.example .env

# 2. Build and run all services in background
docker compose up -d --build

# 3. Apply database migrations inside container
docker compose exec web alembic upgrade head

# 4. Verify running containers and health
docker compose ps
curl http://localhost:8000/health
curl http://localhost:8000/health/db
curl http://localhost:8000/ready
```

---

## 5. Initial Accounts & User Roles

LedgerLine operates with three segregated roles:

### 1. Administrator (`admin`)
- **Credentials**: Configured via `LEDGERLINE_ADMIN_EMAIL` and `LEDGERLINE_ADMIN_PASSWORD` during bootstrap (default: `admin@gmail.com` / `Admin@2026`).
- **Capabilities**:
  - Full institutional dashboard.
  - Access to all accounts (system clearing and customer accounts).
  - User management (`GET /users`).
  - Auditor account provisioning (`POST /users/auditors` and `PATCH /users/{id}/role`).
  - Full system audit trail (`GET /audit/events`).
  - Cryptographic ledger integrity verification (`GET /ledger/verify`).
  - Balance reconciliation (`GET /ledger/reconciliation`).

### 2. Auditor (`auditor`)
- **Provisioning**:
  - **Via UI**: Admin signs in &rarr; visits **User Management** &rarr; clicks **＋ Provision Auditor**.
  - **Via API**: Admin calls `POST /users/auditors` or promotes an existing user via `PATCH /users/{id}/role`.
  - **Via Bootstrap**: Optional `LEDGERLINE_AUDITOR_EMAIL` and `LEDGERLINE_AUDITOR_PASSWORD`.
- **Capabilities (Strictly Read-Only)**:
  - Allowed: Inspect all accounts (`/accounts`), view any statement (`/statements/{id}`), audit trail (`/audit/events`), ledger integrity (`/ledger/verify`), reconciliation (`/ledger/reconciliation`).
  - Forbidden: Transfers, deposits, withdrawals, creating accounts, user management (returns `HTTP 403 Forbidden`).

### 3. Account Holder (`account_holder`)
- **Registration**: Any public user can register at `POST /auth/register` (or via the **Create account** tab in the dashboard). Public registration *always* assigns `account_holder`.
- **Capabilities**:
  - Personal dashboard displaying own accounts and balances.
  - Account creation for permitted currencies.
  - Fund transfers from own accounts with atomic double-entry balance updates.
  - Deposits and withdrawals against the clearing account.
  - Personal cryptographic statements (`/statements/{id}`).
  - Cross-account access or viewing other users' accounts is strictly rejected with `HTTP 403 Forbidden`.

---

## 6. Interactive Swagger API Testing (`/docs`)

LedgerLine features an enhanced Swagger UI for testing every endpoint:

1. Open `/docs` in your browser.
2. **Authenticate**:
   - Scroll to `POST /auth/login`.
   - Click **Try it out** and enter your credentials (e.g. `admin@gmail.com` / `Admin@2026`).
   - Click **Execute** and copy the returned `access_token` string.
3. **Authorize**:
   - Scroll to the top right and click the green **Authorize 🔓** button.
   - Paste the token into the **Value** field and click **Authorize**.
4. **Execute Protected Endpoints**:
   - All subsequent calls in Swagger UI will automatically include your Bearer token!
   - Response latency (in milliseconds) and response headers are displayed in real-time.

---

## 7. Environment Variables Reference

| Variable | Type | Default | Description |
| :--- | :--- | :--- | :--- |
| `LEDGERLINE_ENVIRONMENT` | `string` | `development` | Environment mode (`development`, `staging`, `production`) |
| `LEDGERLINE_DATABASE_URL` | `string` | `postgresql+psycopg://...` | PostgreSQL connection URL with psycopg3 driver |
| `LEDGERLINE_REDIS_URL` | `string` | `redis://localhost:6379/0` | Redis connection URL (`redis://` or `rediss://` for TLS) |
| `LEDGERLINE_STRICT_REDIS` | `bool` | `false` | When `true`, rejects with 503 if Redis is unreachable in production. When `false`, falls back to in-memory sliding window with a warning. |
| `LEDGERLINE_JWT_SECRET` | `secret` | *(dev secret)* | Cryptographic HMAC-SHA256 secret key (minimum 32 characters in production) |
| `LEDGERLINE_TOKEN_EXPIRY_MINUTES` | `int` | `30` | JWT expiration duration in minutes |
| `LEDGERLINE_RATE_LIMIT_PER_MINUTE` | `int` | `60` | Maximum requests per minute per IP / authenticated user |
| `LEDGERLINE_ADMIN_EMAIL` | `string` | `admin@ledgerline.local` | Email address for initial bootstrapped administrator |
| `LEDGERLINE_ADMIN_PASSWORD` | `secret` | `AdminInitialPass2026!` | Password for initial bootstrapped administrator |
| `LEDGERLINE_AUDITOR_EMAIL` | `string` | `None` | (Optional) Email address for bootstrapped auditor |
| `LEDGERLINE_AUDITOR_PASSWORD` | `secret` | `None` | (Optional) Password for bootstrapped auditor |
| `LEDGERLINE_CLEARING_ACCOUNT_NAME` | `string` | `SYSTEM_CLEARING` | Name of the system clearing account for deposits/withdrawals |

---

## 8. Health, Monitoring & Operational Endpoints

| Endpoint | Method | Expected Output | Purpose |
| :--- | :---: | :--- | :--- |
| `/health` | `GET` | `{"status": "ok"}` | Basic uptime check for load balancers |
| `/health/db` | `GET` | `{"status": "ok", "database": "connected"}` | Live database connectivity probe |
| `/health/redis` | `GET` | `{"status": "ok", "redis": "connected"}` | Live Redis connectivity probe |
| `/ready` | `GET` | `{"status": "ready", ...}` | Full container readiness check |
| `/ledger/verify` | `GET` | `{"verified": true, "total_entries": N, ...}` | Cryptographic SHA-256 hash-chain verification |
| `/ledger/reconciliation` | `GET` | `{"is_reconciled": true, "total_balance_minor": 0}` | Zero-sum balance invariant check (`Debits = Credits`) |

---

## 9. Automated Testing & Verification

Run all test suites locally:

```powershell
# Run the complete test suite (30 automated tests)
python -m pytest -v

# Run specific functional test suites
python -m pytest tests/test_auditor_provisioning.py -v
python -m pytest tests/test_frontend_auth_and_rbac_workflow.py -v
python -m pytest tests/test_production_rate_limiting.py -v
python -m pytest tests/test_concurrency.py -v
python -m pytest tests/test_health.py -v

# Run code formatting and linter check
python -m ruff check src tests
```
