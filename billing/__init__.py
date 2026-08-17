from flask import Blueprint, request, redirect, url_for, flash
from auth.decorators import is_authenticated, get_current_user

billing_bp = Blueprint('billing', __name__, url_prefix='/billing')

@billing_bp.before_request
def check_billing_auth():
    if request.path in ['/billing/login', '/billing/logout']:
        return None
    if not is_authenticated():
        flash('Please sign in with Cashier / Billing credentials to access POS operations.', 'warning')
        return redirect(url_for('auth.login', portal='billing', next=request.url))
    user = get_current_user()
    if not user or not user.can_access_portal('billing'):
        flash(f'Access restricted: Your staff role ({user.role.title() if user else "guest"}) is not authorized for POS & Billing.', 'error')
        return redirect(url_for('auth.login', portal='billing'))

@billing_bp.route('/login')
def login():
    return redirect(url_for('auth.login', portal='billing', next=request.args.get('next')))

@billing_bp.route('/logout')
def logout():
    return redirect(url_for('auth.logout', portal='billing'))

from . import routes
