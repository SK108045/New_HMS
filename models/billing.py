from datetime import datetime, date
from models.base import db

class Invoice(db.Model):
    """
    Patient Bill / Tax Invoice compiling all clinical services.
    """
    __tablename__ = 'invoices'

    id = db.Column(db.Integer, primary_key=True)
    invoice_number = db.Column(db.String(60), unique=True, nullable=False)
    patient_id = db.Column(db.Integer, db.ForeignKey('patients.id'), nullable=False)
    queue_entry_id = db.Column(db.Integer, db.ForeignKey('queue_entries.id'), nullable=True)

    subtotal = db.Column(db.Float, default=0.0, nullable=False)
    discount_amount = db.Column(db.Float, default=0.0, nullable=False)
    tax_amount = db.Column(db.Float, default=0.0, nullable=False)
    total_due = db.Column(db.Float, default=0.0, nullable=False)
    amount_paid = db.Column(db.Float, default=0.0, nullable=False)
    balance_due = db.Column(db.Float, default=0.0, nullable=False)

    status = db.Column(db.String(30), default='unpaid') # unpaid, partially_paid, paid, waived, cancelled
    cashier_name = db.Column(db.String(120), nullable=True)
    notes = db.Column(db.Text, nullable=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    paid_at = db.Column(db.DateTime, nullable=True)

    # Relationships
    patient = db.relationship('Patient', backref='invoices', lazy=True)
    queue_entry = db.relationship('QueueEntry', backref='invoice', lazy=True)
    payments = db.relationship('Payment', back_populates='invoice', cascade='all, delete-orphan', lazy=True)

    @classmethod
    def generate_invoice_number(cls, session=None):
        today_str = date.today().strftime('%Y%m%d')
        sess = session or db.session
        count = sess.query(cls).filter(
            cls.invoice_number.like(f'INV-{today_str}-%')
        ).count()
        return f"INV-{today_str}-{count + 1:04d}"

    @property
    def is_settled(self):
        return self.status == 'paid' or self.balance_due <= 0.0

    def __repr__(self):
        return f"<Invoice {self.invoice_number} Patient={self.patient_id} Total={self.total_due} Status={self.status}>"


class Payment(db.Model):
    """
    Split Tender Payment & Settlement Transaction.
    """
    __tablename__ = 'payments'

    id = db.Column(db.Integer, primary_key=True)
    receipt_number = db.Column(db.String(60), unique=True, nullable=False)
    invoice_id = db.Column(db.Integer, db.ForeignKey('invoices.id'), nullable=False)
    patient_id = db.Column(db.Integer, db.ForeignKey('patients.id'), nullable=False)

    total_amount_paid = db.Column(db.Float, nullable=False)
    payment_method_summary = db.Column(db.String(100), default='Cash')

    # Cash Tender Details
    cash_amount = db.Column(db.Float, default=0.0)
    cash_tendered = db.Column(db.Float, default=0.0)
    change_returned = db.Column(db.Float, default=0.0)

    # M-Pesa Mobile Money Details
    mpesa_amount = db.Column(db.Float, default=0.0)
    mpesa_reference = db.Column(db.String(60), nullable=True)
    mpesa_phone = db.Column(db.String(40), nullable=True)

    # Insurance / SHA / Corporate Claim Details
    insurance_amount = db.Column(db.Float, default=0.0)
    insurance_company = db.Column(db.String(100), nullable=True)
    insurance_policy_number = db.Column(db.String(80), nullable=True)
    insurance_claim_number = db.Column(db.String(80), nullable=True)

    # Debit / Credit Card Details
    card_amount = db.Column(db.Float, default=0.0)
    card_auth_code = db.Column(db.String(60), nullable=True)

    cashier_name = db.Column(db.String(120), nullable=False)
    shift_code = db.Column(db.String(60), nullable=True)
    notes = db.Column(db.Text, nullable=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    # Relationships
    invoice = db.relationship('Invoice', back_populates='payments')
    patient = db.relationship('Patient', backref='payments', lazy=True)

    @classmethod
    def generate_receipt_number(cls, session=None):
        today_str = date.today().strftime('%Y%m%d')
        sess = session or db.session
        count = sess.query(cls).filter(
            cls.receipt_number.like(f'RCP-{today_str}-%')
        ).count()
        return f"RCP-{today_str}-{count + 1:04d}"

    def __repr__(self):
        return f"<Payment {self.receipt_number} Total={self.total_amount_paid} Method={self.payment_method_summary}>"


class ShiftRegister(db.Model):
    """
    Cashier Shift Reconciliation (X & Z Audit Reports).
    """
    __tablename__ = 'shift_registers'

    id = db.Column(db.Integer, primary_key=True)
    shift_code = db.Column(db.String(60), unique=True, nullable=False)
    cashier_name = db.Column(db.String(120), nullable=False)
    counter_number = db.Column(db.String(40), default='POS-01')

    opened_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    closed_at = db.Column(db.DateTime, nullable=True)

    opening_float = db.Column(db.Float, default=5000.0, nullable=False)
    cash_collected = db.Column(db.Float, default=0.0)
    mpesa_collected = db.Column(db.Float, default=0.0)
    insurance_billed = db.Column(db.Float, default=0.0)
    card_collected = db.Column(db.Float, default=0.0)
    total_revenue = db.Column(db.Float, default=0.0)

    counted_cash = db.Column(db.Float, nullable=True)
    discrepancy = db.Column(db.Float, nullable=True) # counted - (float + cash_collected)
    status = db.Column(db.String(30), default='open') # open, closed
    notes = db.Column(db.Text, nullable=True)

    @classmethod
    def generate_shift_code(cls, session=None):
        today_str = date.today().strftime('%Y%m%d')
        sess = session or db.session
        count = sess.query(cls).filter(
            cls.shift_code.like(f'SHF-{today_str}-%')
        ).count()
        return f"SHF-{today_str}-{count + 1:02d}"

    def __repr__(self):
        return f"<ShiftRegister {self.shift_code} Cashier={self.cashier_name} Status={self.status}>"


class InsuranceScheme(db.Model):
    """
    Insurance Underwriter & Social Health Authority (SHA) Catalog.
    """
    __tablename__ = 'insurance_schemes'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), unique=True, nullable=False)
    code = db.Column(db.String(40), unique=True, nullable=False) # e.g. SHA-PUB, JUB-01, AAR-01, BRT-01
    scheme_type = db.Column(db.String(40), default='private_insurer') # public_sha, private_insurer, corporate
    coverage_percentage = db.Column(db.Float, default=100.0)
    requires_preauth = db.Column(db.Boolean, default=True)
    copay_fixed_amount = db.Column(db.Float, default=0.0)
    copay_percentage = db.Column(db.Float, default=0.0)
    contact_phone = db.Column(db.String(40), nullable=True)
    claims_portal_url = db.Column(db.String(255), nullable=True)
    status = db.Column(db.String(20), default='active') # active, suspended

    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    claims = db.relationship('InsuranceClaim', back_populates='scheme', lazy=True)

    def __repr__(self):
        return f"<InsuranceScheme {self.name} ({self.code}) Type={self.scheme_type}>"


class InsuranceClaim(db.Model):
    """
    Patient Insurance & SHA Pre-Authorisation / Reimbursement Claim.
    """
    __tablename__ = 'insurance_claims'

    id = db.Column(db.Integer, primary_key=True)
    claim_number = db.Column(db.String(60), unique=True, nullable=False)
    invoice_id = db.Column(db.Integer, db.ForeignKey('invoices.id'), nullable=False)
    patient_id = db.Column(db.Integer, db.ForeignKey('patients.id'), nullable=False)
    scheme_id = db.Column(db.Integer, db.ForeignKey('insurance_schemes.id'), nullable=True)

    scheme_name = db.Column(db.String(120), nullable=False)
    member_number = db.Column(db.String(80), nullable=False)
    policy_number = db.Column(db.String(80), nullable=True)
    preauth_code = db.Column(db.String(80), nullable=True)

    claimed_amount = db.Column(db.Float, nullable=False, default=0.0)
    approved_amount = db.Column(db.Float, nullable=False, default=0.0)
    copay_amount = db.Column(db.Float, nullable=False, default=0.0)

    status = db.Column(db.String(40), default='preauth_pending') # preauth_pending, preauth_approved, submitted, reimbursed, rejected, disputed
    rejection_reason = db.Column(db.Text, nullable=True)
    notes = db.Column(db.Text, nullable=True)

    created_by = db.Column(db.String(120), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    submitted_at = db.Column(db.DateTime, nullable=True)
    settled_at = db.Column(db.DateTime, nullable=True)

    # Relationships
    invoice = db.relationship('Invoice', backref=db.backref('insurance_claims', lazy=True))
    patient = db.relationship('Patient', backref=db.backref('insurance_claims', lazy=True))
    scheme = db.relationship('InsuranceScheme', back_populates='claims')

    @classmethod
    def generate_claim_number(cls, session=None):
        today_str = date.today().strftime('%Y%m%d')
        sess = session or db.session
        count = sess.query(cls).filter(
            cls.claim_number.like(f'CLM-{today_str}-%')
        ).count()
        return f"CLM-{today_str}-{count + 1:04d}"

    def __repr__(self):
        return f"<InsuranceClaim {self.claim_number} Scheme={self.scheme_name} Status={self.status} Amount={self.claimed_amount}>"


class CreditNote(db.Model):
    """
    Credit Note & Patient Refund Request with Dual-Authorization.
    """
    __tablename__ = 'credit_notes'

    id = db.Column(db.Integer, primary_key=True)
    credit_note_number = db.Column(db.String(60), unique=True, nullable=False)
    invoice_id = db.Column(db.Integer, db.ForeignKey('invoices.id'), nullable=False)
    patient_id = db.Column(db.Integer, db.ForeignKey('patients.id'), nullable=False)

    amount = db.Column(db.Float, nullable=False)
    reason = db.Column(db.String(80), nullable=False) # billing_error, medication_returned, service_cancelled, overpayment
    status = db.Column(db.String(30), default='pending_approval') # pending_approval, approved, rejected
    requested_by = db.Column(db.String(120), nullable=False)
    approved_by = db.Column(db.String(120), nullable=True)
    notes = db.Column(db.Text, nullable=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    approved_at = db.Column(db.DateTime, nullable=True)

    invoice = db.relationship('Invoice', backref=db.backref('credit_notes', lazy=True))
    patient = db.relationship('Patient', backref=db.backref('credit_notes', lazy=True))

    @classmethod
    def generate_credit_note_number(cls, session=None):
        today_str = date.today().strftime('%Y%m%d')
        sess = session or db.session
        count = sess.query(cls).filter(
            cls.credit_note_number.like(f'CRN-{today_str}-%')
        ).count()
        return f"CRN-{today_str}-{count + 1:04d}"

    def __repr__(self):
        return f"<CreditNote {self.credit_note_number} Amount={self.amount} Status={self.status}>"


class FeeWaiver(db.Model):
    """
    Indigent Patient & Emergency Fee Waivers with Administrative Oversight.
    """
    __tablename__ = 'fee_waivers'

    id = db.Column(db.Integer, primary_key=True)
    waiver_number = db.Column(db.String(60), unique=True, nullable=False)
    invoice_id = db.Column(db.Integer, db.ForeignKey('invoices.id'), nullable=False)
    patient_id = db.Column(db.Integer, db.ForeignKey('patients.id'), nullable=False)

    amount = db.Column(db.Float, nullable=False)
    category = db.Column(db.String(80), default='indigent_patient') # indigent_patient, staff_discount, clinical_emergency, board_approved
    justification = db.Column(db.Text, nullable=False)
    status = db.Column(db.String(30), default='pending_approval') # pending_approval, approved, rejected
    requested_by = db.Column(db.String(120), nullable=False)
    approved_by = db.Column(db.String(120), nullable=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    approved_at = db.Column(db.DateTime, nullable=True)

    invoice = db.relationship('Invoice', backref=db.backref('fee_waivers', lazy=True))
    patient = db.relationship('Patient', backref=db.backref('fee_waivers', lazy=True))

    @classmethod
    def generate_waiver_number(cls, session=None):
        today_str = date.today().strftime('%Y%m%d')
        sess = session or db.session
        count = sess.query(cls).filter(
            cls.waiver_number.like(f'WVR-{today_str}-%')
        ).count()
        return f"WVR-{today_str}-{count + 1:04d}"

    def __repr__(self):
        return f"<FeeWaiver {self.waiver_number} Amount={self.amount} Status={self.status}>"

