import os
import sys
import json
import tempfile
import unittest
from datetime import datetime, date, timedelta
from decimal import Decimal

# Ensure project root is on python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from config import Config

class TestConfig(Config):
    TESTING = True
    WTF_CSRF_ENABLED = False
    CONSULTATION_FEE = 500.0
    AUTO_INIT_DB = False
    SEED_DEMO_DATA = False

class ClinicalWorkflowsTestCase(unittest.TestCase):
    def setUp(self):
        # Create isolated temporary SQLite database for every test run
        self.temp_db_fd, self.temp_db_path = tempfile.mkstemp(suffix='_test.db')
        self.temp_upload_dir = tempfile.mkdtemp(suffix='_uploads')

        TestConfig.SQLALCHEMY_DATABASE_URI = f"sqlite:///{self.temp_db_path}"
        TestConfig.PRIVATE_UPLOAD_FOLDER = os.path.join(self.temp_upload_dir, 'private')
        TestConfig.UPLOAD_FOLDER = os.path.join(self.temp_upload_dir, 'public')

        from app import create_app
        self.app = create_app(TestConfig)
        self.client = self.app.test_client()

        with self.app.app_context():
            from models import db
            self.db = db
            self.db.create_all()
            from app import seed_security_catalog
            seed_security_catalog()
            from models import SecuritySetting
            settings = SecuritySetting.get_settings()
            settings.require_2fa_for_admin_doctor = False
            self.db.session.commit()
            self._seed_test_users()

    def tearDown(self):
        with self.app.app_context():
            self.db.session.remove()
            self.db.drop_all()

        try:
            os.close(self.temp_db_fd)
            if os.path.exists(self.temp_db_path):
                os.remove(self.temp_db_path)
        except Exception:
            pass

        import shutil
        try:
            shutil.rmtree(self.temp_upload_dir, ignore_errors=True)
        except Exception:
            pass

    def _seed_test_users(self):
        from models import User, RolePermission, Permission
        from werkzeug.security import generate_password_hash

        # Canonical doctor & pharmacist
        doc = User(
            username='dr_test',
            email='dr_test@hospital.org',
            password_hash=generate_password_hash('Pass@123'),
            role='doctor',
            full_name='Dr. Test Physician',
            staff_id='STF-DOC-01',
            portal='doctor',
            status='active', department='Testing', custom_permissions_json='["inpatient:admit", "inpatient:transfer"]'
        )
        pharm = User(
            username='pharm_test',
            email='pharm_test@hospital.org',
            password_hash=generate_password_hash('Pass@123'),
            role='pharmacist',
            full_name='Pharm. Test Pharmacist',
            staff_id='STF-PHARM-01',
            portal='pharmacy',
            status='active', department='Testing'
        )
        self.db.session.add_all([doc, pharm])
        self.db.session.commit()

    def _login(self, user):
        from tests.support import authenticate
        authenticate(self.client, self.app, user)

    # ================= 1. LAB INBOX TESTS =================
    def test_empty_lab_inbox_get_never_invents_results(self):
        """GET /doctor/lab_results must never invent or persist results into the database."""
        with self.app.app_context():
            from models import Patient, LabOrder, User
            doc = User.query.filter_by(username='dr_test').first()
            p = Patient(
                hospital_id='HSP-TEST-001',
                first_name='John',
                last_name='Doe',
                full_name='John Doe',
                phone='0711000000',
                date_of_birth=date(1990, 1, 1),
                gender='Male',
                next_of_kin_name='Jane Doe',
                next_of_kin_phone='0722000000',
                next_of_kin_relation='Spouse'
            )
            self.db.session.add(p)
            self.db.session.flush()

            order = LabOrder(
                order_number='LAB-TEST-0001',
                patient_id=p.id,
                doctor_name=doc.full_name,
                tests_json=json.dumps([{"id": "FBC", "name": "Full Blood Count"}]),
                status='pending',
                result_data=None
            )
            self.db.session.add(order)
            self.db.session.commit()

            order_id = order.id

        self._login(doc)
        res = self.client.get('/doctor/lab_results')
        self.assertEqual(res.status_code, 200)
        self.assertIn(b'LAB-TEST-0001', res.data)
        self.assertIn(b'Awaiting Lab Results', res.data)

        # Ensure database record was NOT mutated with fabricated findings
        with self.app.app_context():
            from models import LabOrder
            reloaded = LabOrder.query.get(order_id)
            self.assertIsNone(reloaded.result_data)
            self.assertEqual(reloaded.status, 'pending')

    def test_lab_results_review_gating_and_recording(self):
        """Only completed results can be signed off; POST record_lab_results records provenance and sets completed."""
        with self.app.app_context():
            from models import Patient, LabOrder, User
            doc = User.query.filter_by(username='dr_test').first()
            p = Patient(
                hospital_id='HSP-TEST-002',
                first_name='Alice',
                last_name='Wanjiru',
                full_name='Alice Wanjiru',
                phone='0711000001',
                date_of_birth=date(1985, 5, 12),
                gender='Female',
                next_of_kin_name='Bob Wanjiru',
                next_of_kin_phone='0722000001',
                next_of_kin_relation='Brother'
            )
            self.db.session.add(p)
            self.db.session.flush()

            order = LabOrder(
                order_number='LAB-TEST-0002',
                patient_id=p.id,
                doctor_name=doc.full_name,
                tests_json=json.dumps([{"id": "BS_MALARIA", "name": "Malaria Blood Slide"}]),
                status='pending',
                result_data=None
            )
            self.db.session.add(order)
            self.db.session.commit()
            order_id = order.id

        self._login(doc)

        # 1. Attempting to review a pending order should be blocked
        review_res = self.client.post(f'/doctor/lab_results/{order_id}/review', follow_redirects=True)
        self.assertIn(b'Only completed lab results can be reviewed', review_res.data)

        with self.app.app_context():
            from models import LabOrder
            o = LabOrder.query.get(order_id)
            self.assertFalse(o.reviewed_by_doctor)

        # 2. Record deliberate structured lab results
        record_res = self.client.post(
            f'/doctor/lab_results/{order_id}/record',
            data={
                'result_Malaria Blood Slide': 'Negative for Plasmodium trophozoites',
                'findings': 'Slide clear, no parasites identified.'
            },
            follow_redirects=True
        )
        self.assertEqual(record_res.status_code, 200)

        # Verify completed status & provenance in database
        with self.app.app_context():
            from models import LabOrder
            completed_order = LabOrder.query.get(order_id)
            self.assertEqual(completed_order.status, 'completed')
            self.assertIsNotNone(completed_order.result_data)
            data_dict = json.loads(completed_order.result_data)
            self.assertIn('Malaria Blood Slide', data_dict)
            self.assertIn('_provenance', data_dict)
            self.assertEqual(data_dict['_provenance']['recorded_by'], self.db.session.get(User, __import__('sqlalchemy').inspect(doc).identity[0]).full_name)

        # 3. Now review/sign-off succeeds
        final_review = self.client.post(f'/doctor/lab_results/{order_id}/review', follow_redirects=True)
        self.assertEqual(final_review.status_code, 200)
        with self.app.app_context():
            from models import LabOrder
            signed = LabOrder.query.get(order_id)
            self.assertTrue(signed.reviewed_by_doctor)
            self.assertIsNotNone(signed.reviewed_at)

    # ================= 2. CONSULTATION DUPLICATE FEE PREVENTION =================
    def test_consultation_duplicate_fee_prevention(self):
        """If same queue entry already has paid consultation BillingItem, don't stage another. Use CONSULTATION_FEE=500."""
        with self.app.app_context():
            from models import Patient, QueueEntry, BillingItem, User
            doc = User.query.filter_by(username='dr_test').first()
            p = Patient(
                hospital_id='HSP-TEST-003',
                first_name='Grace',
                last_name='Achieng',
                full_name='Grace Achieng',
                phone='0711000002',
                date_of_birth=date(1995, 3, 20),
                gender='Female',
                next_of_kin_name='Peter Achieng',
                next_of_kin_phone='0722000002',
                next_of_kin_relation='Father'
            )
            self.db.session.add(p)
            self.db.session.flush()

            q1 = QueueEntry(
                ticket_number='T-101',
                patient_id=p.id,
                stage='consultation',
                status='in_progress',
                assigned_doctor=doc.full_name
            )
            q2 = QueueEntry(
                ticket_number='T-102',
                patient_id=p.id,
                stage='consultation',
                status='in_progress',
                assigned_doctor=doc.full_name
            )
            self.db.session.add_all([q1, q2])
            self.db.session.flush()

            # Q1 already has a paid consultation item at reception/triage
            paid_fee = BillingItem(
                patient_id=p.id,
                queue_entry_id=q1.id,
                service_type='consultation',
                item_description='Paid Doctor Consultation',
                quantity=1,
                unit_price=500.0,
                total_amount=500.0,
                status='paid'
            )
            self.db.session.add(paid_fee)
            self.db.session.commit()
            q1_id = q1.id
            q2_id = q2.id

        self._login(doc)

        # Submit consultation for Q1 (already paid)
        res1 = self.client.post(f'/doctor/consultation/{q1_id}', data={
            'subjective_notes': 'Mild headache',
            'assessment_notes': 'Tension headache',
            'plan_notes': 'Rest and hydration'
        }, follow_redirects=True)
        self.assertEqual(res1.status_code, 200)

        # Submit consultation for Q2 (unpaid)
        res2 = self.client.post(f'/doctor/consultation/{q2_id}', data={
            'subjective_notes': 'Fever and chills',
            'assessment_notes': 'Suspected infection',
            'plan_notes': 'Hydration'
        }, follow_redirects=True)
        self.assertEqual(res2.status_code, 200)

        with self.app.app_context():
            from models import BillingItem
            # Q1 should have ONLY the 1 original paid item, NO second staged item
            q1_items = BillingItem.query.filter_by(queue_entry_id=q1_id, service_type='consultation').all()
            self.assertEqual(len(q1_items), 1)
            self.assertEqual(q1_items[0].status, 'paid')

            # Q2 should have exactly 1 staged consultation item with configured 500.0 fee
            q2_items = BillingItem.query.filter_by(queue_entry_id=q2_id, service_type='consultation').all()
            self.assertEqual(len(q2_items), 1)
            self.assertEqual(q2_items[0].status, 'staged')
            self.assertEqual(q2_items[0].unit_price, 500.0)
            self.assertEqual(q2_items[0].total_amount, 500.0)

    # ================= 3. PHARMACY MEDICATION MATCHING & VALIDATION =================
    def test_exact_medication_matching_and_ambiguity_rejection(self):
        """Prescription resolution uses medication_id or exact legacy match, rejecting ambiguity and strength mismatch."""
        with self.app.app_context():
            from models import MedicationItem, Prescription, Patient, User
            from pharmacy.routes import resolve_prescribed_medication

            med1 = MedicationItem(
                name='Amoxicillin 500mg Capsules',
                generic_name='Amoxicillin',
                category='Antibiotic',
                strength='500mg',
                current_stock=100,
                unit_price=30.0
            )
            med2 = MedicationItem(
                name='Amoxicillin 250mg Suspension',
                generic_name='Amoxicillin',
                category='Antibiotic',
                strength='250mg',
                current_stock=50,
                unit_price=45.0
            )
            self.db.session.add_all([med1, med2])
            self.db.session.commit()
            med1_id = med1.id
            med2_id = med2.id

            # 1. Match by medication_id
            item_with_id = {'medication_id': med1_id, 'drug': 'Amoxicillin 500mg', 'dosage': '500mg'}
            resolved, err = resolve_prescribed_medication(item_with_id)
            self.assertIsNone(err)
            self.assertEqual(resolved.id, med1_id)

            # 2. Strength mismatch with medication_id
            mismatch_item = {'medication_id': med1_id, 'drug': 'Amoxicillin 500mg', 'dosage': '250mg'}
            resolved, err = resolve_prescribed_medication(mismatch_item)
            self.assertIsNone(resolved)
            self.assertIn("Strength mismatch", err)

            # 3. Exact legacy name match
            exact_item = {'drug': 'Amoxicillin 500mg Capsules', 'dosage': '500mg'}
            resolved, err = resolve_prescribed_medication(exact_item)
            self.assertIsNone(err)
            self.assertEqual(resolved.id, med1_id)

            # 4. Ambiguity rejection on generic name when multiple exist
            ambiguous_item = {'drug': 'Amoxicillin'}
            resolved, err = resolve_prescribed_medication(ambiguous_item)
            self.assertIsNone(resolved)
            self.assertIn("Ambiguous", err)

            # 5. First-word fuzzy matching must NOT resolve
            fuzzy_item = {'drug': 'Amoxicillin syrup'}
            resolved, err = resolve_prescribed_medication(fuzzy_item)
            self.assertIsNone(resolved)

    # ================= 4. PHARMACY BATCH FILTERING & ATOMIC DISPENSE =================
    def test_invalid_batches_and_atomic_dispense(self):
        """Expired batches are excluded; over-quantity is rejected; valid dispense mutates inventory atomically."""
        with self.app.app_context():
            from models import Patient, MedicationItem, DrugBatch, Prescription, User
            pharm = User.query.filter_by(username='pharm_test').first()

            p = Patient(
                hospital_id='HSP-TEST-004',
                first_name='David',
                last_name='Kipkorir',
                full_name='David Kipkorir',
                phone='0711000003',
                date_of_birth=date(1988, 7, 10),
                gender='Male',
                next_of_kin_name='Sarah Kipkorir',
                next_of_kin_phone='0722000003',
                next_of_kin_relation='Spouse'
            )
            self.db.session.add(p)
            self.db.session.flush()

            med = MedicationItem(
                name='Paracetamol 500mg Tablets',
                category='Analgesic',
                strength='500mg',
                current_stock=50,
                unit_price=10.0
            )
            self.db.session.add(med)
            self.db.session.flush()

            # Active batch
            valid_batch = DrugBatch(
                medication_id=med.id,
                batch_number='BATCH-VALID-01',
                quantity_received=50,
                quantity_remaining=50,
                expiry_date=date.today() + timedelta(days=180),
                status='active'
            )
            # Expired batch
            expired_batch = DrugBatch(
                medication_id=med.id,
                batch_number='BATCH-EXP-02',
                quantity_received=50,
                quantity_remaining=30,
                expiry_date=date.today() - timedelta(days=10),
                status='active'
            )
            self.db.session.add_all([valid_batch, expired_batch])

            rx = Prescription(
                rx_number='RX-TEST-0001',
                patient_id=p.id,
                doctor_name='Dr. Test Physician',
                medications_json=json.dumps([{
                    'medication_id': med.id,
                    'drug': 'Paracetamol 500mg Tablets',
                    'dosage': '500mg',
                    'quantity': 10,
                    'cost': 100.0
                }]),
                status='pending_dispense'
            )
            self.db.session.add(rx)
            self.db.session.commit()

            rx_id = rx.id
            med_id = med.id
            valid_batch_id = valid_batch.id
            exp_batch_id = expired_batch.id

        self._login(pharm)

        # GET dispense view: verify expired batch is NOT listed
        get_res = self.client.get(f'/pharmacy/dispense/{rx_id}')
        self.assertEqual(get_res.status_code, 200)
        self.assertIn(b'BATCH-VALID-01', get_res.data)
        self.assertNotIn(b'BATCH-EXP-02', get_res.data)

        # POST with expired batch -> must be rejected
        bad_post = self.client.post(f'/pharmacy/dispense/{rx_id}', data={
            'pharmacist_name': 'Pharm. Test',
            'qty_dispensed_0': '10',
            'batch_id_0': str(exp_batch_id)
        }, follow_redirects=True)
        self.assertIn(b'expired', bad_post.data.lower())

        # POST with valid batch -> succeeds
        good_post = self.client.post(f'/pharmacy/dispense/{rx_id}', data={
            'pharmacist_name': 'Pharm. Test',
            'qty_dispensed_0': '10',
            'batch_id_0': str(valid_batch_id)
        }, follow_redirects=True)
        self.assertEqual(good_post.status_code, 200)

        # Verify stock decrement and dispensation record
        with self.app.app_context():
            from models import MedicationItem, DrugBatch, Prescription, DispensationRecord
            reloaded_med = MedicationItem.query.get(med_id)
            reloaded_batch = DrugBatch.query.get(valid_batch_id)
            reloaded_rx = Prescription.query.get(rx_id)

            self.assertEqual(reloaded_med.current_stock, 40)
            self.assertEqual(reloaded_batch.quantity_remaining, 40)
            self.assertEqual(reloaded_rx.status, 'dispensed')

            disp_rec = DispensationRecord.query.filter_by(prescription_id=rx_id).first()
            self.assertIsNotNone(disp_rec)

        # Attempt to re-dispense already dispensed prescription must be blocked
        re_dispense = self.client.post(f'/pharmacy/dispense/{rx_id}', data={
            'pharmacist_name': 'Pharm. Test',
            'qty_dispensed_0': '10',
            'batch_id_0': str(valid_batch_id)
        }, follow_redirects=True)
        self.assertIn(b'cannot be re-dispensed', re_dispense.data)

    # ================= 5. INPATIENT ADMISSION & EMERGENCY CONTACT =================
    def test_inpatient_admission_emergency_contact_fallback(self):
        """Inpatient admission falls back to patient's next_of_kin fields when optional emergency contact is empty."""
        with self.app.app_context():
            from models import Patient, Ward, Bed, User
            doc = User.query.filter_by(username='dr_test').first()

            p = Patient(
                hospital_id='HSP-TEST-005',
                first_name='Samuel',
                last_name='Mwangi',
                full_name='Samuel Mwangi',
                phone='0711000004',
                date_of_birth=date(1980, 4, 15),
                gender='Male',
                next_of_kin_name='Agnes Mwangi',
                next_of_kin_phone='0722999888',
                next_of_kin_relation='Spouse'
            )
            ward = Ward(name='Male Medical Ward', code='MMW', is_active=True)
            self.db.session.add_all([p, ward])
            self.db.session.flush()

            bed = Bed(ward_id=ward.id, bed_number='B01', daily_rate=1500.0, status='available')
            self.db.session.add(bed)
            self.db.session.commit()

            p_id = p.id
            w_id = ward.id
            b_id = bed.id

        self._login(doc)

        res = self.client.post('/inpatient/admit', data={
            'patient_id': p_id,
            'ward_id': w_id,
            'bed_id': b_id,
            'admitting_doctor': 'Dr. Test Physician',
            'admitting_diagnosis': 'Acute Lobar Pneumonia',
            'emergency_contact_name': '',  # left empty to test fallback
            'emergency_contact_phone': '',
            'emergency_contact_relation': '',
            'deposit_amount': '2500'
        }, follow_redirects=True)
        self.assertEqual(res.status_code, 200)

        with self.app.app_context():
            from models import Admission, Bed
            adm = Admission.query.filter_by(patient_id=p_id, status='admitted').first()
            self.assertIsNotNone(adm)
            self.assertEqual(adm.emergency_contact_name, 'Agnes Mwangi')
            self.assertEqual(adm.emergency_contact_phone, '0722999888')
            self.assertEqual(adm.emergency_contact_relation, 'Spouse')
            self.assertEqual(adm.deposit_amount, 2500.0)

            # Bed status must be atomically set to occupied
            b = Bed.query.get(b_id)
            self.assertEqual(b.status, 'occupied')

    # ================= 6. INPATIENT WARD/BED LINKAGE & DOUBLE ALLOCATION =================
    def test_inpatient_ward_bed_validation_and_double_allocation(self):
        """Validate ward/bed linkage and prevent double bed allocation atomically."""
        with self.app.app_context():
            from models import Patient, Ward, Bed, User
            doc = User.query.filter_by(username='dr_test').first()

            p1 = Patient(
                hospital_id='HSP-TEST-006A', first_name='Peter', last_name='Ochieng',
                full_name='Peter Ochieng', phone='0711111111', date_of_birth=date(1991, 1, 1),
                gender='Male', next_of_kin_name='Mary', next_of_kin_phone='0722111111', next_of_kin_relation='Sister'
            )
            p2 = Patient(
                hospital_id='HSP-TEST-006B', first_name='James', last_name='Kariuki',
                full_name='James Kariuki', phone='0711222222', date_of_birth=date(1992, 2, 2),
                gender='Male', next_of_kin_name='Ann', next_of_kin_phone='0722222222', next_of_kin_relation='Mother'
            )
            w1 = Ward(name='Surgical Ward', code='SW', is_active=True)
            w2 = Ward(name='Pediatric Ward', code='PW', is_active=True)
            self.db.session.add_all([p1, p2, w1, w2])
            self.db.session.flush()

            # Bed belongs to w1
            b = Bed(ward_id=w1.id, bed_number='SW-01', daily_rate=2000.0, status='available')
            self.db.session.add(b)
            self.db.session.commit()

            p1_id, p2_id = p1.id, p2.id
            w1_id, w2_id = w1.id, w2.id
            b_id = b.id

        self._login(doc)

        # 1. Invalid ward/bed linkage (submitting w2 with bed belonging to w1)
        bad_linkage = self.client.post('/inpatient/admit', data={
            'patient_id': p1_id,
            'ward_id': w2_id,
            'bed_id': b_id,
            'admitting_doctor': 'Dr. Test',
            'admitting_diagnosis': 'Test'
        }, follow_redirects=True)
        self.assertIn(b'does not belong to', bad_linkage.data)

        # 2. Successful admission for p1
        admit1 = self.client.post('/inpatient/admit', data={
            'patient_id': p1_id,
            'ward_id': w1_id,
            'bed_id': b_id,
            'admitting_doctor': 'Dr. Test',
            'admitting_diagnosis': 'Appendicitis'
        }, follow_redirects=True)
        self.assertEqual(admit1.status_code, 200)

        # 3. Concurrent/duplicate admission attempt on same bed for p2 -> must fail
        admit2 = self.client.post('/inpatient/admit', data={
            'patient_id': p2_id,
            'ward_id': w1_id,
            'bed_id': b_id,
            'admitting_doctor': 'Dr. Test',
            'admitting_diagnosis': 'Fracture'
        }, follow_redirects=True)
        self.assertIn(b'not available', admit2.data)

    # ================= 7. INPATIENT TRANSFER BED CHARGES & SEGMENTS =================
    def test_inpatient_transfer_bed_charges_and_deposit_handling(self):
        """Discharge computes bed charges per stay segment using rate snapshots, not current rate for whole stay."""
        with self.app.app_context():
            from models import Patient, Ward, Bed, Admission, BedTransfer, User
            doc = User.query.filter_by(username='dr_test').first()

            p = Patient(
                hospital_id='HSP-TEST-007', first_name='Tom', last_name='Mutua',
                full_name='Tom Mutua', phone='0711333333', date_of_birth=date(1975, 8, 20),
                gender='Male', next_of_kin_name='Lucy', next_of_kin_phone='0722333333', next_of_kin_relation='Wife'
            )
            w_gen = Ward(name='General Ward', code='GW', is_active=True)
            w_icu = Ward(name='Intensive Care Unit', code='ICU', is_active=True)
            self.db.session.add_all([p, w_gen, w_icu])
            self.db.session.flush()

            b_gen = Bed(ward_id=w_gen.id, bed_number='GW-10', daily_rate=1000.0, status='occupied')
            b_icu = Bed(ward_id=w_icu.id, bed_number='ICU-01', daily_rate=5000.0, status='available')
            self.db.session.add_all([b_gen, b_icu])
            self.db.session.flush()

            # Admitted 3 days ago into General Ward (rate 1000)
            t0 = datetime.utcnow() - timedelta(days=3)
            adm = Admission(
                admission_number='ADM-TEST-0007',
                patient_id=p.id,
                ward_id=w_gen.id,
                bed_id=b_gen.id,
                initial_bed_rate=1000.0,
                admitting_doctor='Dr. Test',
                admitting_diagnosis='Post-op care',
                admitted_at=t0,
                deposit_amount=5000.0,
                status='admitted'
            )
            self.db.session.add(adm)
            self.db.session.flush()

            # Transferred 1 day ago to ICU (rate 5000)
            # Segment 1: in GW (rate 1000) for 2 days
            # Segment 2: in ICU (rate 5000) for 1 day
            t1 = datetime.utcnow() - timedelta(days=1)
            tr = BedTransfer(
                admission_id=adm.id,
                patient_id=p.id,
                from_ward_id=w_gen.id,
                from_bed_id=b_gen.id,
                from_bed_rate=1000.0,
                to_ward_id=w_icu.id,
                to_bed_id=b_icu.id,
                to_bed_rate=5000.0,
                transfer_reason='Respiratory deterioration',
                transferred_by='Nurse Joyce',
                transferred_at=t1
            )
            adm.ward_id = w_icu.id
            adm.bed_id = b_icu.id
            b_icu.status = 'occupied'
            self.db.session.add(tr)
            self.db.session.commit()

            adm_id = adm.id

        self._login(doc)

        # Discharge patient now
        disch_res = self.client.post(f'/inpatient/patient/{adm_id}/discharge', data={
            'discharge_type': 'Routine Medical Clearance (Discharged Home)',
            'condition_on_discharge': 'Recovered / Clinically Stable',
            'discharge_summary': 'Patient stabilized and recovered well after ICU stepdown.',
            'discharge_instructions': 'Take oral medication as prescribed, follow-up in 1 week.'
        }, follow_redirects=True)
        self.assertEqual(disch_res.status_code, 200)

        with self.app.app_context():
            from models import Admission, BillingItem, Invoice
            discharge_adm = Admission.query.get(adm_id)
            self.assertEqual(discharge_adm.status, 'discharged')

            # Verify bed billing items created per segment
            bed_items = BillingItem.query.filter_by(patient_id=discharge_adm.patient_id, service_type='bed').all()
            self.assertGreaterEqual(len(bed_items), 2, "Expected distinct BillingItems per bed-stay segment")

            total_charged = sum(item.total_amount for item in bed_items)
            # Segment 1: ~2 days @ 1000 = ~2000
            # Segment 2: ~1 day @ 5000 = ~5000
            # Total ~7000. Under old single-rate bug it would have been 3 * 5000 = 15000!
            self.assertAlmostEqual(total_charged, 7000.0, delta=100.0)

            # Verify that unrecorded deposit was NOT subtracted from invoice balance as an unrecorded cash payment
            inv = Invoice.query.filter_by(patient_id=discharge_adm.patient_id).first()
            self.assertIsNotNone(inv)
            self.assertEqual(inv.amount_paid, 0.0, "Unrecorded admission deposit must NOT be deducted as recorded payment")

    # ================= 8. DOCUMENT ATTACHMENT UPLOAD =================
    def test_upload_attachment_private_storage(self):
        """Document uploads store files in relative private storage and handle validation."""
        import io
        with self.app.app_context():
            from models import Patient, User
            doc = User.query.filter_by(username='dr_test').first()
            p = Patient(
                hospital_id='HSP-TEST-008', first_name='Ken', last_name='Oloo',
                full_name='Ken Oloo', phone='0711444444', date_of_birth=date(1993, 9, 5),
                gender='Male', next_of_kin_name='Faith', next_of_kin_phone='0722444444', next_of_kin_relation='Sister'
            )
            self.db.session.add(p)
            self.db.session.commit()
            p_id = p.id

        self._login(doc)

        # Valid PDF upload
        fake_pdf = (io.BytesIO(b"%PDF-1.4 test document content\n%%EOF\n"), 'radiology_scan.pdf')
        upload_res = self.client.post(
            f'/doctor/patient/{p_id}/documents/upload',
            data={
                'title': 'Chest CT Scan Report',
                'document_type': 'radiology_report',
                'description': 'Normal lung parenchyma',
                'file': fake_pdf
            },
            content_type='multipart/form-data',
            follow_redirects=True
        )
        self.assertEqual(upload_res.status_code, 200)

        with self.app.app_context():
            from models import ClinicalDocument
            uploaded_doc = ClinicalDocument.query.filter_by(patient_id=p_id).first()
            self.assertIsNotNone(uploaded_doc)
            self.assertTrue(uploaded_doc.file_path.startswith('documents/'))
            self.assertTrue(uploaded_doc.file_path.endswith('.pdf'))

        # Invalid upload (disallowed extension or empty file)
        fake_bad = (io.BytesIO(b"bad content"), 'virus.exe')
        bad_upload = self.client.post(
            f'/doctor/patient/{p_id}/documents/upload',
            data={
                'title': 'Bad File',
                'document_type': 'other',
                'file': fake_bad
            },
            content_type='multipart/form-data',
            follow_redirects=True
        )
        self.assertIn(b'rejected', bad_upload.data.lower())


if __name__ == '__main__':
    unittest.main()
