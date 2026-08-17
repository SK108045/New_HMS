from flask import Blueprint, request, redirect, url_for, flash
from auth.decorators import is_authenticated, get_current_user

triage_bp = Blueprint('triage', __name__, url_prefix='/triage')

@triage_bp.before_request
def check_triage_auth():
    if request.path in ['/triage/login', '/triage/logout']:
        return None
    if not is_authenticated():
        flash('Please sign in with Nursing / Triage credentials to access Triage operations.', 'warning')
        return redirect(url_for('auth.login', portal='triage', next=request.url))
    user = get_current_user()
    if not user or not user.can_access_portal('triage'):
        flash(f'Access restricted: Your staff role ({user.role.title() if user else "guest"}) is not authorized for Triage.', 'error')
        return redirect(url_for('auth.login', portal='triage'))

@triage_bp.route('/login')
def login():
    return redirect(url_for('auth.login', portal='triage', next=request.args.get('next')))

@triage_bp.route('/logout')
def logout():
    return redirect(url_for('auth.logout', portal='triage'))

from . import routes
