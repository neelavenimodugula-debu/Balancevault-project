import hashlib
import json
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import func
from sqlalchemy.orm import Session

from balancevault.config import get_settings
from balancevault.models import (
    Account,
    AuditEvent,
    IdempotencyRequest,
    JournalTransaction,
    LedgerEntry,
    User,
    UserRole,
)


class LedgerException(Exception):
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


class InsufficientFundsException(LedgerException):
    def __init__(self, message: str = "Insufficient funds in account"):
        super().__init__(message, status_code=400)


class AccountNotFoundException(LedgerException):
    def __init__(self, message: str = "Account not found"):
        super().__init__(message, status_code=404)


class UnauthorizedAccountAccessException(LedgerException):
    def __init__(self, message: str = "Unauthorized account access"):
        super().__init__(message, status_code=403)


class IdempotencyConflictException(LedgerException):
    def __init__(self, message: str):
        super().__init__(message, status_code=409)


def compute_payload_fingerprint(path: str, payload: dict[str, Any]) -> str:
    serialized = f"{path}:{json.dumps(payload, sort_keys=True, default=str)}"
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def compute_entry_hash(
    prev_hash: str,
    sequence: int,
    journal_id: UUID,
    account_id: UUID,
    amount_minor: int,
    balance_after: int,
) -> str:
    raw = f"{prev_hash}:{sequence}:{journal_id}:{account_id}:{amount_minor}:{balance_after}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def record_audit_event(
    session: Session,
    actor_id: UUID | None,
    action: str,
    outcome: str,
    account_id: UUID | None = None,
    details: dict[str, Any] | None = None,
) -> AuditEvent:
    event = AuditEvent(
        id=uuid4(),
        actor_user_id=actor_id,
        account_id=account_id,
        action=action,
        outcome=outcome,
        details=details or {},
    )
    session.add(event)
    session.commit()
    return event


def get_or_create_system_clearing_account(session: Session, currency: str = "INR") -> Account:
    clearing = (
        session.query(Account)
        .filter(
            Account.is_system_account.is_(True),
            Account.name == get_settings().clearing_account_name,
            Account.currency == currency,
        )
        .first()
    )
    if not clearing:
        clearing = Account(
            id=uuid4(),
            owner_user_id=None,
            name=get_settings().clearing_account_name,
            currency=currency,
            balance_minor=0,
            is_system_account=True,
        )
        session.add(clearing)
        session.flush()
    return clearing


def check_idempotency_preflight(
    session: Session,
    actor_id: UUID,
    key: str,
    fingerprint: str,
) -> tuple[bool, dict[str, Any] | None, int | None]:
    record = (
        session.query(IdempotencyRequest)
        .filter_by(actor_user_id=actor_id, key=key)
        .first()
    )
    if not record:
        return False, None, None

    if record.request_fingerprint != fingerprint:
        raise IdempotencyConflictException(
            "Idempotency key reuse detected with different request payload."
        )

    if record.response_status is None:
        raise IdempotencyConflictException(
            "Concurrent request in progress with this idempotency key. Please wait."
        )

    return True, record.response_body, record.response_status


def lock_accounts(session: Session, account_ids: list[UUID]) -> dict[UUID, Account]:
    unique_ids = sorted(list(set(account_ids)))
    query = session.query(Account).filter(Account.id.in_(unique_ids))
    try:
        query = query.with_for_update()
    except Exception:
        pass  # dialect does not support row-level locking (e.g. SQLite)
    accounts = query.order_by(Account.id.asc()).all()
    account_map = {acc.id: acc for acc in accounts}

    for acc_id in unique_ids:
        if acc_id not in account_map:
            raise AccountNotFoundException(f"Account {acc_id} not found.")

    return account_map


def _append_ledger_entries(
    session: Session,
    journal_id: UUID,
    entry_definitions: list[tuple[Account, int]],  # (Account, amount_minor)
) -> list[LedgerEntry]:
    # Invariant: Total sum of double-entry postings must be 0
    total_change = sum(amount for _, amount in entry_definitions)
    if total_change != 0:
        raise LedgerException(
            f"Double-entry ledger invariant violation: sum of entries is {total_change}, must be 0."
        )

    # Fetch the latest ledger entry to continue the cryptographic hash chain
    latest_entry = (
        session.query(LedgerEntry)
        .order_by(LedgerEntry.entry_sequence.desc(), LedgerEntry.created_at.desc())
        .first()
    )

    current_prev_hash = latest_entry.entry_hash if latest_entry else "0" * 64
    current_sequence = latest_entry.entry_sequence if latest_entry else 0

    created_entries = []
    for account, amount in entry_definitions:
        if amount == 0:
            raise LedgerException("Nonzero entry constraint violation: amount cannot be 0.")

        # Immediate pre-check
        if not account.is_system_account and (account.balance_minor + amount < 0):
            raise InsufficientFundsException(
                f"Insufficient funds in account {account.id}. Balance: {account.balance_minor}, Debit: {abs(amount)}"
            )

        # Atomic conditional database update - protects against concurrency races across all SQL engines
        condition = Account.id == account.id
        if not account.is_system_account:
            condition = condition & (Account.balance_minor + amount >= 0)

        rows_updated = (
            session.query(Account)
            .filter(condition)
            .update(
                {Account.balance_minor: Account.balance_minor + amount},
                synchronize_session=False,
            )
        )
        if rows_updated == 0:
            raise InsufficientFundsException(
                f"Insufficient funds or concurrent balance modification on account {account.id}."
            )

        session.refresh(account)
        new_balance = account.balance_minor
        current_sequence += 1

        entry_hash = compute_entry_hash(
            prev_hash=current_prev_hash,
            sequence=current_sequence,
            journal_id=journal_id,
            account_id=account.id,
            amount_minor=amount,
            balance_after=new_balance,
        )

        entry = LedgerEntry(
            id=uuid4(),
            journal_transaction_id=journal_id,
            account_id=account.id,
            amount_minor=amount,
            balance_after_minor=new_balance,
            entry_sequence=current_sequence,
            prev_hash=current_prev_hash,
            entry_hash=entry_hash,
        )
        session.add(entry)
        created_entries.append(entry)
        current_prev_hash = entry_hash

    return created_entries


def execute_transfer(
    session: Session,
    actor: User,
    source_account_id: UUID,
    destination_account_id: UUID,
    amount_minor: int,
    idempotency_key: str | None = None,
    path: str = "/transfers",
    description: str = "Account transfer",
) -> dict[str, Any]:
    if amount_minor <= 0:
        raise LedgerException("Amount must be a positive integer in minor units (paise).")

    if source_account_id == destination_account_id:
        raise LedgerException("Source and destination accounts must be distinct.")

    # Idempotency preflight
    fingerprint = None
    if idempotency_key:
        payload = {
            "source_account_id": str(source_account_id),
            "destination_account_id": str(destination_account_id),
            "amount_minor": amount_minor,
            "description": description,
        }
        fingerprint = compute_payload_fingerprint(path, payload)
        is_replay, cached_body, status_code = check_idempotency_preflight(
            session, actor.id, idempotency_key, fingerprint
        )
        if is_replay:
            return cached_body

    try:
        # Lock accounts in deterministic order
        account_map = lock_accounts(session, [source_account_id, destination_account_id])
        source_account = account_map[source_account_id]
        dest_account = account_map[destination_account_id]

        # Ownership authorization: account_holder can only debit their own account
        is_admin = actor.role == UserRole.ADMIN or str(actor.role) == "admin"
        if not is_admin and source_account.owner_user_id != actor.id:
            raise UnauthorizedAccountAccessException(
                "You do not have authorization to debit this account."
            )

        if source_account.currency != dest_account.currency:
            raise LedgerException("Cross-currency transfers are not supported in this release.")

        journal_id = uuid4()
        journal_tx = JournalTransaction(
            id=journal_id,
            actor_user_id=actor.id,
            operation="TRANSFER",
            source_account_id=source_account.id,
            destination_account_id=dest_account.id,
            amount_minor=amount_minor,
        )
        session.add(journal_tx)

        # Double-entry postings: debit source (-amount), credit dest (+amount)
        _append_ledger_entries(
            session,
            journal_id=journal_id,
            entry_definitions=[
                (source_account, -amount_minor),
                (dest_account, amount_minor),
            ],
        )

        response_body = {
            "transaction_id": str(journal_id),
            "operation": "TRANSFER",
            "source_account_id": str(source_account_id),
            "destination_account_id": str(destination_account_id),
            "amount_minor": amount_minor,
            "currency": source_account.currency,
            "source_balance_after": source_account.balance_minor,
            "destination_balance_after": dest_account.balance_minor,
            "description": description,
            "created_at": datetime.now(UTC).isoformat(),
        }

        # Store idempotency record
        if idempotency_key and fingerprint:
            idem_record = IdempotencyRequest(
                id=uuid4(),
                actor_user_id=actor.id,
                key=idempotency_key,
                request_fingerprint=fingerprint,
                response_status=200,
                response_body=response_body,
            )
            session.add(idem_record)

        # Audit event inside transaction
        audit_event = AuditEvent(
            id=uuid4(),
            actor_user_id=actor.id,
            account_id=source_account_id,
            action="TRANSFER",
            outcome="success",
            details=response_body,
        )
        session.add(audit_event)

        session.commit()
        return response_body

    except Exception as exc:
        session.rollback()
        # Record refused audit event outside rolled-back transaction
        record_audit_event(
            session=session,
            actor_id=actor.id,
            action="TRANSFER",
            outcome="refused",
            account_id=source_account_id,
            details={
                "error": str(exc),
                "source_account_id": str(source_account_id),
                "destination_account_id": str(destination_account_id),
                "amount_minor": amount_minor,
            },
        )
        raise exc


def execute_deposit(
    session: Session,
    actor: User,
    account_id: UUID,
    amount_minor: int,
    idempotency_key: str | None = None,
    path: str = "/deposits",
    description: str = "Account deposit",
) -> dict[str, Any]:
    if amount_minor <= 0:
        raise LedgerException("Amount must be a positive integer in minor units (paise).")

    fingerprint = None
    if idempotency_key:
        payload = {
            "account_id": str(account_id),
            "amount_minor": amount_minor,
            "description": description,
        }
        fingerprint = compute_payload_fingerprint(path, payload)
        is_replay, cached_body, status_code = check_idempotency_preflight(
            session, actor.id, idempotency_key, fingerprint
        )
        if is_replay:
            return cached_body

    try:
        account_map = lock_accounts(session, [account_id])
        customer_account = account_map[account_id]

        is_admin = actor.role == UserRole.ADMIN or str(actor.role) == "admin"
        if not is_admin and customer_account.owner_user_id != actor.id:
            raise UnauthorizedAccountAccessException(
                "You do not have authorization to deposit into this account."
            )

        clearing_account = get_or_create_system_clearing_account(
            session, currency=customer_account.currency
        )
        # Lock clearing account as well
        lock_accounts(session, [clearing_account.id])

        journal_id = uuid4()
        journal_tx = JournalTransaction(
            id=journal_id,
            actor_user_id=actor.id,
            operation="DEPOSIT",
            source_account_id=clearing_account.id,
            destination_account_id=customer_account.id,
            amount_minor=amount_minor,
        )
        session.add(journal_tx)

        # Balanced double-entry: clearing account -amount, customer account +amount (sum = 0)
        _append_ledger_entries(
            session,
            journal_id=journal_id,
            entry_definitions=[
                (clearing_account, -amount_minor),
                (customer_account, amount_minor),
            ],
        )

        response_body = {
            "transaction_id": str(journal_id),
            "operation": "DEPOSIT",
            "account_id": str(account_id),
            "amount_minor": amount_minor,
            "currency": customer_account.currency,
            "balance_after": customer_account.balance_minor,
            "description": description,
            "created_at": datetime.now(UTC).isoformat(),
        }

        if idempotency_key and fingerprint:
            idem_record = IdempotencyRequest(
                id=uuid4(),
                actor_user_id=actor.id,
                key=idempotency_key,
                request_fingerprint=fingerprint,
                response_status=200,
                response_body=response_body,
            )
            session.add(idem_record)

        audit_event = AuditEvent(
            id=uuid4(),
            actor_user_id=actor.id,
            account_id=account_id,
            action="DEPOSIT",
            outcome="success",
            details=response_body,
        )
        session.add(audit_event)

        session.commit()
        return response_body

    except Exception as exc:
        session.rollback()
        record_audit_event(
            session=session,
            actor_id=actor.id,
            action="DEPOSIT",
            outcome="refused",
            account_id=account_id,
            details={"error": str(exc), "amount_minor": amount_minor},
        )
        raise exc


def execute_withdrawal(
    session: Session,
    actor: User,
    account_id: UUID,
    amount_minor: int,
    idempotency_key: str | None = None,
    path: str = "/withdrawals",
    description: str = "Account withdrawal",
) -> dict[str, Any]:
    if amount_minor <= 0:
        raise LedgerException("Amount must be a positive integer in minor units (paise).")

    fingerprint = None
    if idempotency_key:
        payload = {
            "account_id": str(account_id),
            "amount_minor": amount_minor,
            "description": description,
        }
        fingerprint = compute_payload_fingerprint(path, payload)
        is_replay, cached_body, status_code = check_idempotency_preflight(
            session, actor.id, idempotency_key, fingerprint
        )
        if is_replay:
            return cached_body

    try:
        account_map = lock_accounts(session, [account_id])
        customer_account = account_map[account_id]

        is_admin = actor.role == UserRole.ADMIN or str(actor.role) == "admin"
        if not is_admin and customer_account.owner_user_id != actor.id:
            raise UnauthorizedAccountAccessException(
                "You do not have authorization to withdraw from this account."
            )

        clearing_account = get_or_create_system_clearing_account(
            session, currency=customer_account.currency
        )
        lock_accounts(session, [clearing_account.id])

        journal_id = uuid4()
        journal_tx = JournalTransaction(
            id=journal_id,
            actor_user_id=actor.id,
            operation="WITHDRAWAL",
            source_account_id=customer_account.id,
            destination_account_id=clearing_account.id,
            amount_minor=amount_minor,
        )
        session.add(journal_tx)

        # Balanced double-entry: customer account -amount, clearing account +amount (sum = 0)
        _append_ledger_entries(
            session,
            journal_id=journal_id,
            entry_definitions=[
                (customer_account, -amount_minor),
                (clearing_account, amount_minor),
            ],
        )

        response_body = {
            "transaction_id": str(journal_id),
            "operation": "WITHDRAWAL",
            "account_id": str(account_id),
            "amount_minor": amount_minor,
            "currency": customer_account.currency,
            "balance_after": customer_account.balance_minor,
            "description": description,
            "created_at": datetime.now(UTC).isoformat(),
        }

        if idempotency_key and fingerprint:
            idem_record = IdempotencyRequest(
                id=uuid4(),
                actor_user_id=actor.id,
                key=idempotency_key,
                request_fingerprint=fingerprint,
                response_status=200,
                response_body=response_body,
            )
            session.add(idem_record)

        audit_event = AuditEvent(
            id=uuid4(),
            actor_user_id=actor.id,
            account_id=account_id,
            action="WITHDRAWAL",
            outcome="success",
            details=response_body,
        )
        session.add(audit_event)

        session.commit()
        return response_body

    except Exception as exc:
        session.rollback()
        record_audit_event(
            session=session,
            actor_id=actor.id,
            action="WITHDRAWAL",
            outcome="refused",
            account_id=account_id,
            details={"error": str(exc), "amount_minor": amount_minor},
        )
        raise exc


def verify_ledger_hash_chain(session: Session) -> dict[str, Any]:
    entries = session.query(LedgerEntry).order_by(LedgerEntry.entry_sequence.asc()).all()
    if not entries:
        return {
            "verified": True,
            "total_entries": 0,
            "message": "Ledger is empty; genesis intact.",
        }

    expected_prev_hash = "0" * 64
    for idx, entry in enumerate(entries):
        expected_sequence = idx + 1
        if entry.entry_sequence != expected_sequence:
            return {
                "verified": False,
                "broken_at_entry_id": str(entry.id),
                "error": f"Sequence discontinuity: expected {expected_sequence}, found {entry.entry_sequence}.",
            }

        if entry.prev_hash != expected_prev_hash:
            return {
                "verified": False,
                "broken_at_entry_id": str(entry.id),
                "error": f"Hash chain break: prev_hash {entry.prev_hash} does not match expected {expected_prev_hash}.",
            }

        recomputed_hash = compute_entry_hash(
            prev_hash=entry.prev_hash,
            sequence=entry.entry_sequence,
            journal_id=entry.journal_transaction_id,
            account_id=entry.account_id,
            amount_minor=entry.amount_minor,
            balance_after=entry.balance_after_minor,
        )

        if entry.entry_hash != recomputed_hash:
            return {
                "verified": False,
                "broken_at_entry_id": str(entry.id),
                "error": f"Tamper detected: entry_hash {entry.entry_hash} does not match recomputed {recomputed_hash}.",
            }

        expected_prev_hash = entry.entry_hash

    return {
        "verified": True,
        "total_entries": len(entries),
        "latest_sequence": entries[-1].entry_sequence,
        "latest_hash": entries[-1].entry_hash,
        "message": "Cryptographic ledger hash chain successfully verified.",
    }


def reconcile_ledger_balances(session: Session) -> dict[str, Any]:
    accounts = session.query(Account).all()
    discrepancies = []
    total_ledger_sum = (
        session.query(func.coalesce(func.sum(LedgerEntry.amount_minor), 0)).scalar() or 0
    )

    for account in accounts:
        entry_sum = (
            session.query(func.coalesce(func.sum(LedgerEntry.amount_minor), 0))
            .filter(LedgerEntry.account_id == account.id)
            .scalar()
            or 0
        )
        if account.balance_minor != entry_sum:
            discrepancies.append(
                {
                    "account_id": str(account.id),
                    "account_name": account.name,
                    "cached_balance": account.balance_minor,
                    "ledger_sum": entry_sum,
                    "difference": account.balance_minor - entry_sum,
                }
            )

    is_balanced = (len(discrepancies) == 0) and (total_ledger_sum == 0)

    return {
        "is_reconciled": is_balanced,
        "total_system_ledger_sum": total_ledger_sum,
        "accounts_checked": len(accounts),
        "discrepancies_count": len(discrepancies),
        "discrepancies": discrepancies,
    }
