import time
from functools import wraps
from datetime import datetime
from flask import session, redirect, url_for, flash, request, abort
from models import db, User, SecuritySetting, AuditLog

def get_current_user():
    user_id = session.get('user_id')
    if not user_id:
        return None
    return db.session.get(User, user_id)

def is_authenticated():
    return 'user_id' in session and session.get('2fa_verified', True)

def is_pending_2fa():
    return 'pending_2fa_user_id' in session

def login_user(user, is_2fa_verified=True):
    session['user_id'] = user.id
    session['username'] = user.username
    session['full_name'] = user.full_name
    session['staff_id'] = user.staff_id
    session['role'] = user.role
    session['portal'] = user.portal
    session['department'] = user.department
    session['2fa_verified'] = is_2fa_verified
    session['last_active'] = time.time()

    user.last_login = datetime.utcnow()
    user.last_activity_at = datetime.utcnow()
    user.reset_failed_logins()
    db.session.commit()

def logout_user():
    session.pop('user_id', None)
    session.pop('username', None)
    session.pop('full_name', None)
    session.pop('staff_id', None)
    session.pop('role', None)
    session.pop('portal', None)
    session.pop('department', None)
    session.pop('2fa_verified', None)
    session.pop('last_active', None)
    session.pop('pending_2fa_user_id', None)

def login_required(portal=None):
    """
    Decorator that checks if a user is logged in, has passed 2FA verification,
    and is authorized for the specific portal.
    """
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            # Check 2FA pending state
            if is_pending_2fa():
                flash('Please complete Google Authenticator 2FA verification.', 'info')
                return redirect(url_for('auth.verify_2fa'))

            if not is_authenticated():
                target_portal = portal or 'reception'
                flash('Authentication required. Please sign in to access this clinical station.', 'warning')
                return redirect(url_for('auth.login', portal=target_portal, next=request.url))
            
            user = get_current_user()
            if not user or user.status != 'active':
                logout_user()
                flash('Your account is inactive or suspended. Please contact administration.', 'error')
                return redirect(url_for('auth.login', portal=portal or 'reception'))

            # Force Password Change on First Sign-in or Admin Trigger
            if user.force_password_change and request.endpoint not in ['auth.change_password', 'auth.logout']:
                flash('Hospital Security Policy requires you to set a new password before proceeding.', 'warning')
                return redirect(url_for('auth.change_password'))

            # Portal Access Verification
            if portal and not user.can_access_portal(portal):
                AuditLog.log_event(
                    'unauthorized_portal_access',
                    'portal',
                    portal,
                    f"User {user.username} ({user.role}) attempted unauthorized access to {portal} portal.",
                    actor=user,
                    severity='warning'
                )
                flash(f'Access denied. Your profile ({user.role.title()}) is not authorized for the {portal.title()} Portal.', 'error')
                
                # Redirect to the user's authorized home portal
                if user.role == 'admin':
                    return redirect(url_for('admin.dashboard'))
                elif user.portal == 'doctor':
                    return redirect(url_for('doctor.dashboard'))
                elif user.portal == 'inpatient':
                    return redirect(url_for('inpatient.dashboard'))
                elif user.portal == 'triage':
                    return redirect(url_for('triage.dashboard'))
                elif user.portal == 'pharmacy':
                    return redirect(url_for('pharmacy.dashboard'))
                elif user.portal == 'billing':
                    return redirect(url_for('billing.pos'))
                else:
                    return redirect(url_for('reception.dashboard'))

            return f(*args, **kwargs)
        return decorated_function
    return decorator


def permission_required(permission_code: str):
    """
    Granular RBAC Decorator enforcing specific functional capabilities.
    e.g. @permission_required('clinical:prescribe')
    """
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if not is_authenticated():
                flash('Authentication required.', 'warning')
                return redirect(url_for('auth.login', next=request.url))
            
            user = get_current_user()
            if not user or not user.has_permission(permission_code):
                AuditLog.log_event(
                    'permission_denied',
                    'permission',
                    permission_code,
                    f"Permission Denied: {user.username if user else 'Unknown'} attempted action requiring '{permission_code}'.",
                    actor=user,
                    severity='warning'
                )
                flash(f"Security Alert: Your role does not possess the '{permission_code}' permission.", 'error')
                if request.headers.get('HX-Request'):
                    return "<div class='p-4 bg-rose-100 text-rose-900 border border-rose-300 rounded-xl text-xs font-bold'>Permission Denied: Action requires '" + permission_code + "' privilege.</div>", 403
                return redirect(request.referrer or url_for('reception.dashboard'))

            return f(*args, **kwargs)
        return decorated_function
    return decorator
