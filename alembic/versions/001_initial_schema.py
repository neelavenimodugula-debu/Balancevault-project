"""Initial schema with double-entry ledger, idempotency, and hash chain

Revision ID: 001_initial_schema
Revises: 
Create Date: 2026-11-12 20:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '001_initial_schema'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Users table
    op.create_table(
        'users',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('email', sa.String(length=320), nullable=False),
        sa.Column('password_hash', sa.String(length=255), nullable=False),
        sa.Column('role', sa.String(length=24), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.text('true')),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_users_email'), 'users', ['email'], unique=True)

    # Accounts table
    op.create_table(
        'accounts',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('owner_user_id', sa.Uuid(), nullable=True),
        sa.Column('name', sa.String(length=120), nullable=False),
        sa.Column('currency', sa.String(length=3), nullable=False, server_default='INR'),
        sa.Column('balance_minor', sa.BigInteger(), nullable=False, server_default='0'),
        sa.Column('is_system_account', sa.Boolean(), nullable=False, server_default=sa.text('false')),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(['owner_user_id'], ['users.id'], ondelete='RESTRICT'),
        sa.PrimaryKeyConstraint('id'),
        sa.CheckConstraint('is_system_account OR balance_minor >= 0', name='nonnegative_balance'),
        sa.CheckConstraint('is_system_account OR owner_user_id IS NOT NULL', name='customer_account_has_owner')
    )
    op.create_index(op.f('ix_accounts_owner_user_id'), 'accounts', ['owner_user_id'], unique=False)

    # Journal transactions table
    op.create_table(
        'journal_transactions',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('actor_user_id', sa.Uuid(), nullable=False),
        sa.Column('operation', sa.String(length=24), nullable=False),
        sa.Column('source_account_id', sa.Uuid(), nullable=True),
        sa.Column('destination_account_id', sa.Uuid(), nullable=True),
        sa.Column('amount_minor', sa.BigInteger(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(['actor_user_id'], ['users.id'], ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['source_account_id'], ['accounts.id'], ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['destination_account_id'], ['accounts.id'], ondelete='RESTRICT'),
        sa.PrimaryKeyConstraint('id')
    )

    # Ledger entries table with hash-chaining fields
    op.create_table(
        'ledger_entries',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('journal_transaction_id', sa.Uuid(), nullable=False),
        sa.Column('account_id', sa.Uuid(), nullable=False),
        sa.Column('amount_minor', sa.BigInteger(), nullable=False),
        sa.Column('balance_after_minor', sa.BigInteger(), nullable=False),
        sa.Column('entry_sequence', sa.BigInteger(), nullable=False, server_default='0'),
        sa.Column('prev_hash', sa.String(length=64), nullable=False, server_default='0' * 64),
        sa.Column('entry_hash', sa.String(length=64), nullable=False, server_default=''),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(['account_id'], ['accounts.id'], ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['journal_transaction_id'], ['journal_transactions.id'], ondelete='RESTRICT'),
        sa.PrimaryKeyConstraint('id'),
        sa.CheckConstraint('amount_minor <> 0', name='nonzero_entry'),
        sa.UniqueConstraint('journal_transaction_id', 'account_id', name='one_entry_per_account')
    )
    op.create_index(op.f('ix_ledger_entries_account_id'), 'ledger_entries', ['account_id'], unique=False)
    op.create_index(op.f('ix_ledger_entries_journal_transaction_id'), 'ledger_entries', ['journal_transaction_id'], unique=False)
    op.create_index(op.f('ix_ledger_entries_entry_sequence'), 'ledger_entries', ['entry_sequence'], unique=False)

    # Idempotency requests table
    op.create_table(
        'idempotency_requests',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('actor_user_id', sa.Uuid(), nullable=False),
        sa.Column('key', sa.String(length=128), nullable=False),
        sa.Column('request_fingerprint', sa.String(length=64), nullable=False),
        sa.Column('response_status', sa.Integer(), nullable=True),
        sa.Column('response_body', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(['actor_user_id'], ['users.id'], ondelete='RESTRICT'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('actor_user_id', 'key', name='unique_actor_idempotency_key')
    )

    # Audit events table
    op.create_table(
        'audit_events',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('actor_user_id', sa.Uuid(), nullable=True),
        sa.Column('account_id', sa.Uuid(), nullable=True),
        sa.Column('action', sa.String(length=48), nullable=False),
        sa.Column('outcome', sa.String(length=24), nullable=False),
        sa.Column('details', sa.JSON(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(['account_id'], ['accounts.id'], ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['actor_user_id'], ['users.id'], ondelete='RESTRICT'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_audit_events_account_id'), 'audit_events', ['account_id'], unique=False)


def downgrade() -> None:
    op.drop_table('audit_events')
    op.drop_table('idempotency_requests')
    op.drop_table('ledger_entries')
    op.drop_table('journal_transactions')
    op.drop_table('accounts')
    op.drop_table('users')

