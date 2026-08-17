from flask import Blueprint, request, redirect, url_for, flash
from auth.decorators import is_authenticated, get_current_user

pharmacy_bp = Blueprint('pharmacy', __name__, url_prefix='/pharmacy')

@pharmacy_bp.before_request
def check_pharmacy_auth():
    if request.path in ['/pharmacy/login', '/pharmacy/logout']:
        return None
    if not is_authenticated():
        flash('Please sign in with Pharmacy credentials to access Dispensing services.', 'warning')
        return redirect(url_for('auth.login', portal='pharmacy', next=request.url))
    user = get_current_user()
    if not user or not user.can_access_portal('pharmacy'):
        flash(f'Access restricted: Your staff role ({user.role.title() if user else "guest"}) is not authorized for Pharmacy.', 'error')
        return redirect(url_for('auth.login', portal='pharmacy'))

@pharmacy_bp.route('/login')
def login():
    return redirect(url_for('auth.login', portal='pharmacy', next=request.args.get('next')))

@pharmacy_bp.route('/logout')
def logout():
    return redirect(url_for('auth.logout', portal='pharmacy'))

from . import routes
