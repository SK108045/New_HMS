import base64
import io
from datetime import datetime, timedelta
import qrcode
from flask import abort, current_app, render_template, request, redirect, url_for, flash, session
from models import db, User, SecuritySetting, AuditLog
from . import auth_bp
from .decorators import login_user, logout_user, is_authenticated, get_current_user, is_pending_2fa

PORTAL_META = {
    'reception': {
        'key': 'reception',
        'name': 'Reception & Front-Desk Portal',
        'station': 'STATION DESK-01',
        'dept': 'Patient Registration & Intake Unit',
        'role_title': 'Front-Desk Receptionist',
        'sample_username': 'reception',
        'sample_password': 'Reception@2026',
        'sample_name': 'Mary Wanjiku (Admissions Desk)',
        'staff_id': 'STF-REC-01',
        'theme_class': 'portal-reception',
        'badge_label': 'DESK-01',
        'home_endpoint': 'reception.dashboard',
        'icon': 'clipboard'
    },
    'triage': {
        'key': 'triage',
        'name': 'Triage & Nursing Station Portal',
        'station': 'STATION TRIAGE-01',
        'dept': 'Clinical Triage & Emergency Assessment',
        'role_title': 'Staff Nurse / Clinical Officer',
        'sample_username': 'nurse',
        'sample_password': 'Triage@2026',
        'sample_name': 'Nurse Mercy Akinyi',
        'staff_id': 'STF-TRG-01',
        'theme_class': 'portal-triage',
        'badge_label': 'TRIAGE-01',
        'home_endpoint': 'triage.dashboard',
        'icon': 'heart-rate'
    },
    'doctor': {
        'key': 'doctor',
        'name': 'Doctor & Clinical EMR Portal',
        'station': 'STATION ROOM-01',
        'dept': 'General Outpatient & Clinical Specialty',
        'role_title': 'Medical Officer / Consultant',
        'sample_username': 'doctor',
        'sample_password': 'Doctor@2026',
        'sample_name': 'Dr. Sarah Kamau (OPD Lead)',
        'staff_id': 'STF-DOC-01',
        'theme_class': 'portal-doctor',
        'badge_label': 'ROOM-01',
        'home_endpoint': 'doctor.dashboard',
        'icon': 'stethoscope'
    },
    'pharmacy': {
        'key': 'pharmacy',
        'name': 'Pharmacy & Dispensation Portal',
        'station': 'STATION PHARM-01',
        'dept': 'Central Pharmacy & Dispensing Services',
        'role_title': 'Lead Pharmacist',
        'sample_username': 'pharmacy',
        'sample_password': 'Pharm@2026',
        'sample_name': 'Pharm. Evans Omondi',
        'staff_id': 'STF-PHM-01',
        'theme_class': 'portal-pharmacy',
        'badge_label': 'PHARM-01',
        'home_endpoint': 'pharmacy.dashboard',
        'icon': 'pill'
    },
    'billing': {
        'key': 'billing',
        'name': 'Point-of-Sale & Billing Portal',
        'station': 'STATION POS-01',
        'dept': 'Revenue Operations & Financial Settlement',
        'role_title': 'Billing Officer / Cashier',
        'sample_username': 'cashier',
        'sample_password': 'Billing@2026',
        'sample_name': 'Cashier Joyce Wambui',
        'staff_id': 'STF-BIL-01',
        'theme_class': 'portal-billing',
        'badge_label': 'POS-01',
        'home_endpoint': 'billing.pos',
        'icon': 'cash'
    },
    'inpatient': {
        'key': 'inpatient',
        'name': 'Inpatient Care & Ward Station',
        'station': 'STATION WARD-01',
        'dept': 'Inpatient Admissions & Ward Services',
        'role_title': 'Ward Charge Nurse',
        'sample_username': 'nurse_ward',
        'sample_password': 'Ward@2026',
        'sample_name': 'Nurse Joyce Chebet (Ward Lead)',
        'staff_id': 'STF-WRD-01',
        'theme_class': 'portal-inpatient',
        'badge_label': 'WARD-01',
        'home_endpoint': 'inpatient.dashboard',
        'icon': 'bed'
    },
    'admin': {
        'key': 'admin',
        'name': 'Hospital Command & Superuser Gateway',
        'station': 'CENTRAL DIRECTORY',
        'dept': 'Hospital Directorate & System Administration',
        'role_title': 'Medical Superintendent',
        'sample_username': 'admin',
        'sample_password': 'Admin@2026',
        'sample_name': 'Dr. Robert Odhiambo (Director)',
        'staff_id': 'STF-ADM-00',
        'theme_class': 'portal-admin',
        'badge_label': 'HQ-00',
        'home_endpoint': 'admin.dashboard',
        'icon': 'shield'
    }
}

@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    portal_key = request.args.get('portal', 'reception')
    if portal_key not in PORTAL_META:
        portal_key = 'reception'
    return handle_portal_login(portal_key)

@auth_bp.route('/login/<portal_name>', methods=['GET', 'POST'])
def login_portal(portal_name):
    if portal_name not in PORTAL_META:
        flash(f'Unknown portal "{portal_name}". Redirecting to Reception Portal.', 'warning')
        return redirect(url_for('auth.login', portal='reception'))
    return handle_portal_login(portal_name)

def handle_portal_login(portal_key):
    meta = PORTAL_META.get(portal_key, PORTAL_META['reception'])
    next_url = request.args.get('next') or request.form.get('next')
    settings = SecuritySetting.get_settings()

    # If already authenticated and authorized for this portal, redirect to destination
    if is_authenticated():
        current_u = get_current_user()
        if current_u and current_u.can_access_portal(portal_key):
            if next_url and next_url.startswith('/'):
                return redirect(next_url)
            return redirect(url_for(meta['home_endpoint']))

    if request.method == 'POST':
        username = request.form.get('username', '').strip().lower()
        password = request.form.get('password', '')

        if not username or not password:
            flash('Please enter both your staff username and clinical password.', 'error')
            return render_template('auth/login.html', meta=meta, portals=PORTAL_META, next_url=next_url, current_portal=portal_key)

        user = User.query.filter_by(username=username).first()

        if not user:
            AuditLog.log_event(
                'failed_login_unknown_user',
                'auth',
                None,
                f"Failed login attempt for unknown username: {username}",
                severity='warning'
            )
            flash('Invalid clinical staff credentials. Please recheck your username and password.', 'error')
            return render_template('auth/login.html', meta=meta, portals=PORTAL_META, next_url=next_url, current_portal=portal_key)

        # Check Brute Force Account Lockout
        if user.is_locked():
            remaining_mins = max(1, int((user.locked_until - datetime.utcnow()).total_seconds() / 60))
            AuditLog.log_event(
                'login_attempt_locked_account',
                'user',
                user.id,
                f"Attempted sign-in to locked account: {user.username}. Locked for {remaining_mins} more minutes.",
                actor=user,
                severity='security_breach'
            )
            flash(f'Account locked due to excessive failed attempts. Try again in {remaining_mins} minute(s) or contact an administrator.', 'error')
            return render_template('auth/login.html', meta=meta, portals=PORTAL_META, next_url=next_url, current_portal=portal_key)

        if not user.check_password(password):
            user.record_failed_login(max_attempts=settings.max_failed_attempts, lockout_minutes=settings.lockout_duration_minutes)
            attempts_left = max(0, settings.max_failed_attempts - user.failed_login_attempts)
            AuditLog.log_event(
                'failed_login_bad_password',
                'user',
                user.id,
                f"Failed password for user: {user.username}. Attempts remaining: {attempts_left}",
                actor=user,
                severity='warning'
            )
            if user.is_locked():
                flash(f'Account locked for {settings.lockout_duration_minutes} minutes due to {settings.max_failed_attempts} failed login attempts.', 'error')
            else:
                flash(f'Invalid password. You have {attempts_left} attempt(s) remaining before temporary lockout.', 'error')
            return render_template('auth/login.html', meta=meta, portals=PORTAL_META, next_url=next_url, current_portal=portal_key)

        if user.status != 'active':
            AuditLog.log_event(
                'login_inactive_user',
                'user',
                user.id,
                f"Attempted login on inactive/suspended user: {user.username}",
                actor=user,
                severity='warning'
            )
            flash('Your account has been suspended or deactivated. Contact HMS Hospital Administrator.', 'error')
            return render_template('auth/login.html', meta=meta, portals=PORTAL_META, next_url=next_url, current_portal=portal_key)

        # Determine 2FA Requirement (Google Authenticator)
        is_2fa_mandated = settings.require_2fa_for_all or (
            settings.require_2fa_for_admin_doctor and user.role in ['admin', 'doctor']
        )

        if user.is_2fa_enabled:
            # Stage 2FA challenge
            session['pending_2fa_user_id'] = user.id
            session['pending_target_portal'] = portal_key
            session['pending_next_url'] = next_url
            return redirect(url_for('auth.verify_2fa'))

        elif is_2fa_mandated:
            # Force 2FA setup wizard
            session['pending_2fa_user_id'] = user.id
            session['pending_target_portal'] = portal_key
            session['pending_next_url'] = next_url
            flash('Hospital Security Policy requires Google Authenticator 2FA setup for your clinical role.', 'info')
            return redirect(url_for('auth.setup_2fa'))

        # Standard authentication without 2FA
        login_user(user, is_2fa_verified=True)
        AuditLog.log_event(
            'login_success',
            'user',
            user.id,
            f"User {user.username} successfully signed in to {portal_key} portal (2FA not enabled).",
            actor=user,
            severity='info'
        )

        if user.can_access_portal(portal_key):
            flash(f'Welcome back, {user.full_name}! Signed in to {meta["name"]}.', 'info')
            if next_url and next_url.startswith('/') and not next_url.startswith('/login') and not next_url.startswith('/logout'):
                return redirect(next_url)
            return redirect(url_for(meta['home_endpoint']))
        else:
            user_meta = PORTAL_META.get(user.portal, PORTAL_META['reception'])
            flash(f'Welcome, {user.full_name}! Signed in and routed to your assigned station: {user_meta["name"]}.', 'info')
            return redirect(url_for(user_meta['home_endpoint']))

    return render_template(
        'auth/login.html',
        meta=meta,
        portals=PORTAL_META,
        next_url=next_url,
        current_portal=portal_key
    )


# ==================== 2FA GOOGLE AUTHENTICATOR VERIFICATION ====================
@auth_bp.route('/verify-2fa', methods=['GET', 'POST'])
def verify_2fa():
    pending_uid = session.get('pending_2fa_user_id')
    if not pending_uid:
        flash('No active sign-in challenge found. Please sign in.', 'warning')
        return redirect(url_for('auth.login'))

    user = db.session.get(User, pending_uid)
    if not user:
        session.pop('pending_2fa_user_id', None)
        return redirect(url_for('auth.login'))

    target_portal = session.get('pending_target_portal', 'reception')
    next_url = session.get('pending_next_url')
    meta = PORTAL_META.get(target_portal, PORTAL_META['reception'])

    if request.method == 'POST':
        totp_code = request.form.get('totp_code', '').strip().replace(' ', '').replace('-', '')
        use_backup = request.form.get('use_backup', 'false') == 'true'

        is_valid = False
        if use_backup:
            # Verify emergency single-use recovery code
            is_valid = user.verify_backup_code(totp_code)
            auth_method = "Emergency Backup Recovery Code"
        else:
            # Verify 6-digit Google Authenticator code
            is_valid = user.verify_totp(totp_code)
            auth_method = "Google Authenticator TOTP"

        if is_valid:
            # Successful 2FA verification
            session.pop('pending_2fa_user_id', None)
            session.pop('pending_target_portal', None)
            session.pop('pending_next_url', None)

            login_user(user, is_2fa_verified=True)
            AuditLog.log_event(
                '2fa_verification_success',
                'user',
                user.id,
                f"User {user.username} passed 2FA verification using {auth_method}.",
                actor=user,
                severity='info'
            )

            flash(f'Two-Factor Authentication verified. Welcome back, {user.full_name}!', 'success')
            if next_url and next_url.startswith('/') and not next_url.startswith('/login') and not next_url.startswith('/logout'):
                return redirect(next_url)

            if user.can_access_portal(target_portal):
                return redirect(url_for(meta['home_endpoint']))
            else:
                user_meta = PORTAL_META.get(user.portal, PORTAL_META['reception'])
                return redirect(url_for(user_meta['home_endpoint']))
        else:
            user.record_failed_login(max_attempts=5, lockout_minutes=15)
            AuditLog.log_event(
                '2fa_verification_failed',
                'user',
                user.id,
                f"Failed 2FA code attempt for user {user.username} ({auth_method}).",
                actor=user,
                severity='warning'
            )
            flash('Invalid 6-digit Authenticator code or recovery key. Please check your Google Authenticator app.', 'error')

    return render_template(
        'auth/verify_2fa.html',
        user=user,
        meta=meta
    )


# ==================== 2FA SETUP WIZARD WITH QR CODE ====================
@auth_bp.route('/setup-2fa', methods=['GET', 'POST'])
def setup_2fa():
    # Allow setup for logged-in user OR pending 2FA setup user
    user = get_current_user()
    is_pending = False
    if not user:
        pending_uid = session.get('pending_2fa_user_id')
        if pending_uid:
            user = db.session.get(User, pending_uid)
            is_pending = True

    if not user:
        flash('Please sign in to configure Two-Factor Authentication.', 'warning')
        return redirect(url_for('auth.login'))

    # Generate or retrieve Base32 secret key
    secret = user.generate_totp_secret()
    totp_uri = user.get_totp_uri(issuer="Apex Regional Medical Center")

    # Generate scannable QR Code image as base64 Data URL
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_L,
        box_size=8,
        border=3,
    )
    qr.add_data(totp_uri)
    qr.make(fit=True)
    img = qr.make_image(fill_color="#0f172a", back_color="#ffffff")
    
    buf = io.BytesIO()
    img.save(buf, format='PNG')
    qr_data_url = f"data:image/png;base64,{base64.b64encode(buf.getvalue()).decode('utf-8')}"

    if request.method == 'POST':
        verification_code = request.form.get('verification_code', '').strip().replace(' ', '')

        if user.verify_totp(verification_code):
            # Activate 2FA and generate 8 emergency recovery codes
            user.is_2fa_enabled = True
            backup_codes = user.generate_backup_codes(count=8)
            db.session.commit()

            AuditLog.log_event(
                '2fa_enabled',
                'user',
                user.id,
                f"User {user.username} successfully enabled Google Authenticator 2FA.",
                actor=user,
                severity='info'
            )

            # Establish full authenticated session
            session.pop('pending_2fa_user_id', None)
            target_portal = session.pop('pending_target_portal', user.portal or 'reception')
            login_user(user, is_2fa_verified=True)

            return render_template(
                'auth/backup_codes.html',
                user=user,
                backup_codes=backup_codes,
                target_portal=target_portal
            )
        else:
            flash('Invalid 6-digit code. Make sure you scanned the QR code with Google Authenticator and enter the live 6-digit token.', 'error')

    return render_template(
        'auth/setup_2fa.html',
        user=user,
        secret=secret,
        qr_data_url=qr_data_url,
        is_pending=is_pending
    )


# ==================== DISABLE 2FA ====================
@auth_bp.route('/disable-2fa', methods=['POST'])
def disable_2fa():
    user = get_current_user()
    if not user:
        flash('Authentication required.', 'error')
        return redirect(url_for('auth.login'))

    password = request.form.get('password', '')
    if not user.check_password(password):
        flash('Incorrect password confirmation. 2FA was not modified.', 'error')
        return redirect(request.referrer or url_for('admin.dashboard'))

    user.is_2fa_enabled = False
    user.totp_secret = None
    user.backup_codes_json = None
    db.session.commit()

    AuditLog.log_event(
        '2fa_disabled',
        'user',
        user.id,
        f"Two-Factor Authentication was disabled for user {user.username}.",
        actor=user,
        severity='critical'
    )
    flash('Two-Factor Authentication has been disabled for your account.', 'info')
    return redirect(request.referrer or url_for('admin.dashboard'))


# ==================== SELF-SERVICE PASSWORD CHANGE ====================
@auth_bp.route('/change-password', methods=['GET', 'POST'])
def change_password():
    user = get_current_user()
    if not user:
        flash('Authentication required to change password.', 'warning')
        return redirect(url_for('auth.login'))

    settings = SecuritySetting.get_settings()

    if request.method == 'POST':
        current_pw = request.form.get('current_password', '')
        new_pw = request.form.get('new_password', '')
        confirm_pw = request.form.get('confirm_password', '')

        if not user.check_password(current_pw):
            flash('Your current password does not match.', 'error')
            return render_template('auth/change_password.html', user=user, settings=settings)

        if len(new_pw) < settings.password_min_length:
            flash(f'New password must be at least {settings.password_min_length} characters in length.', 'error')
            return render_template('auth/change_password.html', user=user, settings=settings)

        if new_pw != confirm_pw:
            flash('New password and confirmation do not match.', 'error')
            return render_template('auth/change_password.html', user=user, settings=settings)

        if current_pw == new_pw:
            flash('New password cannot be the same as your current password.', 'warning')
            return render_template('auth/change_password.html', user=user, settings=settings)

        user.set_password(new_pw)
        db.session.commit()

        AuditLog.log_event(
            'password_changed',
            'user',
            user.id,
            f"User {user.username} successfully updated their login password.",
            actor=user,
            severity='info'
        )

        flash('Your password has been changed successfully.', 'success')
        portal_meta = PORTAL_META.get(user.portal, PORTAL_META['reception'])
        return redirect(url_for(portal_meta['home_endpoint']))

    return render_template('auth/change_password.html', user=user, settings=settings)


@auth_bp.route('/auth/demo-login/<portal_name>', methods=['GET', 'POST'])
def demo_login(portal_name):
    """
    Convenience instant 1-click test login for reviewers to seamlessly jump into any portal.
    """
    if not current_app.config.get('DEMO_LOGIN_ENABLED'):
        abort(404)

    if portal_name not in PORTAL_META:
        portal_name = 'reception'

    meta = PORTAL_META[portal_name]
    user = User.query.filter_by(username=meta['sample_username']).first()

    if not user:
        flash('Demo user not found. Re-initializing seed credentials.', 'warning')
        return redirect(url_for('auth.login', portal=portal_name))

    login_user(user, is_2fa_verified=True)
    flash(f'Signed in as {user.full_name} ({user.role.title()}) on {meta["name"]}.', 'info')
    return redirect(url_for(meta['home_endpoint']))

@auth_bp.route('/logout')
def logout():
    portal = request.args.get('portal', session.get('portal', 'reception'))
    user = get_current_user()
    if user:
        AuditLog.log_event('logout', 'user', user.id, f"User {user.username} signed out of {portal} workstation.", actor=user, severity='info')
    logout_user()
    flash('You have successfully signed out of the clinical workstation.', 'info')
    return redirect(url_for('auth.login', portal=portal))
