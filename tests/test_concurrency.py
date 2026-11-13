import concurrent.futures
import tempfile
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import balancevault.database as db_mod
from balancevault.auth import create_access_token, hash_password
from balancevault.database import Base
from balancevault.main import app
from balancevault.models import Account, User, UserRole


@pytest.fixture(scope="session", autouse=True)
def setup_test_engine():
    temp_dir = tempfile.TemporaryDirectory()
    db_path = Path(temp_dir.name) / "test_concurrency.db"
    engine = create_engine(
        f"sqlite:///{db_path}",
        connect_args={"check_same_thread": False, "timeout": 30},
    )
    # Enable WAL mode for concurrent execution
    with engine.connect() as conn:
        conn.exec_driver_sql("PRAGMA journal_mode=WAL;")
        conn.exec_driver_sql("PRAGMA busy_timeout=30000;")
    Base.metadata.create_all(bind=engine)
    db_mod.engine = engine
    db_mod.SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    yield engine
    engine.dispose()
    try:
        temp_dir.cleanup()
    except Exception:
        pass


def test_concurrent_withdrawal_race_condition(setup_test_engine) -> None:
    from balancevault.rate_limit import _memory_counters
    _memory_counters.clear()
    session = db_mod.SessionLocal()
    # Create user and account
    user = User(
        id=uuid.uuid4(),
        email=f"race_user_{uuid.uuid4().hex[:6]}@example.com",
        password_hash=hash_password("Pass123!"),
        role=UserRole.ACCOUNT_HOLDER,
        is_active=True,
    )
    account = Account(
        id=uuid.uuid4(),
        owner_user_id=user.id,
        name="Race Account",
        currency="INR",
        balance_minor=10000,  # 10,000 paise
        is_system_account=False,
    )
    session.add_all([user, account])
    session.commit()
    token = create_access_token(user)
    session.close()

    # 5 concurrent threads attempt to withdraw 8,000 paise each
    # Since only 10,000 is available, exactly ONE must succeed, 4 must fail with 400
    def attempt_withdrawal(worker_id: int):
        with TestClient(app) as local_client:
            return local_client.post(
                "/withdrawals",
                json={"account_id": str(account.id), "amount_minor": 8000},
                headers={
                    "Authorization": f"Bearer {token}",
                    "Idempotency-Key": f"race-{worker_id}-{uuid.uuid4()}",
                },
            )

    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
        futures = [executor.submit(attempt_withdrawal, i) for i in range(5)]
        results = [f.result() for f in concurrent.futures.as_completed(futures)]

    status_codes = [r.status_code for r in results]
    successes = status_codes.count(200)
    failures = status_codes.count(400)

    assert successes == 1, f"Expected exactly 1 success, got {successes}. Statuses: {status_codes}"
    assert failures == 4, f"Expected 4 failures, got {failures}. Statuses: {status_codes}"

    # Verify final balance is exactly 2,000 paise (never negative)
    verify_session = db_mod.SessionLocal()
    final_acc = verify_session.get(Account, account.id)
    assert final_acc.balance_minor == 2000
    verify_session.close()


def test_opposing_transfers_no_deadlock(setup_test_engine) -> None:
    from balancevault.rate_limit import _memory_counters
    _memory_counters.clear()
    session = db_mod.SessionLocal()
    user_a = User(
        id=uuid.uuid4(),
        email=f"opp_a_{uuid.uuid4().hex[:6]}@example.com",
        password_hash=hash_password("Pass123!"),
        role=UserRole.ACCOUNT_HOLDER,
        is_active=True,
    )
    user_b = User(
        id=uuid.uuid4(),
        email=f"opp_b_{uuid.uuid4().hex[:6]}@example.com",
        password_hash=hash_password("Pass123!"),
        role=UserRole.ACCOUNT_HOLDER,
        is_active=True,
    )
    acc_a = Account(
        id=uuid.uuid4(),
        owner_user_id=user_a.id,
        name="Account A",
        currency="INR",
        balance_minor=100000,
        is_system_account=False,
    )
    acc_b = Account(
        id=uuid.uuid4(),
        owner_user_id=user_b.id,
        name="Account B",
        currency="INR",
        balance_minor=100000,
        is_system_account=False,
    )
    session.add_all([user_a, user_b, acc_a, acc_b])
    session.commit()
    token_a = create_access_token(user_a)
    token_b = create_access_token(user_b)
    session.close()

    def transfer_a_to_b(i: int):
        with TestClient(app) as client:
            return client.post(
                "/transfers",
                json={"source_account_id": str(acc_a.id), "destination_account_id": str(acc_b.id), "amount_minor": 100},
                headers={"Authorization": f"Bearer {token_a}", "Idempotency-Key": f"opp-a-{i}-{uuid.uuid4()}"},
            )

    def transfer_b_to_a(i: int):
        with TestClient(app) as client:
            return client.post(
                "/transfers",
                json={"source_account_id": str(acc_b.id), "destination_account_id": str(acc_a.id), "amount_minor": 100},
                headers={"Authorization": f"Bearer {token_b}", "Idempotency-Key": f"opp-b-{i}-{uuid.uuid4()}"},
            )

    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as executor:
        f_a = [executor.submit(transfer_a_to_b, i) for i in range(3)]
        f_b = [executor.submit(transfer_b_to_a, i) for i in range(3)]
        all_results = [f.result() for f in concurrent.futures.as_completed(f_a + f_b)]

    # All 6 transfers should succeed without deadlock
    assert all(r.status_code == 200 for r in all_results)
