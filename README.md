# Hospital Management System

Flask, SQLAlchemy and SQLite application with reception, triage, doctor, pharmacy, billing, inpatient and administration portals. Patient attachments and photographs are stored privately. Demo accounts are never created during normal startup.

## Development

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
npm ci
npm run build:css
flask --app 'app:create_app()' db-upgrade
flask --app 'app:create_app()' create-admin
python app.py
```

The development server binds to `127.0.0.1:5000`. A stable development signing key is created in `instance/.secret_key`; preserve it across restarts. The initial administrator must change their password and enroll in 2FA when policy requires it. Configure role permissions through administration, including the new laboratory result, consultation collection and telephony permissions.

For an explicitly disposable demonstration environment, set `HMS_ENABLE_DEMO_LOGIN=true` and run `flask --app 'app:create_app()' seed-demo`. Demo seeding is forbidden in production. Existing accounts are not reactivated or reassigned by seeding.

## Production

Set `HMS_ENV=production`, a long random `SECRET_KEY`, and `DATABASE_URL=sqlite:////absolute/path/hms.db`. Production startup does not migrate or seed automatically. Back up the database, signing key and private uploads before applying migrations. The supplied migrations support SQLite and record completed revisions; failures stop the upgrade.

```bash
flask --app 'app:create_app()' db-upgrade
flask --app 'app:create_app()' migrate-private-files
gunicorn --bind 127.0.0.1:8000 --workers 2 'app:create_app()'
```

Use an HTTPS reverse proxy; production session cookies require HTTPS. Keep `instance/private` outside any public document root. Legacy patient file URLs under `/static/uploads/` are blocked; authenticated routes serve them during migration. Do not serve the entire repository as static content. Back up SQLite using its backup API or stop application writes before copying the database.

Configure integrations through environment variables:

- `PAYSTACK_SECRET_KEY`: payment provider secret; unset configuration fails closed.
- `AFRICASTALKING_USERNAME`, `AFRICASTALKING_API_KEY`: live SMS credentials.
- `HMS_SMS_LIVE=true`: default live delivery; simulations are labeled and cannot verify phone ownership.
- `HMS_BASE_URL`: canonical public origin used for onboarding links.

Configure the provider callback to `https://your-domain/webhooks/paystack`. [Paystack webhooks](https://paystack.com/docs/payments/webhooks/) are authenticated with HMAC SHA512 and settled idempotently, even when the browser closes.

Credential text files are ignored and no longer tracked. Previously committed credentials remain in Git history and must be rotated with the providers. Never put live keys in tests. Insurer approvals require a recorded provider authorization; there is no automatic insurer integration. Paid-invoice refunds require a reversal workflow and are rejected instead of silently altering paid balances. Deposits are not treated as payments unless a payment record exists.

## Verification

```bash
source venv/bin/activate
python -m unittest discover -s tests -v
python test_security_and_docs.py
npm run build:css
```

Regression tests use temporary SQLite databases and mocked providers. The historical test entry point now runs this isolated suite and cannot mutate `hms.db` or contact live gateways. CSRF remains enabled in normal application operation.
