# Threat model and current status

This document tracks how LedgerLine could lose, create, misroute, or conceal money. Status is explicit: the current Day 1 code has no accounts or money-moving routes, so none of the integrity controls below should be read as implemented yet.

## Assets and trust boundaries

- Account balances, journal transactions, postings, idempotency results, and audit events.
- User identity, role, account ownership, and authorization decisions.
- API requests may be duplicated, reordered, interrupted, or sent concurrently.
- PostgreSQL is trusted to provide transaction and row-lock semantics. The application process is not trusted to serialize concurrent requests by itself.
- Database administrators and infrastructure operators remain privileged; application-level append-only rules cannot prevent a database owner from rewriting the database and its backups.

## Threats and mitigations

| Threat | Planned control | Status and test |
| --- | --- | --- |
| Two withdrawals both observe the same available funds | Lock account rows with PostgreSQL `SELECT ... FOR UPDATE`, check and debit under the same transaction | Open. Add a real concurrent withdrawal test with separate connections; assert one success, one refusal, and a nonnegative final balance. |
| Transfer debit commits but credit does not | Insert both sides of the double-entry journal and update projections in one database transaction | Open. Inject a failure between writes and assert rollback leaves balances and postings unchanged. |
| Same request is retried or submitted concurrently | Unique idempotency key scoped to actor, payload fingerprint, and saved original result | Open. Replay sequentially and concurrently; assert one journal transaction and the same response. Different payload with same key must be rejected. |
| Transfer source belongs to another user | Check role and ownership server-side inside the transfer service on every request | Open. Attempt cross-user source and destination access and verify no money or postings change. |
| Transfer deadlock from opposite account ordering | Lock all involved accounts by stable account ID order | Open. Add opposing-transfer concurrency coverage and bounded retry/error handling if PostgreSQL reports a deadlock. |
| Ledger row is edited or deleted to conceal a payment | Runtime DB role receives no update/delete on posted entries; add database append-only enforcement and separate migration-owner credentials | Open. Test update/delete through the runtime role. Database-owner compromise remains a documented residual risk. |
| Cached balance drifts from ledger | Update projection in the same transaction; run a ledger-to-balance reconciliation check | Open. Add invariant tests and a reconciliation command/test. |
| Refused attempt disappears when the money transaction rolls back | Record the refusal in a separate audit transaction after the failed operation transaction is rolled back | Open. Verify insufficient-funds and authorization refusals remain visible without creating postings. |
| Float rounding creates or destroys minor units | Represent currency as integer minor units and validate positive bounded amounts | Planned for Day 2. Add input validation and conservation tests. |
| Idempotency key is reused for a different operation | Persist and compare a canonical request fingerprint; return conflict on mismatch | Open. Include payload mismatch test. |
| External funding/withdrawal breaks conservation | Post the other side to a controlled external clearing account and record the actor | Open. Test total ledger debits equal credits across internal and external movement. |
| Secret leakage enables unauthorized activity | Use environment variables/secrets manager; ignore `.env`; never put real credentials in README or Git | Partially addressed: `.env` is ignored. No credentials or deployment secrets exist yet. |

## Deliberate scope limits

The first release is single-currency, has no overdraft, and has no automatic AI-initiated movement. Holds, scheduled payments, multi-currency FX, and automated reversals are out of scope unless the core invariants and attack tests are complete first. Admin adjustments must be explicit, attributed, and represented as balanced ledger transactions rather than edits to balances.

## Review checklist

Before release, run the money-race, idempotency-replay, cross-account authorization, partial-failure, and ledger-tampering tests against PostgreSQL. Repeat those checks against the deployed URL. Update this document whenever an implementation or test changes the status of a risk; do not mark a mitigation closed based only on a code review.