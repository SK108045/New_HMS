from flask import Blueprint, flash, redirect, request, url_for

from auth.decorators import get_current_user, is_authenticated

admin_bp = Blueprint('admin', __name__, url_prefix='/admin')


@admin_bp.before_request
def require_administrator():
    if request.path in ['/admin/login', '/admin/logout']:
        return None
    if not is_authenticated():
        flash('Administrator sign-in is required to access hospital controls.', 'warning')
        return redirect(url_for('auth.login', portal='admin', next=request.url))
    user = get_current_user()
    if not user or user.status != 'active' or user.role != 'admin':
        flash('Administrator access is required for hospital-wide controls.', 'error')
        return redirect(url_for('auth.login', portal='admin'))


@admin_bp.route('/login')
def login():
    return redirect(url_for('auth.login', portal='admin', next=request.args.get('next')))


@admin_bp.route('/logout')
def logout():
    return redirect(url_for('auth.logout', portal='admin'))


from . import routes
