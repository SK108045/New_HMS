import os
import tempfile
import unittest
import pyotp
from datetime import datetime, timedelta

from flask import session
from app import create_app
from config import Config
from models import (
    db, User, SecuritySetting, Permission, RolePermission, AuditLog
)
from auth.policy import is_safe_url, validate_password_policy


class TestSecurityConfig(Config):
    TESTING = True
    WTF_CSRF_ENABLED = False
    SECRET_KEY = 'test-security-secret-key-xyz-987'
    AUTO_INIT_DB = False
    SEED_DEMO_DATA = False
    DEMO_LOGIN_ENABLED = False
    SQLALCHEMY_TRACK_MODIFICATIONS = False


class TestAuthSecurity(unittest.TestCase):

    def setUp(self):
        self.temp_db = tempfile.NamedTemporaryFile(suffix='.db', delete=False)
        self.temp_db_path = self.temp_db.name
        self.temp_db.close()

        self.temp_upload_dir = tempfile.mkdtemp()

        class RuntimeConfig(TestSecurityConfig):
            SQLALCHEMY_DATABASE_URI = f"sqlite:///{self.temp_db_path}"
            PRIVATE_UPLOAD_FOLDER = os.path.join(self.temp_upload_dir, 'private')
            UPLOAD_FOLDER = os.path.join(self.temp_upload_dir, 'public')

        self.app = create_app(RuntimeConfig)
        self.app_context = self.app.app_context()
        self.app_context.push()

        db.create_all()

        # Seed minimal security settings
        self.settings = SecuritySetting(
            require_2fa_for_all=False,
            require_2fa_for_admin_doctor=True,
            session_timeout_minutes=30,
            max_failed_attempts=3,
            lockout_duration_minutes=15,
            password_min_length=8,
            require_special_chars=True
        )
        db.session.add(self.settings)

        # Seed permissions
        perms = [
            Permission(code='patient:view', name='View Patient', category='Patients'),
            Permission(code='patient:register', name='Register Patient', category='Patients'),
            Permission(code='patient:edit', name='Edit Patient', category='Patients'),
            Permission(code='clinical:consult', name='Consultation', category='Clinical'),
            Permission(code='clinical:order_labs', name='Order Labs', category='Clinical'),
            Permission(code='clinical:record_results', name='Record Results', category='Clinical'),
            Permission(code='billing:collect_payment', name='Collect Payment', category='Billing'),
            Permission(code='telephony:send', name='Send Telephony', category='Telephony'),
            Permission(code='admin:manage_users', name='Manage Users', category='Admin'),
            Permission(code='admin:security_config', name='Security Config', category='Admin'),
            Permission(code='inpatient:chart', name='Inpatient Chart', category='Inpatient'),
        ]
        db.session.add_all(perms)

        # Seed role permissions
        role_perms = [
            RolePermission(role='doctor', permission_code='patient:view'),
            RolePermission(role='doctor', permission_code='clinical:consult'),
            RolePermission(role='doctor', permission_code='clinical:order_labs'),
            RolePermission(role='doctor', permission_code='clinical:record_results'),
            RolePermission(role='receptionist', permission_code='patient:view'),
            RolePermission(role='receptionist', permission_code='patient:register'),
            RolePermission(role='receptionist', permission_code='patient:edit'),
            RolePermission(role='receptionist', permission_code='telephony:send'),
            RolePermission(role='cashier', permission_code='patient:view'),
            RolePermission(role='cashier', permission_code='billing:collect_payment'),
        ]
        db.session.add_all(role_perms)
        db.session.commit()

        self.client = self.app.test_client()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.app_context.pop()
        if os.path.exists(self.temp_db_path):
            os.remove(self.temp_db_path)

    def _create_user(self, username, role='receptionist', portal='reception', password='Password@123',
                     is_2fa_enabled=False, force_password_change=False, status='active'):
        user = User(
            username=username,
            full_name=f"Test {username.title()}",
            staff_id='TEST-' + username,
            role=role,
            portal=portal,
            department='General',
            status=status,
            is_2fa_enabled=is_2fa_enabled,
            force_password_change=force_password_change
        )
        user.set_password(password, force_change=force_password_change)
        db.session.add(user)
        db.session.commit()
        return user

    # 1. Secret Inaccessible Pending Challenge
    def test_secret_inaccessible_pending_challenge(self):
        user = self._create_user('doc_challenge', role='doctor', portal='doctor', password='Password@123', is_2fa_enabled=True)
        secret = user.generate_totp_secret()
        db.session.commit()

        # Step 1: Submit credentials to start 2FA challenge
        res_login = self.client.post('/login/doctor', data={
            'username': 'doc_challenge',
            'password': 'Password@123'
        }, follow_redirects=False)

        self.assertEqual(res_login.status_code, 302)
        self.assertIn('/verify-2fa', res_login.headers.get('Location', ''))

        with self.client.session_transaction() as sess:
            self.assertEqual(sess.get('pending_2fa_user_id'), user.id)

        # Step 2: Attempt to access setup_2fa while challenge is pending
        res_setup = self.client.get('/setup-2fa', follow_redirects=False)
        self.assertEqual(res_setup.status_code, 302)
        self.assertIn('/verify-2fa', res_setup.headers.get('Location', ''))

        res_setup_follow = self.client.get('/setup-2fa', follow_redirects=True)
        # Secret must not be disclosed in HTML
        self.assertNotIn(secret.encode(), res_setup_follow.data)
        self.assertIn(b"Two-Factor Authentication", res_setup_follow.data)

        # Attempt setup_2fa via POST to bypass challenge
        totp = pyotp.TOTP(secret)
        res_post_bypass = self.client.post('/setup-2fa', data={'verification_code': totp.now()}, follow_redirects=False)
        self.assertEqual(res_post_bypass.status_code, 302)
        self.assertIn('/verify-2fa', res_post_bypass.headers.get('Location', ''))

    # 2. Mandatory Enrollment for Unenrolled Accounts
    def test_mandatory_enrollment_unenrolled_account(self):
        # require_2fa_for_admin_doctor is True, unenrolled doctor logs in
        doc = self._create_user('doc_unauth', role='doctor', portal='doctor', password='Password@123', is_2fa_enabled=False)

        res_login = self.client.post('/login/doctor', data={
            'username': 'doc_unauth',
            'password': 'Password@123'
        }, follow_redirects=False)

        self.assertEqual(res_login.status_code, 302)
        self.assertIn('/setup-2fa', res_login.headers.get('Location', ''))

        with self.client.session_transaction() as sess:
            self.assertEqual(sess.get('pending_2fa_enrollment_user_id'), doc.id)
            self.assertIsNone(sess.get('user_id'))  # Not logged in yet!

        # Attempt to access operational portal while enrollment is pending
        res_dash = self.client.get('/doctor/dashboard', follow_redirects=False)
        self.assertEqual(res_dash.status_code, 302)
        self.assertIn('/setup-2fa', res_dash.headers.get('Location', ''))

        # Complete enrollment
        res_setup_page = self.client.get('/setup-2fa')
        self.assertEqual(res_setup_page.status_code, 200)

        db.session.refresh(doc)
        totp = pyotp.TOTP(doc.totp_secret)
        code = totp.now()

        res_activate = self.client.post('/setup-2fa', data={'verification_code': code}, follow_redirects=False)
        self.assertEqual(res_activate.status_code, 200)  # Renders backup codes
        self.assertIn(b"2FA Activated Successfully", res_activate.data)

        db.session.refresh(doc)
        self.assertTrue(doc.is_2fa_enabled)

        # Now active session exists
        with self.client.session_transaction() as sess:
            self.assertEqual(sess.get('user_id'), doc.id)
            self.assertTrue(sess.get('2fa_verified'))
            self.assertIsNone(sess.get('pending_2fa_enrollment_user_id'))

    # 3. Lockout Behavior
    def test_lockout_on_failed_attempts(self):
        user = self._create_user('lock_target', password='Password@123')
        self.settings.max_failed_attempts = 3
        self.settings.lockout_duration_minutes = 15
        db.session.commit()

        # Submit 3 failed attempts
        for _ in range(3):
            self.client.post('/login/reception', data={
                'username': 'lock_target',
                'password': 'WrongPassword999!'
            })

        db.session.refresh(user)
        self.assertTrue(user.is_locked())

        # Attempt with correct password while locked
        res_correct_locked = self.client.post('/login/reception', data={
            'username': 'lock_target',
            'password': 'Password@123'
        }, follow_redirects=True)

        self.assertIn(b"Account locked due to excessive failed attempts", res_correct_locked.data)

        # Unlock user
        user.reset_failed_logins()
        db.session.commit()
        self.assertFalse(user.is_locked())

        # Now login succeeds
        res_unlocked = self.client.post('/login/reception', data={
            'username': 'lock_target',
            'password': 'Password@123'
        }, follow_redirects=False)
        self.assertEqual(res_unlocked.status_code, 302)

    # 4. Inactive Account Blocked
    def test_inactive_account_blocked(self):
        user = self._create_user('inactive_user', status='inactive', password='Password@123')

        # Login attempt fails
        res = self.client.post('/login/reception', data={
            'username': 'inactive_user',
            'password': 'Password@123'
        }, follow_redirects=True)
        self.assertIn(b"suspended or deactivated", res.data)

        # Existing session for newly deactivated account is blocked centrally
        active_user = self._create_user('active_to_inactive', status='active', password='Password@123')
        with self.client.session_transaction() as sess:
            sess['auth_version'] = active_user.auth_version
            sess['user_id'] = active_user.id
            sess['username'] = active_user.username
            sess['role'] = active_user.role
            sess['portal'] = active_user.portal
            sess['2fa_verified'] = True
            sess['auth_password_changed_at'] = active_user.password_changed_at.isoformat()

        # Deactivate user in DB
        active_user.status = 'suspended'
        db.session.commit()

        # Access operational portal
        res_portal = self.client.get('/reception/dashboard', follow_redirects=False)
        self.assertEqual(res_portal.status_code, 302)
        self.assertIn('/login', res_portal.headers.get('Location', ''))

        with self.client.session_transaction() as sess:
            self.assertIsNone(sess.get('user_id'))  # Session was cleared

    # 5. Changed Password Flag Existing Session
    def test_changed_password_flag_existing_session(self):
        user = self._create_user('pw_flag_user', role='doctor', portal='doctor', password='Password@123', is_2fa_enabled=True)

        with self.client.session_transaction() as sess:
            sess['auth_version'] = user.auth_version
            sess['user_id'] = user.id
            sess['username'] = user.username
            sess['role'] = user.role
            sess['portal'] = user.portal
            sess['2fa_verified'] = True
            sess['auth_password_changed_at'] = user.password_changed_at.isoformat()

        # Flag force_password_change
        user.force_password_change = True
        db.session.commit()

        res_op = self.client.get('/doctor/dashboard', follow_redirects=False)
        self.assertEqual(res_op.status_code, 302)
        self.assertIn('/force-change-password', res_op.headers.get('Location', ''))

        # Also test password changed timestamp mismatch (external password reset)
        user.force_password_change = False
        user.set_password('NewPassword@999')
        db.session.commit()

        res_op_pw_changed = self.client.get('/doctor/dashboard', follow_redirects=False)
        self.assertEqual(res_op_pw_changed.status_code, 302)
        self.assertIn('/login', res_op_pw_changed.headers.get('Location', ''))

    # 6. Revoked Action Permission Denied Returns 403
    def test_revoked_action_permission_denied_returns_403(self):
        # Receptionist attempts doctor action or mutation requiring clinical:record_results
        rec = self._create_user('rec_worker', role='receptionist', portal='reception', password='Password@123')

        with self.client.session_transaction() as sess:
            sess['auth_version'] = rec.auth_version
            sess['user_id'] = rec.id
            sess['username'] = rec.username
            sess['role'] = rec.role
            sess['portal'] = rec.portal
            sess['2fa_verified'] = True
            sess['auth_password_changed_at'] = rec.password_changed_at.isoformat()

        # Newly added doctor.record_lab_results requiring clinical:record_results
        res_denied = self.client.post('/doctor/lab_results/record', data={})
        self.assertEqual(res_denied.status_code, 403)
        self.assertIn(b"clinical:record_results", res_denied.data)

        # Cashier mutation attempted by receptionist
        res_cashier_perm = self.client.post('/billing/pos/settle/1', data={})
        self.assertEqual(res_cashier_perm.status_code, 403)

    # 7. Safe Next Redirect
    def test_safe_next_redirect(self):
        user = self._create_user('safe_redir_user', role='receptionist', password='Password@123')

        # Test malicious open-redirect URLs
        malicious_urls = [
            '//evil.com',
            '//evil.com/path',
            '/\\evil.com',
            'https://evil.com',
            'http://attacker.org/steal',
            'javascript:alert(1)',
            '/login',
            '/auth/login'
        ]

        for bad_url in malicious_urls:
            self.assertFalse(is_safe_url(bad_url), f"URL {bad_url} should be recognized as unsafe")
            res = self.client.post(f'/login/reception?next={bad_url}', data={
                'username': 'safe_redir_user',
                'password': 'Password@123'
            }, follow_redirects=False)

            location = res.headers.get('Location', '')
            self.assertNotIn('evil.com', location)
            self.assertNotIn('attacker.org', location)
            self.assertTrue(location.endswith('/dashboard') or location == '/')

        # Safe local URL
        with self.app.test_request_context():
            self.assertTrue(is_safe_url('/reception/search'))
        res_safe = self.client.post('/login/reception?next=/reception/search', data={
            'username': 'safe_redir_user',
            'password': 'Password@123'
        }, follow_redirects=False)
        self.assertEqual(res_safe.headers.get('Location'), '/reception/search')

    # 8. Onboarding Token Binding and Single-Use
    def test_onboarding_token_binding_and_single_use(self):
        user = self._create_user('onboard_staff', role='nurse', password='Password@123', is_2fa_enabled=False)
        token = user.get_2fa_onboarding_token(self.app.config['SECRET_KEY'])
        self.assertIsNotNone(token)

        # Token verifies successfully initially
        verified_user = User.verify_2fa_onboarding_token(token, self.app.config['SECRET_KEY'])
        self.assertIsNotNone(verified_user)
        self.assertEqual(verified_user.id, user.id)

        # Invalidation if user password changes
        user.set_password('NewPassword@456')
        db.session.commit()
        self.assertIsNone(User.verify_2fa_onboarding_token(token, self.app.config['SECRET_KEY']))

        # Reset password and create new token
        user.set_password('Password@123')
        db.session.commit()
        new_token = user.get_2fa_onboarding_token(self.app.config['SECRET_KEY'])
        self.assertIsNotNone(User.verify_2fa_onboarding_token(new_token, self.app.config['SECRET_KEY']))

        # Single-use on activation: once 2FA is activated, token becomes invalid
        user.is_2fa_enabled = True
        db.session.commit()
        self.assertIsNone(User.verify_2fa_onboarding_token(new_token, self.app.config['SECRET_KEY']))

    # 9. Password Special-Char Policy
    def test_password_special_char_policy(self):
        self.settings.password_min_length = 8
        self.settings.require_special_chars = True
        db.session.commit()

        # Too short
        ok, msg = validate_password_policy('Pass@1', self.settings)
        self.assertFalse(ok)
        self.assertIn("at least 8 characters", msg)

        # Missing special character
        ok, msg = validate_password_policy('Password123', self.settings)
        self.assertFalse(ok)
        self.assertIn("special character", msg)

        # Valid password
        ok, msg = validate_password_policy('ValidPassword@2026', self.settings)
        self.assertTrue(ok)

    # 10. Demo Login Respects Policies
    def test_demo_login_respects_policies(self):
        # Enable DEMO_LOGIN_ENABLED in app config
        self.app.config['DEMO_LOGIN_ENABLED'] = True

        # Demo doctor with 2FA enabled
        doc = self._create_user('doctor', role='doctor', portal='doctor', password='Password@123', is_2fa_enabled=True)
        res = self.client.get('/auth/demo-login/doctor', follow_redirects=False)
        self.assertEqual(res.status_code, 302)
        self.assertIn('/verify-2fa', res.headers.get('Location', ''))

        # Demo doctor with force_password_change
        doc.is_2fa_enabled = False
        doc.force_password_change = True
        db.session.commit()

        res_pw = self.client.get('/auth/demo-login/doctor', follow_redirects=False)
        self.assertEqual(res_pw.status_code, 302)
        self.assertIn('/force-change-password', res_pw.headers.get('Location', ''))

    # 11. Protect Auth Setup user_id Admin/Self Paths
    def test_setup_user_id_requires_admin(self):
        u1 = self._create_user('user_one', role='receptionist', password='Password@123')
        u2 = self._create_user('user_two', role='nurse', password='Password@123')

        # Log in as u1
        with self.client.session_transaction() as sess:
            sess['auth_version'] = u1.auth_version
            sess['user_id'] = u1.id
            sess['username'] = u1.username
            sess['role'] = u1.role
            sess['portal'] = u1.portal
            sess['2fa_verified'] = True
            sess['auth_password_changed_at'] = u1.password_changed_at.isoformat()

        # u1 attempts to configure 2FA for u2 -> 403 Forbidden
        res = self.client.get(f'/setup-2fa-user/{u2.id}')
        self.assertEqual(res.status_code, 403)


if __name__ == '__main__':
    unittest.main()
