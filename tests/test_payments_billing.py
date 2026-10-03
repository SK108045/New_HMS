import os
import math
import shutil
import tempfile
import unittest
from datetime import datetime, date
from unittest.mock import patch, MagicMock

from app import create_app
from models.base import db
from models.user import User
from models.patient import Patient
from models.queue import QueueEntry
from models.billing import (
    Invoice, Payment, ShiftRegister, PaystackTransaction,
    InsuranceScheme, InsuranceClaim, CreditNote, FeeWaiver
)
from models.emr import BillingItem
from services.paystack_service import PaystackService, paystack_service


class BaseBillingTestCase(unittest.TestCase):
    """Base setup for payment and billing regression test cases using isolated temporary DB."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.temp_db_path = os.path.join(self.temp_dir, 'test_hms.db')
        self.private_uploads = os.path.join(self.temp_dir, 'private')
        os.makedirs(self.private_uploads, exist_ok=True)

        class TestConfig:
            TESTING = True
            SECRET_KEY = 'test-secret-key-billing-suite'
            SQLALCHEMY_DATABASE_URI = f'sqlite:///{self.temp_db_path}'
            SQLALCHEMY_TRACK_MODIFICATIONS = False
            WTF_CSRF_ENABLED = False
            PRIVATE_UPLOAD_FOLDER = self.private_uploads
            UPLOAD_FOLDER = os.path.join(self.temp_dir, 'uploads')
            CONSULTATION_FEE = 500.0
            PAYSTACK_SECRET_KEY = 'fake-paystack-credential-for-isolated-tests'

        self.app = create_app(TestConfig)
        self.client = self.app.test_client()

        with self.app.app_context():
            db.create_all()
            from models import SecuritySetting
            settings = SecuritySetting.get_settings()
            settings.require_2fa_for_admin_doctor = False
            db.session.commit()

            # Create test users
            self.admin_user = User(
                username='test_admin',
                full_name='Dr. Admin Mukasa',
                staff_id='STF-ADM-001',
                role='admin',
                portal='all',
                department='Administration',
                status='active',
                is_2fa_enabled=False
            )
            self.admin_user.set_password('AdminPass123!')

            self.cashier_user = User(
                username='test_cashier',
                full_name='Joyce Wambui (Lead Cashier)',
                staff_id='STF-CSH-001',
                role='cashier',
                portal='billing',
                department='Finance',
                status='active',
                is_2fa_enabled=False
            )
            self.cashier_user.set_password('CashierPass123!')

            # Create test patient
            self.patient = Patient(
                full_name='Test Patient', next_of_kin_name='Kin', next_of_kin_phone='+254700000002', next_of_kin_relation='Sibling',
                first_name='John',
                last_name='Otieno',
                gender='male',
                date_of_birth=date(1990, 5, 15),
                phone='+254712345678',
                hospital_id='HSP-2026-0001',
                primary_payer='Cash'
            )

            # Create test insurance scheme
            self.scheme = InsuranceScheme(
                name='Jubilee Health Insurance',
                code='JUB-01',
                scheme_type='private_insurer',
                coverage_percentage=100.0,
                requires_preauth=True,
                copay_fixed_amount=200.0,
                copay_percentage=10.0,
                status='active'
            )

            db.session.add_all([self.admin_user, self.cashier_user, self.patient, self.scheme])
            db.session.commit()

            self.admin_id = self.admin_user.id
            self.cashier_id = self.cashier_user.id
            self.patient_id = self.patient.id
            self.scheme_id = self.scheme.id

    def tearDown(self):
        with self.app.app_context():
            db.session.remove()
            db.drop_all()
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def login_as(self, user):
        from tests.support import authenticate
        authenticate(self.client, self.app, user)


class TestPaystackServiceUnit(BaseBillingTestCase):
    """Unit tests for Paystack service fail-closed config, prompt, verify, and settlement."""

    def test_fail_closed_configuration(self):
        """Service must fail closed when secret key is missing; no hardcoded key fallback."""
        service = PaystackService(secret_key=None)
        with self.app.app_context():
            with patch.dict(os.environ, {}, clear=True):
                self.app.config['PAYSTACK_SECRET_KEY'] = None
                self.assertFalse(service.is_configured)
                with self.assertRaises(ValueError):
                    _ = service.headers

                prompt_res = service.prompt_mpesa_charge('+254712345678', 500.0)
                self.assertFalse(prompt_res['success'])
                self.assertIn('Secret key missing', prompt_res['error'])

                verify_res = service.verify_transaction('REF-12345')
                self.assertFalse(verify_res['paid'])
                self.assertEqual(verify_res['status'], 'failed')

    @patch('services.paystack_service.requests.post')
    def test_prompt_mpesa_charge_success(self, mock_post):
        """Prompt sends STK push request and records audit event."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "status": True,
            "data": {
                "reference": "PSK-TEST-REF-001",
                "status": "pay_offline",
                "display_text": "Enter PIN on phone"
            }
        }
        mock_post.return_value = mock_resp

        with self.app.app_context():
            service = PaystackService(secret_key='fake-paystack-credential-for-isolated-tests')
            res = service.prompt_mpesa_charge(
                phone='0712345678',
                amount_kes=500.0,
                patient_name='John Otieno',
                patient_id=self.patient_id
            )
            self.assertTrue(res['success'])
            self.assertEqual(res['reference'], 'PSK-TEST-REF-001')
            self.assertEqual(res['phone'], '+254712345678')
            self.assertEqual(res['amount'], 500.0)

            # Ensure payload uses 50000 subunits
            sent_payload = mock_post.call_args[1]['json']
            self.assertEqual(sent_payload['amount'], 50000)
            self.assertEqual(sent_payload['currency'], 'KES')

    @patch('services.paystack_service.requests.get')
    def test_verify_transaction_status_only(self, mock_get):
        """verify_transaction queries gateway status without mutating database."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "status": True,
            "data": {
                "status": "success",
                "reference": "PSK-TEST-REF-001",
                "amount": 50000,
                "currency": "KES",
                "channel": "mobile_money"
            }
        }
        mock_get.return_value = mock_resp

        with self.app.app_context():
            service = PaystackService(secret_key='fake-paystack-credential-for-isolated-tests')
            res = service.verify_transaction('PSK-TEST-REF-001')
            self.assertTrue(res['paid'])
            self.assertEqual(res['status'], 'success')
            self.assertEqual(res['amount'], 500.0)
            self.assertEqual(res['currency'], 'KES')

            # Verify no invoice was created by verify_transaction
            self.assertEqual(Invoice.query.count(), 0)

    def test_settle_unknown_reference_rejected(self):
        """Cannot settle unknown or unpersisted transaction reference."""
        with self.app.app_context():
            service = PaystackService(secret_key='fake-paystack-credential-for-isolated-tests')
            with self.assertRaises(ValueError) as ctx:
                service.settle_consultation_payment('UNKNOWN-REF-999')
            self.assertIn('Cannot settle unknown or unverified', str(ctx.exception))

    def test_settlement_reference_rebinding_protection(self):
        """Cannot rebind reference to a different patient or altered amount."""
        with self.app.app_context():
            # Create another patient
            patient2 = Patient(
                full_name='Test Patient', next_of_kin_name='Kin', next_of_kin_phone='+254700000002', next_of_kin_relation='Sibling',
                first_name='Mary',
                last_name='Wanjiku',
                gender='female',
                date_of_birth=date(1995, 3, 20),
                phone='+254799887766',
                hospital_id='HSP-2026-0002',
                primary_payer='Cash'
            )
            db.session.add(patient2)

            tx = PaystackTransaction(
                reference='PSK-REBIND-TEST',
                patient_id=self.patient_id,
                amount=500.0,
                currency='KES',
                status='pending'
            )
            db.session.add(tx)
            db.session.commit()

            service = PaystackService(secret_key='fake-paystack-credential-for-isolated-tests')
            # Attempt to switch patient
            with self.assertRaises(ValueError) as ctx:
                service.settle_consultation_payment('PSK-REBIND-TEST', patient_id=patient2.id)
            self.assertIn('Patient mismatch', str(ctx.exception))

            # Attempt to switch amount
            with self.assertRaises(ValueError) as ctx2:
                service.settle_consultation_payment('PSK-REBIND-TEST', patient_id=self.patient_id, amount=100.0)
            self.assertIn('Amount mismatch', str(ctx2.exception))

    def test_settle_consultation_payment_and_fk_linking(self):
        """Settlement links new queue entry foreign key via flush before assignment."""
        with self.app.app_context():
            tx = PaystackTransaction(
                reference='PSK-FLUSH-FK-001', verified_at=datetime.utcnow(),
                patient_id=self.patient_id,
                amount=500.0,
                currency='KES',
                destination_department='Pediatrics',
                assigned_doctor='Dr. Kamau',
                status='success'
            )
            db.session.add(tx)
            db.session.commit()

            service = PaystackService(secret_key='fake-paystack-credential-for-isolated-tests')
            res = service.settle_consultation_payment('PSK-FLUSH-FK-001')

            self.assertTrue(res['success'])
            self.assertIsNotNone(res['queue_id'])
            self.assertIsNotNone(res['invoice_id'])
            self.assertIsNotNone(res['payment_id'])

            # Verify queue FK linking in database
            invoice = Invoice.query.get(res['invoice_id'])
            self.assertIsNotNone(invoice.queue_entry_id)
            self.assertEqual(invoice.queue_entry_id, res['queue_id'])

            billing_item = BillingItem.query.filter_by(invoice_id=invoice.id).first()
            self.assertIsNotNone(billing_item.queue_entry_id)
            self.assertEqual(billing_item.queue_entry_id, res['queue_id'])

            # Verify transaction updated to settled
            tx_updated = PaystackTransaction.query.filter_by(reference='PSK-FLUSH-FK-001').first()
            self.assertEqual(tx_updated.status, 'settled')
            self.assertEqual(tx_updated.queue_entry_id, res['queue_id'])

    def test_idempotent_repeat_settlement(self):
        """Repeat settlement calls return identical settlement data without duplicate entries."""
        with self.app.app_context():
            tx = PaystackTransaction(
                reference='PSK-IDEMPOTENT-001', verified_at=datetime.utcnow(),
                patient_id=self.patient_id,
                amount=500.0,
                currency='KES',
                status='success'
            )
            db.session.add(tx)
            db.session.commit()

            service = PaystackService(secret_key='fake-paystack-credential-for-isolated-tests')
            res1 = service.settle_consultation_payment('PSK-IDEMPOTENT-001')
            res2 = service.settle_consultation_payment('PSK-IDEMPOTENT-001')

            self.assertEqual(res1['payment_id'], res2['payment_id'])
            self.assertEqual(res1['invoice_id'], res2['invoice_id'])
            self.assertEqual(res1['ticket_number'], res2['ticket_number'])

            # Ensure only 1 invoice and 1 payment were created
            self.assertEqual(Invoice.query.filter_by(patient_id=self.patient_id).count(), 1)
            self.assertEqual(Payment.query.filter_by(patient_id=self.patient_id).count(), 1)


class TestReceptionPaymentRoutes(BaseBillingTestCase):
    def setUp(self):
        super().setUp()
        with self.app.app_context():
            user = db.session.get(User, self.cashier_id)
            user.role = 'receptionist'
            user.portal = 'reception'
            db.session.commit()
        self.login_as(self.cashier_user)

    """Integration tests for reception /paystack/prompt, /paystack/verify, and /paystack/manual-settle."""

    @patch('services.paystack_service.PaystackService.prompt_mpesa_charge')
    def test_prompt_enforces_server_tariff_rejects_arbitrary_browser_amount(self, mock_prompt):
        """Prompt ignores browser charge amount and uses server CONSULTATION_FEE tariff."""
        mock_prompt.side_effect = lambda **kw: {
            "success": True,
            "reference": kw['reference'],
            "status": "pay_offline",
            "display_text": "Enter PIN",
            "phone": "+254712345678",
            "amount": 500.0
        }

        # Browser attempts to pass arbitrary 1.0 Bob
        response = self.client.post('/reception/paystack/prompt', json={
            'patient_id': self.patient_id,
            'phone': '+254712345678',
            'amount': 1.0,  # Tampered amount from browser
            'department': 'General OPD'
        })

        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertTrue(data['success'])
        self.assertEqual(data['amount'], 500.0)

        # Service was called with server tariff amount 500.0
        mock_prompt.assert_called_once()
        self.assertEqual(mock_prompt.call_args[1]['amount_kes'], 500.0)

        # Ensure durable PaystackTransaction created with 500.0
        with self.app.app_context():
            tx = PaystackTransaction.query.filter_by(reference=data['reference']).first()
            self.assertIsNotNone(tx)
            self.assertEqual(tx.amount, 500.0)
            self.assertEqual(tx.status, 'pending')

    def test_get_verify_is_status_only_without_mutation(self):
        """GET /paystack/verify/<ref> is read-only and does not mutate or settle."""
        with self.app.app_context():
            tx = PaystackTransaction(
                reference='PSK-GET-STATUS-ONLY',
                patient_id=self.patient_id,
                amount=500.0,
                currency='KES',
                status='pending'
            )
            db.session.add(tx)
            db.session.commit()

        with patch('services.paystack_service.PaystackService.verify_transaction') as mock_verify:
            mock_verify.return_value = {
                "paid": True,
                "status": "success",
                "reference": "PSK-GET-STATUS-ONLY",
                "amount": 500.0,
                "currency": "KES"
            }
            resp = self.client.get('/reception/paystack/verify/PSK-GET-STATUS-ONLY')
            self.assertEqual(resp.status_code, 200)
            data = resp.get_json()
            self.assertTrue(data['paid'])

            # Must NOT settle via GET!
            with self.app.app_context():
                tx_check = PaystackTransaction.query.filter_by(reference='PSK-GET-STATUS-ONLY').first()
                self.assertEqual(tx_check.status, 'pending')
                self.assertIsNone(tx_check.invoice_id)
                self.assertEqual(Invoice.query.count(), 0)

    @patch('services.paystack_service.PaystackService.verify_transaction')
    def test_post_verify_amount_tamper_rejected(self, mock_verify):
        """POST verification rejects when provider returns tampered amount."""
        with self.app.app_context():
            tx = PaystackTransaction(
                reference='PSK-TAMPER-001',
                patient_id=self.patient_id,
                amount=500.0,
                currency='KES',
                status='pending'
            )
            db.session.add(tx)
            db.session.commit()

        # Provider claims 100.0 instead of expected 500.0
        mock_verify.return_value = {
            "paid": True,
            "status": "success",
            "reference": "PSK-TAMPER-001",
            "amount": 100.0,
            "currency": "KES"
        }

        resp = self.client.post('/reception/paystack/verify/PSK-TAMPER-001')
        self.assertEqual(resp.status_code, 400)
        data = resp.get_json()
        self.assertFalse(data['paid'])
        self.assertIn('Amount tamper detected', data['error'])

        # Transaction remains pending
        with self.app.app_context():
            tx_check = PaystackTransaction.query.filter_by(reference='PSK-TAMPER-001').first()
            self.assertEqual(tx_check.status, 'pending')
            self.assertIsNone(tx_check.invoice_id)

    @patch('services.paystack_service.PaystackService.verify_transaction')
    def test_post_verify_success_and_idempotent_repeat(self, mock_verify):
        """POST verification settles properly and repeat verification returns idempotent response."""
        with self.app.app_context():
            tx = PaystackTransaction(
                reference='PSK-VERIFY-SUCCESS',
                patient_id=self.patient_id,
                amount=500.0,
                currency='KES',
                destination_department='General OPD',
                status='pending'
            )
            db.session.add(tx)
            db.session.commit()

        mock_verify.return_value = {
            "paid": True,
            "status": "success",
            "reference": "PSK-VERIFY-SUCCESS",
            "amount": 500.0,
            "currency": "KES",
            "channel": "mobile_money"
        }

        # First verification settlement
        resp1 = self.client.post('/reception/paystack/verify/PSK-VERIFY-SUCCESS')
        self.assertEqual(resp1.status_code, 200)
        data1 = resp1.get_json()
        self.assertTrue(data1['paid'])
        self.assertEqual(data1['status'], 'success')
        self.assertIn('payment_id', data1)
        self.assertIn('receipt_number', data1)

        # Second repeat verification
        resp2 = self.client.post('/reception/paystack/verify/PSK-VERIFY-SUCCESS')
        self.assertEqual(resp2.status_code, 200)
        data2 = resp2.get_json()
        self.assertTrue(data2['paid'])
        self.assertEqual(data2['payment_id'], data1['payment_id'])
        self.assertEqual(data2['ticket_number'], data1['ticket_number'])

    def test_manual_cash_settlement_separate_accounting(self):
        """Manual cash settlement records Cash tender, authenticated actor, and not Paystack gateway."""
        self.login_as(self.cashier_user)

        resp = self.client.post('/reception/paystack/manual-settle', data={
            'patient_id': str(self.patient_id),
            'amount': '500.0',
            'reference': 'test-cash-request',
            'department': 'General OPD',
            'doctor_name': 'Dr. Kamau'
        }, follow_redirects=True)

        self.assertEqual(resp.status_code, 200)

        with self.app.app_context():
            payment = Payment.query.filter_by(patient_id=self.patient_id).first()
            self.assertIsNotNone(payment)
            self.assertEqual(payment.payment_method_summary, 'Cash')
            self.assertEqual(payment.cash_amount, 500.0)
            self.assertEqual(payment.mpesa_amount, 0.0)
            self.assertIsNone(payment.mpesa_reference)
            self.assertEqual(payment.cashier_name, self.cashier_user.full_name)

            invoice = payment.invoice
            self.assertEqual(invoice.status, 'paid')
            self.assertEqual(invoice.cashier_name, self.cashier_user.full_name)
            self.assertIsNotNone(invoice.queue_entry_id)


class TestPOSBillingRegressions(BaseBillingTestCase):
    """Regressions for POS un-invoiced staged item counting, partial payments, and split settlement."""

    def test_pos_totals_no_double_count_linked_staged_items(self):
        """POS counts only un-invoiced staged items + open invoice balance; no linked item double count."""
        with self.app.app_context():
            # 1. Create partially paid invoice for patient (subtotal 1000, paid 400, balance 600)
            inv = Invoice(
                invoice_number=Invoice.generate_invoice_number(db.session),
                patient_id=self.patient_id,
                subtotal=1000.0,
                discount_amount=0.0,
                tax_amount=0.0,
                total_due=1000.0,
                amount_paid=400.0,
                balance_due=600.0,
                status='partially_paid',
                cashier_name=self.cashier_user.full_name
            )
            db.session.add(inv)
            db.session.flush()

            # Linked staged item already on invoice
            linked_item = BillingItem(
                patient_id=self.patient_id,
                invoice_id=inv.id,
                service_type='laboratory',
                item_description='FBC Test',
                quantity=1,
                unit_price=1000.0,
                total_amount=1000.0,
                status='staged'
            )
            db.session.add(linked_item)

            # 2. Un-invoiced staged item (not yet on an invoice)
            un_invoiced_item = BillingItem(
                patient_id=self.patient_id,
                invoice_id=None,
                service_type='pharmacy',
                item_description='Paracetamol Syrup',
                quantity=1,
                unit_price=250.0,
                total_amount=250.0,
                status='staged'
            )
            db.session.add(un_invoiced_item)
            db.session.commit()

        # Query POS terminal
        self.login_as(self.cashier_user)
        resp = self.client.get(f'/billing/pos/{self.patient_id}')
        self.assertEqual(resp.status_code, 200)

        # Expected unpaid total = 600.0 (invoice balance) + 250.0 (un-invoiced staged item) = 850.0
        # If linked item was double counted, it would be 850 + 1000 = 1850!
        with self.app.app_context():
            un_invoiced = BillingItem.query.filter(
                BillingItem.patient_id == self.patient_id,
                BillingItem.status == 'staged',
                BillingItem.invoice_id.is_(None)
            ).all()
            open_invs = Invoice.query.filter(
                Invoice.patient_id == self.patient_id,
                Invoice.status.in_(['unpaid', 'partially_paid'])
            ).all()

            unpaid_total = round(
                sum(float(i.total_amount) for i in un_invoiced) +
                sum(float(inv.balance_due) for inv in open_invs),
                2
            )
            self.assertEqual(unpaid_total, 850.0)

    def test_pos_settlement_validates_patient_amounts_and_duplicate_reference(self):
        """Settlement validates patient folio, finite amounts, duplicate references, and cashier actor."""
        self.login_as(self.cashier_user)

        with self.app.app_context():
            invoice = Invoice(
                invoice_number='INV-TEST-SETTLE-001',
                patient_id=self.patient_id,
                subtotal=1500.0,
                total_due=1500.0,
                amount_paid=0.0,
                balance_due=1500.0,
                status='unpaid'
            )
            db.session.add(invoice)
            db.session.commit()
            inv_id = invoice.id

            # Create existing payment with reference MPESA-EXISTING-01
            existing_payment = Payment(
                receipt_number='RCP-EXISTING-01',
                invoice_id=inv_id,
                patient_id=self.patient_id,
                total_amount_paid=500.0,
                payment_method_summary='M-Pesa [MPESA-EXISTING-01]',
                mpesa_amount=500.0,
                mpesa_reference='MPESA-EXISTING-01',
                cashier_name=self.cashier_user.full_name
            )
            db.session.add(existing_payment)
            db.session.commit()

        # 1. Test duplicate M-Pesa reference rejection
        resp_dup = self.client.post(f'/billing/pos/settle/{inv_id}', data={'idempotency_key': __import__('uuid').uuid4().hex,
            'patient_id': str(self.patient_id),
            'mpesa_amount': '500.0',
            'mpesa_reference': 'MPESA-EXISTING-01'
        }, follow_redirects=True)
        self.assertEqual(resp_dup.status_code, 200)
        self.assertIn(b'Duplicate payment reference', resp_dup.data)

        # 2. Test patient mismatch rejection
        resp_mismatch = self.client.post(f'/billing/pos/settle/{inv_id}', data={
            'patient_id': '99999',
            'idempotency_key': __import__('uuid').uuid4().hex,
            'cash_amount': '500.0'
        }, follow_redirects=True)
        self.assertIn(b'Patient folio mismatch', resp_mismatch.data)

        # 3. Test repeat settlement guard on settled invoice
        with self.app.app_context():
            inv = Invoice.query.get(inv_id)
            inv.status = 'paid'
            inv.balance_due = 0.0
            db.session.commit()

        resp_repeat = self.client.post(f'/billing/pos/settle/{inv_id}', data={
            'patient_id': str(self.patient_id),
            'idempotency_key': __import__('uuid').uuid4().hex,
            'cash_amount': '100.0'
        }, follow_redirects=True)
        self.assertIn(b'already settled and cannot accept another payment', resp_repeat.data)


class TestCreditNotesAndWaiversGovernance(BaseBillingTestCase):
    """Governance tests: admin-only approvals, no self-approval, once-only transition, true approver."""

    def setUp(self):
        super().setUp()
        with self.app.app_context():
            self.invoice = Invoice(
                invoice_number='INV-TEST-GOV-001',
                patient_id=self.patient_id,
                subtotal=2000.0,
                total_due=2000.0,
                amount_paid=0.0,
                balance_due=2000.0,
                status='unpaid'
            )
            db.session.add(self.invoice)
            db.session.commit()
            self.invoice_id = self.invoice.id

    def test_unauthorized_non_admin_cannot_approve_credit_note_or_waiver(self):
        """Cashiers and non-admin users cannot approve credit notes or fee waivers."""
        with self.app.app_context():
            cn = CreditNote(
                credit_note_number='CRN-UNAUTH-001',
                invoice_id=self.invoice_id,
                patient_id=self.patient_id,
                amount=500.0,
                reason='billing_error',
                status='pending_approval',
                requested_by='Cashier Joyce Wambui'
            )
            fw = FeeWaiver(
                waiver_number='WVR-UNAUTH-001',
                invoice_id=self.invoice_id,
                patient_id=self.patient_id,
                amount=500.0,
                justification='Emergency',
                status='pending_approval',
                requested_by='Cashier Joyce Wambui'
            )
            db.session.add_all([cn, fw])
            db.session.commit()
            cn_id, fw_id = cn.id, fw.id

        # Cashier tries to approve
        self.login_as(self.cashier_user)

        resp_cn = self.client.post(f'/billing/credit-notes/{cn_id}/action', data={'action': 'approve'}, follow_redirects=True)
        self.assertIn(b'Only hospital administrators can approve', resp_cn.data)

        resp_fw = self.client.post(f'/billing/waivers/{fw_id}/action', data={'action': 'approve'}, follow_redirects=True)
        self.assertIn(b'Only hospital administrators can approve', resp_fw.data)

        with self.app.app_context():
            self.assertEqual(CreditNote.query.get(cn_id).status, 'pending_approval')
            self.assertEqual(FeeWaiver.query.get(fw_id).status, 'pending_approval')

    def test_cannot_self_approve_credit_note_or_waiver(self):
        """Admin who requested credit note/waiver cannot self-approve it."""
        with self.app.app_context():
            cn = CreditNote(
                credit_note_number='CRN-SELF-001',
                invoice_id=self.invoice_id,
                patient_id=self.patient_id,
                amount=300.0,
                reason='billing_error',
                status='pending_approval',
                requested_by=self.admin_user.full_name  # Requested by the same admin
            )
            db.session.add(cn)
            db.session.commit()
            cn_id = cn.id

        self.login_as(self.admin_user)
        resp = self.client.post(f'/billing/credit-notes/{cn_id}/action', data={'action': 'approve'}, follow_redirects=True)
        self.assertIn(b'Self-approval of credit notes is strictly prohibited', resp.data)

        with self.app.app_context():
            self.assertEqual(CreditNote.query.get(cn_id).status, 'pending_approval')

    def test_credit_note_reconciles_balances_and_marks_cancelled_not_paid(self):
        """Credit note reducing balance to 0 marks no-cash invoice 'cancelled', never 'paid'."""
        with self.app.app_context():
            cn = CreditNote(
                credit_note_number='CRN-CANCEL-001',
                invoice_id=self.invoice_id,
                patient_id=self.patient_id,
                amount=2000.0,  # Covers full balance
                reason='service_cancelled',
                status='pending_approval',
                requested_by='Cashier Joyce Wambui'
            )
            db.session.add(cn)
            db.session.commit()
            cn_id = cn.id

        self.login_as(self.admin_user)
        resp = self.client.post(f'/billing/credit-notes/{cn_id}/action', data={'action': 'approve'}, follow_redirects=True)
        self.assertEqual(resp.status_code, 200)

        with self.app.app_context():
            cn_updated = CreditNote.query.get(cn_id)
            self.assertEqual(cn_updated.status, 'approved')
            self.assertEqual(cn_updated.approved_by, self.admin_user.full_name)

            invoice = Invoice.query.get(self.invoice_id)
            self.assertEqual(invoice.balance_due, 0.0)
            # Reconcile discount: discount_amount is 2000
            self.assertEqual(invoice.discount_amount, 2000.0)
            self.assertEqual(invoice.total_due, 0.0)
            # Must NOT be marked 'paid' since no money was collected!
            self.assertEqual(invoice.status, 'cancelled')

    def test_paid_invoice_refund_rejected_with_actionable_message(self):
        """Credit note on an already paid invoice rejects approval with actionable message."""
        with self.app.app_context():
            inv = Invoice.query.get(self.invoice_id)
            inv.status = 'paid'
            inv.amount_paid = 2000.0
            inv.balance_due = 0.0

            cn = CreditNote(
                credit_note_number='CRN-REFUND-001',
                invoice_id=self.invoice_id,
                patient_id=self.patient_id,
                amount=500.0,
                reason='overpayment',
                status='pending_approval',
                requested_by='Cashier Joyce Wambui'
            )
            db.session.add(cn)
            db.session.commit()
            cn_id = cn.id

        self.login_as(self.admin_user)
        resp = self.client.post(f'/billing/credit-notes/{cn_id}/action', data={'action': 'approve'}, follow_redirects=True)
        self.assertIn(b'Paid-invoice refunds require explicit reverse-payment accounting', resp.data)

        with self.app.app_context():
            self.assertEqual(CreditNote.query.get(cn_id).status, 'pending_approval')

    def test_repeat_approval_transition_applied_once(self):
        """Repeat approval attempts on already approved waiver or credit note are blocked."""
        with self.app.app_context():
            fw = FeeWaiver(
                waiver_number='WVR-ONCE-001',
                invoice_id=self.invoice_id,
                patient_id=self.patient_id,
                amount=200.0,
                category='indigent_patient',
                justification='Needy patient',
                status='pending_approval',
                requested_by='Cashier Joyce Wambui'
            )
            db.session.add(fw)
            db.session.commit()
            fw_id = fw.id

        self.login_as(self.admin_user)
        # First approval
        resp1 = self.client.post(f'/billing/waivers/{fw_id}/action', data={'action': 'approve'}, follow_redirects=True)
        self.assertIn(b'approved', resp1.data)

        # Second approval attempt
        resp2 = self.client.post(f'/billing/waivers/{fw_id}/action', data={'action': 'approve'}, follow_redirects=True)
        self.assertIn(b'already been processed', resp2.data)


class TestInsurancePreauthDesk(BaseBillingTestCase):
    """Insurance preauth creation starts pending, requires provider code to approve, validates status."""

    def test_preauth_creation_starts_pending_without_fake_code(self):
        """Preauth without explicit approval code starts as preauth_pending with approved_amount=0.0."""
        with self.app.app_context():
            inv = Invoice(
                invoice_number='INV-INS-001',
                patient_id=self.patient_id,
                subtotal=3000.0,
                total_due=3000.0,
                amount_paid=0.0,
                balance_due=3000.0,
                status='unpaid'
            )
            db.session.add(inv)
            db.session.commit()
            inv_id = inv.id

        self.login_as(self.cashier_user)
        resp = self.client.post('/billing/claims/create-preauth', data={
            'invoice_id': str(inv_id),
            'scheme_id': str(self.scheme_id),
            'member_number': 'JUB-M-88910',
            'policy_number': 'POL-992',
            'claimed_amount': '3000.0',
            'preauth_code': ''  # Leave blank: pending insurer approval
        }, follow_redirects=True)

        self.assertEqual(resp.status_code, 200)

        with self.app.app_context():
            claim = InsuranceClaim.query.filter_by(invoice_id=inv_id).first()
            self.assertIsNotNone(claim)
            self.assertEqual(claim.status, 'preauth_pending')
            self.assertIsNone(claim.preauth_code)
            self.assertEqual(claim.approved_amount, 0.0)

    def test_preauth_approval_requires_explicit_provider_code(self):
        """Transitioning to preauth_approved requires recorded provider approval code."""
        with self.app.app_context():
            inv = Invoice(
                invoice_number='INV-INS-002',
                patient_id=self.patient_id,
                subtotal=2000.0,
                total_due=2000.0,
                amount_paid=0.0,
                balance_due=2000.0,
                status='unpaid'
            )
            db.session.add(inv)
            db.session.flush()

            claim = InsuranceClaim(
                claim_number='CLM-PREAUTH-001',
                invoice_id=inv.id,
                patient_id=self.patient_id,
                scheme_id=self.scheme_id,
                scheme_name='Jubilee Health Insurance',
                member_number='JUB-1234',
                claimed_amount=2000.0,
                approved_amount=0.0,
                copay_amount=200.0,
                status='preauth_pending',
                created_by=self.cashier_user.full_name
            )
            db.session.add(claim)
            db.session.commit()
            claim_id = claim.id

        self.login_as(self.cashier_user)

        # Attempt to approve without code
        resp_no_code = self.client.post(f'/billing/claims/{claim_id}/update-status', data={
            'status': 'preauth_approved',
            'preauth_code': ''
        }, follow_redirects=True)
        self.assertIn(b'Provider Pre-Authorisation Approval Code is required', resp_no_code.data)

        with self.app.app_context():
            self.assertEqual(InsuranceClaim.query.get(claim_id).status, 'preauth_pending')

        # Approve with explicit provider code
        resp_with_code = self.client.post(f'/billing/claims/{claim_id}/update-status', data={
            'status': 'preauth_approved',
            'preauth_code': 'JUB-AUTH-77889'
        }, follow_redirects=True)
        self.assertIn(b'updated to Preauth Approved', resp_with_code.data)

        with self.app.app_context():
            claim_approved = InsuranceClaim.query.get(claim_id)
            self.assertEqual(claim_approved.status, 'preauth_approved')
            self.assertEqual(claim_approved.preauth_code, 'JUB-AUTH-77889')
            # Approved amount = claimed - copay = 2000 - 200 = 1800
            self.assertEqual(claim_approved.approved_amount, 1800.0)


if __name__ == '__main__':
    unittest.main()
