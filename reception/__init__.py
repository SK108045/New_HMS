from flask import Blueprint, request, redirect, url_for, flash
from auth.decorators import is_authenticated, get_current_user

reception_bp = Blueprint(
    'reception', 
    __name__, 
    url_prefix='/reception',
    template_folder='../templates'
)

@reception_bp.before_request
def check_reception_auth():
    if request.path in ['/reception/login', '/reception/logout']:
        return None
    if not is_authenticated():
        flash('Please sign in with Reception credentials to access Front-Desk operations.', 'warning')
        return redirect(url_for('auth.login', portal='reception', next=request.url))
    user = get_current_user()
    if not user or not user.can_access_portal('reception'):
        flash(f'Access restricted: Your staff role ({user.role.title() if user else "guest"}) is not authorized for Reception.', 'error')
        return redirect(url_for('auth.login', portal='reception'))

@reception_bp.route('/login')
def login():
    return redirect(url_for('auth.login', portal='reception', next=request.args.get('next')))

@reception_bp.route('/logout')
def logout():
    return redirect(url_for('auth.logout', portal='reception'))

from . import routes
