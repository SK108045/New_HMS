import os
import secrets
import re
from werkzeug.security import generate_password_hash, check_password_hash
import logging
import africastalking
from datetime import datetime, timedelta
from models import db, SMSLog, PatientOTP, Appointment, Patient, QueueEntry, AuditLog

logger = logging.getLogger(__name__)

class SMSService:
    """
    Production Africa's Talking SMS & Telephony Integration Service.
    Handles OTP generation, Appointment Reminders, Queue Announcements, and Telephony Audit Logs.
    """

    def __init__(self):
        self.username = os.getenv("AFRICASTALKING_USERNAME", "").strip()
        self.api_key = os.getenv("AFRICASTALKING_API_KEY", "").strip()
        self.sms = None
        self._initialized = False
        if self.username and self.api_key:
            try:
                africastalking.initialize(self.username, self.api_key)
                self.sms = africastalking.SMS
                self._initialized = True
            except Exception:
                logger.exception("Unable to initialize SMS gateway")

    @staticmethod
    def format_phone(phone: str) -> str:
        """
        Sanitizes and normalizes telephone numbers to E.164 (+254...) format.
        """
        if not phone:
            return ""
        clean = "".join(c for c in phone if c.isdigit() or c == "+")
        if clean.startswith("0"):
            clean = "+254" + clean[1:]
        elif clean.startswith("254") and not clean.startswith("+"):
            clean = "+" + clean
        elif not clean.startswith("+") and len(clean) == 9:
            clean = "+254" + clean
        return clean

    def send_sms(self, recipient: str, message_text: str, patient_id: int = None, message_type: str = "custom", is_live: bool = None) -> dict:
        """
        Sends an SMS. Supports safe zero-cost Simulation Mode and Live Africa's Talking Gateway.
        Defaults to safe simulation unless live is explicitly requested or HMS_SMS_LIVE=true.
        """
        formatted_recipient = self.format_phone(recipient)
        if not re.fullmatch(r"\+[1-9]\d{7,14}", formatted_recipient):
            return {"success": False, "error": "Invalid recipient phone number."}

        # Check live flag: default to safe mode unless explicitly specified
        if is_live is None:
            is_live = (os.getenv("HMS_SMS_LIVE", "false").lower() == "true")

        # Create pending log entry
        log_entry = SMSLog(
            recipient=formatted_recipient,
            patient_id=patient_id,
            message_type=message_type,
            message_text="[Verification code redacted]" if message_type == "otp" else message_text,
            status="Pending",
            created_at=datetime.utcnow()
        )
        db.session.add(log_entry)
        db.session.flush()

        # If running in safe simulation mode or service uninitialized, use zero-cost simulator
        if not is_live:
            log_entry.status = "Simulated"
            log_entry.status_code = 100
            log_entry.cost = "KES 0.00 (Simulated)"
            log_entry.message_id = f"SIM-{secrets.token_hex(8)}"
            log_entry.error_message = None
            AuditLog.log_event(
                "sms_dispatched_simulated",
                "sms_log",
                log_entry.id,
                f"Simulated SMS [{message_type}] dispatched to {formatted_recipient} (Zero cost / Safe Mode)."
            )

            db.session.commit()
            return {
                "success": True,
                "log_id": log_entry.id,
                "cost": log_entry.cost,
                "message_id": log_entry.message_id,
                "simulated": True
            }

        if not self._initialized or not self.sms:
            log_entry.status = "Failed"
            log_entry.error_message = "Live SMS credentials are not configured."
            AuditLog.log_event("sms_configuration_missing", "sms_log", log_entry.id, severity="warning")
            db.session.commit()
            return {"success": False, "simulated": False, "error": log_entry.error_message, "log_id": log_entry.id}

        # Persist the delivery intent and release SQLite writes before gateway I/O.
        db.session.commit()
        try:
            response = self.sms.send(message_text, [formatted_recipient], timeout=30)
            
            # Parse Africa's Talking Response
            recipients = response.get("SMSMessageData", {}).get("Recipients", [])
            if recipients:
                rec_data = recipients[0]
                status = rec_data.get("status", "Failed")
                status_code = rec_data.get("statusCode", 100)
                cost = rec_data.get("cost")
                message_id = rec_data.get("messageId", "")

                log_entry.status = "Success" if status.lower() == "success" else "Failed"
                log_entry.status_code = status_code
                log_entry.cost = cost
                log_entry.message_id = message_id
                log_entry.error_message = None if log_entry.status == "Success" else f"Status: {status} (Code: {status_code})"
            else:
                log_entry.status = "Failed"
                log_entry.error_message = "No recipient data returned by gateway."

            AuditLog.log_event(
                "sms_dispatched_live",
                "sms_log",
                log_entry.id,
                f"Live Africa's Talking SMS [{message_type}] dispatched to {formatted_recipient}. Status: {log_entry.status} (Cost: {log_entry.cost or 'N/A'})."
            )

            db.session.commit()
            return {
                "success": (log_entry.status == "Success"),
                "error": log_entry.error_message,
                "log_id": log_entry.id,
                "cost": log_entry.cost,
                "message_id": log_entry.message_id,
                "response": response,
                "simulated": False
            }

        except Exception as e:
            logger.error("SMS gateway transmission failed (%s)", type(e).__name__)
            log_entry.status = "Failed"
            log_entry.error_message = "SMS gateway could not accept the message."
            db.session.commit()
            return {"success": False, "error": log_entry.error_message, "log_id": log_entry.id}

    def generate_and_send_otp(self, patient_id: int, phone: str = None, purpose: str = "patient_verification", is_live: bool = None) -> dict:
        """
        Generates a secure 6-digit OTP, stores it with 10-min expiry, and delivers via SMS.
        """
        from services.transactions import begin_write
        begin_write()
        target_phone = phone
        patient = None
        if patient_id:
            patient = Patient.query.get(patient_id)
            if patient and not target_phone:
                target_phone = patient.phone

        target_phone = self.format_phone(target_phone)
        if not re.fullmatch(r"\+[1-9]\d{7,14}", target_phone):
            return {"success": False, "error": "Patient phone number missing or invalid."}

        # Generate 6-digit OTP
        previous = PatientOTP.query.filter_by(phone=target_phone).order_by(PatientOTP.id.desc()).first()
        if previous and (datetime.utcnow() - previous.created_at).total_seconds() < 60:
            return {"success": False, "error": "Wait one minute before requesting another verification code."}
        PatientOTP.query.filter_by(phone=target_phone, is_verified=False).update({"expires_at": datetime.utcnow()}, synchronize_session=False)
        otp_code = f"{secrets.randbelow(1_000_000):06d}"
        expires_at = datetime.utcnow() + timedelta(minutes=10)

        otp_record = PatientOTP(
            patient_id=patient.id if patient else None,
            phone=target_phone,
            otp_code="",
            otp_hash=generate_password_hash(otp_code),
            failed_attempts=0,
            purpose=purpose,
            is_verified=False,
            expires_at=expires_at,
            created_at=datetime.utcnow()
        )
        db.session.add(otp_record)
        db.session.commit()

        message_text = (
            f"Apex Medical HMS: Your verification OTP code is {otp_code}. "
            f"Valid for 10 minutes. Please present this code to the receptionist for intake verification."
        )

        res = self.send_sms(target_phone, message_text, patient_id=patient.id if patient else None, message_type="otp", is_live=is_live)
        res["otp_id"] = otp_record.id
        if not res.get("success") or res.get("simulated"):
            # An undelivered challenge cannot establish ownership of a telephone number.
            otp_record.expires_at = datetime.utcnow()
            db.session.commit()
        return res

    def verify_otp(self, phone: str, otp_code: str, patient_id: int = None) -> dict:
        """
        Verifies a user-supplied OTP against database records.
        """
        formatted_phone = self.format_phone(phone)
        otp_code = str(otp_code).strip()

        query = PatientOTP.query.filter_by(phone=formatted_phone, is_verified=False)
        if patient_id:
            query = query.filter_by(patient_id=patient_id)
        otp_record = query.order_by(PatientOTP.id.desc()).first()
        if not otp_record or otp_record.is_expired or not otp_record.otp_hash or otp_record.failed_attempts >= 5:
            return {"verified": False, "error": "Invalid, expired or already consumed verification code."}
        if not re.fullmatch(r"\d{6}", otp_code) or not check_password_hash(otp_record.otp_hash, otp_code):
            PatientOTP.query.filter_by(id=otp_record.id, is_verified=False).update(
                {"failed_attempts": PatientOTP.failed_attempts + 1}, synchronize_session=False)
            db.session.commit()
            return {"verified": False, "error": "Invalid verification code."}
        consumed = PatientOTP.query.filter(
            PatientOTP.id == otp_record.id, PatientOTP.is_verified == False,
            PatientOTP.expires_at > datetime.utcnow(), PatientOTP.failed_attempts < 5
        ).update({"is_verified": True}, synchronize_session=False)
        if not consumed:
            db.session.rollback()
            return {"verified": False, "error": "Verification code was already consumed."}
        AuditLog.log_event("otp_verified", "patient_otp", otp_record.id,
                           "Patient phone ownership verified.")
        db.session.commit()

        return {"verified": True, "message": "Phone number verified successfully!"}

    def send_appointment_reminder(self, appointment_id: int, is_live: bool = None) -> dict:
        """
        Dispatches personalized appointment reminder SMS.
        """
        app = Appointment.query.get_or_404(appointment_id)
        patient = app.patient
        formatted_phone = self.format_phone(patient.phone)

        message_text = (
            f"Dear {patient.full_name}, reminder for your appointment at Apex Regional Medical Center "
            f"on {app.scheduled_date.strftime('%a, %d %b %Y')} at {app.scheduled_time} "
            f"with {app.doctor_name or 'General OPD'}. Ref: {app.appointment_number or app.id}. "
            f"Helpline: +254 700 000 100."
        )

        res = self.send_sms(formatted_phone, message_text, patient_id=patient.id, message_type="appointment_reminder", is_live=is_live)
        if res.get("success") and not res.get("simulated"):
            app.reminder_sent_sms = True
            app.last_reminder_at = datetime.utcnow()
            db.session.commit()

        return res

    def send_queue_alert(self, queue_entry_id: int, is_live: bool = None) -> dict:
        """
        Sends live or simulated SMS notice when patient's ticket is called to consultation room.
        """
        entry = QueueEntry.query.get_or_404(queue_entry_id)
        patient = entry.patient
        formatted_phone = self.format_phone(patient.phone)

        message_text = (
            f"Apex Medical Alert: {patient.full_name}, your Queue Ticket #{entry.ticket_number} "
            f"is now ready for consultation in {entry.destination_department} "
            f"with {entry.assigned_doctor or 'Attending Doctor'}. Please proceed to the room."
        )

        return self.send_sms(formatted_phone, message_text, patient_id=patient.id, message_type="queue_alert", is_live=is_live)

# Singleton Instance
sms_service = SMSService()
