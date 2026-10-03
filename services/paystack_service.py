import os
import math
import logging
import requests
from datetime import datetime, date
from models import db, Patient, QueueEntry, Invoice, Payment, AuditLog
from models.billing import PaystackTransaction
from models.emr import BillingItem

logger = logging.getLogger(__name__)

class PaystackService:
    """
    Paystack Payment Integration Service for Mobile Money (MPesa) and Card Settlements.
    Handles Consultation Fee STK Push Prompts, Verification, and Automated Queue Routing.
    Fails closed when secret key configuration is missing.
    """

    def __init__(self, secret_key: str = None):
        self._secret_key = secret_key
        self.base_url = "https://api.paystack.co"

    def get_secret_key(self) -> str:
        """
        Retrieves configured Paystack secret key with fail-closed behavior.
        Checks explicit instance key, Flask current_app config, then environment variable.
        Never uses hardcoded credential fallback.
        """
        if self._secret_key:
            return self._secret_key.strip()
        try:
            from flask import current_app
            if current_app and current_app.config.get("PAYSTACK_SECRET_KEY"):
                return current_app.config.get("PAYSTACK_SECRET_KEY").strip()
        except Exception:
            pass
        env_key = os.getenv("PAYSTACK_SECRET_KEY")
        if env_key:
            return env_key.strip()
        return None

    @property
    def is_configured(self) -> bool:
        return bool(self.get_secret_key())

    @property
    def headers(self) -> dict:
        secret_key = self.get_secret_key()
        if not secret_key:
            raise ValueError("Paystack secret key is not configured. Service is failing closed.")
        return {
            "Authorization": f"Bearer {secret_key}",
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

    def prompt_mpesa_charge(self, phone: str, amount_kes: float = 500.0, email: str = None, patient_name: str = None, patient_id: int = None, reference: str = None) -> dict:
        """
        Triggers an in-portal MPesa STK Push prompt to the patient's phone for consultation fees.
        """
        if not self.is_configured:
            return {"success": False, "error": "Paystack gateway is not configured. Secret key missing."}

        formatted_phone = self.format_phone_e164(phone)
        if not formatted_phone:
            return {"success": False, "error": "Invalid phone number format. Please provide a valid Kenyan phone number."}

        if not math.isfinite(amount_kes) or amount_kes <= 0:
            return {"success": False, "error": "Invalid consultation fee amount."}

        # Paystack KES amount is in subunits (cents/kobo) -> KES 500 = 50000
        amount_subunits = int(round(amount_kes * 100))
        customer_email = email or f"patient.{formatted_phone.replace('+', '')}@apexmedical.org"

        metadata = {
            "service": "Consultation Fee",
            "patient_name": patient_name or "Hospital Patient",
            "phone": formatted_phone
        }
        if patient_id:
            metadata["patient_id"] = patient_id

        payload = {
            "amount": amount_subunits,
            "currency": "KES",
            "email": customer_email,
            "mobile_money": {
                "phone": formatted_phone,
                "provider": "mpesa"
            },
            "metadata": metadata
        }

        if reference:
            payload["reference"] = reference
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
                    "currency": "KES",
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
        Verifies transaction status on Paystack without mutating application state.
        """
        if not self.is_configured:
            return {"paid": False, "status": "failed", "error": "Paystack gateway is not configured. Secret key missing."}

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
                currency = c_data.get("currency")
                amount = (c_data.get("amount", 0) / 100.0) if c_data.get("amount") is not None else 0.0
                if charge_status == "success":
                    return {
                        "paid": True,
                        "status": "success",
                        "reference": c_data.get("reference"),
                        "amount": amount,
                        "currency": currency,
                        "channel": "mobile_money"
                    }
                elif charge_status in ["pay_offline", "pending", "send_otp"]:
                    return {
                        "paid": False,
                        "status": "pending",
                        "reference": reference,
                        "amount": amount,
                        "currency": currency,
                        "message": c_data.get("display_text", "Awaiting patient PIN confirmation on mobile device...")
                    }
                else:
                    return {
                        "paid": False,
                        "status": charge_status or "failed",
                        "reference": reference,
                        "amount": amount,
                        "currency": currency,
                        "message": c_data.get("message", "Payment prompt not completed or rejected.")
                    }

            # Fallback to transaction verify endpoint
            url_tx = f"{self.base_url}/transaction/verify/{reference}"
            res_t = requests.get(url_tx, headers=self.headers, timeout=15)
            data_t = res_t.json()

            if res_t.status_code == 200 and data_t.get("status"):
                t_data = data_t.get("data", {})
                tx_status = t_data.get("status")
                currency = t_data.get("currency")
                amount = (t_data.get("amount", 0) / 100.0) if t_data.get("amount") is not None else 0.0
                if tx_status == "success":
                    return {
                        "paid": True,
                        "status": "success",
                        "reference": t_data.get("reference"),
                        "amount": amount,
                        "currency": currency,
                        "channel": t_data.get("channel", "mobile_money")
                    }
                elif tx_status in ["ongoing", "pending", "processing"]:
                    return {
                        "paid": False,
                        "status": "pending",
                        "reference": reference,
                        "amount": amount,
                        "currency": currency,
                        "message": "Awaiting customer authorization on phone..."
                    }
                else:
                    return {
                        "paid": False,
                        "status": tx_status or "failed",
                        "reference": reference,
                        "amount": amount,
                        "currency": currency,
                        "message": t_data.get("gateway_response", "Transaction was not completed.")
                    }

            return {"paid": False, "status": "pending", "reference": reference, "message": "Verifying..."}

        except Exception as e:
            logger.error("Paystack verification exception for %s: %s", reference, e)
            return {"paid": False, "status": "error", "reference": reference, "message": "Payment gateway verification is unavailable. Retry shortly."}

    def settle_consultation_payment(self, reference: str, destination_dept: str = "General OPD", assigned_doctor: str = None, patient_id: int = None, amount: float = None, verification: dict = None) -> dict:
        """
        Settles consultation payment idempotently and database-backed concurrent-safe using unique references.
        Cannot settle unknown/unverified/replayed references or switch patient/amount.
        Fixes queue foreign-key linking by flushing queue entry before assigning queue_entry_id.
        """
        from services.transactions import begin_write
        begin_write()
        tx = PaystackTransaction.query.filter_by(reference=reference).populate_existing().first()
        if not tx:
            raise ValueError(f"Cannot settle unknown or unverified Paystack reference: {reference}")

        if patient_id is not None and int(patient_id) != tx.patient_id:
            raise ValueError('Patient mismatch for persisted transaction reference.')
        if amount is not None and (not math.isfinite(float(amount)) or round(float(amount), 2) != round(tx.amount, 2)):
            raise ValueError('Amount mismatch for persisted transaction reference.')
        if tx.status != 'settled':
            if verification is not None:
                from decimal import Decimal, InvalidOperation
                try:
                    valid_amount = Decimal(str(verification.get('amount'))) == Decimal(str(tx.amount))
                except InvalidOperation:
                    valid_amount = False
                if (verification.get('paid') is not True or verification.get('status') != 'success'
                        or verification.get('reference') != tx.reference
                        or verification.get('currency') != tx.currency or not valid_amount):
                    raise ValueError('Provider verification does not match the authorized transaction.')
                tx.verified_at = datetime.utcnow()
            elif tx.status != 'success' or not tx.verified_at:
                raise ValueError('Transaction has not been verified by the provider.')
            if tx.status not in {'pending', 'success'}:
                raise ValueError('Transaction cannot be settled in its current state.')

        # Idempotency guard: already settled transaction returns preserved payload
        if tx.status == 'settled' and tx.invoice_id and tx.payment_id:
            inv = Invoice.query.get(tx.invoice_id)
            pmt = Payment.query.get(tx.payment_id)
            q = QueueEntry.query.get(tx.queue_entry_id) if tx.queue_entry_id else None
            return {
                "success": True,
                "payment_id": tx.payment_id,
                "invoice_id": tx.invoice_id,
                "invoice_number": inv.invoice_number if inv else "",
                "receipt_number": pmt.receipt_number if pmt else "",
                "ticket_number": q.ticket_number if q else "",
                "queue_id": tx.queue_entry_id,
                "patient_name": tx.patient.full_name if tx.patient else "",
                "amount": tx.amount
            }

        # Guard against switching patient or amount
        if patient_id is not None and int(patient_id) != tx.patient_id:
            raise ValueError("Security violation: Patient mismatch. Cannot switch patient for persisted transaction reference.")
        if amount is not None and round(float(amount), 2) != round(float(tx.amount), 2):
            raise ValueError("Security violation: Amount mismatch. Cannot switch amount for persisted transaction reference.")

        # Re-check if payment already recorded with this mpesa reference
        existing_pmt = Payment.query.filter_by(mpesa_reference=reference).first()
        if existing_pmt:
            if existing_pmt.patient_id != tx.patient_id or round(existing_pmt.total_amount_paid, 2) != round(tx.amount, 2):
                raise ValueError('Provider reference is already bound to a different payment.')
            tx.status = 'settled'
            tx.payment_id = existing_pmt.id
            tx.invoice_id = existing_pmt.invoice_id
            inv = existing_pmt.invoice
            q = inv.queue_entry if inv else None
            if q:
                tx.queue_entry_id = q.id
            tx.settled_at = datetime.utcnow()
            db.session.commit()
            return {
                "success": True,
                "payment_id": existing_pmt.id,
                "invoice_id": inv.id if inv else None,
                "invoice_number": inv.invoice_number if inv else "",
                "receipt_number": existing_pmt.receipt_number,
                "ticket_number": q.ticket_number if q else "",
                "queue_id": q.id if q else None,
                "patient_name": tx.patient.full_name if tx.patient else "",
                "amount": tx.amount
            }

        try:
            patient = tx.patient or Patient.query.get_or_404(tx.patient_id)
            settle_amount = tx.amount
            dept = destination_dept or tx.destination_department or "General OPD"
            doc = assigned_doctor or tx.assigned_doctor

            # 1. Create Paid Invoice
            inv_number = Invoice.generate_invoice_number(db.session)
            invoice = Invoice(
                invoice_number=inv_number,
                patient_id=patient.id,
                subtotal=settle_amount,
                discount_amount=0.0,
                tax_amount=0.0,
                total_due=settle_amount,
                amount_paid=settle_amount,
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
                item_description=f"Outpatient Consultation Fee ({dept})",
                quantity=1,
                unit_price=settle_amount,
                total_amount=settle_amount,
                status="paid",
                created_at=datetime.utcnow()
            )
            db.session.add(billing_item)
            db.session.flush()

            # 3. Record Payment
            rcpt_number = Payment.generate_receipt_number(db.session)
            payment = Payment(
                receipt_number=rcpt_number,
                idempotency_key="paystack:" + reference,
                invoice_id=invoice.id,
                patient_id=patient.id,
                total_amount_paid=settle_amount,
                payment_method_summary="Paystack MPesa",
                mpesa_amount=settle_amount,
                mpesa_reference=reference,
                mpesa_phone=tx.phone or patient.phone or "",
                cashier_name="Paystack Online Gateway",
                notes=f"Paystack STK Push Consultation Fee (Ref: {reference})",
                created_at=datetime.utcnow()
            )
            db.session.add(payment)
            db.session.flush()

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
                    destination_department=dept,
                    assigned_doctor=doc
                )
                db.session.add(queue_entry)
                db.session.flush()  # Populates queue_entry.id for FK assignment

            # Link queue entry to invoice and billing item
            invoice.queue_entry_id = queue_entry.id
            billing_item.queue_entry_id = queue_entry.id

            # Update PaystackTransaction record
            tx.status = 'settled'
            tx.invoice_id = invoice.id
            tx.payment_id = payment.id
            tx.queue_entry_id = queue_entry.id
            tx.settled_at = datetime.utcnow()

            AuditLog.log_event(
                "paystack_consultation_settled",
                "invoice",
                invoice.id,
                f"Consultation fee KES {settle_amount:.2f} settled via Paystack (Ref: {reference}) for {patient.full_name}. Generated Ticket #{ticket_number}."
            )

            db.session.commit()

            return {
                "success": True,
                "payment_id": payment.id,
                "invoice_id": invoice.id,
                "invoice_number": inv_number,
                "receipt_number": rcpt_number,
                "ticket_number": ticket_number,
                "queue_id": queue_entry.id,
                "patient_name": patient.full_name,
                "amount": settle_amount
            }

        except Exception as e:
            db.session.rollback()
            # In case of concurrent settlement race, re-check settled status
            tx_recheck = PaystackTransaction.query.filter_by(reference=reference).first()
            if tx_recheck and tx_recheck.status == 'settled' and tx_recheck.payment_id:
                inv = Invoice.query.get(tx_recheck.invoice_id)
                pmt = Payment.query.get(tx_recheck.payment_id)
                q = QueueEntry.query.get(tx_recheck.queue_entry_id) if tx_recheck.queue_entry_id else None
                return {
                    "success": True,
                    "payment_id": tx_recheck.payment_id,
                    "invoice_id": tx_recheck.invoice_id,
                    "invoice_number": inv.invoice_number if inv else "",
                    "receipt_number": pmt.receipt_number if pmt else "",
                    "ticket_number": q.ticket_number if q else "",
                    "queue_id": tx_recheck.queue_entry_id,
                    "patient_name": tx_recheck.patient.full_name if tx_recheck.patient else "",
                    "amount": tx_recheck.amount
                }
            raise

    def settle_cash_consultation(self, patient_id: int, amount: float, cashier_name: str, destination_dept: str = "General OPD", assigned_doctor: str = None, reference: str = None) -> dict:
        """
        Manual cash settlement: separate accounting type and authenticated actor,
        validates positive finite amounts and idempotency, not mislabeled Paystack gateway.
        """
        if not math.isfinite(amount) or amount <= 0:
            raise ValueError("Settlement amount must be a positive finite number.")

        from services.transactions import begin_write
        begin_write()
        patient = Patient.query.get_or_404(patient_id)
        actor_name = cashier_name or "Reception Cashier"

        # Idempotency check if custom reference is supplied
        if reference:
            existing_payment = Payment.query.filter_by(idempotency_key="cash:" + reference).first()
            if existing_payment:
                if existing_payment.patient_id != patient_id or round(existing_payment.total_amount_paid, 2) != round(amount, 2):
                    raise ValueError('Cash request key is already bound to a different patient or amount.')
                invoice = existing_payment.invoice
                queue_entry = invoice.queue_entry if invoice else None
                return {
                    "success": True,
                    "payment_id": existing_payment.id,
                    "invoice_id": invoice.id if invoice else None,
                    "invoice_number": invoice.invoice_number if invoice else "",
                    "receipt_number": existing_payment.receipt_number,
                    "ticket_number": queue_entry.ticket_number if queue_entry else "",
                    "queue_id": queue_entry.id if queue_entry else None,
                    "patient_name": patient.full_name,
                    "amount": existing_payment.total_amount_paid
                }

        # 1. Create Invoice
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
            cashier_name=actor_name,
            notes=f"Reception Cash Consultation Settlement",
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
        db.session.flush()

        # 3. Record Payment (Separate Cash Accounting)
        rcpt_number = reference if (reference and reference.startswith("RCP-")) else Payment.generate_receipt_number(db.session)
        payment = Payment(
            receipt_number=rcpt_number,
            idempotency_key="cash:" + reference if reference else None,
            invoice_id=invoice.id,
            patient_id=patient.id,
            total_amount_paid=amount,
            payment_method_summary="Cash",
            cash_amount=amount,
            cash_tendered=amount,
            change_returned=0.0,
            mpesa_amount=0.0,
            mpesa_reference=None,
            cashier_name=actor_name,
            notes=f"Reception Cash Consultation Fee",
            created_at=datetime.utcnow()
        )
        db.session.add(payment)
        db.session.flush()

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
                chief_complaint="Outpatient Consultation (Consultation Fee Settled via Cash)",
                destination_department=destination_dept or "General OPD",
                assigned_doctor=assigned_doctor
            )
            db.session.add(queue_entry)
            db.session.flush()  # Populates queue_entry.id for FK assignment

        invoice.queue_entry_id = queue_entry.id
        billing_item.queue_entry_id = queue_entry.id

        AuditLog.log_event(
            "cash_consultation_settled",
            "invoice",
            invoice.id,
            f"Consultation fee KES {amount:.2f} settled via Cash for {patient.full_name} by {actor_name}. Generated Ticket #{ticket_number}."
        )

        db.session.commit()

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
