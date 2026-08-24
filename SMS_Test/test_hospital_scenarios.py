#!/usr/bin/env python3
from sms_service import SMSService
import json

def test_hospital_flow():
    sms = SMSService()
    test_phone = "+254711082302"
    
    print("=====================================================")
    print(" Testing Hospital Management System SMS Notifications")
    print("=====================================================")

    # 1. Appointment Notification
    print("\n1. Sending Appointment Confirmation...")
    res1 = sms.send_appointment_notification(
        phone=test_phone,
        patient_name="Jane Doe",
        doctor_name="Smith (Cardiology)",
        appointment_time="Monday, 24th Aug at 10:30 AM"
    )
    print("Result:", json.dumps(res1, indent=2))

    # 2. Triage Queue Notification
    print("\n2. Sending Triage Queue Alert...")
    res2 = sms.send_triage_alert(
        phone=test_phone,
        patient_name="Jane Doe",
        queue_number="A-014",
        department="General Outpatient (OPD)"
    )
    print("Result:", json.dumps(res2, indent=2))

    # 3. Billing Payment Receipt
    print("\n3. Sending Payment Receipt Notification...")
    res3 = sms.send_billing_receipt(
        phone=test_phone,
        patient_name="Jane Doe",
        receipt_no="REC-2026-8831",
        amount="3,500.00"
    )
    print("Result:", json.dumps(res3, indent=2))

if __name__ == "__main__":
    test_hospital_flow()
