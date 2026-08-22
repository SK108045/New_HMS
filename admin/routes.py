from datetime import date, datetime, timedelta
from flask import flash, redirect, render_template, request, url_for
from auth.decorators import get_current_user, permission_required
from models import (
    db, Appointment, AuditLog, DrugBatch, Invoice, LabOrder, MedicationItem,
    Patient, Payment, Prescription, QueueEntry, ShiftRegister, User,
    SecuritySetting, Permission, RolePermission
)
from . import admin_bp

ROLE_PORTALS = {
    'admin': 'all',
    'receptionist': 'reception',
    'nurse': 'triage',
    'doctor': 'doctor',
    'pharmacist': 'pharmacy',
    'cashier': 'billing',
    'inpatient': 'inpatient',
}

def log_action(action, entity_type, entity_id=None, details=None, severity='info'):
    actor = get_current_user()
    AuditLog.log_event(
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        details=details or "",
        actor=actor,
        severity=severity
    )

@admin_bp.route('/')
@admin_bp.route('/dashboard')
def dashboard():
    today_start = datetime.combine(date.today(), datetime.min.time())
    active_staff = User.query.filter_by(status='active').count()
    active_queue = QueueEntry.query.filter(QueueEntry.status.in_(['waiting', 'in_progress'])).count()
    open_balance = db.session.query(db.func.coalesce(db.func.sum(Invoice.balance_due), 0)).filter(
        Invoice.status.in_(['unpaid', 'partially_paid'])
    ).scalar()
    today_collections = db.session.query(db.func.coalesce(db.func.sum(Payment.total_amount_paid), 0)).filter(
        Payment.created_at >= today_start
    ).scalar()
    low_stock = MedicationItem.query.filter(MedicationItem.current_stock <= MedicationItem.reorder_level).count()
    expiring = DrugBatch.query.filter(
        DrugBatch.status == 'active', DrugBatch.quantity_remaining > 0,
        DrugBatch.expiry_date <= date.today() + timedelta(days=90)
    ).count()
    
    # 2FA Metric
    total_users = User.query.count()
    two_fa_count = User.query.filter_by(is_2fa_enabled=True).count()
    two_fa_pct = round((two_fa_count / total_users * 100) if total_users else 0, 1)

    return render_template(
        'admin/dashboard.html', active_staff=active_staff, active_queue=active_queue,
        open_balance=open_balance, today_collections=today_collections, low_stock=low_stock,
        expiring=expiring, two_fa_pct=two_fa_pct, two_fa_count=two_fa_count,
        recent_audit=AuditLog.query.order_by(AuditLog.created_at.desc()).limit(8).all(),
        recent_patients=Patient.query.order_by(Patient.created_at.desc()).limit(6).all(),
    )


@admin_bp.route('/staff', methods=['GET', 'POST'])
def staff():
    if request.method == 'POST':
        username = request.form.get('username', '').strip().lower()
        full_name = request.form.get('full_name', '').strip()
        staff_id = request.form.get('staff_id', '').strip().upper()
        role = request.form.get('role', '').strip()
        password = request.form.get('password', '')
        if not username or not full_name or not staff_id or not password or role not in ROLE_PORTALS:
            flash('Name, staff ID, username, password, and a valid role are required.', 'error')
        elif User.query.filter(db.or_(User.username == username, User.staff_id == staff_id)).first():
            flash('A user already exists with that username or staff ID.', 'error')
        else:
            user = User(
                username=username, full_name=full_name, staff_id=staff_id, role=role,
                portal=ROLE_PORTALS[role], department=request.form.get('department', '').strip() or 'General Administration',
                email=request.form.get('email', '').strip() or None, phone=request.form.get('phone', '').strip() or None,
                status='active',
            )
            user.set_password(password)
            user.force_password_change = True  # Force employee to establish private password on first login
            db.session.add(user)
            db.session.flush()
            log_action('staff_created', 'user', user.id, f'Created {role} account for {full_name} with temporary password.')
            db.session.commit()
            flash(f'{full_name} has been added as {role.title()}. They will be prompted to update their password on first sign-in.', 'success')
            return redirect(url_for('admin.staff'))
    return render_template('admin/staff.html', staff=User.query.order_by(User.full_name).all(), roles=ROLE_PORTALS)


@admin_bp.route('/staff/<int:user_id>/update', methods=['POST'])
def update_staff(user_id):
    user = User.query.get_or_404(user_id)
    role = request.form.get('role', user.role)
    status = request.form.get('status', user.status)
    if role not in ROLE_PORTALS or status not in {'active', 'inactive', 'suspended'}:
        flash('Invalid staff role or account status.', 'error')
        return redirect(url_for('admin.staff'))
    actor = get_current_user()
    if user.id == actor.id and (role != 'admin' or status != 'active'):
        flash('You cannot remove or disable your own administrator access.', 'error')
        return redirect(url_for('admin.staff'))
    user.role = role
    user.portal = ROLE_PORTALS[role]
    user.status = status
    user.department = request.form.get('department', user.department).strip() or user.department
    new_password = request.form.get('new_password', '')
    if new_password:
        user.set_password(new_password)
    log_action('staff_updated', 'user', user.id, f'Role: {role}; status: {status}.')
    db.session.commit()
    flash(f'Updated {user.full_name}.', 'success')
    return redirect(url_for('admin.staff'))


# ==================== SECURITY COMMAND CENTER & RBAC ====================
@admin_bp.route('/security')
def security():
    settings = SecuritySetting.get_settings()
    users = User.query.order_by(User.full_name).all()
    total_users = len(users)
    two_fa_enabled_count = sum(1 for u in users if u.is_2fa_enabled)
    two_fa_percentage = round((two_fa_enabled_count / total_users * 100) if total_users else 0, 1)
    
    security_incidents_count = AuditLog.query.filter(
        AuditLog.severity.in_(['warning', 'critical', 'security_breach'])
    ).count()

    permissions = Permission.query.order_by(Permission.category, Permission.name).all()
    role_perms = RolePermission.query.all()
    
    # Map role -> {perm_code: True}
    role_matrix = {}
    for rp in role_perms:
        if rp.role not in role_matrix:
            role_matrix[rp.role] = {}
        role_matrix[rp.role][rp.permission_code] = True

    audit_logs = AuditLog.query.order_by(AuditLog.created_at.desc()).limit(50).all()

    return render_template(
        'admin/security.html',
        settings=settings,
        users=users,
        total_users=total_users,
        two_fa_enabled_count=two_fa_enabled_count,
        two_fa_percentage=two_fa_percentage,
        security_incidents_count=security_incidents_count,
        permissions=permissions,
        role_matrix=role_matrix,
        audit_logs=audit_logs
    )


@admin_bp.route('/security/settings', methods=['POST'])
def update_security_settings():
    settings = SecuritySetting.get_settings()
    actor = get_current_user()

    settings.require_2fa_for_all = bool(request.form.get('require_2fa_for_all'))
    settings.require_2fa_for_admin_doctor = bool(request.form.get('require_2fa_for_admin_doctor'))
    settings.session_timeout_minutes = int(request.form.get('session_timeout_minutes', 30))
    settings.max_failed_attempts = int(request.form.get('max_failed_attempts', 5))
    settings.lockout_duration_minutes = int(request.form.get('lockout_duration_minutes', 15))
    settings.password_min_length = int(request.form.get('password_min_length', 8))
    settings.require_special_chars = bool(request.form.get('require_special_chars'))
    settings.updated_at = datetime.utcnow()
    settings.updated_by = actor.full_name if actor else 'System Administrator'

    db.session.commit()
    log_action('security_settings_updated', 'security_setting', settings.id, "Hospital-wide security and 2FA policies updated.", severity='warning')
    flash('Hospital security policies updated and deployed successfully.', 'success')
    return redirect(url_for('admin.security'))


@admin_bp.route('/security/permissions', methods=['POST'])
def update_role_permissions():
    permissions = Permission.query.all()
    roles = ['doctor', 'nurse', 'pharmacist', 'cashier', 'receptionist']

    # Clear existing role permissions
    RolePermission.query.delete()

    for role in roles:
        for perm in permissions:
            field_name = f"perm_{role}_{perm.code}"
            if request.form.get(field_name):
                rp = RolePermission(role=role, permission_code=perm.code)
                db.session.add(rp)

    db.session.commit()
    log_action('rbac_matrix_updated', 'role_permission', None, "RBAC Role-Permission matrix reconfigured.", severity='warning')
    flash('Role-Based Access Control (RBAC) matrix saved successfully.', 'success')
    return redirect(url_for('admin.security'))


@admin_bp.route('/staff/<int:user_id>/revoke-2fa', methods=['POST'])
@admin_bp.route('/security/reset-2fa/<int:user_id>', methods=['POST'])
def reset_user_2fa(user_id):
    user = User.query.get_or_404(user_id)
    user.is_2fa_enabled = False
    user.totp_secret = None
    user.backup_codes_json = None
    db.session.commit()

    log_action('admin_revoke_user_2fa', 'user', user.id, f"Admin revoked and deleted 2FA secret from DB for {user.full_name} ({user.username}).", severity='critical')
    flash(f"Two-Factor Authentication for {user.full_name} has been revoked and deleted from the database.", 'warning')
    
    referrer = request.referrer
    if referrer and '/admin/staff' in referrer:
        return redirect(url_for('admin.staff'))
    return redirect(url_for('admin.security'))


@admin_bp.route('/security/unlock/<int:user_id>', methods=['POST'])
def unlock_user(user_id):
    user = User.query.get_or_404(user_id)
    user.reset_failed_logins()
    db.session.commit()

    log_action('admin_unlocked_user', 'user', user.id, f"Admin unlocked brute-forced account: {user.full_name} ({user.username}).", severity='info')
    flash(f"Account for {user.full_name} unlocked successfully.", 'success')
    return redirect(url_for('admin.security'))


@admin_bp.route('/security/force-password-change/<int:user_id>', methods=['POST'])
def force_user_password_change(user_id):
    user = User.query.get_or_404(user_id)
    user.force_password_change = True
    db.session.commit()

    log_action('admin_forced_password_change', 'user', user.id, f"Admin flagged {user.full_name} to update password on next sign-in.", severity='info')
    flash(f"{user.full_name} will be required to change their password on next workstation login.", 'info')
    return redirect(url_for('admin.security'))


@admin_bp.route('/operations')
def operations():
    today_start = datetime.combine(date.today(), datetime.min.time())
    return render_template(
        'admin/operations.html',
        queue_entries=QueueEntry.query.filter(QueueEntry.status.in_(['waiting', 'in_progress'])).order_by(QueueEntry.checked_in_at).limit(20).all(),
        appointments=Appointment.query.filter(Appointment.scheduled_date >= date.today()).order_by(Appointment.scheduled_date, Appointment.scheduled_time).limit(12).all(),
        labs=LabOrder.query.filter(LabOrder.status != 'completed').order_by(LabOrder.created_at).limit(12).all(),
        prescriptions=Prescription.query.filter(Prescription.status.in_(['pending_dispense', 'partially_dispensed'])).order_by(Prescription.created_at).limit(12).all(),
        today_patients=Patient.query.filter(Patient.created_at >= today_start).order_by(Patient.created_at.desc()).all(),
    )


@admin_bp.route('/finance')
def finance():
    return render_template(
        'admin/finance.html',
        invoices=Invoice.query.order_by(Invoice.created_at.desc()).limit(20).all(),
        payments=Payment.query.order_by(Payment.created_at.desc()).limit(20).all(),
        shifts=ShiftRegister.query.order_by(ShiftRegister.opened_at.desc()).limit(10).all(),
    )


@admin_bp.route('/inventory')
def inventory():
    return render_template(
        'admin/inventory.html',
        medications=MedicationItem.query.order_by(MedicationItem.name).all(),
        batches=DrugBatch.query.filter(DrugBatch.quantity_remaining > 0).order_by(DrugBatch.expiry_date).limit(20).all(),
    )


@admin_bp.route('/audit')
def audit():
    return render_template('admin/audit.html', logs=AuditLog.query.order_by(AuditLog.created_at.desc()).limit(100).all())
