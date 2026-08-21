from datetime import datetime
from .base import db

class SecuritySetting(db.Model):
    """
    Singleton system-wide security policies managed by Hospital Administrators.
    """
    __tablename__ = 'security_settings'

    id = db.Column(db.Integer, primary_key=True)
    
    # 2FA / MFA Policy
    require_2fa_for_all = db.Column(db.Boolean, default=False)
    require_2fa_for_admin_doctor = db.Column(db.Boolean, default=True)
    
    # Session Management
    session_timeout_minutes = db.Column(db.Integer, default=30)  # Inactivity sliding timeout (10 - 120 mins)
    enforce_single_session = db.Column(db.Boolean, default=False)
    
    # Brute Force Protection & Password Policy
    max_failed_attempts = db.Column(db.Integer, default=5)       # Lock account after N failed logins
    lockout_duration_minutes = db.Column(db.Integer, default=15) # Lock duration in minutes
    password_min_length = db.Column(db.Integer, default=8)
    require_special_chars = db.Column(db.Boolean, default=True)
    password_expiry_days = db.Column(db.Integer, default=90)     # 0 for never

    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    updated_by = db.Column(db.String(120), default='System Administrator')

    @classmethod
    def get_settings(cls):
        settings = cls.query.first()
        if not settings:
            settings = cls()
            db.session.add(settings)
            db.session.commit()
        return settings


class Permission(db.Model):
    """
    Canonical system permissions catalog.
    """
    __tablename__ = 'permissions'

    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(80), unique=True, nullable=False, index=True)  # e.g. 'patient:register', 'clinical:prescribe'
    name = db.Column(db.String(120), nullable=False)
    category = db.Column(db.String(50), nullable=False)  # Patients, Clinical, Pharmacy, Billing, Inpatient, Admin, Documents
    description = db.Column(db.String(255), nullable=True)

    def __repr__(self):
        return f"<Permission {self.code}>"


class RolePermission(db.Model):
    """
    Role to Permission mapping matrix.
    """
    __tablename__ = 'role_permissions'

    id = db.Column(db.Integer, primary_key=True)
    role = db.Column(db.String(50), nullable=False, index=True)  # admin, doctor, nurse, pharmacist, cashier, receptionist
    permission_code = db.Column(db.String(80), db.ForeignKey('permissions.code', ondelete='CASCADE'), nullable=False)
    
    permission = db.relationship('Permission', foreign_keys=[permission_code])

    __table_args__ = (
        db.UniqueConstraint('role', 'permission_code', name='uq_role_permission'),
    )

    def __repr__(self):
        return f"<RolePermission {self.role} -> {self.permission_code}>"
