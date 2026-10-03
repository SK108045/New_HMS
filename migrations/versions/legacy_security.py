"""0001: replace the old silent startup ALTER TABLE helper."""
from migrations import add_missing_columns


def upgrade(connection):
    add_missing_columns(connection, 'users', [
        ('is_2fa_enabled', 'BOOLEAN NOT NULL DEFAULT 0'), ('totp_secret', 'VARCHAR(64)'),
        ('backup_codes_json', 'TEXT'), ('failed_login_attempts', 'INTEGER NOT NULL DEFAULT 0'),
        ('locked_until', 'DATETIME'), ('password_changed_at', 'DATETIME'),
        ('force_password_change', 'BOOLEAN NOT NULL DEFAULT 0'), ('last_activity_at', 'DATETIME'),
        ('custom_permissions_json', 'TEXT'),
    ])
    add_missing_columns(connection, 'audit_logs', [
        ('ip_address', 'VARCHAR(64)'), ('user_agent', 'VARCHAR(255)'),
        ('severity', "VARCHAR(30) DEFAULT 'info'"), ('details_json', 'TEXT'),
    ])
