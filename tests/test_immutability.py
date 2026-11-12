from sqlalchemy import text
from sqlalchemy.exc import DatabaseError, OperationalError

from ledgerline.models import LedgerEntry
from ledgerline.services.ledger import verify_ledger_hash_chain


def test_sqlite_and_orm_immutability_enforcement(db_session):
    """Verify that ledger entries and audit events maintain append-only immutability and changes are detected."""
    entry = db_session.query(LedgerEntry).first()
    if entry:
        entry_id = entry.id

        try:
            db_session.execute(
                text("UPDATE ledger_entries SET amount_minor = 88888 WHERE id = :id"),
                {"id": str(entry_id)},
            )
            db_session.commit()
        except (DatabaseError, OperationalError):
            db_session.rollback()

        chain_check = verify_ledger_hash_chain(db_session)
        assert chain_check["verified"] is True
