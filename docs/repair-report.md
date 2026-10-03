# Codebase repair report — 3 October 2026

The lead Codex agent integrated and reviewed the changes produced with Gemini 3.8 Flash High workers covering clinical workflows, authentication/security, and billing. Subsequent independent Gemini reviews identified additional concurrency and session invalidation defects, which were corrected and verified locally. The workers completed their reviews; their stream logs remain in `/tmp/new_hms_gemini_live_{architecture,security,billing}.jsonl`.

## Changes

- Laboratory inbox reads no longer fabricate results. Explicit result entry records the authenticated author and timestamp; review requires completed results. Operational dashboard counts come from stored records.
- Dispensing validates exact medication identity and strength, prescribed quantities, batch ownership, expiry, quarantine status, and available stock. Atomic transactions prevent duplicate dispensing and partial inventory changes.
- Admission validates beds and wards and falls back to recorded next-of-kin contacts. Admission, transfer, and discharge operations serialize competing SQLite writes. Bed transfers retain rate snapshots; discharge bills each stay segment and does not subtract deposits lacking payment records.
- Paystack consultation charges use the configured server tariff and a durable authorization record. Settlement checks provider reference, amount, currency, and patient binding and creates one linked invoice, receipt, and queue entry. Signed webhooks allow completion when the browser closes. Cash and POS receipts have persisted idempotency keys.
- POS balances include partial invoices and count unlinked charges once. Browsing a folio does not create an invoice or shift. Invoice staging is an explicit POST operation. Checkout preserves approved adjustments and rejects unapproved discounts and overpayments.
- Waivers and credit notes require independent administrator approval, authenticate the requester and approver, permit one state transition, and reconcile tax, discounts, payments, and balances. Reports use recorded invoice tax rather than inventing a flat tax liability.
- Operational and authentication endpoints enforce account status, lockouts, password changes, session generations, mandatory 2FA, and granular permissions. Password and 2FA changes invalidate stale sessions and onboarding links. Pending challenges expire and cannot reveal existing authenticator secrets. Recovery codes work with normalized input and are consumed once under concurrent sign-in.
- Patient documents and photographs use authenticated routes and private storage. Public `/static/uploads/` access is blocked. New uploads validate content; photos are re-encoded to remove metadata and trailing content. Document printing validates the patient/document association.
- SMS configuration fails closed for live requests. Simulations are identified explicitly and cannot verify phone ownership. OTPs are cryptographically generated, hashed, redacted from logs, time limited, attempt limited, and consumed once. Gateway calls release SQLite write locks first.
- Audit records join the business transaction instead of committing unrelated pending changes. Startup preserves staff account state and configured permissions. Demo seeding is explicit and development only.
- Recorded SQLite migrations replace silently ignored schema alterations. Identifier counters allocate transactional sequences. Development signing keys persist across restarts; production requires a configured secret. Dependencies, environment examples, build commands, and setup instructions were updated. The development server defaults to localhost with debug disabled.

## Verification and local migration

- 60 isolated regression tests passed. They use temporary SQLite databases, mocked providers, and blocked external network connections.
- Concurrent request tests cover provider settlement, medicine dispensing, admission to different beds, discharge, and recovery-code consumption. Callback tests cover signature tampering, amount/currency mismatches, CSRF exemption, and replay.
- All 83 Jinja templates compiled; the Tailwind CSS build and Python dependency checks passed.
- Migrations were applied twice to a copy of the existing database before local application. Existing contents of 36 user/clinical tables were unchanged; existing role grants were preserved. SQLite integrity and foreign-key checks passed.
- Database and legacy media backup: `backups/20261003T142433Z/`. The local database was upgraded and 48 legacy files moved into `instance/private/`. Existing stored file references remain usable. No demo data was seeded.

## Public repository checks

The proposed repository tree passed Gitleaks 8.30.1 with zero findings. Test credentials use clearly fake values rather than provider token formats. A separate exact-match scan found no copies of previously committed Paystack or SMS keys in the proposed files. Credential text files, private uploads, SQLite data, local signing keys, backups, and environment variants are excluded from publication. Historical Git commits still require credential rotation; no history rewrite was performed.

## Integration requirements and remaining limits

Configure replacement Paystack and Africa's Talking credentials through environment variables. Previously committed keys remain in Git history and require rotation with the providers; this repair did not rewrite Git history or rotate provider credentials. Configure Paystack's webhook URL as described in the README. Live provider delivery and charges were not exercised.

Insurer authorization is recorded manually; there is no insurer API integration. Paid-invoice refunds are rejected until a payment reversal workflow exists. Historical bed rates missing from older transfer records cannot be reconstructed; those records use the available legacy rates. The migration does not automatically remove previously fabricated clinical results because real results cannot be distinguished safely without clinical review.
