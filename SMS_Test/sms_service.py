import os
import logging
import africastalking

logger = logging.getLogger(__name__)

class SMSService:
    def __init__(self, api_key: str = None, username: str = "sandbox"):
        self.username = username
        
        # Load API key from parameter, env var, or SMS_Test/api.txt fallback
        if not api_key:
            api_key = os.getenv("AFRICASTALKING_API_KEY")
            
        if not api_key:
            base_dir = os.path.dirname(os.path.abspath(__file__))
            key_file = os.path.join(base_dir, "api.txt")
            if os.path.exists(key_file):
                with open(key_file, "r") as f:
                    api_key = f.read().strip()

        if not api_key:
            raise ValueError("Africa's Talking API key is required. Set AFRICASTALKING_API_KEY or create api.txt.")

        self.api_key = api_key
        africastalking.initialize(self.username, self.api_key)
        self.sms = africastalking.SMS

    def send_sms(self, recipient: str, message: str, sender_id: str = None) -> dict:
        """
        Send an SMS to a single recipient.
        Format recipient with country code (e.g. +254711082302)
        """
        try:
            response = self.sms.send(message, [recipient], sender_id=sender_id, timeout=30)
            return {"success": True, "data": response}
        except Exception as e:
            logger.error(f"Failed to send SMS to {recipient}: {e}")
            return {"success": False, "error": str(e)}

    def send_appointment_notification(self, phone: str, patient_name: str, doctor_name: str, appointment_time: str) -> dict:
        """Send appointment confirmation SMS"""
        message = (
            f"Dear {patient_name}, your appointment with Dr. {doctor_name} "
            f"has been scheduled for {appointment_time}. Please arrive 15 minutes early."
        )
        return self.send_sms(phone, message)

    def send_triage_alert(self, phone: str, patient_name: str, queue_number: str, department: str) -> dict:
        """Send triage queue alert SMS"""
        message = (
            f"HMS Notice: {patient_name}, you have been assigned Queue #{queue_number} "
            f"at {department}. Please proceed to the waiting area."
        )
        return self.send_sms(phone, message)

    def send_billing_receipt(self, phone: str, patient_name: str, receipt_no: str, amount: str) -> dict:
        """Send payment receipt SMS"""
        message = (
            f"HMS Receipt: Dear {patient_name}, payment of KES {amount} "
            f"for Receipt #{receipt_no} has been received. Thank you."
        )
        return self.send_sms(phone, message)
