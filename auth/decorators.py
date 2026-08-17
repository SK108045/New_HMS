from functools import wraps
from flask import session, redirect, url_for, flash, request
from models import db, User

def get_current_user():
    user_id = session.get('user_id')
    if not user_id:
        return None
    return db.session.get(User, user_id)

def is_authenticated():
    return 'user_id' in session

def login_user(user):
    session['user_id'] = user.id
    session['username'] = user.username
    session['full_name'] = user.full_name
    session['staff_id'] = user.staff_id
    session['role'] = user.role
    session['portal'] = user.portal
    session['department'] = user.department

def logout_user():
    session.pop('user_id', None)
    session.pop('username', None)
    session.pop('full_name', None)
    session.pop('staff_id', None)
    session.pop('role', None)
    session.pop('portal', None)
    session.pop('department', None)

def login_required(portal=None):
    """
    Decorator that checks if a user is logged in and authorized for the specific portal.
    If not, redirects to the portal-specific login page.
    """
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if not is_authenticated():
                target_portal = portal or 'reception'
                flash('Authentication required. Please sign in to access this clinical station.', 'warning')
                return redirect(url_for('auth.login', portal=target_portal, next=request.url))
            
            user = get_current_user()
            if not user or user.status != 'active':
                logout_user()
                flash('Your account is inactive or not found. Please contact administration.', 'error')
                return redirect(url_for('auth.login', portal=portal or 'reception'))

            if portal and not user.can_access_portal(portal):
                flash(f'Access denied. Your profile ({user.role.title()}) is not authorized for the {portal.title()} Portal.', 'error')
                # Redirect to the user's authorized home portal
                if user.portal == 'doctor':
                    return redirect(url_for('doctor.dashboard'))
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
