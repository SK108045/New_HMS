import hashlib
import hmac
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta, datetime
from threading import Barrier

from models import (db, PaystackTransaction, Payment, Invoice, QueueEntry, MedicationItem,
                    DrugBatch, Prescription, DispensationRecord, Ward, Bed, Admission,
                    BillingItem, User, SecuritySetting)
from services.paystack_service import paystack_service
from tests.support import AppTestCase, authenticate


class ConcurrencyAndCallbackTests(AppTestCase):
    def parallel(self, operations):
        barrier = Barrier(len(operations))
        db.session.remove()
        def run(operation):
            with self.app.app_context():
                barrier.wait(timeout=10)
                return operation()
        with ThreadPoolExecutor(max_workers=len(operations)) as pool:
            return list(pool.map(run, operations))

    def clients_for(self, user):
        clients = [self.app.test_client(), self.app.test_client()]
        for client in clients:
            authenticate(client, self.app, user)
        return clients

    def pending_payment(self):
        patient = self.patient()
        tx = PaystackTransaction(reference='HMS-concurrent-test', patient_id=patient.id,
                                amount=500, currency='KES', status='pending')
        db.session.add(tx); db.session.commit()
        return tx.reference

    def test_simultaneous_provider_settlement_issues_one_receipt_and_queue_entry(self):
        reference = self.pending_payment()
        def settle():
            return paystack_service.settle_consultation_payment(reference, verification={
                'paid': True, 'status': 'success', 'reference': reference, 'currency': 'KES', 'amount': 500})
        outcomes = self.parallel([settle, settle])
        self.assertEqual(outcomes[0]['payment_id'], outcomes[1]['payment_id'])
        self.assertEqual((Payment.query.count(), Invoice.query.count(), QueueEntry.query.count()), (1, 1, 1))
        tx = PaystackTransaction.query.one()
        self.assertIsNotNone(tx.queue_entry_id)
        self.assertEqual(tx.invoice.queue_entry_id, tx.queue_entry_id)

    def test_signed_webhook_checks_amount_currency_signature_and_replays_safely(self):
        reference = self.pending_payment()
        self.app.config['PAYSTACK_SECRET_KEY'] = 'test-webhook-secret'
        self.app.config['WTF_CSRF_ENABLED'] = True
        def send(amount=50000, currency='KES', signature=True):
            body = json.dumps({'event': 'charge.success', 'data': {'reference': reference,
                              'status': 'success', 'amount': amount, 'currency': currency}}).encode()
            digest = hmac.new(b'test-webhook-secret', body, hashlib.sha512).hexdigest() if signature else 'tampered'
            return self.client.post('/webhooks/paystack', data=body, content_type='application/json',
                                    headers={'X-Paystack-Signature': digest})
        self.assertEqual(send(signature=False).status_code, 403)
        self.assertEqual(send(amount=1).status_code, 400)
        self.assertEqual(send(currency='USD').status_code, 400)
        self.assertEqual(Payment.query.count(), 0)
        self.assertEqual(send().status_code, 200)
        self.assertEqual(send().status_code, 200)
        self.assertEqual(Payment.query.count(), 1)

    def test_simultaneous_dispensing_reduces_stock_once(self):
        patient = self.patient(); staff = self.user('pharmacist', 'pharmacy')
        med = MedicationItem(name='Test drug', category='Test', strength='5mg', current_stock=40, unit_price=10)
        db.session.add(med); db.session.flush()
        batch = DrugBatch(medication_id=med.id, batch_number='TEST-1', quantity_received=40,
                         quantity_remaining=40, expiry_date=date.today() + timedelta(days=90), status='active')
        rx = Prescription(rx_number='RX-CONCURRENT', patient_id=patient.id, doctor_name='Test physician',
                          medications_json=json.dumps([{'medication_id': med.id, 'drug': med.name,
                                                        'dosage': '5mg', 'quantity': 10, 'cost': 100}]))
        db.session.add_all([batch, rx]); db.session.commit()
        batch_id, rx_id, med_id = batch.id, rx.id, med.id
        clients = self.clients_for(staff)
        def request_for(client):
            return lambda: client.post(f'/pharmacy/dispense/{rx_id}', data={
                'batch_id_0': str(batch_id), 'qty_dispensed_0': '10'}).status_code
        self.assertEqual(self.parallel([request_for(c) for c in clients]), [302, 302])
        self.assertEqual(DispensationRecord.query.count(), 1)
        self.assertEqual(db.session.get(DrugBatch, batch_id).quantity_remaining, 30)
        self.assertEqual(db.session.get(MedicationItem, med_id).current_stock, 30)

    def test_simultaneous_admission_to_different_beds_reserves_one(self):
        patient = self.patient(); staff = self.user()
        ward = Ward(name='Test Ward', code='TEST'); db.session.add(ward); db.session.flush()
        beds = [Bed(ward_id=ward.id, bed_number=str(i), daily_rate=1500) for i in (1, 2)]
        db.session.add_all(beds); db.session.commit()
        patient_id, ward_id = patient.id, ward.id
        bed_ids = [bed.id for bed in beds]; clients = self.clients_for(staff)
        operations = [lambda c=c, b=b: c.post('/inpatient/admit', data={
            'patient_id': str(patient_id), 'ward_id': str(ward_id), 'bed_id': str(b),
            'admitting_doctor': 'Test physician', 'admitting_diagnosis': 'Observation'}).status_code
            for c, b in zip(clients, bed_ids)]
        self.assertEqual(self.parallel(operations), [302, 302])
        self.assertEqual(Admission.query.filter_by(status='admitted').count(), 1)
        self.assertEqual(Bed.query.filter_by(status='occupied').count(), 1)

    def test_simultaneous_discharge_adds_accommodation_once(self):
        patient = self.patient(); staff = self.user()
        ward = Ward(name='Test Ward', code='TEST'); db.session.add(ward); db.session.flush()
        bed = Bed(ward_id=ward.id, bed_number='1', daily_rate=1500, status='occupied')
        db.session.add(bed); db.session.flush()
        adm = Admission(admission_number='ADM-CONCURRENT', patient_id=patient.id, ward_id=ward.id,
                        bed_id=bed.id, initial_bed_rate=1500, admitting_doctor='Test physician',
                        admitting_diagnosis='Observation', admitted_at=datetime.utcnow() - timedelta(hours=2))
        db.session.add(adm); db.session.commit(); adm_id = adm.id
        clients = self.clients_for(staff)
        outcomes = self.parallel([lambda c=c: c.post(f'/inpatient/patient/{adm_id}/discharge', data={
            'discharge_summary': 'Stable', 'discharge_instructions': 'Follow up with clinician', 'condition_on_discharge': 'Improved'}).status_code for c in clients])
        self.assertEqual(outcomes, [302, 302])
        self.assertEqual(Invoice.query.count(), 1)
        self.assertEqual(BillingItem.query.count(), 1)
        self.assertEqual(Invoice.query.one().total_due, 1500)

    def test_partial_checkout_replay_and_unapproved_discount_preserve_balances(self):
        patient = self.patient(); staff = self.user('cashier', 'billing'); self.sign_in(staff)
        inv = Invoice(invoice_number='INV-PARTIAL', patient_id=patient.id, subtotal=1000, discount_amount=100,
                      tax_amount=50, total_due=950, amount_paid=0, balance_due=950, status='unpaid')
        db.session.add(inv); db.session.commit(); inv_id = inv.id
        path = f'/billing/pos/settle/{inv_id}'
        form = {'idempotency_key': 'partial-unique', 'cash_amount': '300'}
        first = self.client.post(path, data=form)
        second = self.client.post(path, data=form)
        self.assertEqual(first.headers['Location'], second.headers['Location'])
        self.client.post(path, data={'idempotency_key': 'bad-discount', 'cash_amount': '200', 'discount_amount': '10'})
        db.session.expire_all(); invoice = db.session.get(Invoice, inv_id)
        self.assertEqual((invoice.amount_paid, invoice.balance_due, invoice.discount_amount), (300, 650, 100))
        self.assertEqual(Payment.query.count(), 1)

    def test_pending_2fa_cannot_survive_password_reset(self):
        import pyotp
        staff = self.user('doctor', 'doctor')
        staff.totp_secret = pyotp.random_base32(); staff.is_2fa_enabled = True
        secret, user_id = staff.totp_secret, staff.id
        db.session.commit()
        response = self.client.post('/login/doctor', data={'username': staff.username, 'password': 'Test!Password123'})
        self.assertIn('/verify-2fa', response.headers['Location'])
        staff.set_password('Replacement!Password123', force_change=False); db.session.commit()
        self.client.post('/verify-2fa', data={'totp_code': pyotp.TOTP(secret).now()})
        with self.client.session_transaction() as values:
            self.assertNotIn('user_id', values)
            self.assertNotIn('pending_2fa_user_id', values)
        self.assertEqual(db.session.get(User, user_id).auth_version, 2)

    def test_simultaneous_backup_code_signins_consume_code_once(self):
        import pyotp
        from auth.decorators import stage_auth
        from flask import session
        staff = self.user('doctor', 'doctor')
        staff.totp_secret = pyotp.random_base32(); staff.is_2fa_enabled = True
        code = staff.generate_backup_codes(count=1)[0]; db.session.commit()
        clients = [self.app.test_client(), self.app.test_client()]
        with self.app.test_request_context():
            stage_auth(staff, 'pending_2fa_user_id')
            values = dict(session)
        for client in clients:
            with client.session_transaction() as target: target.update(values)
        self.parallel([lambda c=c: c.post('/verify-2fa', data={
            'totp_code': code, 'use_backup': 'true'}).status_code for c in clients])
        signed_in = 0
        for client in clients:
            with client.session_transaction() as target: signed_in += bool(target.get('user_id'))
        self.assertEqual(signed_in, 1)

    def test_mandatory_enrollment_commits_new_session_and_invalidates_old_token(self):
        import pyotp
        staff = self.user('doctor', 'doctor')
        settings = SecuritySetting.get_settings(); settings.require_2fa_for_admin_doctor = True
        db.session.commit()
        token = staff.get_2fa_onboarding_token(self.app.config['SECRET_KEY'])
        self.client.post('/login/doctor', data={'username': staff.username, 'password': 'Test!Password123'})
        self.assertEqual(self.client.get('/setup-2fa').status_code, 200)
        db.session.expire_all(); secret = db.session.get(User, staff.id).totp_secret
        response = self.client.post('/setup-2fa', data={'verification_code': pyotp.TOTP(secret).now()})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.client.get('/doctor/dashboard').status_code, 200)
        db.session.expire_all(); user = db.session.get(User, staff.id)
        user.is_2fa_enabled = False; user.auth_version += 1; db.session.commit()
        self.assertIsNone(User.verify_2fa_onboarding_token(token, self.app.config['SECRET_KEY']))
        self.assertEqual(self.client.get('/doctor/dashboard').status_code, 302)

    def test_revoked_patient_view_denies_get_and_head_and_mutation_permissions_cover_routes(self):
        from auth.policy import ENDPOINT_PERMISSIONS
        from models import RolePermission
        staff = self.user('pharmacist', 'pharmacy')
        RolePermission.query.filter_by(role='pharmacist', permission_code='patient:view').delete()
        db.session.commit(); self.sign_in(staff)
        for method in ('GET', 'HEAD'):
            for path in ('/pharmacy/prescription/999/print', '/pharmacy/label/999', '/pharmacy/dispense/999'):
                self.assertEqual(self.client.open(path, method=method).status_code, 403)
        for rule in self.app.url_map.iter_rules():
            if rule.endpoint.startswith(('reception.', 'doctor.', 'pharmacy.', 'billing.', 'triage.', 'inpatient.', 'admin.')):
                if 'POST' in rule.methods and not rule.endpoint.endswith(('.login', '.logout')):
                    self.assertIn((rule.endpoint, 'POST'), ENDPOINT_PERMISSIONS, rule.endpoint)
