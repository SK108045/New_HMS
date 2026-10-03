import io
import os
from pathlib import Path
from unittest.mock import Mock, patch
from PIL import Image
from werkzeug.datastructures import FileStorage
from sqlalchemy import text
from models import db, AuditLog, PatientOTP, SMSLog, ClinicalDocument, User, RolePermission
from services.private_files import store_document, store_photo, private_path
from services.sms_service import SMSService
from tests.support import AppTestCase


class PlatformIntegrityTests(AppTestCase):
    def test_startup_does_not_seed_users_or_regrant_revoked_permissions(self):
        from app import seed_security_catalog
        self.assertEqual(User.query.count(), 0)
        RolePermission.query.filter_by(role='doctor', permission_code='clinical:prescribe').delete()
        seed_security_catalog()
        self.assertIsNone(RolePermission.query.filter_by(role='doctor', permission_code='clinical:prescribe').first())

    def test_audit_rolls_back_with_caller_transaction(self):
        p = self.patient()
        p.full_name = 'Uncommitted'
        AuditLog.log_event('test', 'patient', p.id)
        db.session.rollback()
        self.assertEqual(db.session.get(type(p), p.id).full_name, 'Test Patient')
        self.assertEqual(AuditLog.query.filter_by(action='test').count(), 0)

    def test_uploads_validate_content_and_strip_image_metadata(self):
        with self.assertRaises(ValueError):
            store_document(FileStorage(stream=io.BytesIO(b'<script>alert(1)</script>'), filename='scan.jpg'))
        with self.assertRaises(ValueError):
            store_document(FileStorage(stream=io.BytesIO(b'not pdf'), filename='scan.pdf'))
        image = io.BytesIO()
        Image.new('RGB', (2, 2), 'blue').save(image, 'PNG')
        name = store_photo(image.getvalue() + b'<script>trailing content</script>')
        path = private_path('photos/' + name)
        self.assertNotIn(b'<script>', path.read_bytes())
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        with self.assertRaises(ValueError):
            private_path('../app.py')
        with self.assertRaises(ValueError):
            private_path('/etc/passwd')

    def test_patient_files_require_fully_verified_authorization(self):
        patient = self.patient()
        pdf = FileStorage(stream=io.BytesIO(b'%PDF-1.4\n%%EOF\n'), filename='report.pdf')
        metadata = store_document(pdf)
        doc = ClinicalDocument(document_number='TEST-DOC', patient_id=patient.id,
                               document_type='lab_report', title='Report', **metadata)
        db.session.add(doc); db.session.commit()
        for path in ['/documents/view/' + str(doc.id), '/patients/' + str(patient.id) + '/photo']:
            self.assertIn(self.client.get(path).status_code, (302, 403))
        self.assertEqual(self.client.get('/static/uploads/documents/report.pdf').status_code, 404)
        user = self.user(); self.sign_in(user)
        response = self.client.get('/documents/view/' + str(doc.id))
        self.assertEqual(response.status_code, 200)
        self.assertIn('no-store', response.headers['Cache-Control'])
        user.force_password_change = True; db.session.commit()
        self.assertEqual(self.client.get('/documents/view/' + str(doc.id)).status_code, 302)
        self.assertEqual(self.client.get('/patients/' + str(patient.id) + '/photo').status_code, 302)

    def test_live_sms_without_credentials_fails_instead_of_simulating(self):
        with patch.dict(os.environ, {'AFRICASTALKING_USERNAME': '', 'AFRICASTALKING_API_KEY': ''}):
            service = SMSService()
        result = service.send_sms('+254700000001', 'hello', is_live=True)
        self.assertFalse(result['success'])
        self.assertFalse(result['simulated'])
        self.assertEqual(SMSLog.query.get(result['log_id']).status, 'Failed')
        result = service.send_sms('+254700000001', 'hello', is_live=False)
        self.assertTrue(result['simulated'])
        self.assertEqual(SMSLog.query.get(result['log_id']).status, 'Simulated')

    def test_otp_hashed_redacted_one_use_and_attempt_limited(self):
        with patch.dict(os.environ, {'AFRICASTALKING_USERNAME': '', 'AFRICASTALKING_API_KEY': ''}):
            service = SMSService()
        service._initialized = True
        service.sms = Mock()
        service.sms.send.return_value = {'SMSMessageData': {'Recipients': [{'status': 'Success', 'statusCode': 101}]}}
        with patch('services.sms_service.secrets.randbelow', return_value=123456):
            result = service.generate_and_send_otp(None, '+254700000001', is_live=True)
        self.assertNotIn('otp_code_preview', result)
        record = PatientOTP.query.get(result['otp_id'])
        self.assertEqual(record.otp_code, '')
        self.assertNotEqual(record.otp_hash, '123456')
        self.assertNotIn('123456', SMSLog.query.get(result['log_id']).message_text)
        self.assertTrue(service.verify_otp(record.phone, '123456')['verified'])
        self.assertFalse(service.verify_otp(record.phone, '123456')['verified'])
        with patch('services.sms_service.secrets.randbelow', return_value=654321):
            result = service.generate_and_send_otp(None, '+254700000003', is_live=True)
        for _ in range(5):
            self.assertFalse(service.verify_otp('+254700000003', '000000')['verified'])
        self.assertFalse(service.verify_otp('+254700000003', '654321')['verified'])

    def test_migrations_record_versions_and_repeat_safely(self):
        from migrations import upgrade_database
        upgrade_database(); upgrade_database()
        versions = db.session.execute(text('SELECT revision FROM schema_migrations ORDER BY revision')).scalars().all()
        self.assertEqual(versions, ['0001_legacy_security', '0002_integrity_controls'])

    def test_csrf_forms_and_ajax_accept_valid_token_reject_tampering(self):
        import re
        self.app.config['WTF_CSRF_ENABLED'] = True
        user = self.user(role='receptionist', portal='reception')
        blocked = self.client.post('/login/reception', data={'username': user.username, 'password': 'Test!Password123'})
        self.assertEqual(blocked.status_code, 400)
        page = self.client.get('/login/reception')
        token = re.search(r'name="csrf_token"\s+value="([^"]+)"', page.get_data(as_text=True)).group(1)
        response = self.client.post('/login/reception', data={'username': user.username, 'password': 'Test!Password123', 'csrf_token': token})
        self.assertEqual(response.status_code, 302)
        dashboard = self.client.get('/reception/dashboard')
        token = re.search(r'name="csrf-token"\s+content="([^"]+)"', dashboard.get_data(as_text=True)).group(1)
        forged = self.client.post('/reception/paystack/prompt', json={}, headers={'X-CSRFToken': 'tampered'})
        self.assertEqual(forged.status_code, 400)
        self.assertIn('CSRF', forged.get_json()['error'])
        valid = self.client.post('/reception/paystack/prompt', json={}, headers={'X-CSRFToken': token})
        self.assertNotIn('CSRF', valid.get_json().get('error', ''))

    def test_identifier_allocation_is_atomic_and_does_not_reuse_deleted_ids(self):
        from models import Patient, QueueEntry
        first = Patient.generate_hospital_id(db.session)
        second = Patient.generate_hospital_id(db.session)
        self.assertNotEqual(first, second)
        db.session.commit()
        self.assertNotEqual(second, Patient.generate_hospital_id(db.session))
        self.assertNotEqual(QueueEntry.generate_daily_ticket(db.session), QueueEntry.generate_daily_ticket(db.session))
