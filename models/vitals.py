from datetime import datetime
from .base import db

class VitalsRecord(db.Model):
    __tablename__ = 'vitals_records'

    id = db.Column(db.Integer, primary_key=True)
    patient_id = db.Column(db.Integer, db.ForeignKey('patients.id'), nullable=False, index=True)
    queue_entry_id = db.Column(db.Integer, db.ForeignKey('queue_entries.id'), nullable=True, index=True)
    
    # Blood Pressure (mmHg)
    systolic_bp = db.Column(db.Integer, nullable=True)   # Normal: 90 - 120
    diastolic_bp = db.Column(db.Integer, nullable=True)  # Normal: 60 - 80
    
    # Heart / Pulse Rate (bpm)
    pulse_rate = db.Column(db.Integer, nullable=True)    # Normal: 60 - 100
    
    # Temperature (°C)
    temperature = db.Column(db.Float, nullable=True)     # Normal: 36.5 - 37.5
    
    # Respiratory Rate (breaths/min)
    respiratory_rate = db.Column(db.Integer, nullable=True) # Normal: 12 - 20
    
    # Oxygen Saturation SpO2 (%)
    spo2 = db.Column(db.Float, nullable=True)            # Normal: 95 - 100%
    
    # Anthropometry
    weight_kg = db.Column(db.Float, nullable=True)
    height_cm = db.Column(db.Float, nullable=True)
    bmi = db.Column(db.Float, nullable=True)
    bmi_category = db.Column(db.String(50), nullable=True) # Underweight, Normal, Overweight, Obese
    
    # Triage Acuity Categorization
    # 'green' (Routine / Non-urgent), 'yellow' (Urgent / Priority), 'red' (Emergency / Resuscitation)
    triage_category = db.Column(db.String(20), nullable=False, default='green', index=True)
    
    # Clinical Presenting Symptoms & Alerts
    chief_complaint = db.Column(db.Text, nullable=True)
    allergies = db.Column(db.Text, nullable=True)
    triage_notes = db.Column(db.Text, nullable=True)
    
    # Staff & Routing Destination
    recorded_by = db.Column(db.String(100), nullable=False, default='Nurse on Duty')
    assigned_doctor = db.Column(db.String(100), nullable=True)
    destination_clinic = db.Column(db.String(100), nullable=False, default='General OPD')
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)

    @property
    def bp_display(self) -> str:
        if self.systolic_bp and self.diastolic_bp:
            return f"{self.systolic_bp}/{self.diastolic_bp} mmHg"
        return "N/A"

    @property
    def is_bp_abnormal(self) -> bool:
        if self.systolic_bp and (self.systolic_bp >= 140 or self.systolic_bp < 90):
            return True
        if self.diastolic_bp and (self.diastolic_bp >= 90 or self.diastolic_bp < 60):
            return True
        return False

    @property
    def is_temp_abnormal(self) -> bool:
        if self.temperature and (self.temperature >= 38.0 or self.temperature < 35.5):
            return True
        return False

    @property
    def is_spo2_abnormal(self) -> bool:
        if self.spo2 and self.spo2 < 95.0:
            return True
        return False

    @property
    def is_pulse_abnormal(self) -> bool:
        if self.pulse_rate and (self.pulse_rate > 100 or self.pulse_rate < 55):
            return True
        return False

    @property
    def triage_badge_class(self) -> str:
        if self.triage_category == 'red':
            return 'bg-rose-100 text-rose-800 border-rose-300 font-bold'
        elif self.triage_category == 'yellow':
            return 'bg-amber-100 text-amber-800 border-amber-300 font-bold'
        return 'bg-slate-100 text-slate-800 border-slate-300 font-semibold'

    @classmethod
    def calculate_bmi(cls, weight_kg: float, height_cm: float):
        if not weight_kg or not height_cm or height_cm <= 0:
            return None, None
        
        height_m = height_cm / 100.0
        bmi_val = round(weight_kg / (height_m * height_m), 1)
        
        if bmi_val < 18.5:
            cat = 'Underweight'
        elif bmi_val < 25.0:
            cat = 'Normal weight'
        elif bmi_val < 30.0:
            cat = 'Overweight'
        else:
            cat = 'Obese'
            
        return bmi_val, cat

    def __repr__(self):
        return f"<VitalsRecord #{self.id} Patient #{self.patient_id} [{self.triage_category.upper()}]>"
