from .base import db


class IdentifierCounter(db.Model):
    """Transactional counters serialize identifier allocation between workers."""
    __tablename__ = 'identifier_counters'
    key = db.Column(db.String(160), primary_key=True)
    value = db.Column(db.Integer, nullable=False)
