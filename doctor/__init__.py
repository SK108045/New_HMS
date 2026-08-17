from flask import Blueprint, request, redirect, url_for, flash
from auth.decorators import is_authenticated, get_current_user

doctor_bp = Blueprint('doctor', __name__, url_prefix='/doctor')

@doctor_bp.before_request
def check_doctor_auth():
    if request.path in ['/doctor/login', '/doctor/logout']:
        return None
    if not is_authenticated():
        flash('Please sign in with Doctor / Consultant credentials to access Clinical EMR.', 'warning')
        return redirect(url_for('auth.login', portal='doctor', next=request.url))
    user = get_current_user()
    if not user or not user.can_access_portal('doctor'):
        flash(f'Access restricted: Your staff role ({user.role.title() if user else "guest"}) is not authorized for Clinical EMR.', 'error')
        return redirect(url_for('auth.login', portal='doctor'))

@doctor_bp.route('/login')
def login():
    return redirect(url_for('auth.login', portal='doctor', next=request.args.get('next')))

@doctor_bp.route('/logout')
def logout():
    return redirect(url_for('auth.logout', portal='doctor'))

from . import routes
