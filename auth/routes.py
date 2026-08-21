from datetime import datetime
from flask import abort, current_app, render_template, request, redirect, url_for, flash, session
from models import db, User
from . import auth_bp
from .decorators import login_user, logout_user, is_authenticated, get_current_user

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

        if not user or not user.check_password(password):
            flash('Invalid clinical staff username or password. Please recheck your credentials.', 'error')
            return render_template('auth/login.html', meta=meta, portals=PORTAL_META, next_url=next_url, current_portal=portal_key)

        if user.status != 'active':
            flash('Your account has been suspended or deactivated. Contact HMS Hospital Administrator.', 'error')
            return render_template('auth/login.html', meta=meta, portals=PORTAL_META, next_url=next_url, current_portal=portal_key)

        # Successful login
        login_user(user)
        user.last_login = datetime.utcnow()
        db.session.commit()

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

    login_user(user)
    user.last_login = datetime.utcnow()
    db.session.commit()

    flash(f'Signed in as {user.full_name} ({user.role.title()}) on {meta["name"]}.', 'info')
    return redirect(url_for(meta['home_endpoint']))

@auth_bp.route('/logout')
def logout():
    portal = request.args.get('portal', session.get('portal', 'reception'))
    logout_user()
    flash('You have successfully signed out of the clinical workstation.', 'info')
    return redirect(url_for('auth.login', portal=portal))
