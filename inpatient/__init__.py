from flask import Blueprint, redirect, url_for, request, flash
from auth.decorators import is_authenticated, get_current_user

inpatient_bp = Blueprint('inpatient', __name__, url_prefix='/inpatient')

@inpatient_bp.before_request
def check_inpatient_session():
    # Allow explicit login/logout endpoints without session loop
    if request.path in ['/inpatient/login', '/inpatient/logout']:
        return None

    if not is_authenticated():
        flash('Please sign in to access the Inpatient Care & Ward Station.', 'warning')
        return redirect(url_for('auth.login', portal='inpatient', next=request.url))
    
    user = get_current_user()
    if not user or user.status != 'active':
        flash('Your staff account is currently inactive. Please contact the Hospital Administrator.', 'error')
        return redirect(url_for('auth.login', portal='inpatient'))

    # Check if user has permission to access inpatient portal
    if not user.can_access_portal('inpatient') and user.role not in ['admin', 'doctor', 'nurse']:
        flash(f'Access denied. Account "{user.username}" is designated for the {user.portal.title()} station.', 'error')
        return redirect(url_for('auth.login', portal=user.portal))

@inpatient_bp.route('/login')
def login():
    return redirect(url_for('auth.login', portal='inpatient', next=request.args.get('next')))

@inpatient_bp.route('/logout')
def logout():
    return redirect(url_for('auth.logout', portal='inpatient'))

from . import routes
