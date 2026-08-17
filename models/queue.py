from datetime import datetime, date
from sqlalchemy import func
from .base import db

class QueueEntry(db.Model):
    __tablename__ = 'queue_entries'

    id = db.Column(db.Integer, primary_key=True)
    ticket_number = db.Column(db.String(30), nullable=False, index=True)
    patient_id = db.Column(db.Integer, db.ForeignKey('patients.id'), nullable=False, index=True)
    
    # Workflow Stages: 'triage', 'consultation', 'laboratory', 'pharmacy', 'billing', 'completed'
    stage = db.Column(db.String(50), nullable=False, default='triage', index=True)
    
    # Priority Levels: 'normal', 'urgent', 'emergency'
    priority = db.Column(db.String(20), nullable=False, default='normal', index=True)
    
    # Status: 'waiting', 'in_progress', 'completed', 'cancelled'
    status = db.Column(db.String(20), nullable=False, default='waiting', index=True)
    
    chief_complaint = db.Column(db.Text, nullable=True)
    destination_department = db.Column(db.String(100), nullable=False, default='General OPD')
    assigned_doctor = db.Column(db.String(100), nullable=True)
    
    checked_in_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    called_at = db.Column(db.DateTime, nullable=True)
    completed_at = db.Column(db.DateTime, nullable=True)
    notes = db.Column(db.Text, nullable=True)

    @property
    def wait_time_minutes(self) -> int:
        if self.called_at:
            delta = self.called_at - self.checked_in_at
        else:
            delta = datetime.utcnow() - self.checked_in_at
        return max(0, int(delta.total_seconds() / 60))

    @property
    def priority_badge_class(self) -> str:
        if self.priority == 'emergency':
            return 'bg-rose-50 text-rose-800 border-rose-300 font-semibold'
        elif self.priority == 'urgent':
            return 'bg-amber-50 text-amber-800 border-amber-300 font-semibold'
        return 'bg-slate-100 text-slate-700 border-slate-200'

    @classmethod
    def generate_daily_ticket(cls, session=None) -> str:
        """
        Generates daily sequential ticket number: TRG-001, TRG-002, etc.
        Resets sequence each day.
        """
        target_session = session or db.session
        today_start = datetime.combine(date.today(), datetime.min.time())
        
        count_today = target_session.query(func.count(cls.id)).filter(
            cls.checked_in_at >= today_start
        ).scalar() or 0

        next_num = count_today + 1
        return f"TRG-{next_num:03d}"

    def __repr__(self):
        return f"<QueueEntry {self.ticket_number} - Patient #{self.patient_id} [{self.priority.upper()}]>"
