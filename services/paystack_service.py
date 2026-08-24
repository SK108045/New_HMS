import os
import random
import logging
import requests
from datetime import datetime, date
from models import db, Patient, QueueEntry, Invoice, Payment, AuditLog

logger = logging.getLogger(__name__)

class PaystackService:
    """
    Paystack Payment Integration Service for Mobile Money (MPesa) and Card Settlements.
    Handles Consultation Fee (KES 500) STK Push Prompts, Verification, and Automated Queue Routing.
    """

    def __init__(self, secret_key: str = None):
        self.secret_key = secret_key or os.getenv("PAYSTACK_SECRET_KEY") or "sk_live_91baa01872ba458e72ab98118415ed9a69778dee"
        self.base_url = "https://api.paystack.co"

    @property
    def headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.secret_key.strip()}",
            "Content-Type": "application/json"
        }

    @staticmethod
    def format_phone_e164(phone: str) -> str:
        """
        Formats telephone number to Paystack KE format (+254...)
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

    def prompt_mpesa_charge(self, phone: str, amount_kes: float = 500.0, email: str = None, patient_name: str = None) -> dict:
        """
        Triggers an in-portal MPesa STK Push prompt to the patient's phone for consultation fees.
        """
        formatted_phone = self.format_phone_e164(phone)
        if not formatted_phone:
            return {"success": False, "error": "Invalid phone number format. Please provide a valid Kenyan phone number."}

        # Paystack KES amount is in subunits (cents/kobo) -> KES 500 = 50000
        amount_subunits = int(round(amount_kes * 100))
        customer_email = email or f"patient.{formatted_phone.replace('+', '')}@apexmedical.org"

        payload = {
            "amount": amount_subunits,
            "currency": "KES",
            "email": customer_email,
            "mobile_money": {
                "phone": formatted_phone,
                "provider": "mpesa"
            },
            "metadata": {
                "service": "Consultation Fee",
                "patient_name": patient_name or "Hospital Patient",
                "phone": formatted_phone
            }
        }

        try:
            url = f"{self.base_url}/charge"
            response = requests.post(url, headers=self.headers, json=payload, timeout=25)
            data = response.json()

            if response.status_code in [200, 201] and data.get("status"):
                res_data = data.get("data", {})
                reference = res_data.get("reference")
                status = res_data.get("status", "pay_offline")
                display_text = res_data.get("display_text", "Please complete authorization process on your mobile phone.")

                AuditLog.log_event(
                    "paystack_charge_initiated",
                    "payment",
                    None,
                    f"Paystack MPesa STK prompt of KES {amount_kes:.2f} initiated for {formatted_phone} (Ref: {reference})."
                )

                return {
                    "success": True,
                    "reference": reference,
                    "status": status,
                    "display_text": display_text,
                    "phone": formatted_phone,
                    "amount": amount_kes,
                    "data": res_data
                }
            else:
                err_msg = data.get("message", "Unable to trigger Paystack mobile charge.")
                logger.error("Paystack Charge Error: %s (Status: %s)", err_msg, response.status_code)
                return {"success": False, "error": err_msg, "status_code": response.status_code}

        except Exception as e:
            logger.exception("Exception during Paystack charge prompt: %s", e)
            return {"success": False, "error": f"Network exception: {str(e)}"}

    def verify_transaction(self, reference: str) -> dict:
        """
        Verifies transaction status on Paystack.
        """
        if not reference:
            return {"paid": False, "status": "failed", "error": "Missing reference"}

        # Check charge status first
        try:
            url_charge = f"{self.base_url}/charge/{reference}"
            res_c = requests.get(url_charge, headers=self.headers, timeout=15)
            data_c = res_c.json()

            if res_c.status_code == 200 and data_c.get("status"):
                c_data = data_c.get("data", {})
                charge_status = c_data.get("status")
                if charge_status == "success":
                    return {
                        "paid": True,
                        "status": "success",
                        "reference": reference,
                        "amount": (c_data.get("amount", 50000) / 100.0),
                        "channel": "mobile_money"
                    }
                elif charge_status in ["pay_offline", "pending", "send_otp"]:
                    return {
                        "paid": False,
                        "status": "pending",
                        "reference": reference,
                        "message": c_data.get("display_text", "Awaiting patient PIN confirmation on mobile device...")
                    }
                else:
                    # Could be failed
                    return {
                        "paid": False,
                        "status": charge_status,
                        "reference": reference,
                        "message": c_data.get("message", "Payment prompt not completed or rejected.")
                    }

            # Fallback to transaction verify endpoint
            url_tx = f"{self.base_url}/transaction/verify/{reference}"
            res_t = requests.get(url_tx, headers=self.headers, timeout=15)
            data_t = res_t.json()

            if res_t.status_code == 200 and data_t.get("status"):
                t_data = data_t.get("data", {})
                tx_status = t_data.get("status")
                if tx_status == "success":
                    return {
                        "paid": True,
                        "status": "success",
                        "reference": reference,
                        "amount": (t_data.get("amount", 50000) / 100.0),
                        "channel": t_data.get("channel", "mobile_money")
                    }
                elif tx_status in ["ongoing", "pending", "processing"]:
                    return {
                        "paid": False,
                        "status": "pending",
                        "reference": reference,
                        "message": "Awaiting customer authorization on phone..."
                    }
                else:
                    return {
                        "paid": False,
                        "status": tx_status or "failed",
                        "reference": reference,
                        "message": t_data.get("gateway_response", "Transaction was not completed.")
                    }

            return {"paid": False, "status": "pending", "reference": reference, "message": "Verifying..."}

        except Exception as e:
            logger.error("Paystack verification exception for %s: %s", reference, e)
            return {"paid": False, "status": "pending", "reference": reference, "error": str(e)}

    def settle_consultation_payment(self, patient_id: int, reference: str, amount: float = 500.0, destination_dept: str = "General OPD", assigned_doctor: str = None) -> dict:
        """
        Marks consultation fee as PAID, generates Invoice, BillingItem & Receipt, and fast-tracks patient into Triage Queue.
        """
        from models.emr import BillingItem
        patient = Patient.query.get_or_404(patient_id)
        
        # 1. Create Paid Invoice
        inv_number = Invoice.generate_invoice_number(db.session)
        invoice = Invoice(
            invoice_number=inv_number,
            patient_id=patient.id,
            subtotal=amount,
            discount_amount=0.0,
            tax_amount=0.0,
            total_due=amount,
            amount_paid=amount,
            balance_due=0.0,
            status="paid",
            cashier_name="Paystack Online Gateway",
            notes=f"Paystack MPesa Consultation Settlement (Ref: {reference})",
            created_at=datetime.utcnow(),
            paid_at=datetime.utcnow()
        )
        db.session.add(invoice)
        db.session.flush()

        # 2. Create Consultation Billing Line Item
        billing_item = BillingItem(
            patient_id=patient.id,
            invoice_id=invoice.id,
            service_type="consultation",
            item_description=f"Outpatient Consultation Fee ({destination_dept})",
            quantity=1,
            unit_price=amount,
            total_amount=amount,
            status="paid",
            created_at=datetime.utcnow()
        )
        db.session.add(billing_item)

        # 3. Record Payment
        rcpt_number = Payment.generate_receipt_number(db.session)
        payment = Payment(
            receipt_number=rcpt_number,
            invoice_id=invoice.id,
            patient_id=patient.id,
            total_amount_paid=amount,
            payment_method_summary="Paystack MPesa",
            mpesa_amount=amount,
            mpesa_reference=reference,
            mpesa_phone=patient.phone or "+254756205063",
            cashier_name="Paystack Online Gateway",
            notes=f"Paystack STK Push Consultation Fee (Ref: {reference})",
            created_at=datetime.utcnow()
        )
        db.session.add(payment)

        # 4. Check into Triage Queue
        today_start = datetime.combine(date.today(), datetime.min.time())
        existing_ticket = QueueEntry.query.filter(
            QueueEntry.patient_id == patient.id,
            QueueEntry.checked_in_at >= today_start,
            QueueEntry.status.in_(['waiting', 'in_progress'])
        ).first()

        if existing_ticket:
            ticket_number = existing_ticket.ticket_number
            queue_entry = existing_ticket
        else:
            ticket_number = QueueEntry.generate_daily_ticket(db.session)
            queue_entry = QueueEntry(
                ticket_number=ticket_number,
                patient_id=patient.id,
                stage="triage",
                priority="normal",
                status="waiting",
                chief_complaint="Outpatient Consultation (Consultation Fee Settled via Paystack MPesa)",
                destination_department=destination_dept or "General OPD",
                assigned_doctor=assigned_doctor
            )
            db.session.add(queue_entry)

        # Link queue entry to invoice
        invoice.queue_entry_id = queue_entry.id
        billing_item.queue_entry_id = queue_entry.id

        db.session.commit()

        AuditLog.log_event(
            "paystack_consultation_settled",
            "invoice",
            invoice.id,
            f"Consultation fee KES {amount:.2f} settled via Paystack (Ref: {reference}) for {patient.full_name}. Generated Ticket #{ticket_number}."
        )

        return {
            "success": True,
            "payment_id": payment.id,
            "invoice_id": invoice.id,
            "invoice_number": inv_number,
            "receipt_number": rcpt_number,
            "ticket_number": ticket_number,
            "queue_id": queue_entry.id,
            "patient_name": patient.full_name,
            "amount": amount
        }

paystack_service = PaystackService()
