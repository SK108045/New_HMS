from datetime import datetime
from werkzeug.security import generate_password_hash, check_password_hash
from .base import db

class User(db.Model):
    __tablename__ = 'users'

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(64), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(256), nullable=False)
    full_name = db.Column(db.String(128), nullable=False)
    staff_id = db.Column(db.String(32), unique=True, nullable=False)
    role = db.Column(db.String(32), nullable=False)  # 'receptionist', 'nurse', 'doctor', 'pharmacist', 'cashier', 'admin'
    portal = db.Column(db.String(32), nullable=False)  # 'reception', 'triage', 'doctor', 'pharmacy', 'billing', 'all'
    department = db.Column(db.String(64), nullable=False)
    email = db.Column(db.String(128), nullable=True)
    phone = db.Column(db.String(32), nullable=True)
    status = db.Column(db.String(16), default='active')  # 'active', 'inactive', 'suspended'
    last_login = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    def can_access_portal(self, portal_name):
        if self.status != 'active':
            return False
        if self.role == 'admin' or self.portal == 'all':
            return True
        return self.portal == portal_name

    def to_dict(self):
        return {
            'id': self.id,
            'username': self.username,
            'full_name': self.full_name,
            'staff_id': self.staff_id,
            'role': self.role,
            'portal': self.portal,
            'department': self.department,
            'status': self.status
        }
