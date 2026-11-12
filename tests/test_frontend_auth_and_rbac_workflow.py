import uuid
from datetime import timedelta

from fastapi import status
from fastapi.testclient import TestClient

from ledgerline.auth import create_access_token, hash_password
from ledgerline.models import User, UserRole


def test_complete_auth_and_rbac_workflow(client: TestClient, db_session):
    """
    Comprehensive test covering all 10 checklist items:
    1. Register new account holder
    2. Attempt to register with admin role -> verify ignored/rejected
    3. Login with valid credentials
    4. Login with invalid credentials
    5. Session handling via GET /auth/me
    6. Verify account-holder permissions
    7. Verify admin-only pages reject account holders
    8. Verify auditor access is read-only
    9. Verify unauthenticated calls are rejected (logout state)
    10. Verify expired tokens are rejected
    """
    unique_suffix = uuid.uuid4().hex[:6]
    holder_email = f"holder_{unique_suffix}@example.com"
    holder_password = "HolderSecurePassword123!"

    # 1. Register a new account holder
    reg_resp = client.post(
        "/auth/register",
        json={"email": holder_email, "password": holder_password, "full_name": "Test Holder"},
    )
    assert reg_resp.status_code == status.HTTP_201_CREATED, reg_resp.text
    reg_data = reg_resp.json()
    assert reg_data["role"].lower() == "account_holder"
    holder_id = reg_data["id"]

    # 2. Attempt to register with an admin role -> verify it is ignored (assigned account_holder)
    sneaky_email = f"sneaky_admin_{unique_suffix}@example.com"
    sneaky_resp = client.post(
        "/auth/register",
        json={"email": sneaky_email, "password": "Password123!", "role": "admin"},
    )
    assert sneaky_resp.status_code == status.HTTP_201_CREATED
    assert sneaky_resp.json()["role"].lower() == "account_holder", "Privilege escalation detected!"

    # 3. Login with valid credentials
    login_resp = client.post(
        "/auth/login",
        json={"email": holder_email, "password": holder_password},
    )
    assert login_resp.status_code == status.HTTP_200_OK
    login_data = login_resp.json()
    assert "access_token" in login_data
    holder_token = login_data["access_token"]
    assert login_data["user"]["role"].lower() == "account_holder"

    # 4. Login with invalid credentials
    bad_login = client.post(
        "/auth/login",
        json={"email": holder_email, "password": "WrongPassword!"},
    )
    assert bad_login.status_code == status.HTTP_401_UNAUTHORIZED

    bad_email = client.post(
        "/auth/login",
        json={"email": "nonexistent@example.com", "password": "Password123!"},
    )
    assert bad_email.status_code == status.HTTP_401_UNAUTHORIZED

    # 5. Session handling via GET /auth/me
    headers_holder = {"Authorization": f"Bearer {holder_token}"}
    me_resp = client.get("/auth/me", headers=headers_holder)
    assert me_resp.status_code == status.HTTP_200_OK
    assert me_resp.json()["email"] == holder_email
    assert me_resp.json()["role"].lower() == "account_holder"

    # 6. Verify account-holder permissions (create account, view own accounts)
    acc_resp = client.post(
        "/accounts",
        headers=headers_holder,
        json={"name": "Holder Checking", "currency": "INR"},
    )
    assert acc_resp.status_code == status.HTTP_201_CREATED
    holder_acc_id = acc_resp.json()["id"]

    # View accounts as account holder -> only returns own accounts
    list_resp = client.get("/accounts", headers=headers_holder)
    assert list_resp.status_code == status.HTTP_200_OK
    accounts_found = list_resp.json()
    assert all(a["owner_user_id"] == holder_id for a in accounts_found if not a["is_system_account"])

    # 7. Verify admin-only pages reject account holders
    users_resp = client.get("/users", headers=headers_holder)
    assert users_resp.status_code == status.HTTP_403_FORBIDDEN

    audit_resp = client.get("/audit/events", headers=headers_holder)
    assert audit_resp.status_code == status.HTTP_403_FORBIDDEN

    sys_acc_resp = client.post(
        "/accounts",
        headers=headers_holder,
        json={"name": "Malicious System Acc", "currency": "INR", "is_system_account": True},
    )
    assert sys_acc_resp.status_code == status.HTTP_403_FORBIDDEN

    # 8. Verify auditor access is read-only
    auditor_user = User(
        id=uuid.uuid4(),
        email=f"auditor_{unique_suffix}@example.com",
        password_hash=hash_password("AuditorPass123!"),
        role=UserRole.AUDITOR,
        is_active=True,
    )
    db_session.add(auditor_user)
    db_session.commit()
    auditor_token = create_access_token(auditor_user)
    headers_auditor = {"Authorization": f"Bearer {auditor_token}"}

    # Auditor CAN read audit events, verify ledger, and reconcile
    aud_audit = client.get("/audit/events", headers=headers_auditor)
    assert aud_audit.status_code == status.HTTP_200_OK

    aud_verify = client.get("/ledger/verify", headers=headers_auditor)
    assert aud_verify.status_code == status.HTTP_200_OK

    aud_recon = client.get("/ledger/reconciliation", headers=headers_auditor)
    assert aud_recon.status_code == status.HTTP_200_OK

    # Auditor CANNOT create accounts
    aud_create_acc = client.post(
        "/accounts",
        headers=headers_auditor,
        json={"name": "Auditor Forbidden Acc", "currency": "INR"},
    )
    assert aud_create_acc.status_code == status.HTTP_403_FORBIDDEN

    # Auditor CANNOT transfer money
    aud_transfer = client.post(
        "/transfers",
        headers=headers_auditor,
        json={
            "source_account_id": holder_acc_id,
            "destination_account_id": holder_acc_id,
            "amount_minor": 100,
            "description": "Auditor forbidden xfer",
        },
    )
    assert aud_transfer.status_code == status.HTTP_403_FORBIDDEN

    # Auditor CANNOT deposit or withdraw
    aud_dep = client.post(
        "/deposits",
        headers=headers_auditor,
        json={"account_id": holder_acc_id, "amount_minor": 500, "description": "Forbidden"},
    )
    assert aud_dep.status_code == status.HTTP_403_FORBIDDEN

    aud_wd = client.post(
        "/withdrawals",
        headers=headers_auditor,
        json={"account_id": holder_acc_id, "amount_minor": 500, "description": "Forbidden"},
    )
    assert aud_wd.status_code == status.HTTP_403_FORBIDDEN

    # 9. Verify unauthenticated calls are rejected (logout state)
    no_auth_accounts = client.get("/accounts")
    assert no_auth_accounts.status_code == status.HTTP_401_UNAUTHORIZED

    no_auth_transfers = client.post("/transfers", json={})
    assert no_auth_transfers.status_code == status.HTTP_401_UNAUTHORIZED

    no_auth_me = client.get("/auth/me")
    assert no_auth_me.status_code == status.HTTP_401_UNAUTHORIZED

    # 10. Verify expired tokens are handled correctly
    expired_token = create_access_token(auditor_user, expires_delta=timedelta(seconds=-10))
    headers_expired = {"Authorization": f"Bearer {expired_token}"}
    expired_resp = client.get("/auth/me", headers=headers_expired)
    assert expired_resp.status_code == status.HTTP_401_UNAUTHORIZED
    assert "expired" in expired_resp.json()["detail"].lower()
