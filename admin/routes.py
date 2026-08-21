from datetime import date, datetime, timedelta

from flask import flash, redirect, render_template, request, url_for

from auth.decorators import get_current_user
from models import (
    db, Appointment, AuditLog, DrugBatch, Invoice, LabOrder, MedicationItem,
    Patient, Payment, Prescription, QueueEntry, ShiftRegister, User
)
from . import admin_bp


ROLE_PORTALS = {
    'admin': 'all',
    'receptionist': 'reception',
    'nurse': 'triage',
    'doctor': 'doctor',
    'pharmacist': 'pharmacy',
    'cashier': 'billing',
}


def log_action(action, entity_type, entity_id=None, details=None):
    actor = get_current_user()
    db.session.add(AuditLog(
        actor_user_id=actor.id,
        actor_name=actor.full_name,
        action=action,
        entity_type=entity_type,
        entity_id=str(entity_id) if entity_id is not None else None,
        details=details,
    ))


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
    return render_template(
        'admin/dashboard.html', active_staff=active_staff, active_queue=active_queue,
        open_balance=open_balance, today_collections=today_collections, low_stock=low_stock,
        expiring=expiring, recent_audit=AuditLog.query.order_by(AuditLog.created_at.desc()).limit(8).all(),
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
            db.session.add(user)
            db.session.flush()
            log_action('staff_created', 'user', user.id, f'Created {role} account for {full_name}.')
            db.session.commit()
            flash(f'{full_name} has been added as {role.title()}.', 'success')
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
