import time
import secrets
from functools import wraps
from datetime import datetime
from flask import session, redirect, url_for, flash, request, abort
from models import db, User, SecuritySetting, AuditLog

def clear_pending_auth_state():
    """Clear all intermediate unverified authentication and enrollment states."""
    session.pop('pending_2fa_user_id', None)
    session.pop('pending_2fa_enrollment_user_id', None)
    session.pop('pending_force_pw_user_id', None)
    session.pop('pending_target_portal', None)
    session.pop('pending_next_url', None)
    session.pop('pending_auth_version', None)
    session.pop('pending_auth_at', None)

def get_current_user():
    user_id = session.get('user_id')
    if not user_id:
        return None
    return db.session.get(User, user_id)

def is_authenticated():
    return (
        'user_id' in session
        and session.get('2fa_verified') is True
        and not session.get('pending_2fa_user_id')
        and not session.get('pending_2fa_enrollment_user_id')
        and not session.get('pending_force_pw_user_id')
    )

def is_pending_2fa():
    return 'pending_2fa_user_id' in session

def is_pending_enrollment():
    return 'pending_2fa_enrollment_user_id' in session

def login_user(user, is_2fa_verified=True):
    clear_pending_auth_state()
    session['user_id'] = user.id
    session['username'] = user.username
    session['full_name'] = user.full_name
    session['staff_id'] = user.staff_id
    session['role'] = user.role
    session['portal'] = user.portal
    session['department'] = user.department
    session['2fa_verified'] = is_2fa_verified
    session['last_active'] = time.time()
    session['auth_version'] = user.auth_version
    user.active_session_token = secrets.token_urlsafe(32)
    session['active_session_token'] = user.active_session_token
    session['auth_password_changed_at'] = user.password_changed_at.isoformat() if user.password_changed_at else None

    user.last_login = datetime.utcnow()
    user.last_activity_at = datetime.utcnow()
    user.reset_failed_logins()
    db.session.flush()

def logout_user():
    session.clear()

def login_required(portal=None):
    """
    Decorator that checks if a user is logged in, has passed 2FA verification,
    and is authorized for the specific portal.
    """
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            # Check 2FA pending challenge state
            if is_pending_2fa():
                flash('Please complete Google Authenticator 2FA verification.', 'info')
                return redirect(url_for('auth.verify_2fa'))

            # Check 2FA pending enrollment state
            if is_pending_enrollment():
                flash('Hospital Security Policy requires Two-Factor Authentication setup before accessing clinical stations.', 'warning')
                return redirect(url_for('auth.setup_2fa'))

            if not is_authenticated():
                target_portal = portal or 'reception'
                flash('Authentication required. Please sign in to access this clinical station.', 'warning')
                return redirect(url_for('auth.login', portal=target_portal, next=request.url))
            
            user = get_current_user()
            if not user or user.status != 'active':
                logout_user()
                flash('Your account is inactive or suspended. Please contact administration.', 'error')
                return redirect(url_for('auth.login', portal=portal or 'reception'))

            if user.is_locked():
                logout_user()
                flash('Account locked due to excessive failed attempts.', 'error')
                return redirect(url_for('auth.login', portal=portal or 'reception'))

            # Invalidate session if password was changed
            if user.password_changed_at and session.get('auth_password_changed_at'):
                if session.get('auth_password_changed_at') != user.password_changed_at.isoformat():
                    logout_user()
                    flash('Your password was recently updated. Please sign in again with your new credentials.', 'warning')
                    return redirect(url_for('auth.login', portal=portal or 'reception'))

            # Force Password Change on First Sign-in or Admin Trigger
            if user.force_password_change and request.endpoint not in ['auth.force_change_password', 'auth.change_password', 'auth.logout']:
                flash('Hospital Security Policy requires you to set a new password before proceeding.', 'warning')
                return redirect(url_for('auth.force_change_password'))

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
                db.session.commit()
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
    Returns HTTP 403 for permission denial.
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
                db.session.commit()
                flash(f"Security Alert: Your role does not possess the '{permission_code}' permission.", 'error')
                if request.headers.get('HX-Request'):
                    return "<div class='p-4 bg-rose-100 text-rose-900 border border-rose-300 rounded-xl text-xs font-bold'>Permission Denied: Action requires '" + permission_code + "' privilege.</div>", 403
                return (f"Forbidden: Action requires '{permission_code}' privilege.", 403)

            return f(*args, **kwargs)
        return decorated_function
    return decorator


def stage_auth(user, key):
    clear_pending_auth_state()
    for name in ('user_id', '2fa_verified', 'auth_version', 'active_session_token'):
        session.pop(name, None)
    session[key] = user.id
    session['pending_auth_version'] = user.auth_version
    session['pending_auth_at'] = time.time()


def pending_auth_valid(user):
    return (user is not None and user.status == 'active' and not user.is_locked()
            and session.get('pending_auth_version') == user.auth_version
            and 0 <= time.time() - session.get('pending_auth_at', 0) < 600)
