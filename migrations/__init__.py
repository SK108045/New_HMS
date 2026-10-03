"""Recorded, additive SQLite migrations for existing HMS installations."""
from datetime import datetime
from sqlalchemy import inspect, text
from models import db

REVISIONS = ('0001_legacy_security', '0002_integrity_controls')


def add_missing_columns(connection, table_name, columns):
    inspector = inspect(connection)
    if not inspector.has_table(table_name):
        return
    existing = {column['name'] for column in inspector.get_columns(table_name)}
    for name, declaration in columns:
        if name not in existing:
            connection.execute(text(f'ALTER TABLE "{table_name}" ADD COLUMN "{name}" {declaration}'))


def upgrade_database():
    """Each revision commits atomically; migration failures are never swallowed."""
    if db.engine.dialect.name != 'sqlite':
        raise RuntimeError('The provided migrations support SQLite. Configure reviewed migrations before using another database.')
    with db.engine.begin() as connection:
        connection.execute(text('CREATE TABLE IF NOT EXISTS schema_migrations '
                                '(revision VARCHAR(80) PRIMARY KEY, applied_at DATETIME NOT NULL)'))
    from migrations.versions import legacy_security, integrity_controls
    modules = (legacy_security, integrity_controls)
    for revision, module in zip(REVISIONS, modules):
        with db.engine.begin() as connection:
            connection.exec_driver_sql('BEGIN IMMEDIATE')
            applied = connection.execute(text('SELECT 1 FROM schema_migrations WHERE revision=:revision'),
                                         {'revision': revision}).first()
            if applied:
                continue
            module.upgrade(connection)
            db.metadata.create_all(bind=connection)
            connection.execute(text('INSERT INTO schema_migrations (revision, applied_at) VALUES (:revision, :now)'),
                               {'revision': revision, 'now': datetime.utcnow()})
    # Register new model tables on fresh databases without changing existing clinical rows.
    db.create_all()
