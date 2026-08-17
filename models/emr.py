import json
from datetime import datetime, date
from . import db

class ConsultationNote(db.Model):
    """
    SOAP Clinical Consultation & EMR Encounter Note.
    """
    __tablename__ = 'consultation_notes'

    id = db.Column(db.Integer, primary_key=True)
    patient_id = db.Column(db.Integer, db.ForeignKey('patients.id'), nullable=False)
    queue_entry_id = db.Column(db.Integer, db.ForeignKey('queue_entries.id'), nullable=True)
    
    doctor_name = db.Column(db.String(120), nullable=False)
    clinic_department = db.Column(db.String(80), nullable=False, default='General OPD')

    # SOAP Sections
    # S - Subjective
    subjective_notes = db.Column(db.Text, nullable=True) # Chief complaint, HPI, symptoms
    # O - Objective
    objective_notes = db.Column(db.Text, nullable=True)  # Physical exam, vitals, general appearance
    anatomical_regions = db.Column(db.Text, nullable=True) # JSON list of examined/tagged 3D body zones
    # A - Assessment
    icd10_code = db.Column(db.String(20), nullable=True)
    icd10_description = db.Column(db.String(255), nullable=True)
    assessment_notes = db.Column(db.Text, nullable=True)
    # P - Plan
    plan_notes = db.Column(db.Text, nullable=True)
    follow_up_date = db.Column(db.Date, nullable=True)

    status = db.Column(db.String(30), default='completed') # completed, in_progress, referred
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    # Relationships
    patient = db.relationship('Patient', back_populates='consultation_notes')
    queue_entry = db.relationship('QueueEntry', backref='consultation_note', lazy=True)
    lab_orders = db.relationship('LabOrder', back_populates='consultation', cascade='all, delete-orphan')
    prescriptions = db.relationship('Prescription', back_populates='consultation', cascade='all, delete-orphan')
    billing_items = db.relationship('BillingItem', back_populates='consultation', cascade='all, delete-orphan')

    @property
    def formatted_diagnosis(self):
        if self.icd10_code and self.icd10_description:
            return f"[{self.icd10_code}] {self.icd10_description}"
        return self.icd10_description or self.assessment_notes or "Clinical review"

    @property
    def tagged_regions_list(self):
        if not self.anatomical_regions:
            return []
        try:
            return json.loads(self.anatomical_regions)
        except Exception:
            return [r.strip() for r in self.anatomical_regions.split(',') if r.strip()]

    def __repr__(self):
        return f"<ConsultationNote {self.id} Patient={self.patient_id} Doc={self.doctor_name}>"


class LabOrder(db.Model):
    """
    Electronic Diagnostic Laboratory Request.
    """
    __tablename__ = 'lab_orders'

    id = db.Column(db.Integer, primary_key=True)
    order_number = db.Column(db.String(50), unique=True, nullable=False)
    patient_id = db.Column(db.Integer, db.ForeignKey('patients.id'), nullable=False)
    consultation_id = db.Column(db.Integer, db.ForeignKey('consultation_notes.id'), nullable=True)
    queue_entry_id = db.Column(db.Integer, db.ForeignKey('queue_entries.id'), nullable=True)

    doctor_name = db.Column(db.String(120), nullable=False)
    tests_json = db.Column(db.Text, nullable=False) # JSON array of test objects: [{"name": "Full Blood Count", "code": "FBC", "cost": 1500, "category": "Hematology"}]
    clinical_indication = db.Column(db.Text, nullable=True)
    urgency = db.Column(db.String(20), default='routine') # routine, urgent, stat
    total_cost = db.Column(db.Float, default=0.0)
    status = db.Column(db.String(30), default='pending') # pending, sample_collected, completed, cancelled
    result_data = db.Column(db.Text, nullable=True) # JSON test results
    reviewed_by_doctor = db.Column(db.Boolean, default=False)
    reviewed_at = db.Column(db.DateTime, nullable=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    # Relationships
    patient = db.relationship('Patient', back_populates='lab_orders')
    consultation = db.relationship('ConsultationNote', back_populates='lab_orders')
    queue_entry = db.relationship('QueueEntry', backref='lab_order', lazy=True)

    @classmethod
    def generate_order_number(cls, session=None):
        today_str = date.today().strftime('%Y%m%d')
        sess = session or db.session
        count = sess.query(cls).filter(
            cls.order_number.like(f'LAB-{today_str}-%')
        ).count()
        return f"LAB-{today_str}-{count + 1:04d}"

    @property
    def test_list(self):
        try:
            return json.loads(self.tests_json)
        except Exception:
            return []

    @property
    def test_names_str(self):
        tests = self.test_list
        if not tests:
            return "General Lab Panel"
        return ", ".join([t.get('name', t) if isinstance(t, dict) else str(t) for t in tests])

    @property
    def results_dict(self):
        if not self.result_data:
            return {}
        try:
            return json.loads(self.result_data)
        except Exception:
            return {"Findings": self.result_data}


class Prescription(db.Model):
    """
    Electronic Prescription (e-Rx).
    """
    __tablename__ = 'prescriptions'

    id = db.Column(db.Integer, primary_key=True)
    rx_number = db.Column(db.String(50), unique=True, nullable=False)
    patient_id = db.Column(db.Integer, db.ForeignKey('patients.id'), nullable=False)
    consultation_id = db.Column(db.Integer, db.ForeignKey('consultation_notes.id'), nullable=True)
    queue_entry_id = db.Column(db.Integer, db.ForeignKey('queue_entries.id'), nullable=True)

    doctor_name = db.Column(db.String(120), nullable=False)
    medications_json = db.Column(db.Text, nullable=False) # JSON array of [{ "drug": "Amoxicillin 500mg", "dosage": "500mg", "frequency": "1 tab TID (8-hrly)", "duration": "5 days", "quantity": 15, "instructions": "After food", "cost": 450 }]
    notes = db.Column(db.Text, nullable=True)
    total_cost = db.Column(db.Float, default=0.0)
    status = db.Column(db.String(30), default='pending_dispense') # pending_dispense, dispensed, partially_dispensed, cancelled

    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    # Relationships
    patient = db.relationship('Patient', back_populates='prescriptions')
    consultation = db.relationship('ConsultationNote', back_populates='prescriptions')
    queue_entry = db.relationship('QueueEntry', backref='prescription', lazy=True)

    @classmethod
    def generate_rx_number(cls, session=None):
        today_str = date.today().strftime('%Y%m%d')
        sess = session or db.session
        count = sess.query(cls).filter(
            cls.rx_number.like(f'RX-{today_str}-%')
        ).count()
        return f"RX-{today_str}-{count + 1:04d}"

    @property
    def medication_list(self):
        try:
            return json.loads(self.medications_json)
        except Exception:
            return []


class BillingItem(db.Model):
    """
    Staged or Incurred Charge generated across clinical touchpoints.
    """
    __tablename__ = 'billing_items'

    id = db.Column(db.Integer, primary_key=True)
    patient_id = db.Column(db.Integer, db.ForeignKey('patients.id'), nullable=False)
    consultation_id = db.Column(db.Integer, db.ForeignKey('consultation_notes.id'), nullable=True)
    queue_entry_id = db.Column(db.Integer, db.ForeignKey('queue_entries.id'), nullable=True)
    invoice_id = db.Column(db.Integer, db.ForeignKey('invoices.id'), nullable=True)

    service_type = db.Column(db.String(40), nullable=False) # consultation, lab, pharmacy, radiology, procedure
    item_description = db.Column(db.String(255), nullable=False)
    quantity = db.Column(db.Integer, default=1)
    unit_price = db.Column(db.Float, nullable=False)
    total_amount = db.Column(db.Float, nullable=False)
    status = db.Column(db.String(30), default='staged') # staged, pending_payment, paid, waived

    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    # Relationships
    patient = db.relationship('Patient', back_populates='billing_items')
    consultation = db.relationship('ConsultationNote', back_populates='billing_items')
    queue_entry = db.relationship('QueueEntry', backref='billing_items', lazy=True)
    invoice = db.relationship('Invoice', backref='billing_items', lazy=True)
