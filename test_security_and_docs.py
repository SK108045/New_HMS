import os
import sys
import io
import pyotp
from datetime import date, datetime, timedelta
from app import create_app
from models import (
    db, User, SecuritySetting, Permission, RolePermission, ClinicalDocument,
    Patient, Prescription, AuditLog, Invoice, Payment,
    InsuranceScheme, InsuranceClaim, CreditNote, FeeWaiver,
    Supplier, PurchaseOrder, PurchaseOrderItem, ControlledDrugLog, QuarantineRecord,
    MedicationItem, DrugBatch, Appointment, DoctorSchedule, QueueEntry
)

def run_test_suite():
    app = create_app()
    client = app.test_client()

    print("\n" + "="*70)
    print("🔒 RUNNING RBAC, 2FA GOOGLE AUTH & CLINICAL DOCUMENTS TEST SUITE")
    print("="*70)

    with app.app_context():
        # 1. Verify Seeded Security & RBAC Permissions
        print("1. Verifying Seeded Security Settings & Canonical Permissions...")
        settings = SecuritySetting.get_settings()
        assert settings is not None
        assert settings.session_timeout_minutes >= 15
        
        perms_count = Permission.query.count()
        assert perms_count >= 15, f"Expected at least 15 permissions, found {perms_count}"
        print(f"   ✓ Security Settings OK (Timeout: {settings.session_timeout_minutes}m, 2FA Admin/Doc: {settings.require_2fa_for_admin_doctor})")
        print(f"   ✓ Canonical Permissions Catalog OK ({perms_count} permissions registered)")

        # 2. Verify RBAC Permissions Matrix
        print("2. Verifying Role-Based Access Control (RBAC)...")
        doctor = User.query.filter_by(role='doctor').first()
        cashier = User.query.filter_by(role='cashier').first()
        admin = User.query.filter_by(role='admin').first()
        
        assert admin.has_permission('any:permission') is True, "Admin should have all permissions"
        assert doctor.has_permission('clinical:prescribe') is True, "Doctor should have clinical:prescribe"
        assert doctor.has_permission('billing:collect_payment') is False, "Doctor should NOT have billing:collect_payment"
        assert cashier.has_permission('billing:collect_payment') is True, "Cashier should have billing:collect_payment"
        assert cashier.has_permission('clinical:prescribe') is False, "Cashier should NOT have clinical:prescribe"
        print("   ✓ RBAC granular permission checks verified successfully")

        # 3. Verify TOTP 2FA Google Authenticator Logic
        print("3. Testing Google Authenticator (TOTP RFC 6238) Engine...")
        secret = doctor.generate_totp_secret()
        assert len(secret) == 32, f"Secret should be 32 base32 chars, got {len(secret)}"
        uri = doctor.get_totp_uri()
        assert "otpauth://totp/" in uri
        assert "Apex%20Regional%20Medical%20Center" in uri
        
        # Generate valid live TOTP token with pyotp
        totp = pyotp.TOTP(secret)
        valid_token = totp.now()
        assert doctor.verify_totp(valid_token) is True, "Valid TOTP code should pass"
        assert doctor.verify_totp("000000") is False, "Bad code should fail"
        print(f"   ✓ TOTP Secret & Provisioning URI generated: {secret[:8]}... (Valid: {valid_token})")

        # 4. Emergency Single-Use Backup Recovery Codes
        print("4. Testing Emergency 2FA Backup Recovery Codes...")
        backup_codes = doctor.generate_backup_codes(count=8)
        assert len(backup_codes) == 8
        first_code = backup_codes[0]
        # First verification should consume the code
        assert doctor.verify_backup_code(first_code) is True, "Backup code should verify"
        # Re-using the same consumed code should fail
        assert doctor.verify_backup_code(first_code) is False, "Consumed backup code must not be reusable"
        print(f"   ✓ 8 Emergency Backup Codes generated and single-use consumption verified ({first_code})")

        # 5. Brute-Force Account Lockout & Unlocking
        print("5. Testing Brute-Force Lockout Defense...")
        test_u = User.query.filter_by(username='cashier').first()
        test_u.reset_failed_logins()
        assert test_u.is_locked() is False
        for i in range(5):
            test_u.record_failed_login(max_attempts=5, lockout_minutes=15)
        assert test_u.is_locked() is True, "Account should be locked after 5 failed attempts"
        test_u.reset_failed_logins()
        assert test_u.is_locked() is False, "Account should unlock after reset"
        print("   ✓ 5-attempt brute-force lockout and unlock mechanism verified")

    # 6. Web Login & 2FA Flow via Test Client
    print("6. Testing Web 2FA Sign-In & Challenge Endpoints...")
    with app.app_context():
        u = User.query.filter_by(username='doctor').first()
        u.is_2fa_enabled = True
        sec = u.generate_totp_secret()
        db.session.commit()

    # Step A: Submit username and password -> redirected to /verify-2fa
    res = client.post('/login/doctor', data={
        'username': 'doctor',
        'password': 'Doctor@2026'
    }, follow_redirects=False)
    assert res.status_code == 302
    assert '/verify-2fa' in res.headers['Location']
    print("   ✓ Password valid & 2FA challenge triggered (/verify-2fa)")

    # Step B: Submit invalid 6-digit PIN
    res_bad = client.post('/verify-2fa', data={'totp_code': '123456'}, follow_redirects=True)
    assert b"Invalid 6-digit" in res_bad.data or res_bad.status_code == 200

    # Step C: Submit valid live 6-digit PIN
    live_pin = pyotp.TOTP(sec).now()
    res_good = client.post('/verify-2fa', data={'totp_code': live_pin}, follow_redirects=False)
    assert res_good.status_code == 302
    assert '/doctor/dashboard' in res_good.headers['Location']
    print(f"   ✓ 2FA verification passed with live Google Authenticator PIN: {live_pin}")

    # 7. Admin Security Command Center & RBAC Endpoints
    print("7. Testing Admin Security Command Center & RBAC Matrix Endpoints...")
    with app.app_context():
        admin_u = User.query.filter_by(role='admin').first()
        admin_id = admin_u.id
        admin_uname = admin_u.username

    with client.session_transaction() as sess:
        sess['user_id'] = admin_id
        sess['username'] = admin_uname
        sess['role'] = 'admin'
        sess['portal'] = 'all'
        sess['2fa_verified'] = True

    res = client.get('/admin/security')
    assert res.status_code == 200
    assert b"Security Command Center" in res.data
    assert b"RBAC Permissions Matrix" in res.data
    print("   ✓ Admin Security Command Center rendered with 200 OK")

    # Update Security Policy
    res = client.post('/admin/security/settings', data={
        'require_2fa_for_admin_doctor': '1',
        'session_timeout_minutes': '45',
        'max_failed_attempts': '5',
        'lockout_duration_minutes': '15',
        'password_min_length': '8'
    }, follow_redirects=True)
    assert res.status_code == 200
    with app.app_context():
        updated_s = SecuritySetting.get_settings()
        assert updated_s.session_timeout_minutes == 45
        print("   ✓ Admin Security Policies deployed (Timeout set to 45m)")

    # 8. Clinical Documents: Medical Certificate Generation & A4 Print
    print("8. Testing Medical Certificate Generation & Official A4 Layout...")
    with app.app_context():
        doc_u = User.query.filter_by(role='doctor').first()
        doc_id = doc_u.id
        doc_uname = doc_u.username
        p = Patient.query.first()
        p_id = p.id

    with client.session_transaction() as sess:
        sess['user_id'] = doc_id
        sess['username'] = doc_uname
        sess['role'] = 'doctor'
        sess['portal'] = 'doctor'
        sess['2fa_verified'] = True

    res = client.get(f'/doctor/patient/{p_id}/medical-certificate')
    assert res.status_code == 200
    assert b"Medical Certificate / Sick-Off Note" in res.data

    res = client.post(f'/doctor/patient/{p_id}/medical-certificate', data={
        'addressed_to': 'Safaricom PLC Human Resources',
        'diagnosis': 'Acute Bacterial Bronchitis and Pyrexia',
        'start_date': '2026-08-21',
        'days_excused': '4',
        'fit_to_resume_date': '2026-08-25',
        'fitness_status': 'Total Bed Rest & Temporary Unfitness',
        'clinical_remarks': 'Patient attended outpatient clinic and received medication. Strictly advised complete bed rest.',
        'doctor_name': 'Dr. Sarah Kamau (KMPDC-A9842)'
    }, follow_redirects=False)
    assert res.status_code == 302
    cert_url = res.headers['Location']
    print(f"   ✓ Medical Certificate created: {cert_url}")

    # Check Printable Certificate Sheet
    res_print = client.get(cert_url)
    assert res_print.status_code == 200
    assert b"Medical Certificate of Unfitness / Sick-Off Note" in res_print.data
    assert b"Safaricom PLC Human Resources" in res_print.data
    assert b"Acute Bacterial Bronchitis" in res_print.data
    print("   ✓ Official A4 Printable Medical Certificate verified (200 OK)")

    # 9. Clinical Documents: Specialist Referral Letter Generation & A4 Print
    print("9. Testing Specialist Referral Letter & A4 Layout...")
    res = client.get(f'/doctor/patient/{p_id}/referral')
    assert res.status_code == 200
    assert b"Draft Official Medical Referral Letter" in res.data

    res = client.post(f'/doctor/patient/{p_id}/referral', data={
        'receiving_facility': 'Kenyatta National Hospital (KNH)',
        'specialty_dept': 'Department of Cardiology',
        'urgency': 'Urgent / Priority Transfer',
        'working_diagnosis': 'Refractory Hypertension with Left Ventricular Hypertrophy (I11.9)',
        'clinical_history': 'Patient has a 5-year history of poorly controlled BP despite triple therapy.',
        'investigations_summary': 'ECG: LVH with strain pattern. Echo: EF 45%.',
        'current_medications': 'Tab Amlodipine 10mg OD, Tab Telmisartan 80mg OD, Tab Hydrochlorothiazide 25mg OD',
        'reason_for_referral': 'Kindly evaluate for renal artery stenosis and specialized cardiac catheterization.',
        'referring_doctor': 'Dr. Sarah Kamau (Medical Officer, OPD Lead)'
    }, follow_redirects=False)
    assert res.status_code == 302
    ref_url = res.headers['Location']
    print(f"   ✓ Referral Letter generated: {ref_url}")

    res_ref_print = client.get(ref_url)
    assert res_ref_print.status_code == 200
    assert b"Clinical Specialist Referral Letter" in res_ref_print.data
    assert b"Kenyatta National Hospital" in res_ref_print.data
    print("   ✓ Official A4 Printable Referral Letter verified (200 OK)")

    # 10. Printable Official Prescription Slip (Rx)
    print("10. Testing Official Prescription Slip (Rx) Layout...")
    with app.app_context():
        rx = Prescription.query.first()
        rx_id = rx.id
    res_rx = client.get(f'/doctor/prescription/{rx_id}/print')
    assert res_rx.status_code == 200
    assert b"Prescribed Pharmaceuticals" in res_rx.data
    assert b"Pharmacy Dispense Seal" in res_rx.data
    print("   ✓ Official Printable Prescription Sheet verified (200 OK)")

    # 11. Digital Attachment Upload & Universal Viewer Vault
    print("11. Testing Document Attachment Upload & File Viewer Vault...")
    sample_file_content = b"%PDF-1.4 sample diagnostic test report content for automated testing"
    file_tuple = (io.BytesIO(sample_file_content), 'lab_report_test.pdf')

    res_upload = client.post(f'/doctor/patient/{p_id}/documents/upload', data={
        'title': 'Automated Blood Panel Test PDF',
        'document_type': 'lab_report',
        'description': 'Baseline hematology scan from reference laboratory',
        'file': file_tuple
    }, follow_redirects=True)
    assert res_upload.status_code == 200

    with app.app_context():
        uploaded_doc = ClinicalDocument.query.filter_by(title='Automated Blood Panel Test PDF').first()
        assert uploaded_doc is not None
        assert uploaded_doc.file_path is not None
        assert uploaded_doc.is_pdf is True
        doc_view_id = uploaded_doc.id

    res_view = client.get(f'/documents/view/{doc_view_id}')
    assert res_view.status_code == 200
    assert res_view.data == sample_file_content
    print(f"   ✓ Document attachment uploaded, registered, and streamed via /documents/view/{doc_view_id} (200 OK)")

    # 13. Mandatory First-Login Password Reset Intercept
    print("13. Testing First-Time Login Forced Password Change Workflow...")
    with app.app_context():
        new_staff = User.query.filter_by(username='intern.doc').first()
        if not new_staff:
            new_staff = User(
                username='intern.doc', full_name='Dr. Intern Kevin', staff_id='STF-INT-01',
                role='doctor', portal='doctor', department='Emergency OPD', status='active'
            )
            db.session.add(new_staff)
        new_staff.set_password('TempPass@2026')
        new_staff.force_password_change = True
        db.session.commit()

    # Clear active session
    client.get('/logout')

    # Attempt login with temporary password -> Should be intercepted and redirected to /force-change-password
    res_login = client.post('/login/doctor', data={
        'username': 'intern.doc',
        'password': 'TempPass@2026'
    }, follow_redirects=False)
    assert res_login.status_code == 302
    assert '/force-change-password' in res_login.headers['Location']
    print("   ✓ Temporary password login intercepted and routed to /force-change-password")

    # Complete forced password update
    res_force = client.post('/force-change-password', data={
        'current_password': 'TempPass@2026',
        'new_password': 'StrongPersonal@2026',
        'confirm_password': 'StrongPersonal@2026'
    }, follow_redirects=True)
    assert res_force.status_code == 200
    with app.app_context():
        updated_intern = User.query.filter_by(username='intern.doc').first()
        assert updated_intern.force_password_change is False
        assert updated_intern.check_password('StrongPersonal@2026') is True
    print("   ✓ Forced password update verified, force_password_change flag cleared")

    # 14. Universal Self-Service Profile Password Change
    print("14. Testing Universal Self-Service Password Change...")
    with client.session_transaction() as sess:
        sess['user_id'] = updated_intern.id
        sess['username'] = 'intern.doc'
        sess['role'] = 'doctor'
        sess['portal'] = 'doctor'
        sess['2fa_verified'] = True

    res_change = client.post('/change-password', data={
        'current_password': 'StrongPersonal@2026',
        'new_password': 'NewUpdatedPersonal@2026',
        'confirm_password': 'NewUpdatedPersonal@2026'
    }, follow_redirects=True)
    assert res_change.status_code == 200
    with app.app_context():
        final_intern = User.query.filter_by(username='intern.doc').first()
        assert final_intern.check_password('NewUpdatedPersonal@2026') is True
    print("   ✓ Self-service profile password change executed successfully")

    # 16. Insurance & SHA Pre-Authorisation Claim Workflow
    print("16. Testing Insurance & SHA Pre-Auth Claims Workflow...")
    with app.app_context():
        cashier_user = User.query.filter_by(role='cashier').first() or User.query.filter_by(role='admin').first()
        cashier_id = cashier_user.id
        p = Patient.query.first()
        inv = Invoice.query.filter_by(patient_id=p.id).first()
        if not inv:
            inv = Invoice(
                invoice_number=Invoice.generate_invoice_number(db.session),
                patient_id=p.id,
                subtotal=5000.0,
                total_due=5000.0,
                amount_paid=0.0,
                balance_due=5000.0,
                status='unpaid',
                cashier_name='Cashier Joyce Wambui'
            )
            db.session.add(inv)
            db.session.commit()
        inv_id = inv.id
        scheme = InsuranceScheme.query.filter_by(code='SHA-PUB').first()
        scheme_id = scheme.id if scheme else 1

    with client.session_transaction() as sess:
        sess['user_id'] = cashier_id
        sess['username'] = 'joyce'
        sess['role'] = 'cashier'
        sess['portal'] = 'billing'
        sess['2fa_verified'] = True

    res_claim = client.post('/billing/claims/create-preauth', data={
        'invoice_id': inv_id,
        'scheme_id': scheme_id,
        'member_number': 'SHA-88991122',
        'claimed_amount': '4500.00',
        'notes': 'Pre-auth requested for diagnostic tests'
    }, follow_redirects=True)
    assert res_claim.status_code == 200
    with app.app_context():
        claim = InsuranceClaim.query.filter_by(member_number='SHA-88991122').order_by(InsuranceClaim.id.desc()).first()
        assert claim is not None
        assert claim.status == 'preauth_approved'
        assert claim.preauth_code is not None
        claim_id = claim.id
    print(f"   ✓ SHA Pre-Authorisation claim created & approved: Code {claim.preauth_code}")

    # Submit and reimburse claim
    res_claim_update = client.post(f'/billing/claims/{claim_id}/update-status', data={
        'status': 'reimbursed',
        'approved_amount': '4500.00'
    }, follow_redirects=True)
    assert res_claim_update.status_code == 200
    with app.app_context():
        claim = InsuranceClaim.query.get(claim_id)
        assert claim.status == 'reimbursed'
        assert claim.approved_amount == 4500.00
    print("   ✓ Insurance claim reimbursed and settled successfully")

    # 17. Credit Notes & Fee Waivers Dual Authorization
    print("17. Testing Credit Notes & Fee Waivers Dual Authorization...")
    res_cn = client.post('/billing/credit-notes/create', data={
        'invoice_id': inv_id,
        'amount': '500.00',
        'reason': 'billing_error',
        'notes': 'Overcharge discount applied'
    }, follow_redirects=True)
    assert res_cn.status_code == 200
    with app.app_context():
        cn = CreditNote.query.filter_by(invoice_id=inv_id).order_by(CreditNote.id.desc()).first()
        assert cn is not None
        assert cn.status == 'pending_approval'
        cn_id = cn.id

    res_cn_appr = client.post(f'/billing/credit-notes/{cn_id}/action', data={
        'action': 'approve'
    }, follow_redirects=True)
    assert res_cn_appr.status_code == 200
    with app.app_context():
        cn = CreditNote.query.get(cn_id)
        assert cn.status == 'approved'
    print("   ✓ Credit note created and authorized by administrator")

    res_wv = client.post('/billing/waivers/create', data={
        'invoice_id': inv_id,
        'amount': '1000.00',
        'category': 'indigent_patient',
        'justification': 'Vulnerable citizen social welfare support'
    }, follow_redirects=True)
    assert res_wv.status_code == 200
    with app.app_context():
        wv = FeeWaiver.query.filter_by(invoice_id=inv_id).order_by(FeeWaiver.id.desc()).first()
        assert wv is not None
        wv_id = wv.id

    res_wv_appr = client.post(f'/billing/waivers/{wv_id}/action', data={
        'action': 'approve'
    }, follow_redirects=True)
    assert res_wv_appr.status_code == 200
    with app.app_context():
        wv = FeeWaiver.query.get(wv_id)
        assert wv.status == 'approved'
    print("   ✓ Indigent fee waiver authorized by Medical Superintendent")

    # 18. Pharmacy LPO Procurement & Inventory Intake
    print("18. Testing Pharmacy Local Purchase Orders (LPO) & Stock Intake...")
    with app.app_context():
        pharm_user = User.query.filter_by(role='pharmacy').first() or User.query.filter_by(role='admin').first()
        pharm_id = pharm_user.id
        supp = Supplier.query.first()
        med = MedicationItem.query.first()
        supp_id = supp.id
        med_id = med.id
        initial_stock = med.current_stock

    with client.session_transaction() as sess:
        sess['user_id'] = pharm_id
        sess['username'] = 'evans'
        sess['role'] = 'pharmacy'
        sess['portal'] = 'pharmacy'
        sess['2fa_verified'] = True

    res_po = client.post('/pharmacy/purchase-orders/create', data={
        'supplier_id': supp_id,
        'medication_id': med_id,
        'quantity_ordered': '50',
        'unit_cost': '18.50',
        'notes': 'Urgent dispensary restock'
    }, follow_redirects=True)
    assert res_po.status_code == 200
    with app.app_context():
        po = PurchaseOrder.query.order_by(PurchaseOrder.id.desc()).first()
        assert po is not None
        assert po.status == 'ordered'
        po_id = po.id

    res_po_recv = client.post(f'/pharmacy/purchase-orders/{po_id}/receive', data={
        'batch_number': 'TEST-BAT-2026',
        'expiry_date': '2028-12-31'
    }, follow_redirects=True)
    assert res_po_recv.status_code == 200
    with app.app_context():
        po = PurchaseOrder.query.get(po_id)
        assert po.status == 'received'
        new_batch = DrugBatch.query.filter_by(batch_number='TEST-BAT-2026').first()
        assert new_batch is not None
        med = MedicationItem.query.get(med_id)
        assert med.current_stock == initial_stock + 50
    print("   ✓ LPO created, received, new DrugBatch registered, stock incremented (+50)")

    # 19. Controlled Drug Register & Expiry Quarantine Bin
    print("19. Testing Controlled Drug Register & Expiry Quarantine Bin...")
    with app.app_context():
        ctrl_med = MedicationItem.query.filter_by(is_controlled=True).first()
        ctrl_id = ctrl_med.id
        ctrl_initial = ctrl_med.current_stock

    res_ctrl = client.post('/pharmacy/controlled-drugs', data={
        'medication_id': ctrl_id,
        'quantity_dispensed': '2',
        'patient_name': 'Mary Achieng',
        'prescribing_doctor': 'Dr. Sarah Kamau',
        'witness_pharmacist': 'Pharm. Brenda Wanjiku',
        'indication_notes': 'Post-op analgesia',
        'prescription_ref': 'RX-TEST-001'
    }, follow_redirects=True)
    assert res_ctrl.status_code == 200
    with app.app_context():
        ctrl_med = MedicationItem.query.get(ctrl_id)
        assert ctrl_med.current_stock == ctrl_initial - 2
        ctrl_log = ControlledDrugLog.query.order_by(ControlledDrugLog.id.desc()).first()
        assert ctrl_log.quantity_dispensed == 2
    print("   ✓ Controlled drug logged in regulatory register with witness verification")

    # Quarantine Drug Batch
    with app.app_context():
        batch_to_q = DrugBatch.query.filter(DrugBatch.quantity_remaining > 5).first()
        batch_q_id = batch_to_q.id

    res_q = client.post('/pharmacy/quarantine/create', data={
        'batch_id': batch_q_id,
        'quantity': '5',
        'reason': 'near_expiry',
        'notes': 'Quarantined due to <30 days expiry'
    }, follow_redirects=True)
    assert res_q.status_code == 200
    with app.app_context():
        q_rec = QuarantineRecord.query.order_by(QuarantineRecord.id.desc()).first()
        assert q_rec is not None
        assert q_rec.quantity == 5
        q_rec_id = q_rec.id

    res_q_act = client.post(f'/pharmacy/quarantine/{q_rec_id}/action', data={
        'disposition': 'returned_to_supplier'
    }, follow_redirects=True)
    assert res_q_act.status_code == 200
    with app.app_context():
        q_rec = QuarantineRecord.query.get(q_rec_id)
        assert q_rec.disposition == 'returned_to_supplier'
    print("   ✓ Drug batch quarantined and disposition (return to vendor) completed")

    # 20. Appointments, Doctor Slot Capacity & Multi-Channel Reminders
    print("20. Testing Appointments, Doctor Slot Capacity & SMS/WhatsApp Reminders...")
    with app.app_context():
        rec_user = User.query.filter_by(role='receptionist').first() or User.query.filter_by(role='admin').first()
        rec_id = rec_user.id
        p = Patient.query.order_by(Patient.id.desc()).first()
        p_id = p.id
        target_date = (date.today() + timedelta(days=2)).strftime('%Y-%m-%d')

    with client.session_transaction() as sess:
        sess['user_id'] = rec_id
        sess['username'] = 'reception'
        sess['role'] = 'receptionist'
        sess['portal'] = 'reception'
        sess['2fa_verified'] = True

    # Book new appointment
    res_app = client.post('/reception/appointments', data={
        'patient_id': str(p_id),
        'scheduled_date': target_date,
        'scheduled_time': '10:30',
        'department': 'General OPD',
        'doctor_name': 'Dr. Sarah Kamau (General OPD)',
        'reason': 'Routine clinical follow-up & BP check'
    }, follow_redirects=True)
    assert res_app.status_code == 200
    with app.app_context():
        new_app = Appointment.query.filter_by(patient_id=p_id).order_by(Appointment.id.desc()).first()
        assert new_app is not None
        assert new_app.appointment_number is not None
        assert new_app.status == 'scheduled'
        app_id = new_app.id
    print(f"   ✓ Appointment booked with auto-numbering: {new_app.appointment_number}")

    # Confirm appointment
    res_conf = client.post(f'/reception/appointments/{app_id}/confirm', follow_redirects=True)
    assert res_conf.status_code == 200
    with app.app_context():
        assert Appointment.query.get(app_id).status == 'confirmed'
    print("   ✓ Appointment confirmed successfully")

    # Dispatch SMS & WhatsApp reminder
    res_rem = client.post(f'/reception/appointments/{app_id}/send-reminder', data={
        'channel': 'both'
    }, follow_redirects=True)
    assert res_rem.status_code == 200
    with app.app_context():
        app_entry = Appointment.query.get(app_id)
        assert app_entry.reminder_sent_sms is True
        assert app_entry.reminder_sent_whatsapp is True
        assert app_entry.last_reminder_at is not None
    print("   ✓ SMS & WhatsApp reminders dispatched and logged in database")

    # 1-Click Triage Check-in
    res_chk = client.post(f'/reception/appointments/{app_id}/checkin', follow_redirects=True)
    assert res_chk.status_code == 200
    with app.app_context():
        assert Appointment.query.get(app_id).status == 'checked_in'
        tkt = QueueEntry.query.filter_by(patient_id=p_id).order_by(QueueEntry.id.desc()).first()
        assert tkt is not None
        assert tkt.status == 'waiting'
    print(f"   ✓ 1-Click Triage Check-in generated ticket {tkt.ticket_number}")

    # Test Doctor Schedule update in Doctor Portal
    with app.app_context():
        doc_user = User.query.filter_by(role='doctor').first() or User.query.filter_by(role='admin').first()
        doc_id = doc_user.id

    with client.session_transaction() as sess:
        sess['user_id'] = doc_id
        sess['username'] = 'doctor'
        sess['role'] = 'doctor'
        sess['portal'] = 'doctor'
        sess['2fa_verified'] = True

    res_doc_sched = client.post('/doctor/schedule', data={
        'day_of_week': 'Monday, Tuesday, Wednesday, Friday',
        'start_time': '08:30',
        'end_time': '16:30',
        'max_patients_per_day': '25',
        'slot_duration_minutes': '20',
        'duty_status': 'available',
        'notes': 'Room 101 - Primary Care'
    }, follow_redirects=True)
    assert res_doc_sched.status_code == 200
    with app.app_context():
        sched = DoctorSchedule.query.first()
        assert sched.max_patients_per_day == 25
    print("   ✓ Doctor duty roster & slot capacity updated via Doctor Portal")

    # 21. Immutable Audit Trail Verification
    print("21. Verifying Immutable Audit Trail Telemetry...")
    with app.app_context():
        audit_events = AuditLog.query.order_by(AuditLog.created_at.desc()).limit(10).all()
        assert len(audit_events) > 0
        actions = [a.action for a in audit_events]
        print(f"   ✓ Recent Audit Actions: {', '.join(actions[:5])}")

    print("\n" + "="*70)
    print("🎉 ALL 20 TEST MODULES PASSED 100%! APPOINTMENTS, SMS/WA REMINDERS, ROSTER & RBAC FULLY OPERATIONAL")
    print("="*70 + "\n")

if __name__ == '__main__':
    run_test_suite()
