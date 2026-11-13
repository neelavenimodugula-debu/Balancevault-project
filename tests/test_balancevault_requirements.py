import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from balancevault.auth import create_access_token, hash_password
from balancevault.models import LedgerEntry, User, UserRole


@pytest.fixture
def admin_user(db_session: Session) -> User:
    user = User(
        id=uuid.uuid4(),
        email=f"admin_{uuid.uuid4().hex[:8]}@balancevault.local",
        password_hash=hash_password("AdminSecurePass2026!"),
        role=UserRole.ADMIN,
        is_active=True,
    )
    db_session.add(user)
    db_session.commit()
    return user


@pytest.fixture
def user_a(db_session: Session) -> User:
    user = User(
        id=uuid.uuid4(),
        email=f"user_a_{uuid.uuid4().hex[:8]}@example.com",
        password_hash=hash_password("PasswordA123!"),
        role=UserRole.ACCOUNT_HOLDER,
        is_active=True,
    )
    db_session.add(user)
    db_session.commit()
    return user


@pytest.fixture
def user_b(db_session: Session) -> User:
    user = User(
        id=uuid.uuid4(),
        email=f"user_b_{uuid.uuid4().hex[:8]}@example.com",
        password_hash=hash_password("PasswordB123!"),
        role=UserRole.ACCOUNT_HOLDER,
        is_active=True,
    )
    db_session.add(user)
    db_session.commit()
    return user


@pytest.fixture
def auditor_user(db_session: Session) -> User:
    user = User(
        id=uuid.uuid4(),
        email=f"auditor_{uuid.uuid4().hex[:8]}@example.com",
        password_hash=hash_password("AuditorPass123!"),
        role=UserRole.AUDITOR,
        is_active=True,
    )
    db_session.add(user)
    db_session.commit()
    return user


def auth_headers(user: User) -> dict[str, str]:
    token = create_access_token(user)
    return {"Authorization": f"Bearer {token}"}


# 1. Health and Readiness Tests
def test_health_and_readiness_endpoints(client: TestClient) -> None:
    res = client.get("/health")
    assert res.status_code == 200
    assert res.json()["status"] == "ok"

    res_db = client.get("/health/db")
    assert res_db.status_code == 200
    assert res_db.json()["database"] == "connected"

    res_ready = client.get("/ready")
    assert res_ready.status_code == 200
    assert res_ready.json()["status"] == "ready"


# 2. User Registration and Login
def test_user_registration_and_login(client: TestClient) -> None:
    unique_email = f"register_{uuid.uuid4().hex[:8]}@example.com"
    reg_res = client.post("/auth/register", json={"email": unique_email, "password": "StrongPassword123!"})
    assert reg_res.status_code == 201
    reg_data = reg_res.json()
    assert reg_data["email"] == unique_email
    assert reg_data["role"] == "account_holder"

    # Re-registering the same email should fail with 409
    dup_res = client.post("/auth/register", json={"email": unique_email, "password": "StrongPassword123!"})
    assert dup_res.status_code == 409

    # Login with valid credentials
    login_res = client.post("/auth/login", json={"email": unique_email, "password": "StrongPassword123!"})
    assert login_res.status_code == 200
    assert "access_token" in login_res.json()

    # Login with invalid password
    bad_login = client.post("/auth/login", json={"email": unique_email, "password": "WrongPassword!"})
    assert bad_login.status_code == 401


# 3. Privilege Escalation Prevention
def test_prevent_privilege_escalation(client: TestClient) -> None:
    # Attempt to supply admin role during registration - role parameter must be ignored
    email = f"attacker_{uuid.uuid4().hex[:8]}@example.com"
    res = client.post("/auth/register", json={"email": email, "password": "AttackerPass123!", "role": "admin"})
    assert res.status_code == 201
    assert res.json()["role"] == "account_holder"


# 4. Account Creation and Isolation
def test_account_creation_and_isolation(client: TestClient, user_a: User, user_b: User) -> None:
    headers_a = auth_headers(user_a)
    headers_b = auth_headers(user_b)

    # User A creates an account
    create_res = client.post("/accounts", json={"name": "A Savings", "currency": "INR"}, headers=headers_a)
    assert create_res.status_code == 201
    account_a_id = create_res.json()["id"]

    # User A can view their account
    get_res = client.get(f"/accounts/{account_a_id}", headers=headers_a)
    assert get_res.status_code == 200
    assert get_res.json()["name"] == "A Savings"

    # User B cannot view User A's account (isolation)
    forbidden_res = client.get(f"/accounts/{account_a_id}", headers=headers_b)
    assert forbidden_res.status_code == 403

    # User A cannot create a system account (privilege restricted)
    sys_res = client.post("/accounts", json={"name": "Sys Account", "currency": "INR", "is_system_account": True}, headers=headers_a)
    assert sys_res.status_code == 403


# 5. Successful Deposits and Withdrawals (Double-Entry Balanced)
def test_successful_deposit_and_withdrawal(client: TestClient, user_a: User) -> None:
    headers_a = auth_headers(user_a)
    acc_res = client.post("/accounts", json={"name": "Wallet A", "currency": "INR"}, headers=headers_a)
    acc_id = acc_res.json()["id"]

    # Deposit 10,000 paise (₹100)
    dep_res = client.post(
        "/deposits",
        json={"account_id": acc_id, "amount_minor": 10000, "description": "Initial funding"},
        headers={"Idempotency-Key": f"dep-{uuid.uuid4()}", **headers_a},
    )
    assert dep_res.status_code == 200
    assert dep_res.json()["balance_after"] == 10000

    # Withdraw 4,000 paise (₹40)
    with_res = client.post(
        "/withdrawals",
        json={"account_id": acc_id, "amount_minor": 4000, "description": "ATM cash"},
        headers={"Idempotency-Key": f"with-{uuid.uuid4()}", **headers_a},
    )
    assert with_res.status_code == 200
    assert with_res.json()["balance_after"] == 6000


# 6. Successful Transfer and Double-Entry Invariant
def test_successful_transfer_and_double_entry_balance(client: TestClient, user_a: User, user_b: User) -> None:
    headers_a = auth_headers(user_a)
    headers_b = auth_headers(user_b)

    acc_a_id = client.post("/accounts", json={"name": "Acc A", "currency": "INR"}, headers=headers_a).json()["id"]
    acc_b_id = client.post("/accounts", json={"name": "Acc B", "currency": "INR"}, headers=headers_b).json()["id"]

    # Fund account A with 5,000 paise
    client.post("/deposits", json={"account_id": acc_a_id, "amount_minor": 5000}, headers=headers_a)

    # Transfer 2,000 paise from A to B
    xfer_res = client.post(
        "/transfers",
        json={"source_account_id": acc_a_id, "destination_account_id": acc_b_id, "amount_minor": 2000, "description": "P2P transfer"},
        headers={"Idempotency-Key": f"xfer-{uuid.uuid4()}", **headers_a},
    )
    assert xfer_res.status_code == 200
    data = xfer_res.json()
    assert data["source_balance_after"] == 3000
    assert data["destination_balance_after"] == 2000

    # Verify reconciliation: sum of all ledger entries must be zero
    recon = client.get("/ledger/reconciliation", headers=auth_headers(user_a))
    # Non-admin cannot call reconciliation
    assert recon.status_code == 403


# 7. Overdraft Prevention
def test_overdraft_prevention(client: TestClient, user_a: User) -> None:
    headers_a = auth_headers(user_a)
    acc_id = client.post("/accounts", json={"name": "Overdraft Test", "currency": "INR"}, headers=headers_a).json()["id"]

    # Fund with 1,000 paise
    client.post("/deposits", json={"account_id": acc_id, "amount_minor": 1000}, headers=headers_a)

    # Attempt to withdraw 5,000 paise
    overdraft_res = client.post(
        "/withdrawals",
        json={"account_id": acc_id, "amount_minor": 5000},
        headers={"Idempotency-Key": f"od-{uuid.uuid4()}", **headers_a},
    )
    assert overdraft_res.status_code == 400
    assert "Insufficient funds" in overdraft_res.json()["detail"]

    # Verify balance was NOT debited
    acc_check = client.get(f"/accounts/{acc_id}", headers=headers_a).json()
    assert acc_check["balance_minor"] == 1000


# 8. Duplicate Idempotency Requests
def test_duplicate_idempotency_requests(client: TestClient, user_a: User, user_b: User) -> None:
    headers_a = auth_headers(user_a)
    acc_a_id = client.post("/accounts", json={"name": "Idem A", "currency": "INR"}, headers=headers_a).json()["id"]
    acc_b_id = client.post("/accounts", json={"name": "Idem B", "currency": "INR"}, headers=auth_headers(user_b)).json()["id"]
    client.post("/deposits", json={"account_id": acc_a_id, "amount_minor": 10000}, headers=headers_a)

    idem_key = f"idem-key-{uuid.uuid4()}"
    payload = {"source_account_id": acc_a_id, "destination_account_id": acc_b_id, "amount_minor": 1500, "description": "Pay"}

    # First request
    res1 = client.post("/transfers", json=payload, headers={"Idempotency-Key": idem_key, **headers_a})
    assert res1.status_code == 200
    tx1_id = res1.json()["transaction_id"]

    # Replay request with exact same idempotency key and payload -> returns cached original response
    res2 = client.post("/transfers", json=payload, headers={"Idempotency-Key": idem_key, **headers_a})
    assert res2.status_code == 200
    assert res2.json()["transaction_id"] == tx1_id
    # Ensure source was only debited ONCE (10000 - 1500 = 8500)
    acc_a_check = client.get(f"/accounts/{acc_a_id}", headers=headers_a).json()
    assert acc_a_check["balance_minor"] == 8500

    # Key reuse with DIFFERENT payload must be rejected with 409 Conflict
    diff_payload = {"source_account_id": acc_a_id, "destination_account_id": acc_b_id, "amount_minor": 9999, "description": "Tampered"}
    res3 = client.post("/transfers", json=diff_payload, headers={"Idempotency-Key": idem_key, **headers_a})
    assert res3.status_code == 409
    assert "Idempotency key reuse detected" in res3.json()["detail"]


# 9. Transaction Rollback on Failure
def test_transaction_rollback_on_failure(client: TestClient, user_a: User, user_b: User, db_session: Session) -> None:
    headers_a = auth_headers(user_a)
    acc_a_id = client.post("/accounts", json={"name": "Rollback A", "currency": "INR"}, headers=headers_a).json()["id"]
    client.post("/deposits", json={"account_id": acc_a_id, "amount_minor": 2000}, headers=headers_a)

    entries_before = db_session.query(LedgerEntry).count()

    # Attempt transfer with invalid nonexistent destination account
    fake_dest_id = str(uuid.uuid4())
    res = client.post(
        "/transfers",
        json={"source_account_id": acc_a_id, "destination_account_id": fake_dest_id, "amount_minor": 1000},
        headers=headers_a,
    )
    assert res.status_code in (400, 404)

    # Verify atomic rollback: no new ledger entries committed and balance unchanged
    entries_after = db_session.query(LedgerEntry).count()
    assert entries_after == entries_before

    acc_a = client.get(f"/accounts/{acc_a_id}", headers=headers_a).json()
    assert acc_a["balance_minor"] == 2000


# 10. Unauthorized Cross-Account Transfer
def test_unauthorized_cross_account_transfer(client: TestClient, user_a: User, user_b: User) -> None:
    headers_a = auth_headers(user_a)
    headers_b = auth_headers(user_b)

    acc_a_id = client.post("/accounts", json={"name": "Vault A", "currency": "INR"}, headers=headers_a).json()["id"]
    acc_b_id = client.post("/accounts", json={"name": "Vault B", "currency": "INR"}, headers=headers_b).json()["id"]
    client.post("/deposits", json={"account_id": acc_a_id, "amount_minor": 5000}, headers=headers_a)

    # User B attempts to transfer money OUT OF User A's account
    stolen_res = client.post(
        "/transfers",
        json={"source_account_id": acc_a_id, "destination_account_id": acc_b_id, "amount_minor": 1000},
        headers=headers_b,
    )
    assert stolen_res.status_code == 403
    assert "You do not have authorization" in stolen_res.json()["detail"]


# 11. RBAC Enforcement (Auditor restrictions)
def test_rbac_auditor_restrictions(client: TestClient, auditor_user: User, user_a: User) -> None:
    headers_auditor = auth_headers(auditor_user)
    headers_a = auth_headers(user_a)

    acc_a_id = client.post("/accounts", json={"name": "Audited Acc", "currency": "INR"}, headers=headers_a).json()["id"]
    client.post("/deposits", json={"account_id": acc_a_id, "amount_minor": 2000}, headers=headers_a)

    # Auditor cannot create accounts or transfer money
    acc_res = client.post("/accounts", json={"name": "Auditor Forbidden", "currency": "INR"}, headers=headers_auditor)
    assert acc_res.status_code == 403

    xfer_res = client.post(
        "/transfers",
        json={"source_account_id": acc_a_id, "destination_account_id": acc_a_id, "amount_minor": 100},
        headers=headers_auditor,
    )
    assert xfer_res.status_code == 403

    # Auditor CAN view statements, reconciliation, and audit log
    stmt_res = client.get(f"/statements/{acc_a_id}", headers=headers_auditor)
    assert stmt_res.status_code == 200

    recon_res = client.get("/ledger/reconciliation", headers=headers_auditor)
    assert recon_res.status_code == 200
    assert recon_res.json()["is_reconciled"] is True

    audit_res = client.get("/audit/events", headers=headers_auditor)
    assert audit_res.status_code == 200


# 12. Ledger Hash-Chain Verification and Tamper Detection
def test_ledger_hash_chain_verification_and_tamper_detection(
    client: TestClient, user_a: User, admin_user: User, db_session: Session
) -> None:
    headers_a = auth_headers(user_a)
    headers_admin = auth_headers(admin_user)
    acc_a_id = client.post("/accounts", json={"name": "Chain Test", "currency": "INR"}, headers=headers_a).json()["id"]

    # Execute multiple deposits
    client.post("/deposits", json={"account_id": acc_a_id, "amount_minor": 1000}, headers=headers_a)
    client.post("/deposits", json={"account_id": acc_a_id, "amount_minor": 2000}, headers=headers_a)

    # Verify clean hash chain (requires Admin or Auditor role)
    verify_res = client.get("/ledger/verify", headers=headers_admin)
    assert verify_res.status_code == 200
    assert verify_res.json()["verified"] is True
    assert verify_res.json()["total_entries"] >= 4  # 2 entries per deposit (clearing + customer)

    # Tamper with an entry directly in database
    entry = db_session.query(LedgerEntry).first()
    original_amount = entry.amount_minor
    entry.amount_minor = original_amount + 99999
    db_session.commit()

    # Re-verify: must catch the tamper (requires Admin or Auditor)
    tamper_res = client.get("/ledger/verify", headers=headers_admin)
    assert tamper_res.status_code == 200
    assert tamper_res.json()["verified"] is False
    assert "Tamper detected" in tamper_res.json()["error"]

    # Restore
    entry.amount_minor = original_amount
    db_session.commit()


# 13. Rate Limiting Protection
def test_rate_limiting(client: TestClient) -> None:
    from balancevault.rate_limit import _memory_counters
    _memory_counters.clear()
    # Rapidly call a rate-limited endpoint (limit is 20)
    responses = []
    for _ in range(25):
        responses.append(client.post("/auth/register", json={"email": f"ratelimit_{uuid.uuid4().hex[:6]}@example.com", "password": "Pass123!"}))

    statuses = [r.status_code for r in responses]
    assert 429 in statuses, f"Expected 429 in statuses, got {set(statuses)}"
    _memory_counters.clear()
