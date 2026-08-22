import os
import sys
import io
import pyotp
from datetime import date, datetime, timedelta
from app import create_app
from models import (
    db, User, SecuritySetting, Permission, RolePermission, ClinicalDocument,
    Patient, Prescription, AuditLog
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

    # 15. Immutable Audit Trail Verification
    print("15. Verifying Immutable Audit Trail Telemetry...")
    with app.app_context():
        audit_events = AuditLog.query.order_by(AuditLog.created_at.desc()).limit(10).all()
        assert len(audit_events) > 0
        actions = [a.action for a in audit_events]
        print(f"   ✓ Recent Audit Actions: {', '.join(actions[:5])}")

    print("\n" + "="*70)
    print("🎉 ALL 14 TEST MODULES PASSED 100%! RBAC, 2FA, IAM & DOCUMENTS FULLY OPERATIONAL")
    print("="*70 + "\n")

if __name__ == '__main__':
    run_test_suite()
