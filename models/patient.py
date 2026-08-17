from datetime import datetime, date
from sqlalchemy import func
from .base import db

class Patient(db.Model):
    __tablename__ = 'patients'

    id = db.Column(db.Integer, primary_key=True)
    hospital_id = db.Column(db.String(30), unique=True, nullable=False, index=True)
    first_name = db.Column(db.String(100), nullable=False)
    last_name = db.Column(db.String(100), nullable=False)
    full_name = db.Column(db.String(200), nullable=False, index=True)
    national_id = db.Column(db.String(50), nullable=True, index=True)
    phone = db.Column(db.String(30), nullable=False, index=True)
    email = db.Column(db.String(120), nullable=True)
    date_of_birth = db.Column(db.Date, nullable=False)
    gender = db.Column(db.String(20), nullable=False)  # 'Male', 'Female', 'Other'
    photo_filename = db.Column(db.String(255), nullable=True)
    
    # Clinical & Administrative Details
    blood_group = db.Column(db.String(10), nullable=True)  # 'A+', 'O-', etc.
    allergies = db.Column(db.Text, nullable=True)
    residential_address = db.Column(db.String(255), nullable=True)
    
    # Billing / Payer Category at Registration
    primary_payer = db.Column(db.String(50), nullable=False, default='Cash')  # 'Cash', 'Insurance', 'Corporate'
    insurance_company = db.Column(db.String(100), nullable=True)
    insurance_policy_number = db.Column(db.String(100), nullable=True)

    # Emergency Contact / Next of Kin
    next_of_kin_name = db.Column(db.String(150), nullable=False)
    next_of_kin_phone = db.Column(db.String(30), nullable=False)
    next_of_kin_relation = db.Column(db.String(50), nullable=False)  # 'Spouse', 'Parent', 'Sibling', 'Guardian', 'Other'

    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    # Relationships
    queue_entries = db.relationship('QueueEntry', backref='patient', lazy=True, order_by='desc(QueueEntry.checked_in_at)')
    appointments = db.relationship('Appointment', backref='patient', lazy=True, order_by='desc(Appointment.scheduled_date)')
    vitals_records = db.relationship('VitalsRecord', backref='patient', lazy=True, order_by='desc(VitalsRecord.created_at)')
    consultation_notes = db.relationship('ConsultationNote', back_populates='patient', lazy=True, order_by='desc(ConsultationNote.created_at)')
    lab_orders = db.relationship('LabOrder', back_populates='patient', lazy=True, order_by='desc(LabOrder.created_at)')
    prescriptions = db.relationship('Prescription', back_populates='patient', lazy=True, order_by='desc(Prescription.created_at)')
    billing_items = db.relationship('BillingItem', back_populates='patient', lazy=True, order_by='desc(BillingItem.created_at)')

    @property
    def age(self) -> int:
        if not self.date_of_birth:
            return 0
        today = date.today()
        return today.year - self.date_of_birth.year - ((today.month, today.day) < (self.date_of_birth.month, self.date_of_birth.day))

    @property
    def initials(self) -> str:
        fn = self.first_name[0].upper() if self.first_name else ''
        ln = self.last_name[0].upper() if self.last_name else ''
        return f"{fn}{ln}" or "PT"

    @property
    def latest_visit(self):
        if self.queue_entries:
            return self.queue_entries[0]
        return None

    @property
    def latest_vitals(self):
        if self.vitals_records:
            return self.vitals_records[0]
        return None

    @classmethod
    def generate_hospital_id(cls, session=None) -> str:
        """
        Generates zero-padded, year-scoped hospital ID: HSP-2026-0001
        """
        current_year = datetime.utcnow().year
        prefix = f"HSP-{current_year}-"
        
        target_session = session or db.session
        # Query highest sequence for current year
        last_patient = target_session.query(cls).filter(
            cls.hospital_id.like(f"{prefix}%")
        ).order_by(cls.id.desc()).first()

        if last_patient and last_patient.hospital_id:
            try:
                last_seq = int(last_patient.hospital_id.split('-')[-1])
                new_seq = last_seq + 1
            except (ValueError, IndexError):
                new_seq = 1
        else:
            new_seq = 1

        return f"{prefix}{new_seq:04d}"

    def __repr__(self):
        return f"<Patient {self.hospital_id}: {self.full_name}>"
