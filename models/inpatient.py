import json
from datetime import datetime, date
from .base import db

class Ward(db.Model):
    """
    Hospital Inpatient Ward Definition (e.g. Male Medical, Female Surgical, Maternity, Pediatric, ICU)
    """
    __tablename__ = 'wards'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False, unique=True)
    code = db.Column(db.String(20), nullable=False, unique=True, index=True)
    gender_category = db.Column(db.String(20), default='Mixed')  # Male, Female, Mixed, Pediatric
    floor = db.Column(db.String(50), default='Ground Floor')
    wing = db.Column(db.String(50), default='Main Hospital Wing')
    description = db.Column(db.String(255), nullable=True)
    daily_nurse_in_charge = db.Column(db.String(120), default='Nurse Joyce Chebet')
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Relationships
    beds = db.relationship('Bed', back_populates='ward', cascade='all, delete-orphan', lazy=True)
    admissions = db.relationship('Admission', back_populates='ward', lazy=True)

    @property
    def total_beds_count(self):
        return len(self.beds)

    @property
    def occupied_beds_count(self):
        return sum(1 for b in self.beds if b.status == 'occupied')

    @property
    def available_beds_count(self):
        return sum(1 for b in self.beds if b.status == 'available')

    @property
    def occupancy_rate(self):
        if not self.beds:
            return 0
        return round((self.occupied_beds_count / len(self.beds)) * 100, 1)


class Bed(db.Model):
    """
    Individual Hospital Inpatient Bed
    """
    __tablename__ = 'beds'

    id = db.Column(db.Integer, primary_key=True)
    ward_id = db.Column(db.Integer, db.ForeignKey('wards.id'), nullable=False, index=True)
    bed_number = db.Column(db.String(30), nullable=False, index=True)
    bed_type = db.Column(db.String(50), default='Standard General')  # Standard General, Semi-Private, Private Suite, ICU Ventilator, Pediatric Crib
    daily_rate = db.Column(db.Float, default=1500.0)  # KES per day
    status = db.Column(db.String(30), default='available', index=True)  # available, occupied, cleaning, maintenance, reserved
    notes = db.Column(db.String(255), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Relationships
    ward = db.relationship('Ward', back_populates='beds')
    current_admission = db.relationship(
        'Admission',
        primaryjoin="and_(Bed.id==Admission.bed_id, Admission.status=='admitted')",
        uselist=False,
        viewonly=True
    )


class Admission(db.Model):
    """
    Inpatient Admission Record
    """
    __tablename__ = 'admissions'

    id = db.Column(db.Integer, primary_key=True)
    admission_number = db.Column(db.String(50), unique=True, nullable=False, index=True)  # ADM-2026-0001
    patient_id = db.Column(db.Integer, db.ForeignKey('patients.id'), nullable=False, index=True)
    ward_id = db.Column(db.Integer, db.ForeignKey('wards.id'), nullable=False, index=True)
    bed_id = db.Column(db.Integer, db.ForeignKey('beds.id'), nullable=False, index=True)
    
    admitting_doctor = db.Column(db.String(120), nullable=False)
    admitting_diagnosis = db.Column(db.Text, nullable=False)
    icd10_code = db.Column(db.String(30), nullable=True)
    admission_type = db.Column(db.String(50), default='Emergency Admission')  # Emergency, Elective/Planned, Transfer In
    
    # Timing & Status
    admitted_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    expected_discharge_date = db.Column(db.Date, nullable=True)
    actual_discharge_date = db.Column(db.DateTime, nullable=True)
    status = db.Column(db.String(30), default='admitted', index=True)  # admitted, transferred, discharged, deceased
    
    # Clinical Care Specifications
    dietary_plan = db.Column(db.String(100), default='Normal Hospital Diet')
    isolation_required = db.Column(db.Boolean, default=False)
    nursing_acuity = db.Column(db.String(30), default='Moderate Care (Level 2)')
    deposit_amount = db.Column(db.Float, default=0.0)
    
    # Emergency Contact
    emergency_contact_name = db.Column(db.String(120), nullable=True)
    emergency_contact_phone = db.Column(db.String(50), nullable=True)
    emergency_contact_relation = db.Column(db.String(50), nullable=True)

    # Discharge Information
    discharge_type = db.Column(db.String(50), nullable=True)  # Routine / Medical Clearance, Transfer to Referral, DAMA (Against Medical Advice), Deceased
    condition_on_discharge = db.Column(db.String(50), nullable=True)  # Recovered / Stable, Improved, Unchanged, Critical
    discharge_summary = db.Column(db.Text, nullable=True)
    discharge_instructions = db.Column(db.Text, nullable=True)
    discharge_medications_json = db.Column(db.Text, nullable=True)
    followup_date = db.Column(db.Date, nullable=True)
    followup_clinic = db.Column(db.String(100), nullable=True)
    discharged_by = db.Column(db.String(120), nullable=True)

    # Relationships
    patient = db.relationship('Patient', backref=db.backref('admissions', lazy=True, order_by='Admission.admitted_at.desc()'))
    ward = db.relationship('Ward', back_populates='admissions')
    bed = db.relationship('Bed', foreign_keys=[bed_id])
    transfers = db.relationship('BedTransfer', back_populates='admission', cascade='all, delete-orphan', lazy=True, order_by='BedTransfer.transferred_at.desc()')
    nursing_notes = db.relationship('NursingNote', back_populates='admission', cascade='all, delete-orphan', lazy=True, order_by='NursingNote.created_at.desc()')
    ward_rounds = db.relationship('WardRoundNote', back_populates='admission', cascade='all, delete-orphan', lazy=True, order_by='WardRoundNote.round_date.desc()')

    @property
    def discharge_medications(self):
        if self.discharge_medications_json:
            try:
                return json.loads(self.discharge_medications_json)
            except Exception:
                return []
        return []

    @discharge_medications.setter
    def discharge_medications(self, val):
        self.discharge_medications_json = json.dumps(val)

    @property
    def length_of_stay_days(self):
        end_time = self.actual_discharge_date or datetime.utcnow()
        delta = end_time - self.admitted_at
        days = delta.days
        # Minimum 1 day for billing calculation
        return max(1, days if delta.seconds < 43200 and days > 0 else days + 1)

    @property
    def total_bed_charge(self):
        rate = self.bed.daily_rate if self.bed else 1500.0
        return self.length_of_stay_days * rate


class BedTransfer(db.Model):
    """
    Audit Trail of Inpatient Inter-Ward or Inter-Bed Transfers
    """
    __tablename__ = 'bed_transfers'

    id = db.Column(db.Integer, primary_key=True)
    admission_id = db.Column(db.Integer, db.ForeignKey('admissions.id'), nullable=False, index=True)
    patient_id = db.Column(db.Integer, db.ForeignKey('patients.id'), nullable=False)
    
    from_ward_id = db.Column(db.Integer, db.ForeignKey('wards.id'), nullable=False)
    from_bed_id = db.Column(db.Integer, db.ForeignKey('beds.id'), nullable=False)
    to_ward_id = db.Column(db.Integer, db.ForeignKey('wards.id'), nullable=False)
    to_bed_id = db.Column(db.Integer, db.ForeignKey('beds.id'), nullable=False)
    
    transfer_reason = db.Column(db.String(255), nullable=False)
    transferred_by = db.Column(db.String(120), nullable=False)
    transferred_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    # Relationships
    admission = db.relationship('Admission', back_populates='transfers')
    from_ward = db.relationship('Ward', foreign_keys=[from_ward_id])
    to_ward = db.relationship('Ward', foreign_keys=[to_ward_id])
    from_bed = db.relationship('Bed', foreign_keys=[from_bed_id])
    to_bed = db.relationship('Bed', foreign_keys=[to_bed_id])


class NursingNote(db.Model):
    """
    Shift-by-Shift Inpatient Nursing Care Observation & Charting
    """
    __tablename__ = 'nursing_notes'

    id = db.Column(db.Integer, primary_key=True)
    admission_id = db.Column(db.Integer, db.ForeignKey('admissions.id'), nullable=False, index=True)
    patient_id = db.Column(db.Integer, db.ForeignKey('patients.id'), nullable=False)
    
    nurse_name = db.Column(db.String(120), nullable=False)
    shift = db.Column(db.String(30), default='Morning Shift')  # Morning (07:00 - 15:00), Afternoon (15:00 - 23:00), Night (23:00 - 07:00)
    
    # Nursing Details
    subjective_assessment = db.Column(db.Text, nullable=True)
    nursing_interventions = db.Column(db.Text, nullable=False)
    vital_signs_summary = db.Column(db.String(255), nullable=True)  # e.g. BP 120/80, Pulse 78, Temp 36.8C, SpO2 98%
    intake_output_notes = db.Column(db.String(255), nullable=True)   # e.g. Oral fluids 1200ml, IV Ringers 1000ml / Urine output 1400ml
    medications_administered = db.Column(db.Text, nullable=True)
    iv_infusions = db.Column(db.String(255), nullable=True)
    handover_instructions = db.Column(db.Text, nullable=True)
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    # Relationships
    admission = db.relationship('Admission', back_populates='nursing_notes')
    patient = db.relationship('Patient')


class WardRoundNote(db.Model):
    """
    Doctor Daily Ward Round Clinical Progress Note
    """
    __tablename__ = 'ward_round_notes'

    id = db.Column(db.Integer, primary_key=True)
    admission_id = db.Column(db.Integer, db.ForeignKey('admissions.id'), nullable=False, index=True)
    patient_id = db.Column(db.Integer, db.ForeignKey('patients.id'), nullable=False)
    
    doctor_name = db.Column(db.String(120), nullable=False)
    round_date = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    
    clinical_progress = db.Column(db.Text, nullable=False)  # Subjective & Objective examination findings on round
    lab_radiology_review = db.Column(db.Text, nullable=True)
    treatment_plan_changes = db.Column(db.Text, nullable=False)  # Modifications to drugs, IV fluids, or procedures
    discharge_readiness = db.Column(db.String(50), default='Continue Inpatient Care')  # Continue Care, Plan Discharge Tomorrow, Fit for Discharge
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    # Relationships
    admission = db.relationship('Admission', back_populates='ward_rounds')
    patient = db.relationship('Patient')
