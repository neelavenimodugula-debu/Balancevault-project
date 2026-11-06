from sqlalchemy import BigInteger

from ledgerline.database import Base
from ledgerline.models import Account, JournalTransaction, LedgerEntry


def test_ledger_schema_uses_integer_minor_units() -> None:
    assert isinstance(Account.__table__.c.balance_minor.type, BigInteger)
    assert isinstance(LedgerEntry.__table__.c.amount_minor.type, BigInteger)
    assert isinstance(LedgerEntry.__table__.c.balance_after_minor.type, BigInteger)


def test_schema_includes_audit_and_idempotency_records() -> None:
    assert {"audit_events", "idempotency_requests"} <= set(Base.metadata.tables)
    assert JournalTransaction.__table__.c.amount_minor is not None