from urllib.parse import urlparse, urljoin
from flask import request, session, redirect, url_for, flash, abort
from models import db, User, SecuritySetting, AuditLog
from auth.decorators import is_authenticated, get_current_user, logout_user


def validate_password_policy(password: str, settings=None) -> tuple[bool, str]:
    """
    Enforces hospital password complexity policies:
    - Minimum length
    - Mandatory special characters when require_special_chars=True
    """
    if not password:
        return False, "Password cannot be empty."

    if settings is None:
        settings = SecuritySetting.get_settings()

    min_len = settings.password_min_length or 8
    if len(password) < min_len:
        return False, f"Password must be at least {min_len} characters in length."

    if settings.require_special_chars:
        # Must contain at least one non-alphanumeric special character
        if not any(not c.isalnum() and not c.isspace() for c in password):
            return False, "Password must contain at least one special character (e.g. !@#$%^&*)."

    return True, ""


def is_safe_url(target: str) -> bool:
    """
    Validates that a redirection target is a safe local path and not an external open-redirect vector.
    Disallows scheme-relative URLs (//) and backslashes (/\\).
    """
    if not target or not isinstance(target, str):
        return False
    target = target.strip()
    if not target:
        return False
    if not target.startswith('/') or target.startswith('//') or target.startswith('/\\'):
        return False
    try:
        ref_url = urlparse(request.host_url)
        test_url = urlparse(urljoin(request.host_url, target))
        if test_url.scheme not in ('http', 'https'):
            return False
        if ref_url.netloc != test_url.netloc:
            return False
    except Exception:
        return False

    # Block recursive redirection into auth endpoints
    for forbidden in ('/login', '/logout', '/auth/login', '/auth/logout', '/verify-2fa', '/auth/verify-2fa'):
        if target == forbidden or target.startswith(forbidden + '/') or target.startswith(forbidden + '?'):
            return False

    return True


ENDPOINT_PERMISSIONS = {('reception.quick_search', 'GET'): 'patient:view',
 ('reception.search', 'GET'): 'patient:view',
 ('reception.register', 'POST'): 'patient:register',
 ('reception.patient_detail', 'GET'): 'patient:view',
 ('reception.edit_patient', 'GET'): 'patient:view',
 ('reception.edit_patient', 'POST'): 'patient:edit',
 ('reception.print_card', 'GET'): 'patient:view',
 ('reception.checkin', 'GET'): 'patient:view',
 ('reception.checkin', 'POST'): 'patient:edit',
 ('reception.cancel_queue', 'POST'): 'patient:edit',
 ('reception.appointments', 'POST'): 'patient:edit',
 ('reception.confirm_appointment', 'POST'): 'patient:edit',
 ('reception.cancel_appointment', 'POST'): 'patient:edit',
 ('reception.send_appointment_reminder', 'POST'): 'telephony:send',
 ('reception.checkin_from_appointment', 'POST'): 'patient:edit',
 ('reception.telephony_hub', 'GET'): 'telephony:send',
 ('reception.send_custom_sms', 'POST'): 'telephony:send',
 ('reception.send_patient_otp', 'POST'): 'telephony:send',
 ('reception.verify_patient_otp', 'POST'): 'telephony:send',
 ('reception.send_queue_sms', 'POST'): 'telephony:send',
 ('reception.paystack_prompt', 'POST'): 'billing:collect_consultation',
 ('reception.paystack_verify', 'GET'): 'billing:collect_consultation',
 ('reception.paystack_verify', 'POST'): 'billing:collect_consultation',
 ('reception.paystack_manual_settle', 'POST'): 'billing:collect_consultation',
 ('reception.receipt_view', 'GET'): 'patient:view',
 ('triage.vitals_intake', 'GET'): 'patient:view',
 ('triage.vitals_intake', 'POST'): ('inpatient:chart', 'clinical:consult'),
 ('triage.direct_vitals', 'GET'): 'patient:view',
 ('triage.direct_vitals', 'POST'): ('inpatient:chart', 'clinical:consult'),
 ('triage.vitals_history_json', 'GET'): 'patient:view',
 ('triage.call_patient', 'POST'): ('inpatient:chart', 'patient:view'),
 ('doctor.consultation', 'GET'): 'patient:view',
 ('doctor.consultation', 'POST'): 'clinical:consult',
 ('doctor.patient_chart', 'GET'): 'patient:view',
 ('doctor.direct_consult', 'GET'): 'patient:view',
 ('doctor.review_lab_order', 'POST'): ('clinical:order_labs', 'clinical:record_results'),
 ('doctor.generate_medical_certificate', 'GET'): 'patient:view',
 ('doctor.generate_medical_certificate', 'POST'): 'documents:generate_cert',
 ('doctor.print_medical_certificate', 'GET'): 'patient:view',
 ('doctor.generate_referral_letter', 'GET'): 'patient:view',
 ('doctor.generate_referral_letter', 'POST'): 'documents:generate_referral',
 ('doctor.print_referral_letter', 'GET'): 'patient:view',
 ('doctor.print_prescription', 'GET'): 'patient:view',
 ('doctor.upload_attachment', 'POST'): 'documents:upload',
 ('doctor.schedule', 'POST'): 'clinical:consult',
 ('doctor.record_lab_results', 'GET'): 'clinical:record_results',
 ('doctor.record_lab_results', 'POST'): 'clinical:record_results',
 ('pharmacy.dispense', 'POST'): 'pharmacy:dispense',
 ('pharmacy.add_medication', 'POST'): 'pharmacy:manage_stock',
 ('pharmacy.restock_medication', 'POST'): 'pharmacy:manage_stock',
 ('pharmacy.create_purchase_order', 'POST'): 'pharmacy:manage_stock',
 ('pharmacy.receive_purchase_order', 'POST'): 'pharmacy:manage_stock',
 ('pharmacy.controlled_drugs', 'POST'): ('pharmacy:dispense', 'pharmacy:manage_stock'),
 ('pharmacy.create_quarantine_record', 'POST'): 'pharmacy:manage_stock',
 ('pharmacy.action_quarantine', 'POST'): 'pharmacy:manage_stock',
 ('billing.pos', 'GET'): 'patient:view',
 ('billing.add_tariff_item', 'POST'): 'billing:create_invoice',
 ('billing.process_settlement', 'POST'): 'billing:collect_payment',
 ('billing.close_shift', 'POST'): 'billing:collect_payment',
 ('billing.create_preauth_claim', 'POST'): 'billing:create_invoice',
 ('billing.update_claim_status', 'POST'): 'billing:create_invoice',
 ('billing.create_credit_note', 'POST'): 'billing:waive_discount',
 ('billing.action_credit_note', 'POST'): 'billing:waive_discount',
 ('billing.create_fee_waiver', 'POST'): 'billing:waive_discount',
 ('billing.action_fee_waiver', 'POST'): 'billing:waive_discount',
 ('inpatient.admit', 'POST'): 'inpatient:admit',
 ('inpatient.patient_chart', 'GET'): 'patient:view',
 ('inpatient.add_nursing_note', 'POST'): 'inpatient:chart',
 ('inpatient.add_ward_round', 'POST'): 'inpatient:chart',
 ('inpatient.transfer_bed', 'POST'): 'inpatient:transfer',
 ('inpatient.discharge', 'GET'): 'patient:view',
 ('inpatient.discharge', 'POST'): 'inpatient:discharge',
 ('inpatient.print_discharge_summary', 'GET'): 'patient:view',
 ('inpatient.beds', 'POST'): 'inpatient:admit',
 ('admin.staff', 'POST'): 'admin:manage_users',
 ('admin.update_staff', 'POST'): 'admin:manage_users',
 ('admin.force_staff_password_change', 'POST'): 'admin:manage_users',
 ('admin.update_security_settings', 'POST'): 'admin:security_config',
 ('admin.update_role_permissions', 'POST'): 'admin:security_config',
 ('admin.reset_user_2fa', 'POST'): 'admin:manage_users',
 ('admin.unlock_user', 'POST'): 'admin:manage_users',
 ('admin.force_user_password_change', 'POST'): 'admin:manage_users',
 ('admin.audit', 'GET'): 'admin:view_audit',
 ('view_document', 'GET'): 'patient:view',
 ('pharmacy.dashboard', 'GET'): 'patient:view',
 ('pharmacy.queue', 'GET'): 'patient:view',
 ('pharmacy.dispense', 'GET'): 'patient:view',
 ('pharmacy.dispense_label', 'GET'): 'patient:view',
 ('pharmacy.inventory', 'GET'): 'pharmacy:manage_stock',
 ('pharmacy.alerts', 'GET'): 'pharmacy:manage_stock',
 ('pharmacy.history', 'GET'): 'patient:view',
 ('pharmacy.batches', 'GET'): 'pharmacy:manage_stock',
 ('pharmacy.print_prescription', 'GET'): 'patient:view',
 ('pharmacy.purchase_orders', 'GET'): 'pharmacy:manage_stock',
 ('pharmacy.controlled_drugs', 'GET'): 'pharmacy:manage_stock',
 ('pharmacy.quarantine', 'GET'): 'pharmacy:manage_stock',
 ('triage.dashboard', 'GET'): 'patient:view',
 ('triage.live_queue', 'GET'): 'patient:view',
 ('triage.history', 'GET'): 'patient:view',
 ('doctor.dashboard', 'GET'): 'patient:view',
 ('doctor.waiting_queue', 'GET'): 'patient:view',
 ('doctor.appointments', 'GET'): 'patient:view',
 ('doctor.lab_results', 'GET'): 'patient:view',
 ('doctor.prescriptions', 'GET'): 'patient:view',
 ('doctor.analytics', 'GET'): 'patient:view',
 ('doctor.history', 'GET'): 'patient:view',
 ('doctor.schedule', 'GET'): 'patient:view',
 ('reception.dashboard', 'GET'): 'patient:view',
 ('reception.register', 'GET'): 'patient:view',
 ('reception.live_queue', 'GET'): 'patient:view',
 ('reception.appointments', 'GET'): 'patient:view',
 ('billing.dashboard', 'GET'): 'patient:view',
 ('billing.receipt', 'GET'): 'patient:view',
 ('billing.invoices', 'GET'): 'patient:view',
 ('billing.shift_report', 'GET'): 'patient:view',
 ('billing.insurance_registry', 'GET'): 'patient:view',
 ('billing.transactions', 'GET'): 'patient:view',
 ('billing.insurance_claims', 'GET'): 'patient:view',
 ('billing.refunds_waivers', 'GET'): 'patient:view',
 ('billing.debtors', 'GET'): 'patient:view',
 ('billing.financial_reports', 'GET'): 'patient:view',
 ('inpatient.dashboard', 'GET'): 'patient:view',
 ('inpatient.admissions', 'GET'): 'patient:view',
 ('inpatient.admit', 'GET'): 'patient:view',
 ('inpatient.beds', 'GET'): 'patient:view',
 ('patient_photo', 'GET'): 'patient:view',
 ('doctor.direct_consult', 'POST'): 'clinical:consult',
 ('billing.stage_invoice', 'POST'): 'billing:create_invoice'}

def enforce_request_security():
    from datetime import datetime, timedelta
    from auth.decorators import stage_auth, pending_auth_valid
    endpoint = request.endpoint
    if not endpoint or endpoint in ('static', 'paystack_webhook'):
        return None
    public = {'auth.login', 'auth.login_portal', 'auth.logout', 'auth.demo_login'}
    if endpoint in public or endpoint.endswith('.login') or endpoint.endswith('.logout'):
        return None
    pending = next(((key, dest) for key, dest in (
        ('pending_force_pw_user_id', 'auth.force_change_password'),
        ('pending_2fa_user_id', 'auth.verify_2fa'),
        ('pending_2fa_enrollment_user_id', 'auth.setup_2fa')) if session.get(key)), None)
    if pending:
        user = db.session.get(User, session[pending[0]])
        if not pending_auth_valid(user):
            logout_user()
            return redirect(url_for('auth.login'))
        allowed = endpoint == pending[1] or (pending[1] == 'auth.setup_2fa' and endpoint == 'auth.onboard_2fa')
        if not allowed:
            return redirect(url_for(pending[1]))
        if (request.view_args or {}).get('user_id') not in (None, user.id):
            abort(403)
        return None
    token = (request.view_args or {}).get('token') or request.args.get('token')
    if endpoint in ('auth.setup_2fa', 'auth.onboard_2fa') and token:
        return None  # The handler validates the signed, expiring, version-bound token.
    operational = endpoint in ('index', 'view_document', 'patient_photo') or endpoint.startswith(
        ('reception.', 'triage.', 'doctor.', 'pharmacy.', 'billing.', 'inpatient.', 'admin.', 'auth.'))
    if not operational:
        return None
    if endpoint == 'index' and not session.get('user_id'):
        return None
    if not is_authenticated():
        return redirect(url_for('auth.login'))
    user = get_current_user()
    if not user or user.status != 'active' or user.is_locked():
        logout_user()
        return redirect(url_for('auth.login'))
    password_state = user.password_changed_at.isoformat() if user.password_changed_at else None
    if session.get('auth_version') != user.auth_version or session.get('auth_password_changed_at') != password_state:
        logout_user()
        return redirect(url_for('auth.login'))
    settings = SecuritySetting.get_settings()
    if settings.enforce_single_session and session.get('active_session_token') != user.active_session_token:
        logout_user()
        return redirect(url_for('auth.login'))
    if settings.password_expiry_days and user.password_changed_at and user.password_changed_at < datetime.utcnow() - timedelta(days=settings.password_expiry_days):
        user.force_password_change = True
        db.session.commit()
    if user.force_password_change and endpoint not in ('auth.force_change_password', 'auth.change_password'):
        return redirect(url_for('auth.force_change_password'))
    if user.requires_2fa(settings) and not user.is_2fa_enabled and endpoint not in ('auth.setup_2fa', 'auth.setup_2fa_user'):
        stage_auth(user, 'pending_2fa_enrollment_user_id')
        return redirect(url_for('auth.setup_2fa'))
    if endpoint == 'auth.setup_2fa_user' or (endpoint == 'auth.setup_2fa' and (request.view_args or {}).get('user_id')):
        target_id = (request.view_args or {}).get('user_id')
        if target_id != user.id and (user.role != 'admin' or not user.has_permission('admin:manage_users')):
            abort(403)
    method = 'GET' if request.method == 'HEAD' else request.method
    required = ENDPOINT_PERMISSIONS.get((endpoint, method))
    allowed = any(user.has_permission(code) for code in required) if isinstance(required, tuple) else not required or user.has_permission(required)
    if not allowed:
        AuditLog.log_event('permission_denied', 'endpoint', endpoint, actor=user, severity='warning')
        db.session.commit()
        return 'Forbidden: action requires ' + str(required), 403
    return None
