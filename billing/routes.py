import json
from datetime import datetime, date, timedelta
from flask import render_template, request, redirect, url_for, flash, jsonify
from models.base import db
from models.patient import Patient
from models.queue import QueueEntry
from models.emr import BillingItem, ConsultationNote, LabOrder, Prescription
from models.billing import Invoice, Payment, ShiftRegister
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


def get_or_create_open_shift():
    """
    Retrieves the currently open cashier shift register or creates a new active shift.
    """
    shift = ShiftRegister.query.filter_by(status='open').order_by(ShiftRegister.id.desc()).first()
    if not shift:
        shift = ShiftRegister(
            shift_code=ShiftRegister.generate_shift_code(db.session),
            cashier_name='Cashier Joyce Wambui (Lead Cashier)',
            counter_number='POS-01',
            opening_float=5000.0,
            status='open',
            opened_at=datetime.utcnow()
        )
        db.session.add(shift)
        db.session.commit()
    return shift


# =================== 1. FINANCIAL DASHBOARD & COMMAND ===================
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

    # Collect patient summary with unpaid amounts
    patient_folios = []
    for p in patients_pool:
        # Sum of unpaid billing items
        unpaid_items = BillingItem.query.filter_by(patient_id=p.id, status='staged').all()
        existing_unpaid_inv = Invoice.query.filter_by(patient_id=p.id, status='unpaid').first()
        
        unpaid_total = sum(i.total_amount for i in unpaid_items)
        if existing_unpaid_inv:
            unpaid_total += existing_unpaid_inv.balance_due

        patient_folios.append({
            'patient': p,
            'unpaid_total': unpaid_total,
            'unpaid_items_count': len(unpaid_items)
        })

    # 2. If a patient is selected, load their staged charges and invoice
    if patient_id:
        selected_patient = Patient.query.get_or_404(patient_id)
        
        # Check if there is an existing unpaid invoice
        selected_invoice = Invoice.query.filter_by(patient_id=selected_patient.id, status='unpaid').order_by(Invoice.id.desc()).first()
        
        # Get all staged billing items for this patient
        staged_items = BillingItem.query.filter_by(patient_id=selected_patient.id, status='staged').order_by(BillingItem.id.asc()).all()

        # If no invoice exists but staged items exist, create an invoice on the fly
        if not selected_invoice and staged_items:
            subtotal = sum(i.total_amount for i in staged_items)
            selected_invoice = Invoice(
                invoice_number=Invoice.generate_invoice_number(db.session),
                patient_id=selected_patient.id,
                subtotal=subtotal,
                discount_amount=0.0,
                tax_amount=0.0,
                total_due=subtotal,
                amount_paid=0.0,
                balance_due=subtotal,
                status='unpaid',
                cashier_name='Cashier Joyce Wambui'
            )
            db.session.add(selected_invoice)
            db.session.flush()

            for item in staged_items:
                item.invoice_id = selected_invoice.id

            db.session.commit()
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
    patient = Patient.query.get_or_404(patient_id)
    service_type = request.form.get('service_type', 'procedure')
    item_description = request.form.get('item_description', '').strip()
    quantity = int(request.form.get('quantity', 1))
    unit_price = float(request.form.get('unit_price', 0.0))

    if item_description and unit_price > 0:
        total_amount = quantity * unit_price
        
        # Get or create active unpaid invoice
        inv = Invoice.query.filter_by(patient_id=patient.id, status='unpaid').first()
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
                cashier_name='Cashier Joyce Wambui'
            )
            db.session.add(inv)
            db.session.flush()
        else:
            inv.subtotal += total_amount
            inv.total_due += total_amount
            inv.balance_due += total_amount

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
        db.session.commit()
        flash(f"Added '{item_description}' (KES {total_amount:.2f}) to patient folio.", 'success')

    return redirect(url_for('billing.pos', patient_id=patient.id))


# =================== 4. PROCESS SPLIT PAYMENT SETTLEMENT ===================
@billing_bp.route('/pos/settle/<int:invoice_id>', methods=['POST'])
def process_settlement(invoice_id):
    """
    Executes split payment checkout (Cash, M-Pesa, Insurance Co-pay, Card).
    Calculates change, records tender breakdown, closes invoice, and transitions queue ticket.
    """
    invoice = Invoice.query.get_or_404(invoice_id)
    patient = invoice.patient

    # Read multi-tender input values
    cash_amount = float(request.form.get('cash_amount') or 0.0)
    cash_tendered = float(request.form.get('cash_tendered') or 0.0)
    change_returned = float(request.form.get('change_returned') or 0.0)

    mpesa_amount = float(request.form.get('mpesa_amount') or 0.0)
    mpesa_reference = request.form.get('mpesa_reference', '').strip().upper()
    mpesa_phone = request.form.get('mpesa_phone', '').strip()

    insurance_amount = float(request.form.get('insurance_amount') or 0.0)
    insurance_company = request.form.get('insurance_company', '').strip()
    insurance_policy_number = request.form.get('insurance_policy_number', '').strip()
    insurance_claim_number = request.form.get('insurance_claim_number', '').strip()

    card_amount = float(request.form.get('card_amount') or 0.0)
    card_auth_code = request.form.get('card_auth_code', '').strip()

    discount_amount = float(request.form.get('discount_amount') or 0.0)
    cashier_name = request.form.get('cashier_name', 'Cashier Joyce Wambui')
    counseling_notes = request.form.get('notes', '').strip()

    total_payment = cash_amount + mpesa_amount + insurance_amount + card_amount

    # Apply discount
    if discount_amount > 0:
        invoice.discount_amount = discount_amount
        invoice.total_due = max(0.0, invoice.subtotal - discount_amount)

    if total_payment <= 0:
        flash("Error: Payment amount must be greater than KES 0.00", 'danger')
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

    active_shift = get_or_create_open_shift()

    # Create Payment Record
    payment = Payment(
        receipt_number=Payment.generate_receipt_number(db.session),
        invoice_id=invoice.id,
        patient_id=patient.id,
        total_amount_paid=total_payment,
        payment_method_summary=payment_summary,
        cash_amount=cash_amount,
        cash_tendered=cash_tendered,
        change_returned=change_returned,
        mpesa_amount=mpesa_amount,
        mpesa_reference=mpesa_reference,
        mpesa_phone=mpesa_phone,
        insurance_amount=insurance_amount,
        insurance_company=insurance_company,
        insurance_policy_number=insurance_policy_number,
        insurance_claim_number=insurance_claim_number,
        card_amount=card_amount,
        card_auth_code=card_auth_code,
        cashier_name=cashier_name,
        shift_code=active_shift.shift_code,
        notes=counseling_notes,
        created_at=datetime.utcnow()
    )
    db.session.add(payment)

    # Update Invoice Status
    invoice.amount_paid += total_payment
    invoice.balance_due = max(0.0, invoice.total_due - invoice.amount_paid)
    if invoice.balance_due <= 0:
        invoice.status = 'paid'
        invoice.paid_at = datetime.utcnow()
    else:
        invoice.status = 'partially_paid'

    # Mark all associated billing items as paid
    for item in invoice.billing_items:
        item.status = 'paid'

    # Update Active Shift Totals
    active_shift.cash_collected += cash_amount
    active_shift.mpesa_collected += mpesa_amount
    active_shift.insurance_billed += insurance_amount
    active_shift.card_collected += card_amount
    active_shift.total_revenue += total_payment

    # Complete Patient Queue Entry if associated
    if invoice.queue_entry:
        invoice.queue_entry.status = 'completed'
        invoice.queue_entry.completed_at = datetime.utcnow()

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
    active_shift = get_or_create_open_shift()
    counted_cash = float(request.form.get('counted_cash') or 0.0)
    notes = request.form.get('notes', '').strip()

    expected_cash = active_shift.opening_float + active_shift.cash_collected
    discrepancy = counted_cash - expected_cash

    active_shift.counted_cash = counted_cash
    active_shift.discrepancy = discrepancy
    active_shift.notes = notes
    active_shift.status = 'closed'
    active_shift.closed_at = datetime.utcnow()

    # Automatically initialize new open shift for next operator
    new_shift = ShiftRegister(
        shift_code=ShiftRegister.generate_shift_code(db.session),
        cashier_name='Cashier Joyce Wambui (Lead Cashier)',
        counter_number='POS-01',
        opening_float=5000.0,
        status='open',
        opened_at=datetime.utcnow()
    )
    db.session.add(new_shift)
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
