# LedgerLine Security Threat Model & Verification

This document tracks security threats, attack vectors, architectural mitigations, and automated test verifications for the LedgerLine financial integrity platform.

## Assets & Trust Boundaries

- **Account Balances & Ledger**: All financial balances are strictly integer minor units (paise). Source of truth is the immutable, double-entry ledger.
- **Identity & Roles**: `admin`, `account_holder`, `auditor`.
- **API Boundary**: Public requests are untrusted; all requests are authenticated, validated against Pydantic schemas, rate-limited, and checked for role authorization.
- **Database Boundary**: PostgreSQL is trusted for transactional atomicity and row-level locking. Defense-in-depth is enforced via database check constraints, unique constraints, and SQL append-only rules.

---

## Threat Matrix and Verification Status

| Threat | Attack Scenario | Implemented Mitigation | Verification & Automated Test | Status |
| :--- | :--- | :--- | :--- | :--- |
| **Race Condition Overdraft** | Multiple simultaneous withdrawals attempt to drain the same account | Account rows locked in deterministic order with `SELECT ... FOR UPDATE`, atomic conditional SQL `UPDATE accounts SET balance_minor = balance_minor + amount WHERE balance_minor + amount >= 0`, and database `CheckConstraint("balance_minor >= 0")`. | `tests/test_concurrency.py::test_concurrent_withdrawal_race_condition` (5 concurrent threads attempt to withdraw ₹80 with only ₹100 available; exactly 1 succeeds, 4 fail with 400). | **CLOSED / VERIFIED** |
| **Deadlock on Opposing Transfers** | Thread 1 transfers A &rarr; B while Thread 2 transfers B &rarr; A | Account IDs are sorted deterministically before acquiring locks (`sorted([source_id, dest_id])`). | `tests/test_concurrency.py::test_opposing_transfers_no_deadlock` (6 concurrent bidirectional transfers complete without deadlock). | **CLOSED / VERIFIED** |
| **Partial Transaction Failure** | Transfer debits source but fails before crediting destination | Both debits and credits, along with journal record and idempotency update, run in a single atomic database transaction. Any failure triggers immediate `session.rollback()`. | `tests/test_balancevault_requirements.py::test_transaction_rollback_on_failure` (Simulated failure verifies zero partial entries created). | **CLOSED / VERIFIED** |
| **Duplicate / Replay Requests** | Network retry causes multiple transfers for one intended operation | Mandatory/optional `Idempotency-Key` header with database unique constraint `(actor_user_id, key)`. Canonical request fingerprint comparison returns identical original response without re-executing. | `tests/test_balancevault_requirements.py::test_duplicate_idempotency_requests` (Exact replay returns same transaction ID and prevents duplicate debit). | **CLOSED / VERIFIED** |
| **Idempotency Key Reuse** | Attacker uses previously valid idempotency key with different payload | Server computes SHA-256 canonical payload fingerprint (`path + sorted json`). If fingerprint differs, request is rejected with `409 Conflict`. | `tests/test_balancevault_requirements.py::test_duplicate_idempotency_requests` (Tampered payload rejected with 409). | **CLOSED / VERIFIED** |
| **Cross-User Account Access** | User B attempts to view or debit User A's account | Backend authorization checks `account.owner_user_id == current_user.id`. Access is strictly forbidden for non-admin/auditor users. | `tests/test_balancevault_requirements.py::test_unauthorized_cross_account_transfer` & `test_account_creation_and_isolation` (Returns 403 Forbidden). | **CLOSED / VERIFIED** |
| **Privilege Escalation** | Attacker registers as `admin` or assigns privileged role | Public registration endpoint `/auth/register` hardcodes `role = UserRole.ACCOUNT_HOLDER` and ignores client-supplied role parameters. First admin is initialized via secure bootstrap. | `tests/test_balancevault_requirements.py::test_prevent_privilege_escalation` (Forced role assignment fails; account holder role assigned). | **CLOSED / VERIFIED** |
| **Unauthorized Action by Auditor** | Auditor user attempts to move money or create accounts | Backend RBAC dependency `require_roles(UserRole.ADMIN, UserRole.ACCOUNT_HOLDER)` forbids auditor from mutation endpoints. | `tests/test_balancevault_requirements.py::test_rbac_auditor_restrictions` (Transfers and account creation return 403; read-only operations succeed). | **CLOSED / VERIFIED** |
| **Ledger Tampering / Row Deletion** | Malicious DB operator or SQL injection modifies entry amount | Cryptographic SHA-256 hash chaining (`entry_hash = H(prev_hash : seq : journal : account : amount : balance_after)`). Tampering or sequence gaps are immediately flagged by `/ledger/verify`. | `tests/test_balancevault_requirements.py::test_ledger_hash_chain_verification_and_tamper_detection` (Direct DB update caught; returns verified: False). | **CLOSED / VERIFIED** |
| **Lost Audit on Failure** | Failed transaction rollback wipes evidence of attack attempt | Audit logging for refused operations is written in a dedicated audit session after the financial transaction rolls back. | `tests/test_balancevault_requirements.py::test_transaction_rollback_on_failure` & `test_overdraft_prevention` (Audit event preserved). | **CLOSED / VERIFIED** |
| **Float Rounding Creation/Loss** | Decimal rounding errors create or lose fractional currency | All monetary values represented exclusively as integer minor units (paise, BigInteger). No floating-point arithmetic permitted in ledger engine. | `tests/test_schema.py::test_ledger_schema_uses_integer_minor_units` (Enforced in database schema). | **CLOSED / VERIFIED** |
| **Conservation Violation** | External deposits/withdrawals create unbalanced entries | Deposits and withdrawals post balanced entries against a system clearing account (`SYSTEM_CLEARING`). Overall ledger sum is zero. | `tests/test_balancevault_requirements.py::test_successful_deposit_and_withdrawal` & `/ledger/reconciliation` (Verified balanced). | **CLOSED / VERIFIED** |
| **Denial of Service / Brute Force** | High-frequency automated attacks overwhelm authentication | Redis sliding-window rate limiting with in-memory fallback. Limits requests per minute per IP/user. Returns 429 Too Many Requests. | `tests/test_balancevault_requirements.py::test_rate_limiting` (Returns 429 after threshold). | **CLOSED / VERIFIED** |
| **Secret Leakage in Version Control** | Production JWT secret or DB passwords committed to Git | `.env` ignored in `.gitignore`. Production validator in `Settings` prevents starting in `production` environment with default development secrets. | `src/ledgerline/config.py::require_production_secret` & `.env.example`. | **CLOSED / VERIFIED** |

---

## Defense in Depth

1. **Application Layer**: Pydantic schema validation, Argon2 password hashing, JWT authentication, RBAC route guards, Redis rate limiting.
2. **Ledger Engine**: Deterministic ID lock order, double-entry sum-to-zero enforcement, conditional atomic SQL updates, cryptographic hash chain calculation.
3. **Database Layer**: PostgreSQL check constraints (`balance_minor >= 0`), unique constraints (`(actor_user_id, key)`), foreign keys with `ON DELETE RESTRICT`, runtime vs migration role separation (`scripts/init_db_roles.sql`), and PostgreSQL rules preventing UPDATE/DELETE on ledger entries.
