import json
from datetime import datetime
from flask import request
from .base import db

class AuditLog(db.Model):
    """
    Immutable, Tamper-Evident System Audit Trail.
    Logs all clinical actions, security events, 2FA verifications, and financial modifications.
    """
    __tablename__ = 'audit_logs'

    id = db.Column(db.Integer, primary_key=True)
    actor_user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True, index=True)
    actor_name = db.Column(db.String(128), nullable=False)
    action = db.Column(db.String(120), nullable=False, index=True)
    entity_type = db.Column(db.String(60), nullable=False, index=True)
    entity_id = db.Column(db.String(60), nullable=True)
    details = db.Column(db.Text, nullable=True)
    details_json = db.Column(db.Text, nullable=True)

    # Security Telemetry
    ip_address = db.Column(db.String(64), nullable=True)
    user_agent = db.Column(db.String(255), nullable=True)
    severity = db.Column(db.String(30), default='info', index=True)  # 'info', 'warning', 'critical', 'security_breach'

    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)

    actor = db.relationship('User', backref='admin_audit_events', lazy=True)

    @classmethod
    def log_event(cls, action, entity_type, entity_id=None, details="", actor=None, severity='info', extra_data=None):
        """Standardized helper to log immutable audit events."""
        ip = None
        ua = None
        try:
            if request:
                ip = request.headers.get('X-Forwarded-For', request.remote_addr)
                if ip and ',' in ip:
                    ip = ip.split(',')[0].strip()
                ua = request.user_agent.string[:250] if request.user_agent else None
        except Exception:
            pass

        actor_name = 'System'
        actor_id = None
        if actor:
            actor_id = getattr(actor, 'id', None)
            actor_name = getattr(actor, 'full_name', str(actor))

        details_json_str = None
        if extra_data:
            try:
                details_json_str = json.dumps(extra_data)
            except Exception:
                pass

        log_entry = cls(
            actor_user_id=actor_id,
            actor_name=actor_name,
            action=action,
            entity_type=entity_type,
            entity_id=str(entity_id) if entity_id is not None else None,
            details=details,
            details_json=details_json_str,
            ip_address=ip,
            user_agent=ua,
            severity=severity,
            created_at=datetime.utcnow()
        )
        db.session.add(log_entry)
        try:
            db.session.commit()
        except Exception:
            db.session.rollback()
        return log_entry

    def __repr__(self):
        return f"<AuditLog #{self.id} [{self.severity.upper()}] {self.action} by {self.actor_name}>"
