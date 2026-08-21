import json
import secrets
from datetime import datetime, timedelta
import pyotp
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
    portal = db.Column(db.String(32), nullable=False)  # 'reception', 'triage', 'doctor', 'pharmacy', 'billing', 'inpatient', 'all'
    department = db.Column(db.String(64), nullable=False)
    email = db.Column(db.String(128), nullable=True)
    phone = db.Column(db.String(32), nullable=True)
    status = db.Column(db.String(16), default='active')  # 'active', 'inactive', 'suspended'
    last_login = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # 2FA / Google Authenticator Fields
    is_2fa_enabled = db.Column(db.Boolean, default=False, nullable=False)
    totp_secret = db.Column(db.String(64), nullable=True)  # Base32 secret for Google Authenticator
    backup_codes_json = db.Column(db.Text, nullable=True)  # JSON array of hashed emergency codes

    # Brute Force Account Lockout & Security
    failed_login_attempts = db.Column(db.Integer, default=0, nullable=False)
    locked_until = db.Column(db.DateTime, nullable=True)
    password_changed_at = db.Column(db.DateTime, default=datetime.utcnow)
    force_password_change = db.Column(db.Boolean, default=False, nullable=False)
    last_activity_at = db.Column(db.DateTime, nullable=True)

    # Granular Custom Permissions Override (JSON array of permission codes)
    custom_permissions_json = db.Column(db.Text, nullable=True)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)
        self.password_changed_at = datetime.utcnow()
        self.force_password_change = False

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    # ==================== 2FA / TOTP METHODS ====================
    def generate_totp_secret(self, force_new=False):
        """Generate a standard 32-character base32 secret for Google Authenticator and persist it."""
        if not self.totp_secret or force_new:
            self.totp_secret = pyotp.random_base32()
            try:
                db.session.commit()
            except Exception:
                db.session.rollback()
        return self.totp_secret

    def get_totp_uri(self, issuer="Apex Regional Medical Center"):
        """Get standard otpauth:// URI for QR code generation."""
        if not self.totp_secret:
            self.generate_totp_secret()
        totp = pyotp.TOTP(self.totp_secret)
        return totp.provisioning_uri(name=f"{self.username} ({self.staff_id})", issuer_name=issuer)

    def verify_totp(self, token: str) -> bool:
        """Verify 6-digit TOTP token with Google Authenticator (with valid window drift)."""
        if not self.totp_secret or not token:
            return False
        clean_token = str(token).strip().replace(' ', '').replace('-', '')
        totp = pyotp.TOTP(self.totp_secret)
        # valid_window=2 allows current 30s period +- 2 periods (60s drift tolerance)
        return totp.verify(clean_token, valid_window=2)

    def generate_backup_codes(self, count=8) -> list:
        """Generate 8 single-use emergency backup codes and store their hashes."""
        raw_codes = []
        hashed_codes = []
        for _ in range(count):
            # Format: XXXX-XXXX
            code = f"{secrets.token_hex(2).upper()}-{secrets.token_hex(2).upper()}"
            raw_codes.append(code)
            hashed_codes.append(generate_password_hash(code))
        self.backup_codes_json = json.dumps(hashed_codes)
        return raw_codes

    def get_2fa_onboarding_token(self, secret_key: str) -> str:
        """Generate a cryptographically signed timed token for employee 2FA onboarding."""
        from itsdangerous import URLSafeTimedSerializer
        serializer = URLSafeTimedSerializer(secret_key)
        return serializer.dumps({'user_id': self.id, 'username': self.username}, salt='2fa-onboarding-token')

    @classmethod
    def verify_2fa_onboarding_token(cls, token: str, secret_key: str, max_age: int = 172800):
        """Verify an onboarding token and return the matching User instance (valid for 48 hours)."""
        from itsdangerous import URLSafeTimedSerializer, SignatureExpired, BadSignature
        serializer = URLSafeTimedSerializer(secret_key)
        try:
            data = serializer.loads(token, salt='2fa-onboarding-token', max_age=max_age)
            user_id = data.get('user_id')
            return cls.query.get(user_id)
        except (SignatureExpired, BadSignature, Exception):
            return None

    def verify_backup_code(self, code: str) -> bool:
        """Verify and consume a one-time emergency backup recovery code."""
        if not self.backup_codes_json or not code:
            return False
        try:
            hashed_codes = json.loads(self.backup_codes_json)
        except Exception:
            return False

        clean_code = str(code).strip().upper()
        for idx, h_code in enumerate(hashed_codes):
            if check_password_hash(h_code, clean_code):
                # Consume used code
                hashed_codes.pop(idx)
                self.backup_codes_json = json.dumps(hashed_codes)
                db.session.commit()
                return True
        return False

    # ==================== ACCOUNT LOCKOUT METHODS ====================
    def is_locked(self) -> bool:
        """Check if account is currently locked due to brute force attempts."""
        if self.locked_until and self.locked_until > datetime.utcnow():
            return True
        return False

    def record_failed_login(self, max_attempts=5, lockout_minutes=15):
        """Increment failed attempts and lock if max reached."""
        self.failed_login_attempts += 1
        if self.failed_login_attempts >= max_attempts:
            self.locked_until = datetime.utcnow() + timedelta(minutes=lockout_minutes)
        db.session.commit()

    def reset_failed_logins(self):
        """Reset failed count and clear lock on successful authentication."""
        self.failed_login_attempts = 0
        self.locked_until = None
        db.session.commit()

    # ==================== RBAC & PERMISSION METHODS ====================
    def can_access_portal(self, portal_name):
        if self.status != 'active':
            return False
        if self.role == 'admin' or self.portal == 'all':
            return True
        return self.portal == portal_name

    def has_permission(self, permission_code: str) -> bool:
        """Check if user has a specific granular permission."""
        if self.status != 'active':
            return False
        # Admins have full system access
        if self.role == 'admin':
            return True

        # Check explicit custom user permission overrides if present
        if self.custom_permissions_json:
            try:
                custom_perms = json.loads(self.custom_permissions_json)
                if permission_code in custom_perms:
                    return True
            except Exception:
                pass

        # Check Role Permissions matrix from database
        from .security import RolePermission
        has_perm = RolePermission.query.filter_by(
            role=self.role,
            permission_code=permission_code
        ).first()
        return has_perm is not None

    def get_all_permissions(self) -> list:
        """Return list of all effective permission codes for this user."""
        if self.role == 'admin':
            from .security import Permission
            return [p.code for p in Permission.query.all()]
        
        perms = set()
        from .security import RolePermission
        role_perms = RolePermission.query.filter_by(role=self.role).all()
        for rp in role_perms:
            perms.add(rp.permission_code)

        if self.custom_permissions_json:
            try:
                for cp in json.loads(self.custom_permissions_json):
                    perms.add(cp)
            except Exception:
                pass
        return sorted(list(perms))

    def to_dict(self):
        return {
            'id': self.id,
            'username': self.username,
            'full_name': self.full_name,
            'staff_id': self.staff_id,
            'role': self.role,
            'portal': self.portal,
            'department': self.department,
            'status': self.status,
            'is_2fa_enabled': self.is_2fa_enabled,
            'is_locked': self.is_locked()
        }
