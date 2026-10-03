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


CANONICAL_PERMISSIONS = [
    # Patient Records
    ("patient:view", "View Patient Records & History", "Patients", "Access demographic profiles and outpatient history"),
    ("patient:register", "Register New Patients", "Patients", "Create new patient records and allocate hospital IDs"),
    ("patient:edit", "Edit Patient Demographics", "Patients", "Modify patient contact info and insurance particulars"),

    # Clinical Consultation & EMR
    ("clinical:consult", "Perform Medical Consultations", "Clinical", "Document clinical notes, examinations, and diagnoses"),
    ("clinical:prescribe", "Prescribe Medications (Rx)", "Clinical", "Generate electronic prescriptions sent to pharmacy"),
    ("clinical:order_labs", "Order Diagnostic Tests", "Clinical", "Request lab tests and radiology imaging"),
    ("clinical:record_results", "Record Diagnostic & Lab Results", "Clinical", "Document and finalize laboratory investigation findings"),

    # Clinical Documents
    ("documents:generate_cert", "Issue Medical Sick-Off Certificates", "Documents", "Generate stamped clinical sick leave notes"),
    ("documents:generate_referral", "Issue Specialist Referral Letters", "Documents", "Draft official hospital referral documents"),
    ("documents:upload", "Upload & Manage Patient Attachments", "Documents", "Upload radiological scans, PDFs, and ID records"),

    # Inpatient Care & Wards
    ("inpatient:admit", "Admit Patient to Wards", "Inpatient", "Assign ward beds and document intake clinical orders"),
    ("inpatient:transfer", "Execute Inter-Ward Bed Transfers", "Inpatient", "Reassign beds and log transfer rationale"),
    ("inpatient:chart", "Document Nursing & Ward Rounds", "Inpatient", "Record shift nursing notes and daily doctor progress"),
    ("inpatient:discharge", "Clinical Inpatient Discharge", "Inpatient", "Finalize discharge clearance and generate certificates"),

    # Pharmacy & Dispensing
    ("pharmacy:dispense", "Dispense Prescriptions", "Pharmacy", "Clear and dispense pharmaceutical orders with counseling"),
    ("pharmacy:manage_stock", "Manage Drug Inventory & Batches", "Pharmacy", "Adjust stock, manage batches, and log purchase entries"),

    # Billing & Financials
    ("billing:create_invoice", "Create & Stage Invoices", "Billing", "Compile invoices and apply departmental fee schedules"),
    ("billing:collect_payment", "Collect Tender Payments", "Billing", "Process cash, M-Pesa, card, and insurance settlements"),
    ("billing:waive_discount", "Waive Charges & Authorize Discounts", "Billing", "Grant authorized discounts and fee waivers"),

    # Telephony & Communications
    ("telephony:send", "Send SMS & OTP Communications", "Telephony", "Dispatch patient SMS notifications, queue alerts, and OTPs"),

    # Hospital Administration & Security
    ("admin:manage_users", "Manage Staff User Accounts", "Admin", "Create, edit, suspend, and reset staff credentials"),
    ("admin:security_config", "Configure Security Policies & 2FA", "Admin", "Manage global 2FA and password requirements"),
    ("admin:view_audit", "Access Immutable Audit Trail", "Admin", "Inspect all clinical and financial activity logs")
]

DEFAULT_PERMISSIONS = CANONICAL_PERMISSIONS


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
