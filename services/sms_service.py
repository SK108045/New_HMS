import os
import random
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
        self.username = "sk10"
        self.api_key = self._load_api_key()
        self._initialized = False

        if self.api_key:
            try:
                africastalking.initialize(self.username, self.api_key)
                self.sms = africastalking.SMS
                self._initialized = True
                logger.info("Africa's Talking SMS Service initialized successfully for user '%s'", self.username)
            except Exception as e:
                logger.error("Failed to initialize Africa's Talking: %s", e)
                self.sms = None

    def _load_api_key(self) -> str:
        # Check environment variable first
        env_key = os.getenv("AFRICASTALKING_API_KEY")
        if env_key:
            return env_key.strip()

        # Check SMS_Test/live_api.txt fallback
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        live_key_path = os.path.join(base_dir, "SMS_Test", "live_api.txt")
        if os.path.exists(live_key_path):
            with open(live_key_path, "r") as f:
                return f.read().strip()

        return ""

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
        if not formatted_recipient:
            return {"success": False, "error": "Invalid recipient phone number."}

        # Check live flag: default to safe mode unless explicitly specified
        if is_live is None:
            is_live = (os.getenv("HMS_SMS_LIVE", "false").lower() == "true")

        # Create pending log entry
        log_entry = SMSLog(
            recipient=formatted_recipient,
            patient_id=patient_id,
            message_type=message_type,
            message_text=message_text,
            status="Pending",
            created_at=datetime.utcnow()
        )
        db.session.add(log_entry)
        db.session.flush()

        # If running in safe simulation mode or service uninitialized, use zero-cost simulator
        if not is_live or not self._initialized or not self.sms:
            log_entry.status = "Success"
            log_entry.status_code = 100
            log_entry.cost = "KES 0.00 (Simulated)"
            log_entry.message_id = f"SIM-{random.randint(100000, 999999)}"
            log_entry.error_message = None
            db.session.commit()

            AuditLog.log_event(
                "sms_dispatched_simulated",
                "sms_log",
                log_entry.id,
                f"Simulated SMS [{message_type}] dispatched to {formatted_recipient} (Zero cost / Safe Mode)."
            )

            return {
                "success": True,
                "log_id": log_entry.id,
                "cost": log_entry.cost,
                "message_id": log_entry.message_id,
                "simulated": True
            }

        try:
            response = self.sms.send(message_text, [formatted_recipient], timeout=30)
            
            # Parse Africa's Talking Response
            recipients = response.get("SMSMessageData", {}).get("Recipients", [])
            if recipients:
                rec_data = recipients[0]
                status = rec_data.get("status", "Success")
                status_code = rec_data.get("statusCode", 100)
                cost = rec_data.get("cost", "KES 0.8000")
                message_id = rec_data.get("messageId", "")

                log_entry.status = "Success" if status.lower() == "success" else "Failed"
                log_entry.status_code = status_code
                log_entry.cost = cost
                log_entry.message_id = message_id
                log_entry.error_message = None if log_entry.status == "Success" else f"Status: {status} (Code: {status_code})"
            else:
                log_entry.status = "Failed"
                log_entry.error_message = "No recipient data returned by gateway."

            db.session.commit()

            AuditLog.log_event(
                "sms_dispatched_live",
                "sms_log",
                log_entry.id,
                f"Live Africa's Talking SMS [{message_type}] dispatched to {formatted_recipient}. Status: {log_entry.status} (Cost: {log_entry.cost or 'N/A'})."
            )

            return {
                "success": (log_entry.status == "Success"),
                "log_id": log_entry.id,
                "cost": log_entry.cost,
                "message_id": log_entry.message_id,
                "response": response,
                "simulated": False
            }

        except Exception as e:
            logger.error("SMS Transmission Exception to %s: %s", formatted_recipient, e)
            log_entry.status = "Failed"
            log_entry.error_message = str(e)
            db.session.commit()
            return {"success": False, "error": str(e), "log_id": log_entry.id}

    def generate_and_send_otp(self, patient_id: int, phone: str = None, purpose: str = "patient_verification", is_live: bool = None) -> dict:
        """
        Generates a secure 6-digit OTP, stores it with 10-min expiry, and delivers via SMS.
        """
        target_phone = phone
        patient = None
        if patient_id:
            patient = Patient.query.get(patient_id)
            if patient and not target_phone:
                target_phone = patient.phone

        target_phone = self.format_phone(target_phone)
        if not target_phone:
            return {"success": False, "error": "Patient phone number missing or invalid."}

        # Generate 6-digit OTP
        otp_code = f"{random.randint(100000, 999999)}"
        expires_at = datetime.utcnow() + timedelta(minutes=10)

        otp_record = PatientOTP(
            patient_id=patient.id if patient else None,
            phone=target_phone,
            otp_code=otp_code,
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
        res["otp_code_preview"] = otp_code
        return res

    def verify_otp(self, phone: str, otp_code: str, patient_id: int = None) -> dict:
        """
        Verifies a user-supplied OTP against database records.
        """
        formatted_phone = self.format_phone(phone)
        otp_code = str(otp_code).strip()

        query = PatientOTP.query.filter(
            PatientOTP.phone == formatted_phone,
            PatientOTP.otp_code == otp_code,
            PatientOTP.is_verified == False
        )
        if patient_id:
            query = query.filter(PatientOTP.patient_id == patient_id)

        otp_record = query.order_by(PatientOTP.id.desc()).first()

        if not otp_record:
            return {"verified": False, "error": "Invalid or already consumed OTP code."}

        if otp_record.is_expired:
            return {"verified": False, "error": "OTP has expired. Please request a new code."}

        otp_record.is_verified = True
        db.session.commit()

        AuditLog.log_event(
            "otp_verified",
            "patient_otp",
            otp_record.id,
            f"Phone {formatted_phone} successfully verified via OTP for {otp_record.purpose}."
        )

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
        if res.get("success"):
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
