"""0002: patient verification and integrity controls (additive, no data deletion)."""
from migrations import add_missing_columns


def upgrade(connection):
    add_missing_columns(connection, 'patient_otps', [
        ('otp_hash', 'VARCHAR(256)'), ('failed_attempts', 'INTEGER NOT NULL DEFAULT 0'),
    ])
    from sqlalchemy import inspect, text
    if inspect(connection).has_table('patient_otps'):
        connection.execute(text("UPDATE patient_otps SET expires_at=CURRENT_TIMESTAMP, otp_code='' WHERE otp_hash IS NULL"))
    add_missing_columns(connection, 'admissions', [('initial_bed_rate', 'FLOAT')])
    add_missing_columns(connection, 'bed_transfers', [('from_bed_rate', 'FLOAT'), ('to_bed_rate', 'FLOAT')])
    add_missing_columns(connection, 'payments', [('idempotency_key', 'VARCHAR(160)')])
    if inspect(connection).has_table('payments'):
        connection.execute(text('CREATE UNIQUE INDEX IF NOT EXISTS uq_payment_idempotency_key ON payments (idempotency_key)'))
    add_missing_columns(connection, 'users', [('auth_version', 'INTEGER NOT NULL DEFAULT 0'), ('active_session_token', 'VARCHAR(64)')])
    for table in ('credit_notes', 'fee_waivers'):
        add_missing_columns(connection, table, [('requested_by_id', 'INTEGER REFERENCES users(id)'), ('approved_by_id', 'INTEGER REFERENCES users(id)')])
