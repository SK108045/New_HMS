from datetime import datetime
from .base import db

class SMSLog(db.Model):
    """
    Tracks all outgoing live SMS messages sent via Africa's Talking.
    """
    __tablename__ = 'sms_logs'

    id = db.Column(db.Integer, primary_key=True)
    recipient = db.Column(db.String(30), nullable=False, index=True)
    patient_id = db.Column(db.Integer, db.ForeignKey('patients.id'), nullable=True, index=True)
    message_type = db.Column(db.String(50), default='general')  # 'otp', 'appointment_reminder', 'queue_alert', 'general_notice', 'custom'
    message_text = db.Column(db.Text, nullable=False)
    status = db.Column(db.String(30), default='Pending')  # 'Success', 'Failed', 'Pending'
    status_code = db.Column(db.Integer, nullable=True)
    message_id = db.Column(db.String(100), nullable=True)
    cost = db.Column(db.String(30), nullable=True)
    error_message = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    patient = db.relationship('Patient', backref=db.backref('sms_logs', lazy=True, order_by='desc(SMSLog.created_at)'))

    @property
    def status_badge_class(self) -> str:
        if self.status == 'Success':
            return 'bg-emerald-50 text-emerald-800 border-emerald-300'
        elif self.status == 'Failed':
            return 'bg-rose-50 text-rose-800 border-rose-300'
        return 'bg-amber-50 text-amber-800 border-amber-300'

    def __repr__(self):
        return f"<SMSLog #{self.id} to {self.recipient} [{self.status}]>"


class PatientOTP(db.Model):
    """
    One-Time Password (OTP) validation for patient phone verification and reception intake.
    """
    __tablename__ = 'patient_otps'

    id = db.Column(db.Integer, primary_key=True)
    patient_id = db.Column(db.Integer, db.ForeignKey('patients.id'), nullable=True, index=True)
    phone = db.Column(db.String(30), nullable=False, index=True)
    otp_code = db.Column(db.String(10), nullable=False)
    purpose = db.Column(db.String(50), default='patient_verification')  # 'patient_verification', 'intake_consent', 'telephony_auth'
    is_verified = db.Column(db.Boolean, default=False)
    expires_at = db.Column(db.DateTime, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    patient = db.relationship('Patient', backref=db.backref('otps', lazy=True, order_by='desc(PatientOTP.created_at)'))

    @property
    def is_expired(self) -> bool:
        return datetime.utcnow() > self.expires_at

    def __repr__(self):
        return f"<PatientOTP #{self.id} for {self.phone}: {self.otp_code} (Verified: {self.is_verified})>"
