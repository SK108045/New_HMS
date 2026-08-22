from datetime import datetime, date
from .base import db

class DoctorSchedule(db.Model):
    """
    Doctor Availability, Duty Shifts & Patient Slot Capacity.
    """
    __tablename__ = 'doctor_schedules'

    id = db.Column(db.Integer, primary_key=True)
    doctor_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True, index=True)
    doctor_name = db.Column(db.String(100), nullable=False)
    department = db.Column(db.String(100), nullable=False, default='General OPD')
    day_of_week = db.Column(db.String(20), nullable=False)  # 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'
    start_time = db.Column(db.String(10), nullable=False, default='08:00')
    end_time = db.Column(db.String(10), nullable=False, default='17:00')
    slot_duration_minutes = db.Column(db.Integer, default=20)
    max_patients_per_day = db.Column(db.Integer, default=20)
    is_available = db.Column(db.Boolean, default=True)
    duty_status = db.Column(db.String(30), default='available')  # 'available', 'on_leave', 'in_surgery', 'off_duty'
    notes = db.Column(db.String(255), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    doctor = db.relationship('User', backref='duty_schedules', lazy=True)

    def __repr__(self):
        return f"<DoctorSchedule {self.doctor_name} ({self.day_of_week} {self.start_time}-{self.end_time}, Max: {self.max_patients_per_day})>"


class Appointment(db.Model):
    __tablename__ = 'appointments'

    id = db.Column(db.Integer, primary_key=True)
    appointment_number = db.Column(db.String(30), unique=True, nullable=True, index=True)
    patient_id = db.Column(db.Integer, db.ForeignKey('patients.id'), nullable=False, index=True)
    
    scheduled_date = db.Column(db.Date, nullable=False, index=True)
    scheduled_time = db.Column(db.String(10), nullable=False)  # e.g. "09:30"
    department = db.Column(db.String(100), nullable=False, default='General OPD')
    doctor_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    doctor_name = db.Column(db.String(100), nullable=True)
    reason = db.Column(db.Text, nullable=True)
    
    # Status: 'scheduled', 'confirmed', 'checked_in', 'completed', 'cancelled', 'no_show'
    status = db.Column(db.String(30), nullable=False, default='scheduled', index=True)
    cancellation_reason = db.Column(db.String(255), nullable=True)
    cancelled_at = db.Column(db.DateTime, nullable=True)
    cancelled_by = db.Column(db.String(100), nullable=True)

    # Reminders via SMS & WhatsApp
    reminder_sent_sms = db.Column(db.Boolean, default=False)
    reminder_sent_whatsapp = db.Column(db.Boolean, default=False)
    last_reminder_at = db.Column(db.DateTime, nullable=True)
    reminder_logs_json = db.Column(db.Text, nullable=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    @classmethod
    def generate_appointment_number(cls, session=None):
        today_str = date.today().strftime('%Y%m%d')
        prefix = f"APT-{today_str}-"
        query = session.query(cls) if session else cls.query
        count = query.filter(cls.appointment_number.like(f"{prefix}%")).count()
        return f"{prefix}{count + 1:03d}"

    @property
    def is_today(self) -> bool:
        return self.scheduled_date == date.today()

    @property
    def status_badge_class(self) -> str:
        mapping = {
            'scheduled': 'bg-sky-50 text-sky-800 border-sky-200',
            'confirmed': 'bg-emerald-50 text-emerald-800 border-emerald-200',
            'checked_in': 'bg-teal-50 text-teal-800 border-teal-200',
            'completed': 'bg-slate-100 text-slate-600 border-slate-200',
            'cancelled': 'bg-rose-50 text-rose-700 border-rose-200',
            'no_show': 'bg-slate-100 text-slate-400 border-slate-200'
        }
        return mapping.get(self.status, 'bg-slate-100 text-slate-700 border-slate-200')

    def __repr__(self):
        return f"<Appointment #{self.id} for Patient {self.patient_id} on {self.scheduled_date} at {self.scheduled_time}>"
