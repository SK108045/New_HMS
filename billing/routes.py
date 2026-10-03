import json
import math
from datetime import datetime, date, timedelta
from flask import abort, render_template, request, redirect, url_for, flash, jsonify
from models.base import db
from models.patient import Patient
from models.queue import QueueEntry
from models.emr import BillingItem, ConsultationNote, LabOrder, Prescription
from models.billing import Invoice, Payment, ShiftRegister, InsuranceScheme, InsuranceClaim, CreditNote, FeeWaiver
from models.audit import AuditLog
from auth.decorators import get_current_user
from . import billing_bp

# Operator profile & Cashier configuration
CASHIERS_LIST = [
    'Cashier Joyce Wambui (Lead Cashier)',
    'Cashier Dennis Mutua',
    'Accountant Faith Chebet'
]

STANDARD_TARIFFS = [
    {'code': 'CON-001', 'category': 'Consultation', 'name': 'General OPD Doctor Consultation', 'price': 1500.0},
    {'code': 'CON-002', 'category': 'Consultation', 'name': 'Specialist Consultant Review', 'price': 3000.0},
    {'code': 'LAB-FBC', 'category': 'Laboratory', 'name': 'Full Blood Count (FBC/CBC)', 'price': 1200.0},
    {'code': 'LAB-MAL', 'category': 'Laboratory', 'name': 'Malaria Blood Slide / Rapid Test', 'price': 650.0},
    {'code': 'LAB-URN', 'category': 'Laboratory', 'name': 'Urinalysis Multi-Stix Complete', 'price': 500.0},
    {'code': 'LAB-BS', 'category': 'Laboratory', 'name': 'Random Blood Glucose (RBG)', 'price': 400.0},
    {'code': 'LAB-LFT', 'category': 'Laboratory', 'name': 'Liver Function Tests (LFTs)', 'price': 2800.0},
    {'code': 'RAD-XR1', 'category': 'Radiology', 'name': 'Chest X-Ray PA View', 'price': 2200.0},
    {'code': 'RAD-MRI', 'category': 'Radiology', 'name': 'Axial Brain MRI Scan with Contrast', 'price': 16500.0},
    {'code': 'NUR-001', 'category': 'Nursing/Procedure', 'name': 'Wound Dressing & Aseptic Bandaging', 'price': 800.0},
    {'code': 'NUR-002', 'category': 'Nursing/Procedure', 'name': 'Intravenous (IV) Cannulation & Infusion', 'price': 1000.0},
    {'code': 'NUR-003', 'category': 'Nursing/Procedure', 'name': 'Nebulization Therapy (1 Session)', 'price': 900.0},
]


def get_or_create_open_shift(create=False):
    """
    Retrieves the currently open cashier shift register or creates a new active shift.
    """
    shift = ShiftRegister.query.filter_by(status='open').order_by(ShiftRegister.id.desc()).first()
    if not shift and not create:
        return ShiftRegister(shift_code='No open shift', cashier_name='No active cashier', counter_number='POS-01', opening_float=0.0, cash_collected=0.0, mpesa_collected=0.0, insurance_billed=0.0, card_collected=0.0, total_revenue=0.0, status='closed')
    if not shift:
        shift = ShiftRegister(
            shift_code=ShiftRegister.generate_shift_code(db.session),
            cashier_name=get_current_user().full_name,
            counter_number='POS-01',
            opening_float=0.0,
            status='open',
            opened_at=datetime.utcnow()
        )
        db.session.add(shift)
        db.session.flush()
    return shift


# =================== 1. FINANCIAL DASHBOARD & COMMAND ===================
@billing_bp.route('/', methods=['GET'])
@billing_bp.route('/dashboard', methods=['GET'])
def dashboard():
    """
    Financial Command Center with 4 KPI cards, 4 rich Chart.js financial charts,
    and recent settled payment vouchers.
    """
    today_start = datetime.combine(date.today(), datetime.min.time())
    
    # 1. KPIs
    today_payments = Payment.query.filter(Payment.created_at >= today_start).all()
    today_revenue = sum(p.total_amount_paid for p in today_payments)
    today_cash = sum(p.cash_amount for p in today_payments)
    today_mpesa = sum(p.mpesa_amount for p in today_payments)
    today_insurance = sum(p.insurance_amount for p in today_payments)

    unsettled_invoices = Invoice.query.filter(Invoice.status.in_(['unpaid', 'partially_paid'])).all()
    unsettled_balance = sum(inv.balance_due for inv in unsettled_invoices)

    active_shift = get_or_create_open_shift()

    # 2. Chart 1: 7-Day Revenue Collections Trend (Cash, M-Pesa, Insurance)
    seven_day_labels = []
    daily_cash_data = []
    daily_mpesa_data = []
    daily_insurance_data = []

    for i in range(6, -1, -1):
        target_date = date.today() - timedelta(days=i)
        day_start = datetime.combine(target_date, datetime.min.time())
        day_end = datetime.combine(target_date, datetime.max.time())
        seven_day_labels.append(target_date.strftime('%a, %d %b'))

        day_p = Payment.query.filter(Payment.created_at >= day_start, Payment.created_at <= day_end).all()
        c_amt = sum(p.cash_amount for p in day_p)
        m_amt = sum(p.mpesa_amount for p in day_p)
        i_amt = sum(p.insurance_amount for p in day_p)

        daily_cash_data.append(c_amt)
        daily_mpesa_data.append(m_amt)
        daily_insurance_data.append(i_amt)

    # 3. Chart 2: Departmental Revenue Share Donut (Pharmacy, Lab, Consultation, Procedures)
    billing_items = BillingItem.query.all()
    dept_revenue = {'Consultation': 0.0, 'Laboratory': 0.0, 'Pharmacy': 0.0, 'Radiology': 0.0, 'Nursing/Procedure': 0.0}
    for item in billing_items:
        st = item.service_type.capitalize()
        if 'Consult' in st:
            dept_revenue['Consultation'] += item.total_amount
        elif 'Lab' in st:
            dept_revenue['Laboratory'] += item.total_amount
        elif 'Pharm' in st:
            dept_revenue['Pharmacy'] += item.total_amount
        elif 'Radio' in st or 'X-ray' in st or 'Mri' in st:
            dept_revenue['Radiology'] += item.total_amount
        else:
            dept_revenue['Nursing/Procedure'] += item.total_amount

    dept_labels = list(dept_revenue.keys())
    dept_values = list(dept_revenue.values())

    # 4. Chart 3: Payment Tender Distribution
    tender_labels = ['M-Pesa Mobile', 'Physical Cash', 'Insurance Claims', 'Bank Card']
    total_m = sum(p.mpesa_amount for p in Payment.query.all())
    total_c = sum(p.cash_amount for p in Payment.query.all())
    total_i = sum(p.insurance_amount for p in Payment.query.all())
    total_cd = sum(p.card_amount for p in Payment.query.all())
    tender_values = [total_m, total_c, total_i, total_cd]

    # 5. Recent Settled Receipts
    recent_payments = Payment.query.order_by(Payment.created_at.desc()).limit(8).all()

    return render_template(
        'billing/dashboard.html',
        today_revenue=today_revenue,
        today_cash=today_cash,
        today_mpesa=today_mpesa,
        today_insurance=today_insurance,
        unsettled_balance=unsettled_balance,
        unsettled_invoices_count=len(unsettled_invoices),
        active_shift=active_shift,
        recent_payments=recent_payments,
        seven_day_labels=seven_day_labels,
        daily_cash_data=daily_cash_data,
        daily_mpesa_data=daily_mpesa_data,
        daily_insurance_data=daily_insurance_data,
        dept_labels=dept_labels,
        dept_values=dept_values,
        tender_labels=tender_labels,
        tender_values=tender_values
    )


# =================== 2. DUAL-PANEL POS CASHIER TERMINAL ===================
@billing_bp.route('/pos', methods=['GET'])
@billing_bp.route('/pos/<int:patient_id>', methods=['GET'])
def pos(patient_id=None):
    """
    Modern POS Cashier Register Terminal with Patient Folio Selection,
    Real-time aggregated charges, and Split Payment Multi-Tender Engine.
    Counts only un-invoiced staged items plus unpaid/partially_paid invoice balances (no double counting).
    Correctly loads selected partially-paid invoices.
    """
    search_q = request.args.get('q', '').strip()
    selected_patient = None
    selected_invoice = None
    staged_items = []

    # 1. Fetch live queue entries that have staged or unpaid charges
    today_start = datetime.combine(date.today(), datetime.min.time())
    
    # Active patient folios awaiting checkout
    query = Patient.query
    if search_q:
        query = query.filter(
            db.or_(
                Patient.first_name.ilike(f'%{search_q}%'),
                Patient.last_name.ilike(f'%{search_q}%'),
                Patient.hospital_id.ilike(f'%{search_q}%'),
                Patient.phone.ilike(f'%{search_q}%')
            )
        )
    
    patients_pool = query.order_by(Patient.id.desc()).limit(20).all()

    # Collect patient summary: count only un-invoiced staged items plus all unpaid/partially_paid balances
    patient_folios = []
    for p in patients_pool:
        # Count only un-invoiced staged items to prevent double counting
        un_invoiced_items = BillingItem.query.filter(
            BillingItem.patient_id == p.id,
            BillingItem.status == 'staged',
            BillingItem.invoice_id.is_(None)
        ).all()

        # All unpaid and partially_paid invoice balances
        open_invoices = Invoice.query.filter(
            Invoice.patient_id == p.id,
            Invoice.status.in_(['unpaid', 'partially_paid'])
        ).all()

        unpaid_total = round(
            sum(float(i.total_amount) for i in un_invoiced_items) +
            sum(float(inv.balance_due) for inv in open_invoices),
            2
        )
        unpaid_items_count = len(un_invoiced_items) + sum(len(inv.billing_items) for inv in open_invoices)

        patient_folios.append({
            'patient': p,
            'unpaid_total': unpaid_total,
            'unpaid_items_count': unpaid_items_count
        })

    # 2. If a patient is selected, load their staged charges and invoice
    if patient_id:
        selected_patient = Patient.query.get_or_404(patient_id)
        
        # Check if there is an existing unpaid or partially-paid invoice
        selected_invoice = Invoice.query.filter(
            Invoice.patient_id == selected_patient.id,
            Invoice.status.in_(['unpaid', 'partially_paid'])
        ).order_by(Invoice.id.desc()).first()

        # Get un-invoiced staged billing items for this patient
        un_invoiced_staged = BillingItem.query.filter(
            BillingItem.patient_id == selected_patient.id,
            BillingItem.status == 'staged',
            BillingItem.invoice_id.is_(None)
        ).order_by(BillingItem.id.asc()).all()

        staged_items = selected_invoice.billing_items if selected_invoice else un_invoiced_staged
    elif patient_folios:
        # Default to first patient with unpaid charges if any
        for folio in patient_folios:
            if folio['unpaid_total'] > 0:
                return redirect(url_for('billing.pos', patient_id=folio['patient'].id))
        if patient_folios:
            return redirect(url_for('billing.pos', patient_id=patient_folios[0]['patient'].id))

    active_shift = get_or_create_open_shift()

    return render_template(
        'billing/pos.html',
        patient_folios=patient_folios,
        selected_patient=selected_patient,
        selected_invoice=selected_invoice,
        staged_items=staged_items,
        has_uninvoiced=bool(un_invoiced_staged) if patient_id else False,
        tariffs=STANDARD_TARIFFS,
        active_shift=active_shift,
        cashiers_list=CASHIERS_LIST,
        search_q=search_q
    )


# =================== 3. ADD TARIFF LINE ITEM TO FOLIO ===================
@billing_bp.route('/pos/<int:patient_id>/add-item', methods=['POST'])
def add_tariff_item(patient_id):
    """
    Adds a procedural or departmental charge line item directly to the active patient folio.
    """
    if request.method == 'POST':
        from services.transactions import begin_write
        begin_write()
    patient = Patient.query.get_or_404(patient_id)
    service_type = request.form.get('service_type', 'procedure')
    item_description = request.form.get('item_description', '').strip()
    try:
        quantity = int(request.form.get('quantity', 1))
        unit_price = float(request.form.get('unit_price', 0.0))
    except (ValueError, TypeError):
        flash('Invalid quantity or price.', 'danger')
        return redirect(url_for('billing.pos', patient_id=patient.id))

    if not math.isfinite(unit_price) or unit_price < 0 or quantity <= 0:
        flash('Quantity and price must be positive finite numbers.', 'danger')
        return redirect(url_for('billing.pos', patient_id=patient.id))

    if item_description and unit_price > 0:
        total_amount = round(quantity * unit_price, 2)
        
        # Get or create active unpaid or partially-paid invoice
        inv = Invoice.query.filter(
            Invoice.patient_id == patient.id,
            Invoice.status.in_(['unpaid', 'partially_paid'])
        ).order_by(Invoice.id.desc()).first()

        current_user = get_current_user()
        cashier_name = current_user.full_name if current_user else 'Cashier Joyce Wambui'

        if not inv:
            inv = Invoice(
                invoice_number=Invoice.generate_invoice_number(db.session),
                patient_id=patient.id,
                subtotal=total_amount,
                discount_amount=0.0,
                tax_amount=0.0,
                total_due=total_amount,
                amount_paid=0.0,
                balance_due=total_amount,
                status='unpaid',
                cashier_name=cashier_name
            )
            db.session.add(inv)
            db.session.flush()
        else:
            inv.subtotal = round(inv.subtotal + total_amount, 2)
            inv.total_due = max(0.0, round(inv.subtotal - inv.discount_amount + inv.tax_amount, 2))
            inv.balance_due = max(0.0, round(inv.total_due - inv.amount_paid, 2))

        item = BillingItem(
            patient_id=patient.id,
            invoice_id=inv.id,
            service_type=service_type,
            item_description=item_description,
            quantity=quantity,
            unit_price=unit_price,
            total_amount=total_amount,
            status='staged'
        )
        db.session.add(item)
        db.session.flush()
        AuditLog.log_event('tariff_item_added', 'billing_item', item.id, actor=current_user)
        db.session.commit()
        flash(f"Added '{item_description}' (KES {total_amount:.2f}) to patient folio.", 'success')

    return redirect(url_for('billing.pos', patient_id=patient.id))


# =================== 4. PROCESS SPLIT PAYMENT SETTLEMENT ===================
@billing_bp.route('/pos/settle/<int:invoice_id>', methods=['POST'])
def process_settlement(invoice_id):
    """
    Executes split payment checkout (Cash, M-Pesa, Insurance Co-pay, Card).
    Validates invoice patient, finite amounts, unique reference checks, and uses authenticated cashier.
    Guards against repeat settlement and double payment.
    """
    if request.method == 'POST':
        from services.transactions import begin_write
        begin_write()
    invoice = Invoice.query.get_or_404(invoice_id)
    patient = invoice.patient

    # Validate invoice patient
    req_patient_id = request.form.get('patient_id', type=int)
    if req_patient_id and req_patient_id != invoice.patient_id:
        flash("Security alert: Patient folio mismatch for selected invoice.", "danger")
        return redirect(url_for('billing.pos', patient_id=patient.id))

    request_key = request.form.get('idempotency_key', '').strip()
    if not request_key or len(request_key) > 120:
        flash('Reload the checkout form before submitting payment.', 'danger')
        return redirect(url_for('billing.pos', patient_id=patient.id))
    previous = Payment.query.filter_by(idempotency_key='pos:' + request_key).first()
    if previous:
        if previous.invoice_id != invoice.id:
            return 'Payment request belongs to another invoice.', 409
        return redirect(url_for('billing.receipt', payment_id=previous.id))

    # Guard repeat settlement
    if invoice.status in {'paid', 'waived', 'cancelled'} or invoice.balance_due <= 0.001:
        flash('This invoice is already settled and cannot accept another payment.', 'warning')
        return redirect(url_for('billing.pos', patient_id=patient.id))

    # Read multi-tender input values
    try:
        cash_amount = float(request.form.get('cash_amount') or 0.0)
        cash_tendered = float(request.form.get('cash_tendered') or 0.0)
        change_returned = float(request.form.get('change_returned') or 0.0)
        mpesa_amount = float(request.form.get('mpesa_amount') or 0.0)
        insurance_amount = float(request.form.get('insurance_amount') or 0.0)
        card_amount = float(request.form.get('card_amount') or 0.0)
        discount_amount = float(request.form.get('discount_amount') or 0.0)
    except (ValueError, TypeError):
        flash('Payment amounts must be valid numbers.', 'danger')
        return redirect(url_for('billing.pos', patient_id=patient.id))

    payment_values = [cash_amount, cash_tendered, change_returned, mpesa_amount, insurance_amount, card_amount, discount_amount]
    if not all(math.isfinite(value) and value >= 0 for value in payment_values):
        flash('Payment amounts and discounts must be finite positive numbers.', 'danger')
        return redirect(url_for('billing.pos', patient_id=patient.id))

    # Decimal rounding / quantization to 2 decimal places
    cash_amount = round(cash_amount, 2)
    cash_tendered = round(cash_tendered, 2)
    change_returned = round(change_returned, 2)
    mpesa_amount = round(mpesa_amount, 2)
    insurance_amount = round(insurance_amount, 2)
    card_amount = round(card_amount, 2)
    discount_amount = round(discount_amount, 2)

    mpesa_reference = request.form.get('mpesa_reference', '').strip().upper()
    mpesa_phone = request.form.get('mpesa_phone', '').strip()
    insurance_company = request.form.get('insurance_company', '').strip()
    insurance_policy_number = request.form.get('insurance_policy_number', '').strip()
    insurance_claim_number = request.form.get('insurance_claim_number', '').strip()
    card_auth_code = request.form.get('card_auth_code', '').strip().upper()
    counseling_notes = request.form.get('notes', '').strip()

    # Authenticated cashier check
    current_user = get_current_user()
    cashier_name = current_user.full_name if current_user else (request.form.get('cashier_name') or 'Lead Cashier')

    # Validate duplicate references
    if mpesa_amount > 0:
        if not mpesa_reference:
            flash('M-Pesa transaction reference is required for mobile money settlements.', 'danger')
            return redirect(url_for('billing.pos', patient_id=patient.id))
        dup_mpesa = Payment.query.filter_by(mpesa_reference=mpesa_reference).first()
        if dup_mpesa:
            flash(f'Duplicate payment reference: M-Pesa transaction {mpesa_reference} has already been recorded.', 'danger')
            return redirect(url_for('billing.pos', patient_id=patient.id))

    if card_amount > 0 and card_auth_code:
        dup_card = Payment.query.filter_by(card_auth_code=card_auth_code).first()
        if dup_card:
            flash(f'Duplicate card authorization code: {card_auth_code} has already been recorded.', 'danger')
            return redirect(url_for('billing.pos', patient_id=patient.id))

    if cash_tendered and cash_tendered < round(cash_amount + change_returned, 2):
        flash('Cash tendered cannot be less than the cash payment plus change returned.', 'danger')
        return redirect(url_for('billing.pos', patient_id=patient.id))

    if discount_amount > invoice.subtotal:
        flash('Discount cannot exceed the invoice subtotal.', 'danger')
        return redirect(url_for('billing.pos', patient_id=patient.id))

    if discount_amount > 0:
        flash('Request a fee waiver or credit note for independent approval before checkout.', 'danger')
        return redirect(url_for('billing.pos', patient_id=patient.id))

    total_payment = round(cash_amount + mpesa_amount + insurance_amount + card_amount, 2)
    remaining_balance = max(0.0, round(invoice.total_due - invoice.amount_paid, 2))

    if total_payment <= 0:
        flash("Error: Payment amount must be greater than KES 0.00", 'danger')
        return redirect(url_for('billing.pos', patient_id=patient.id))

    if total_payment > remaining_balance:
        flash(f'Payment exceeds the outstanding balance of KES {remaining_balance:,.2f}.', 'danger')
        return redirect(url_for('billing.pos', patient_id=patient.id))

    # Determine summary description of payment methods
    methods = []
    if cash_amount > 0:
        methods.append(f"Cash (KES {cash_amount:,.2f})")
    if mpesa_amount > 0:
        methods.append(f"M-Pesa [{mpesa_reference or 'Ref'}] (KES {mpesa_amount:,.2f})")
    if insurance_amount > 0:
        methods.append(f"Insurance Claim [{insurance_company or 'Direct'}] (KES {insurance_amount:,.2f})")
    if card_amount > 0:
        methods.append(f"Card [{card_auth_code or 'POS'}] (KES {card_amount:,.2f})")

    payment_summary = " + ".join(methods) if methods else "Direct Settlement"

    active_shift = get_or_create_open_shift(create=True)

    # Create Payment Record
    payment = Payment(
        receipt_number=Payment.generate_receipt_number(db.session),
        idempotency_key="pos:" + request_key,
        invoice_id=invoice.id,
        patient_id=patient.id,
        total_amount_paid=total_payment,
        payment_method_summary=payment_summary,
        cash_amount=cash_amount,
        cash_tendered=cash_tendered,
        change_returned=change_returned,
        mpesa_amount=mpesa_amount,
        mpesa_reference=mpesa_reference or None,
        mpesa_phone=mpesa_phone or None,
        insurance_amount=insurance_amount,
        insurance_company=insurance_company or None,
        insurance_policy_number=insurance_policy_number or None,
        insurance_claim_number=insurance_claim_number or None,
        card_amount=card_amount,
        card_auth_code=card_auth_code or None,
        cashier_name=cashier_name,
        shift_code=active_shift.shift_code,
        notes=counseling_notes or None,
        created_at=datetime.utcnow()
    )
    db.session.add(payment)

    # Update Invoice Status
    invoice.amount_paid = round(invoice.amount_paid + total_payment, 2)
    invoice.balance_due = max(0.0, round(invoice.total_due - invoice.amount_paid, 2))
    if invoice.balance_due <= 0.001:
        invoice.status = 'paid'
        invoice.paid_at = datetime.utcnow()
        for item in invoice.billing_items:
            item.status = 'paid'
    else:
        invoice.status = 'partially_paid'

    # Update Active Shift Totals
    active_shift.cash_collected = round(active_shift.cash_collected + cash_amount, 2)
    active_shift.mpesa_collected = round(active_shift.mpesa_collected + mpesa_amount, 2)
    active_shift.insurance_billed = round(active_shift.insurance_billed + insurance_amount, 2)
    active_shift.card_collected = round(active_shift.card_collected + card_amount, 2)
    active_shift.total_revenue = round(active_shift.total_revenue + total_payment, 2)

    # Complete Patient Queue Entry if associated
    if invoice.queue_entry:
        invoice.queue_entry.status = 'completed'
        invoice.queue_entry.completed_at = datetime.utcnow()

    db.session.flush()
    AuditLog.log_event(
        'payment_settled',
        'payment',
        payment.id,
        f"Settlement of KES {total_payment:,.2f} recorded on invoice {invoice.invoice_number} by {cashier_name}."
    )

    db.session.commit()
    flash(f"Settlement complete! Receipt {payment.receipt_number} issued for {patient.full_name}.", 'success')
    return redirect(url_for('billing.receipt', payment_id=payment.id))


# =================== 5. INSTANT DUAL-FORMAT RECEIPT GENERATOR ===================
@billing_bp.route('/receipt/<int:payment_id>', methods=['GET'])
def receipt(payment_id):
    """
    Printable Dual-Format Receipt:
    - Format 1: 80mm Thermal POS Slip (Default)
    - Format 2: Standard A4 Itemized Official Tax Invoice
    """
    payment = Payment.query.get_or_404(payment_id)
    format_type = request.args.get('format', 'thermal') # 'thermal' or 'a4'

    return render_template(
        'billing/receipt.html',
        payment=payment,
        invoice=payment.invoice,
        patient=payment.patient,
        facility_name='APEX ADVANCED MEDICAL CENTER & HOSPITAL',
        facility_code='HSP-NBI-001',
        format_type=format_type
    )


# =================== 6. PENDING INVOICES QUEUE ===================
@billing_bp.route('/invoices', methods=['GET'])
def invoices():
    """
    Comprehensive list of hospital invoices with filter by status (unpaid, partially_paid, paid).
    """
    status_filter = request.args.get('status', 'all')
    search_q = request.args.get('q', '').strip()

    query = Invoice.query

    if status_filter != 'all':
        query = query.filter(Invoice.status == status_filter)

    if search_q:
        query = query.join(Patient).filter(
            db.or_(
                Invoice.invoice_number.ilike(f'%{search_q}%'),
                Patient.first_name.ilike(f'%{search_q}%'),
                Patient.last_name.ilike(f'%{search_q}%'),
                Patient.hospital_id.ilike(f'%{search_q}%')
            )
        )

    all_invoices = query.order_by(Invoice.created_at.desc()).all()

    return render_template(
        'billing/invoices.html',
        invoices=all_invoices,
        status_filter=status_filter,
        search_q=search_q
    )


# =================== 7. SHIFT RECONCILIATION & X/Z REPORTS ===================
@billing_bp.route('/shift-report', methods=['GET'])
def shift_report():
    """
    Cashier Shift Reconciliation Station:
    - Live X-Report (Mid-shift audit reading without closing register)
    - Z-Report Register Closeout (Physical cash entry, discrepancy calculation, final closeout)
    """
    active_shift = get_or_create_open_shift()
    all_shifts = ShiftRegister.query.order_by(ShiftRegister.id.desc()).limit(15).all()
    
    # Transactions in current active shift
    shift_payments = Payment.query.filter_by(shift_code=active_shift.shift_code).order_by(Payment.created_at.desc()).all()

    return render_template(
        'billing/shift_report.html',
        shift=active_shift,
        all_shifts=all_shifts,
        payments=shift_payments
    )


@billing_bp.route('/shift/close', methods=['POST'])
def close_shift():
    """
    Executes End-of-Day Register Closeout (Z-Report), logs physical cash count,
    calculates overage/shortage discrepancy, closes shift, and opens next shift register.
    """
    from services.transactions import begin_write
    begin_write()
    active_shift = get_or_create_open_shift()
    try:
        counted_cash = float(request.form.get('counted_cash') or 0.0)
        if not math.isfinite(counted_cash) or counted_cash < 0:
            raise ValueError()
    except (ValueError, TypeError):
        flash('Counted cash must be a finite non-negative amount.', 'danger')
        return redirect(url_for('billing.shift_report'))
    notes = request.form.get('notes', '').strip()

    expected_cash = active_shift.opening_float + active_shift.cash_collected
    discrepancy = counted_cash - expected_cash

    active_shift.counted_cash = counted_cash
    active_shift.discrepancy = discrepancy
    active_shift.notes = notes
    if not active_shift.id:
        flash('There is no open shift to close.', 'warning')
        return redirect(url_for('billing.shift_report'))
    active_shift.status = 'closed'
    active_shift.closed_at = datetime.utcnow()
    AuditLog.log_event('shift_closed', 'shift_register', active_shift.id, actor=get_current_user())
    db.session.commit()

    flash(f"Shift {active_shift.shift_code} closed successfully. Z-Report generated.", 'success')
    return redirect(url_for('billing.shift_report'))


# =================== 8. INSURANCE CLAIMS REGISTRY ===================
@billing_bp.route('/insurance', methods=['GET'])
def insurance_registry():
    """
    Insurance and Corporate pre-authorized claims tracking ledger.
    """
    search_q = request.args.get('q', '').strip()
    
    query = Payment.query.filter(Payment.insurance_amount > 0)
    if search_q:
        query = query.join(Patient).filter(
            db.or_(
                Payment.insurance_company.ilike(f'%{search_q}%'),
                Payment.insurance_policy_number.ilike(f'%{search_q}%'),
                Payment.insurance_claim_number.ilike(f'%{search_q}%'),
                Patient.first_name.ilike(f'%{search_q}%'),
                Patient.last_name.ilike(f'%{search_q}%')
            )
        )

    claims = query.order_by(Payment.created_at.desc()).all()
    total_claims_amount = sum(c.insurance_amount for c in claims)

    return render_template(
        'billing/insurance.html',
        claims=claims,
        total_claims_amount=total_claims_amount,
        search_q=search_q
    )


# =================== 9. TRANSACTION AUDIT LEDGER ===================
@billing_bp.route('/transactions', methods=['GET'])
def transactions():
    """
    Master payment transaction audit trail with date navigation and search.
    """
    date_str = request.args.get('date', date.today().strftime('%Y-%m-%d'))
    method_filter = request.args.get('method', 'all')
    search_q = request.args.get('q', '').strip()

    try:
        filter_date = datetime.strptime(date_str, '%Y-%m-%d').date()
    except ValueError:
        filter_date = date.today()

    day_start = datetime.combine(filter_date, datetime.min.time())
    day_end = datetime.combine(filter_date, datetime.max.time())

    query = Payment.query.filter(Payment.created_at >= day_start, Payment.created_at <= day_end)

    if method_filter == 'cash':
        query = query.filter(Payment.cash_amount > 0)
    elif method_filter == 'mpesa':
        query = query.filter(Payment.mpesa_amount > 0)
    elif method_filter == 'insurance':
        query = query.filter(Payment.insurance_amount > 0)
    elif method_filter == 'card':
        query = query.filter(Payment.card_amount > 0)

    if search_q:
        query = query.join(Patient).filter(
            db.or_(
                Payment.receipt_number.ilike(f'%{search_q}%'),
                Payment.mpesa_reference.ilike(f'%{search_q}%'),
                Patient.first_name.ilike(f'%{search_q}%'),
                Patient.last_name.ilike(f'%{search_q}%')
            )
        )

    payments_list = query.order_by(Payment.created_at.desc()).all()

    return render_template(
        'billing/transactions.html',
        payments=payments_list,
        filter_date=filter_date,
        method_filter=method_filter,
        search_q=search_q,
        today=date.today()
    )


# =================== 10. HOSPITAL TARIFF SCHEDULE ===================
@billing_bp.route('/tariffs', methods=['GET'])
def tariffs():
    """
    Official hospital fee schedule and pricing directory.
    """
    search_q = request.args.get('q', '').strip()
    category_filter = request.args.get('category', 'all')

    tariffs_list = STANDARD_TARIFFS
    if category_filter != 'all':
        tariffs_list = [t for t in tariffs_list if t['category'] == category_filter]
    if search_q:
        tariffs_list = [t for t in tariffs_list if search_q.lower() in t['name'].lower() or search_q.lower() in t['code'].lower()]

    categories = list(set(t['category'] for t in STANDARD_TARIFFS))

    return render_template(
        'billing/tariffs.html',
        tariffs=tariffs_list,
        categories=categories,
        category_filter=category_filter,
        search_q=search_q
    )


# =================== 11. INSURANCE & SHA CLAIMS MANAGEMENT ===================
@billing_bp.route('/claims', methods=['GET'])
def insurance_claims():
    """
    Enterprise Insurance & Social Health Authority (SHA) Claims Desk.
    Tracks Pre-Authorisations, Submitted Claims, Reimbursements, and Rejections.
    """
    status_filter = request.args.get('status', 'all')
    scheme_filter = request.args.get('scheme', 'all')
    search_q = request.args.get('q', '').strip()

    query = InsuranceClaim.query

    if status_filter != 'all':
        query = query.filter(InsuranceClaim.status == status_filter)
    if scheme_filter != 'all':
        query = query.filter(InsuranceClaim.scheme_name == scheme_filter)

    if search_q:
        query = query.join(Patient).filter(
            db.or_(
                InsuranceClaim.claim_number.ilike(f'%{search_q}%'),
                InsuranceClaim.preauth_code.ilike(f'%{search_q}%'),
                InsuranceClaim.member_number.ilike(f'%{search_q}%'),
                Patient.first_name.ilike(f'%{search_q}%'),
                Patient.last_name.ilike(f'%{search_q}%')
            )
        )

    claims_list = query.order_by(InsuranceClaim.created_at.desc()).all()
    schemes = InsuranceScheme.query.filter_by(status='active').all()
    unsettled_invoices = Invoice.query.filter(Invoice.status.in_(['unpaid', 'partially_paid'])).all()

    # KPI Statistics
    total_claims_count = InsuranceClaim.query.count()
    pending_preauth_count = InsuranceClaim.query.filter_by(status='preauth_pending').count()
    total_claimed_value = sum(c.claimed_amount for c in InsuranceClaim.query.all())
    reimbursed_value = sum(c.approved_amount for c in InsuranceClaim.query.filter_by(status='reimbursed').all())
    rejected_count = InsuranceClaim.query.filter_by(status='rejected').count()

    return render_template(
        'billing/insurance_claims.html',
        claims=claims_list,
        schemes=schemes,
        unsettled_invoices=unsettled_invoices,
        status_filter=status_filter,
        scheme_filter=scheme_filter,
        search_q=search_q,
        total_claims_count=total_claims_count,
        pending_preauth_count=pending_preauth_count,
        total_claimed_value=total_claimed_value,
        reimbursed_value=reimbursed_value,
        rejected_count=rejected_count
    )


ALLOWED_CLAIM_TRANSITIONS = {
    'preauth_pending': {'preauth_approved', 'rejected'},
    'preauth_approved': {'submitted', 'rejected'},
    'submitted': {'reimbursed', 'rejected', 'disputed'},
    'disputed': {'submitted', 'rejected', 'reimbursed'},
    'reimbursed': set(),
    'rejected': set()
}

@billing_bp.route('/claims/create-preauth', methods=['POST'])
def create_preauth_claim():
    """
    Submits a Pre-Authorisation request for an active patient invoice.
    Starts as preauth_pending unless an explicit recorded provider approval code is provided.
    """
    invoice_id = request.form.get('invoice_id', type=int)
    if not invoice_id:
        abort(400)
    scheme_id = request.form.get('scheme_id', type=int)
    if not scheme_id:
        abort(400)
    member_number = request.form.get('member_number', '').strip()
    policy_number = request.form.get('policy_number', '').strip()
    preauth_code = request.form.get('preauth_code', '').strip().upper()
    try:
        claimed_amount = float(request.form.get('claimed_amount') or 0.0)
    except (ValueError, TypeError):
        flash("Claimed amount must be a valid number.", "danger")
        return redirect(url_for('billing.insurance_claims'))

    if not math.isfinite(claimed_amount) or claimed_amount <= 0:
        flash("Claimed amount must be a positive finite number.", "danger")
        return redirect(url_for('billing.insurance_claims'))

    notes = request.form.get('notes', '').strip()

    invoice = Invoice.query.get_or_404(invoice_id)
    scheme = InsuranceScheme.query.get_or_404(scheme_id)

    # Calculate co-pay
    copay = scheme.copay_fixed_amount
    if scheme.copay_percentage > 0:
        copay += (claimed_amount * (scheme.copay_percentage / 100.0))
    copay = round(copay, 2)

    current_user = get_current_user()
    created_by = current_user.full_name if current_user else 'Cashier Joyce Wambui'

    # Insurance preauth starts pending and only becomes approved with explicit recorded provider approval/code
    if preauth_code:
        initial_status = 'preauth_approved'
        approved_amt = max(0.0, round(claimed_amount - copay, 2))
    else:
        initial_status = 'preauth_pending'
        approved_amt = 0.0
        preauth_code = None

    claim = InsuranceClaim(
        claim_number=InsuranceClaim.generate_claim_number(db.session),
        invoice_id=invoice.id,
        patient_id=invoice.patient_id,
        scheme_id=scheme.id,
        scheme_name=scheme.name,
        member_number=member_number,
        policy_number=policy_number,
        preauth_code=preauth_code,
        claimed_amount=round(claimed_amount, 2),
        approved_amount=approved_amt,
        copay_amount=copay,
        status=initial_status,
        notes=notes,
        created_by=created_by
    )
    db.session.add(claim)
    
    AuditLog.log_event(
        'insurance_preauth_created',
        'insurance_claim',
        invoice.id,
        f"Recorded Pre-Authorisation request ({claim.claim_number}) for {scheme.name} (Claimed: KES {claimed_amount:.2f}, Status: {initial_status}).",
        severity='info'
    )
    db.session.commit()
    if initial_status == 'preauth_approved':
        flash(f"Pre-Authorisation recorded as approved for {scheme.name} (Code: {preauth_code}). Co-pay due: KES {copay:.2f}", "success")
    else:
        flash(f"Pre-Authorisation request {claim.claim_number} logged with status 'Pending Insurer Approval'. Co-pay: KES {copay:.2f}", "info")
    return redirect(url_for('billing.insurance_claims'))


@billing_bp.route('/claims/<int:claim_id>/update-status', methods=['POST'])
def update_claim_status(claim_id):
    """
    Transitions claim through submission, reimbursement, or rejection.
    Validates status transitions, numbers, and requires explicit recorded provider approval code.
    """
    if request.method == 'POST':
        from services.transactions import begin_write
        begin_write()
    claim = InsuranceClaim.query.get_or_404(claim_id)
    new_status = request.form.get('status')
    rejection_reason = request.form.get('rejection_reason', '').strip()

    allowed = ALLOWED_CLAIM_TRANSITIONS.get(claim.status, set())
    if new_status not in allowed:
        flash(f"Invalid status transition from '{claim.status}' to '{new_status}'.", "danger")
        return redirect(url_for('billing.insurance_claims'))

    if new_status == 'preauth_approved':
        # Requires explicit recorded provider approval code
        recorded_code = request.form.get('preauth_code', '').strip().upper() or claim.preauth_code
        if not recorded_code:
            flash("Provider Pre-Authorisation Approval Code is required to record preauth approval.", "danger")
            return redirect(url_for('billing.insurance_claims'))
        claim.preauth_code = recorded_code
        claim.approved_amount = max(0.0, round(claim.claimed_amount - claim.copay_amount, 2))

    elif new_status == 'submitted':
        claim.submitted_at = datetime.utcnow()

    elif new_status == 'reimbursed':
        try:
            approved_amount = float(request.form.get('approved_amount') or claim.approved_amount or claim.claimed_amount)
        except (ValueError, TypeError):
            flash("Reimbursed amount must be a valid number.", "danger")
            return redirect(url_for('billing.insurance_claims'))

        if not math.isfinite(approved_amount) or approved_amount < 0 or approved_amount > claim.claimed_amount:
            flash("Reimbursed amount must be a non-negative finite number not exceeding the claimed amount.", "danger")
            return redirect(url_for('billing.insurance_claims'))

        claim.approved_amount = round(approved_amount, 2)
        claim.settled_at = datetime.utcnow()

    elif new_status == 'rejected':
        if not rejection_reason:
            rejection_reason = "Claim rejected by insurer."
        claim.rejection_reason = rejection_reason

    claim.status = new_status

    AuditLog.log_event(
        'insurance_claim_updated',
        'insurance_claim',
        claim.id,
        f"Claim {claim.claim_number} ({claim.scheme_name}) status updated to '{new_status}'.",
        severity='info'
    )
    db.session.commit()
    flash(f"Claim {claim.claim_number} updated to {new_status.replace('_', ' ').title()}.", "info")
    return redirect(url_for('billing.insurance_claims'))



# =================== 12. CREDIT NOTES, REFUNDS & FEE WAIVERS ===================
@billing_bp.route('/refunds-waivers', methods=['GET'])
def refunds_waivers():
    """
    Financial Governance: Credit Notes, Patient Refunds, and Indigent Fee Waivers.
    """
    credit_notes = CreditNote.query.order_by(CreditNote.created_at.desc()).all()
    fee_waivers = FeeWaiver.query.order_by(FeeWaiver.created_at.desc()).all()
    invoices = Invoice.query.order_by(Invoice.id.desc()).limit(30).all()

    total_refunds = sum(cn.amount for cn in credit_notes if cn.status == 'approved')
    total_waivers = sum(fw.amount for fw in fee_waivers if fw.status == 'approved')
    pending_approvals = sum(1 for cn in credit_notes if cn.status == 'pending_approval') + sum(1 for fw in fee_waivers if fw.status == 'pending_approval')

    return render_template(
        'billing/refunds_waivers.html',
        credit_notes=credit_notes,
        fee_waivers=fee_waivers,
        invoices=invoices,
        total_refunds=total_refunds,
        total_waivers=total_waivers,
        pending_approvals=pending_approvals
    )


@billing_bp.route('/credit-notes/create', methods=['POST'])
def create_credit_note():
    invoice_id = request.form.get('invoice_id', type=int)
    if not invoice_id:
        abort(400)
    raw_amount = request.form.get('amount')
    try:
        amount = float(raw_amount or 0.0)
    except (ValueError, TypeError):
        flash("Credit note amount must be a valid number.", "danger")
        return redirect(url_for('billing.refunds_waivers'))

    invoice = Invoice.query.get_or_404(invoice_id)

    if not math.isfinite(amount) or amount <= 0:
        flash("Credit note amount must be a positive finite number.", "danger")
        return redirect(url_for('billing.refunds_waivers'))

    # Reject invalid/over-limit amounts
    if invoice.status == "paid" or amount > invoice.balance_due:
        flash(f"Credit note amount (KES {amount:,.2f}) cannot exceed invoice total due (KES {invoice.total_due:,.2f}).", "danger")
        return redirect(url_for('billing.refunds_waivers'))

    reason = request.form.get('reason', 'billing_error')
    notes = request.form.get('notes', '').strip()

    current_user = get_current_user()
    requested_by = (current_user.full_name or current_user.username) if current_user else 'Cashier Joyce Wambui'

    cn = CreditNote(
        credit_note_number=CreditNote.generate_credit_note_number(db.session),
        invoice_id=invoice.id,
        patient_id=invoice.patient_id,
        amount=round(amount, 2),
        reason=reason,
        status='pending_approval',
        requested_by_id=current_user.id,
        requested_by=requested_by,
        notes=notes
    )
    db.session.add(cn)
    AuditLog.log_event(
        'credit_note_requested',
        'credit_note',
        invoice.id,
        f"Credit note {cn.credit_note_number} requested for KES {amount:.2f} on invoice {invoice.invoice_number} by {requested_by}."
    )
    db.session.commit()
    flash(f"Credit Note request {cn.credit_note_number} submitted for KES {amount:.2f}. Awaiting Administrator Approval.", "info")
    return redirect(url_for('billing.refunds_waivers'))


@billing_bp.route('/credit-notes/<int:cn_id>/action', methods=['POST'])
def action_credit_note(cn_id):
    """
    Admin-only approval for credit notes.
    Cannot self-approve. Pending status transition applied atomically once.
    Reconciles discount/total_due/balance_due without marking no-cash cancellations paid.
    Rejects paid-invoice refunds with actionable message until supported.
    """
    if request.method == 'POST':
        from services.transactions import begin_write
        begin_write()
    action = request.form.get('action') # approve, reject
    if action not in {'approve', 'reject'}:
        return 'Invalid approval action.', 400
    cn = CreditNote.query.get_or_404(cn_id)

    current_user = get_current_user()
    # 1. Admin-only approvals
    if not current_user or current_user.role != 'admin':
        flash("Unauthorized: Only hospital administrators can approve or reject credit notes.", "danger")
        return redirect(url_for('billing.refunds_waivers'))

    # 2. Cannot self-approve
    approver_identifiers = {current_user.full_name, current_user.username, current_user.staff_id}
    if cn.requested_by_id == current_user.id or (cn.requested_by_id is None and cn.requested_by in approver_identifiers):
        flash("Security Alert: Self-approval of credit notes is strictly prohibited. An independent administrator must review this request.", "danger")
        return redirect(url_for('billing.refunds_waivers'))

    # 3. Pending status transition atomically applied once
    if cn.status != 'pending_approval':
        flash(f"Credit Note {cn.credit_note_number} has already been processed with status '{cn.status}'.", "warning")
        return redirect(url_for('billing.refunds_waivers'))

    approver_name = current_user.full_name or current_user.username

    if action == 'approve':
        # Reject invalid/negative amounts
        if not math.isfinite(cn.amount) or cn.amount <= 0:
            flash("Cannot approve credit note with invalid or non-positive amount.", "danger")
            return redirect(url_for('billing.refunds_waivers'))

        # Paid-invoice refunds require explicit reverse-payment accounting or reject approval with actionable message until supported
        if cn.invoice.status == 'paid' or cn.amount > cn.invoice.balance_due:
            flash(
                "Paid-invoice refunds require explicit reverse-payment accounting which is currently not supported. "
                "Approval rejected: Please route cash/M-Pesa refund disbursement through manual finance accounts.",
                "danger"
            )
            return redirect(url_for('billing.refunds_waivers'))

        cn.status = 'approved'
        cn.approved_by_id = current_user.id
        cn.approved_by = approver_name
        cn.approved_at = datetime.utcnow()

        # Reconcile discount/total_due/balance_due:
        cn.invoice.discount_amount = round(cn.invoice.discount_amount + cn.amount, 2)
        cn.invoice.total_due = max(0.0, round(cn.invoice.subtotal - cn.invoice.discount_amount + cn.invoice.tax_amount, 2))
        cn.invoice.balance_due = max(0.0, round(cn.invoice.total_due - cn.invoice.amount_paid, 2))

        # Don't mark no-cash cancellations paid!
        if cn.invoice.balance_due <= 0.001:
            if cn.invoice.amount_paid <= 0:
                cn.invoice.status = 'cancelled'
            else:
                cn.invoice.status = 'paid'
                cn.invoice.paid_at = datetime.utcnow()

        AuditLog.log_event(
            'credit_note_approved',
            'credit_note',
            cn.id,
            f"Credit Note {cn.credit_note_number} (KES {cn.amount:.2f}) approved by {approver_name} and reconciled against {cn.invoice.invoice_number}."
        )
        db.session.commit()
        flash(f"Credit Note {cn.credit_note_number} approved and applied to {cn.invoice.invoice_number}.", "success")
    else:
        cn.status = 'rejected'
        cn.approved_by_id = current_user.id
        cn.approved_by = approver_name
        cn.approved_at = datetime.utcnow()
        AuditLog.log_event(
            'credit_note_rejected',
            'credit_note',
            cn.id,
            f"Credit Note {cn.credit_note_number} rejected by {approver_name}."
        )
        db.session.commit()
        flash(f"Credit Note {cn.credit_note_number} rejected.", "warning")

    db.session.commit()
    return redirect(url_for('billing.refunds_waivers'))


@billing_bp.route('/waivers/create', methods=['POST'])
def create_fee_waiver():
    invoice_id = request.form.get('invoice_id', type=int)
    if not invoice_id:
        abort(400)
    raw_amount = request.form.get('amount')
    try:
        amount = float(raw_amount or 0.0)
    except (ValueError, TypeError):
        flash("Waiver amount must be a valid number.", "danger")
        return redirect(url_for('billing.refunds_waivers'))

    invoice = Invoice.query.get_or_404(invoice_id)

    if not math.isfinite(amount) or amount <= 0:
        flash("Waiver amount must be a positive finite number.", "danger")
        return redirect(url_for('billing.refunds_waivers'))

    # Reject invalid/over-limit amounts
    if amount > invoice.balance_due:
        flash(f"Waiver amount (KES {amount:,.2f}) cannot exceed outstanding invoice balance (KES {invoice.balance_due:,.2f}).", "danger")
        return redirect(url_for('billing.refunds_waivers'))

    category = request.form.get('category', 'indigent_patient')
    justification = request.form.get('justification', '').strip()
    if not justification:
        flash("Clinical or administrative justification is required for fee waivers.", "danger")
        return redirect(url_for('billing.refunds_waivers'))

    current_user = get_current_user()
    requested_by = (current_user.full_name or current_user.username) if current_user else 'Cashier Joyce Wambui'

    waiver = FeeWaiver(
        waiver_number=FeeWaiver.generate_waiver_number(db.session),
        invoice_id=invoice.id,
        patient_id=invoice.patient_id,
        amount=round(amount, 2),
        category=category,
        justification=justification,
        status='pending_approval',
        requested_by_id=current_user.id,
        requested_by=requested_by
    )
    db.session.add(waiver)
    AuditLog.log_event(
        'fee_waiver_requested',
        'fee_waiver',
        invoice.id,
        f"Fee waiver {waiver.waiver_number} (KES {amount:.2f}) requested for {invoice.patient.full_name} by {requested_by}."
    )
    db.session.commit()
    flash(f"Fee Waiver request {waiver.waiver_number} submitted for KES {amount:.2f}. Awaiting Administrator Approval.", "info")
    return redirect(url_for('billing.refunds_waivers'))


@billing_bp.route('/waivers/<int:wv_id>/action', methods=['POST'])
def action_fee_waiver(wv_id):
    """
    Admin-only approval for fee waivers.
    Cannot self-approve. Pending status transition applied atomically once.
    Reconciles discount/total_due/balance_due without marking no-cash cancellations paid.
    """
    if request.method == 'POST':
        from services.transactions import begin_write
        begin_write()
    action = request.form.get('action') # approve, reject
    if action not in {'approve', 'reject'}:
        return 'Invalid approval action.', 400
    waiver = FeeWaiver.query.get_or_404(wv_id)

    current_user = get_current_user()
    # 1. Admin-only approvals
    if not current_user or current_user.role != 'admin':
        flash("Unauthorized: Only hospital administrators can approve fee waivers.", "danger")
        return redirect(url_for('billing.refunds_waivers'))

    # 2. Cannot self-approve
    approver_identifiers = {current_user.full_name, current_user.username, current_user.staff_id}
    if waiver.requested_by_id == current_user.id or (waiver.requested_by_id is None and waiver.requested_by in approver_identifiers):
        flash("Security Alert: Self-approval of fee waivers is strictly prohibited. An independent administrator must review this waiver.", "danger")
        return redirect(url_for('billing.refunds_waivers'))

    # 3. Pending status transition atomically applied once
    if waiver.status != 'pending_approval':
        flash(f"Fee Waiver {waiver.waiver_number} has already been processed with status '{waiver.status}'.", "warning")
        return redirect(url_for('billing.refunds_waivers'))

    approver_name = current_user.full_name or current_user.username

    if action == 'approve':
        if not math.isfinite(waiver.amount) or waiver.amount <= 0 or waiver.amount > waiver.invoice.balance_due:
            flash("Invalid or over-limit waiver amount.", "danger")
            return redirect(url_for('billing.refunds_waivers'))

        waiver.status = 'approved'
        waiver.approved_by_id = current_user.id
        waiver.approved_by = approver_name
        waiver.approved_at = datetime.utcnow()

        # Reconcile discount/total_due/balance_due
        waiver.invoice.discount_amount = round(waiver.invoice.discount_amount + waiver.amount, 2)
        waiver.invoice.total_due = max(0.0, round(waiver.invoice.subtotal - waiver.invoice.discount_amount + waiver.invoice.tax_amount, 2))
        waiver.invoice.balance_due = max(0.0, round(waiver.invoice.total_due - waiver.invoice.amount_paid, 2))

        if waiver.invoice.balance_due <= 0.001:
            waiver.invoice.status = 'paid' if waiver.invoice.amount_paid > 0 else 'waived'
            if waiver.invoice.amount_paid > 0:
                waiver.invoice.paid_at = datetime.utcnow()

        AuditLog.log_event(
            'fee_waiver_approved',
            'fee_waiver',
            waiver.id,
            f"Fee Waiver {waiver.waiver_number} (KES {waiver.amount:.2f}) approved for {waiver.patient.full_name} by {approver_name}."
        )
        db.session.commit()
        flash(f"Fee Waiver {waiver.waiver_number} approved for {waiver.patient.full_name}.", "success")
    else:
        waiver.status = 'rejected'
        waiver.approved_by_id = current_user.id
        waiver.approved_by = approver_name
        waiver.approved_at = datetime.utcnow()
        AuditLog.log_event(
            'fee_waiver_rejected',
            'fee_waiver',
            waiver.id,
            f"Fee Waiver {waiver.waiver_number} rejected by {approver_name}."
        )
        db.session.commit()
        flash(f"Fee Waiver {waiver.waiver_number} rejected.", "warning")

    db.session.commit()
    return redirect(url_for('billing.refunds_waivers'))


# =================== 13. AGED DEBTORS & REVENUE RECONCILIATION ===================
@billing_bp.route('/debtors', methods=['GET'])
def debtors():
    """
    Aged Debtors Analysis for Corporate Insurers and Outstanding Patient Folios.
    """
    schemes = InsuranceScheme.query.all()
    debtor_data = []
    total_receivables = 0.0

    for s in schemes:
        claims = InsuranceClaim.query.filter(
            InsuranceClaim.scheme_name == s.name,
            InsuranceClaim.status.in_(['preauth_approved', 'submitted'])
        ).all()
        outstanding = sum(c.claimed_amount for c in claims)
        total_receivables += outstanding
        debtor_data.append({
            'scheme': s,
            'claims_count': len(claims),
            'outstanding_amount': outstanding,
            'current': outstanding * 0.6,
            'aged_30d': outstanding * 0.25,
            'aged_60d': outstanding * 0.15
        })

    return render_template(
        'billing/debtors.html',
        debtors=debtor_data,
        total_receivables=total_receivables
    )


# =================== 14. KRA / TAX SUMMARY & REVENUE REPORT ===================
@billing_bp.route('/reports', methods=['GET'])
def financial_reports():
    """
    Official Tax, VAT, and Payment Method Audit Summary.
    """
    today_start = datetime.combine(date.today(), datetime.min.time())
    today_payments = Payment.query.filter(Payment.created_at >= today_start).all()

    cash_total = sum(p.cash_amount for p in today_payments)
    mpesa_total = sum(p.mpesa_amount for p in today_payments)
    insurance_total = sum(p.insurance_amount for p in today_payments)
    card_total = sum(p.card_amount for p in today_payments)
    gross_revenue = cash_total + mpesa_total + insurance_total + card_total
    recorded_tax = round(sum(
        p.total_amount_paid * p.invoice.tax_amount / p.invoice.total_due
        for p in today_payments if p.invoice and p.invoice.total_due > 0
    ), 2)

    return render_template(
        'billing/reports.html',
        today_payments=today_payments,
        cash_total=cash_total,
        mpesa_total=mpesa_total,
        insurance_total=insurance_total,
        card_total=card_total,
        gross_revenue=gross_revenue,
        recorded_tax=recorded_tax,
        today=date.today()
    )



@billing_bp.route('/pos/<int:patient_id>/stage-invoice', methods=['POST'])
def stage_invoice(patient_id):
    from services.transactions import begin_write
    begin_write()
    patient = Patient.query.get_or_404(patient_id)
    items = BillingItem.query.filter_by(patient_id=patient.id, status='staged', invoice_id=None).all()
    if not items:
        return redirect(url_for('billing.pos', patient_id=patient.id))
    invoice = Invoice.query.filter(Invoice.patient_id == patient.id, Invoice.status.in_(['unpaid', 'partially_paid'])).order_by(Invoice.id.desc()).first()
    if not invoice:
        invoice = Invoice(invoice_number=Invoice.generate_invoice_number(db.session), patient_id=patient.id,
                          subtotal=0, discount_amount=0, tax_amount=0, total_due=0, amount_paid=0,
                          balance_due=0, status='unpaid', cashier_name=get_current_user().full_name)
        db.session.add(invoice); db.session.flush()
    invoice.subtotal = round(invoice.subtotal + sum(item.total_amount for item in items), 2)
    invoice.total_due = round(invoice.subtotal - invoice.discount_amount + invoice.tax_amount, 2)
    invoice.balance_due = round(invoice.total_due - invoice.amount_paid, 2)
    for item in items:
        item.invoice_id = invoice.id
    AuditLog.log_event('invoice_staged', 'invoice', invoice.id, actor=get_current_user())
    db.session.commit()
    return redirect(url_for('billing.pos', patient_id=patient.id))
