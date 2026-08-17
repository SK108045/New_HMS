from datetime import datetime, date
from .base import db

class Appointment(db.Model):
    __tablename__ = 'appointments'

    id = db.Column(db.Integer, primary_key=True)
    patient_id = db.Column(db.Integer, db.ForeignKey('patients.id'), nullable=False, index=True)
    
    scheduled_date = db.Column(db.Date, nullable=False, index=True)
    scheduled_time = db.Column(db.String(10), nullable=False)  # e.g. "09:30"
    department = db.Column(db.String(100), nullable=False, default='General OPD')
    doctor_name = db.Column(db.String(100), nullable=True)
    reason = db.Column(db.Text, nullable=True)
    
    # Status: 'scheduled', 'confirmed', 'checked_in', 'completed', 'cancelled', 'no_show'
    status = db.Column(db.String(30), nullable=False, default='scheduled', index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

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
