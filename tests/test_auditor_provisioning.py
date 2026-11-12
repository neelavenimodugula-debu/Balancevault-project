import uuid

from fastapi import status
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from ledgerline.auth import create_access_token, hash_password
from ledgerline.models import Account, AuditEvent, User, UserRole


def test_admin_provisions_new_auditor_and_audit_event_recorded(client: TestClient, db_session: Session):
    """Admin can provision a new auditor, creating the account and recording an immutable audit event."""
    # Create an admin user
    admin = User(
        id=uuid.uuid4(),
        email=f"admin_{uuid.uuid4().hex[:6]}@firm.com",
        password_hash=hash_password("AdminPass123!"),
        role=UserRole.ADMIN,
        is_active=True,
    )
    db_session.add(admin)
    db_session.commit()
    admin_token = create_access_token(admin)
    admin_headers = {"Authorization": f"Bearer {admin_token}"}

    auditor_email = f"auditor_{uuid.uuid4().hex[:6]}@auditfirm.com"
    auditor_password = "AuditorSecurePass2026!"

    # 1. Admin provisions auditor
    resp = client.post(
        "/users/auditors",
        headers=admin_headers,
        json={"email": auditor_email, "password": auditor_password},
    )
    assert resp.status_code == status.HTTP_201_CREATED, resp.text
    data = resp.json()
    assert data["email"] == auditor_email
    assert data["role"].lower() == "auditor"
    assert data["status"] == "created"
    assert "password" not in data
    assert "password_hash" not in data

    # 2. Check immutable audit event was recorded
    audit_event = (
        db_session.query(AuditEvent)
        .filter_by(action="PROVISION_AUDITOR")
        .order_by(AuditEvent.created_at.desc())
        .first()
    )
    assert audit_event is not None
    assert audit_event.actor_user_id == admin.id
    assert audit_event.details["email"] == auditor_email
    assert audit_event.details["role"] == "auditor"

    # 3. Auditor successfully logs in via POST /auth/login
    login_resp = client.post(
        "/auth/login",
        json={"email": auditor_email, "password": auditor_password},
    )
    assert login_resp.status_code == status.HTTP_200_OK
    login_data = login_resp.json()
    assert "access_token" in login_data
    auditor_jwt = login_data["access_token"]
    assert login_data["user"]["role"].lower() == "auditor"

    # 4. Auditor accesses GET /auth/me
    auditor_headers = {"Authorization": f"Bearer {auditor_jwt}"}
    me_resp = client.get("/auth/me", headers=auditor_headers)
    assert me_resp.status_code == status.HTTP_200_OK
    assert me_resp.json()["email"] == auditor_email
    assert me_resp.json()["role"].lower() == "auditor"


def test_admin_promotes_existing_account_holder_to_auditor(client: TestClient, db_session: Session):
    """Admin can promote an existing account holder to auditor role."""
    admin = User(
        id=uuid.uuid4(),
        email=f"admin_{uuid.uuid4().hex[:6]}@firm.com",
        password_hash=hash_password("AdminPass123!"),
        role=UserRole.ADMIN,
        is_active=True,
    )
    user = User(
        id=uuid.uuid4(),
        email=f"holder_{uuid.uuid4().hex[:6]}@firm.com",
        password_hash=hash_password("HolderPass123!"),
        role=UserRole.ACCOUNT_HOLDER,
        is_active=True,
    )
    db_session.add_all([admin, user])
    db_session.commit()

    admin_headers = {"Authorization": f"Bearer {create_access_token(admin)}"}

    # Promote via POST /users/auditors with same email
    promote_resp = client.post(
        "/users/auditors",
        headers=admin_headers,
        json={"email": user.email, "password": "NewAuditorPass123!"},
    )
    assert promote_resp.status_code == status.HTTP_201_CREATED
    assert promote_resp.json()["status"] == "promoted"
    assert promote_resp.json()["role"].lower() == "auditor"

    # Verify user can log in with new auditor credentials
    login_resp = client.post(
        "/auth/login",
        json={"email": user.email, "password": "NewAuditorPass123!"},
    )
    assert login_resp.status_code == status.HTTP_200_OK
    assert login_resp.json()["user"]["role"].lower() == "auditor"

    # Promote via PATCH /users/{id}/role
    patch_user = User(
        id=uuid.uuid4(),
        email=f"holder2_{uuid.uuid4().hex[:6]}@firm.com",
        password_hash=hash_password("HolderPass123!"),
        role=UserRole.ACCOUNT_HOLDER,
        is_active=True,
    )
    db_session.add(patch_user)
    db_session.commit()

    patch_resp = client.patch(
        f"/users/{patch_user.id}/role",
        headers=admin_headers,
        json={"role": "auditor"},
    )
    assert patch_resp.status_code == status.HTTP_200_OK
    assert patch_resp.json()["role"].lower() == "auditor"


def test_non_admin_cannot_provision_auditor(client: TestClient, db_session: Session):
    """Account holders and unauthenticated requests cannot provision an auditor."""
    holder = User(
        id=uuid.uuid4(),
        email=f"holder_{uuid.uuid4().hex[:6]}@firm.com",
        password_hash=hash_password("HolderPass123!"),
        role=UserRole.ACCOUNT_HOLDER,
        is_active=True,
    )
    db_session.add(holder)
    db_session.commit()

    # Unauthenticated attempt -> 401
    unauth_resp = client.post(
        "/users/auditors",
        json={"email": "hacker_auditor@firm.com", "password": "Password123!"},
    )
    assert unauth_resp.status_code == status.HTTP_401_UNAUTHORIZED

    # Account holder attempt -> 403
    holder_headers = {"Authorization": f"Bearer {create_access_token(holder)}"}
    forbidden_resp = client.post(
        "/users/auditors",
        headers=holder_headers,
        json={"email": "hacker_auditor@firm.com", "password": "Password123!"},
    )
    assert forbidden_resp.status_code == status.HTTP_403_FORBIDDEN


def test_public_registration_cannot_grant_auditor_role(client: TestClient):
    """Public registration ignores any submitted 'role': 'auditor' and creates account_holder."""
    email = f"sneaky_auditor_{uuid.uuid4().hex[:6]}@firm.com"
    reg_resp = client.post(
        "/auth/register",
        json={"email": email, "password": "Password123!", "role": "auditor"},
    )
    assert reg_resp.status_code == status.HTTP_201_CREATED
    assert reg_resp.json()["role"].lower() == "account_holder"


def test_auditor_permissions_allowed_and_forbidden(client: TestClient, db_session: Session):
    """Verify that an Auditor can access read-only inspection endpoints but is strictly blocked from money movement and user management."""
    auditor = User(
        id=uuid.uuid4(),
        email=f"auditor_{uuid.uuid4().hex[:6]}@firm.com",
        password_hash=hash_password("AuditorPass123!"),
        role=UserRole.AUDITOR,
        is_active=True,
    )
    holder = User(
        id=uuid.uuid4(),
        email=f"holder_{uuid.uuid4().hex[:6]}@firm.com",
        password_hash=hash_password("HolderPass123!"),
        role=UserRole.ACCOUNT_HOLDER,
        is_active=True,
    )
    db_session.add_all([auditor, holder])
    db_session.commit()

    acc = Account(
        id=uuid.uuid4(),
        owner_user_id=holder.id,
        name="Holder Account",
        currency="INR",
        balance_minor=50000,
        is_system_account=False,
    )
    db_session.add(acc)
    db_session.commit()

    auditor_headers = {"Authorization": f"Bearer {create_access_token(auditor)}"}

    # ALLOWED ENDPOINTS:
    # 1. GET /accounts (inspect all accounts)
    res_acc = client.get("/accounts", headers=auditor_headers)
    assert res_acc.status_code == status.HTTP_200_OK

    # 2. GET /statements/{account_id}
    res_stmt = client.get(f"/statements/{acc.id}", headers=auditor_headers)
    assert res_stmt.status_code == status.HTTP_200_OK

    # 3. GET /audit/events
    res_audit = client.get("/audit/events", headers=auditor_headers)
    assert res_audit.status_code == status.HTTP_200_OK

    # 4. GET /ledger/verify
    res_verify = client.get("/ledger/verify", headers=auditor_headers)
    assert res_verify.status_code == status.HTTP_200_OK

    # 5. GET /ledger/reconciliation
    res_recon = client.get("/ledger/reconciliation", headers=auditor_headers)
    assert res_recon.status_code == status.HTTP_200_OK

    # FORBIDDEN ENDPOINTS:
    # 1. POST /transfers (money movement)
    res_tx = client.post(
        "/transfers",
        headers=auditor_headers,
        json={"source_account_id": str(acc.id), "destination_account_id": str(acc.id), "amount_minor": 100},
    )
    assert res_tx.status_code == status.HTTP_403_FORBIDDEN

    # 2. POST /deposits
    res_dep = client.post(
        "/deposits",
        headers=auditor_headers,
        json={"account_id": str(acc.id), "amount_minor": 100},
    )
    assert res_dep.status_code == status.HTTP_403_FORBIDDEN

    # 3. POST /withdrawals
    res_wd = client.post(
        "/withdrawals",
        headers=auditor_headers,
        json={"account_id": str(acc.id), "amount_minor": 100},
    )
    assert res_wd.status_code == status.HTTP_403_FORBIDDEN

    # 4. POST /accounts (create account)
    res_new_acc = client.post(
        "/accounts",
        headers=auditor_headers,
        json={"name": "Auditor Account", "currency": "INR"},
    )
    assert res_new_acc.status_code == status.HTTP_403_FORBIDDEN

    # 5. GET /users (user management)
    res_users = client.get("/users", headers=auditor_headers)
    assert res_users.status_code == status.HTTP_403_FORBIDDEN

    # 6. POST /users/auditors (provisioning)
    res_prov = client.post(
        "/users/auditors",
        headers=auditor_headers,
        json={"email": "another@audit.com", "password": "Password123!"},
    )
    assert res_prov.status_code == status.HTTP_403_FORBIDDEN

