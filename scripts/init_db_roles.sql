-- ==============================================================================
-- BalanceVault Database Roles, Permissions, and Append-Only Hardening
-- ==============================================================================

-- 1. Create Migration Admin Role (DDL Owner)
DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'balancevault_migrator') THEN
        CREATE ROLE balancevault_migrator WITH LOGIN PASSWORD 'change_in_production_migrator';
    END IF;
END $$;

-- 2. Create Application Runtime Role (Least Privilege)
DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'balancevault_app') THEN
        CREATE ROLE balancevault_app WITH LOGIN PASSWORD 'change_in_production_app';
    END IF;
END $$;

-- 3. Grant schema usage
GRANT USAGE, CREATE ON SCHEMA public TO balancevault_migrator;
GRANT USAGE ON SCHEMA public TO balancevault_app;

-- 4. Set ownership to migrator
ALTER SCHEMA public OWNER TO balancevault_migrator;

-- 5. Grant table-level permissions to application runtime role
-- Mutable business entities: SELECT, INSERT, UPDATE (no DELETE)
GRANT SELECT, INSERT, UPDATE ON users TO balancevault_app;
GRANT SELECT, INSERT, UPDATE ON accounts TO balancevault_app;
GRANT SELECT, INSERT, UPDATE ON idempotency_requests TO balancevault_app;

-- Append-only ledger and audit tables: ONLY SELECT, INSERT (NO UPDATE, NO DELETE)
GRANT SELECT, INSERT ON journal_transactions TO balancevault_app;
GRANT SELECT, INSERT ON ledger_entries TO balancevault_app;
GRANT SELECT, INSERT ON audit_events TO balancevault_app;

-- Revoke dangerous permissions explicitly from runtime role
REVOKE UPDATE, DELETE, TRUNCATE ON journal_transactions FROM balancevault_app;
REVOKE UPDATE, DELETE, TRUNCATE ON ledger_entries FROM balancevault_app;
REVOKE UPDATE, DELETE, TRUNCATE ON audit_events FROM balancevault_app;

-- 6. PostgreSQL Append-Only Enforcement Triggers (Defense in Depth)
-- Explicitly rejects direct UPDATE, DELETE, and TRUNCATE attempts with an unmissable exception
CREATE OR REPLACE FUNCTION forbid_ledger_mutation()
RETURNS TRIGGER AS $$
BEGIN
    RAISE EXCEPTION 'Table % is strictly append-only. Direct UPDATE, DELETE, and TRUNCATE operations are prohibited.', TG_TABLE_NAME
        USING ERRCODE = '55000';
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_prevent_ledger_entries_mutation ON ledger_entries;
CREATE TRIGGER trg_prevent_ledger_entries_mutation
    BEFORE UPDATE OR DELETE ON ledger_entries
    FOR EACH ROW EXECUTE FUNCTION forbid_ledger_mutation();

DROP TRIGGER IF EXISTS trg_prevent_ledger_entries_truncate ON ledger_entries;
CREATE TRIGGER trg_prevent_ledger_entries_truncate
    BEFORE TRUNCATE ON ledger_entries
    FOR EACH STATEMENT EXECUTE FUNCTION forbid_ledger_mutation();

DROP TRIGGER IF EXISTS trg_prevent_journal_transactions_mutation ON journal_transactions;
CREATE TRIGGER trg_prevent_journal_transactions_mutation
    BEFORE UPDATE OR DELETE ON journal_transactions
    FOR EACH ROW EXECUTE FUNCTION forbid_ledger_mutation();

DROP TRIGGER IF EXISTS trg_prevent_journal_transactions_truncate ON journal_transactions;
CREATE TRIGGER trg_prevent_journal_transactions_truncate
    BEFORE TRUNCATE ON journal_transactions
    FOR EACH STATEMENT EXECUTE FUNCTION forbid_ledger_mutation();

DROP TRIGGER IF EXISTS trg_prevent_audit_events_mutation ON audit_events;
CREATE TRIGGER trg_prevent_audit_events_mutation
    BEFORE UPDATE OR DELETE ON audit_events
    FOR EACH ROW EXECUTE FUNCTION forbid_ledger_mutation();

DROP TRIGGER IF EXISTS trg_prevent_audit_events_truncate ON audit_events;
CREATE TRIGGER trg_prevent_audit_events_truncate
    BEFORE TRUNCATE ON audit_events
    FOR EACH STATEMENT EXECUTE FUNCTION forbid_ledger_mutation();

