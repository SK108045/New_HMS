from sqlalchemy import text
from models import db


def begin_write():
    """Serialize SQLite read/validate/write workflows before loading mutable state.

    The lock is released by the caller's commit/rollback. Provider network calls
    belong before this boundary, so they do not block clinical database writes.
    """
    connection = db.session.connection()
    if connection.dialect.name == 'sqlite':
        driver = connection.connection.driver_connection
        if not driver.in_transaction:
            connection.execute(text('BEGIN IMMEDIATE'))
            # Middleware may have cached account/authorization state before the lock.
            if not (db.session.new or db.session.dirty or db.session.deleted):
                db.session.expire_all()
