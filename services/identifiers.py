from sqlalchemy.dialects.sqlite import insert
from sqlalchemy import func
from models.identifier import IdentifierCounter


def next_sequence(session, column, prefix, scope=None, filters=()):
    """Allocate a sequence atomically in the caller's transaction, preserving existing IDs."""
    table = IdentifierCounter.__table__
    key = column.table.name + ':' + (scope or prefix)
    values = session.query(column).filter(column.like(prefix + '%'), *filters).all()
    maximum = max((int(value[len(prefix):]) for (value,) in values
                   if value and value[len(prefix):].isdigit()), default=0)
    statement = insert(table).values(key=key, value=maximum + 1)
    statement = statement.on_conflict_do_update(
        index_elements=[table.c.key], set_={'value': func.max(table.c.value + 1, maximum + 1)}
    ).returning(table.c.value)
    return session.execute(statement).scalar_one()
