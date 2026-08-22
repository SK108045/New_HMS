import json
from datetime import datetime, date, timedelta
from flask import render_template, request, redirect, url_for, flash, jsonify
from auth.decorators import get_current_user
from models import (
    db, Patient, User, AuditLog, Invoice, BillingItem,
    Ward, Bed, Admission, BedTransfer, NursingNote, WardRoundNote,
    VitalsRecord, ConsultationNote, Prescription
)
from . import inpatient_bp

DOCTORS_LIST = [
    "Dr. Sarah Kamau (Lead Physician)",
    "Dr. Arthur Ndwiga (Internal Medicine)",
    "Dr. Njoroge (General Surgery)",
    "Dr. Grace Mwangi (Pediatrician)",
    "Dr. Robert Odhiambo (Consultant)"
]

ICD10_ADMISSION_PRESETS = [
    {"code": "A09", "desc": "Infectious gastroenteritis and severe dehydration"},
    {"code": "J18.9", "desc": "Pneumonia, unspecified organism"},
    {"code": "I10", "desc": "Hypertensive crisis with end-organ monitoring"},
    {"code": "E11.65", "desc": "Type 2 diabetes with hyperglycemia / DKA"},
    {"code": "B54", "desc": "Severe Plasmodium falciparum malaria"},
    {"code": "K35.80", "desc": "Acute appendicitis awaiting surgical evaluation"},
    {"code": "O80", "desc": "Spontaneous vertex delivery / Maternal admission"},
    {"code": "S06.0X0A", "desc": "Concussion / Mild traumatic brain injury"},
    {"code": "N39.0", "desc": "Severe urosepsis / Acute pyelonephritis"}
]


def log_inpatient_audit(action, entity_type, entity_id=None, details=None):
    actor = get_current_user()
    db.session.add(AuditLog(
        actor_user_id=actor.id if actor else None,
        actor_name=actor.full_name if actor else 'Ward Nurse',
        action=action,
        entity_type=entity_type,
        entity_id=str(entity_id) if entity_id is not None else None,
        details=details
    ))


# =================== 1. INPATIENT EXECUTIVE DASHBOARD & BED RACK ===================
@inpatient_bp.route('/', methods=['GET'])
@inpatient_bp.route('/dashboard', methods=['GET'])
def dashboard():
    today_start = datetime.combine(date.today(), datetime.min.time())
    
    wards = Ward.query.filter_by(is_active=True).all()
    total_beds = Bed.query.count()
    occupied_beds = Bed.query.filter_by(status='occupied').count()
    available_beds = Bed.query.filter_by(status='available').count()
    cleaning_beds = Bed.query.filter_by(status='cleaning').count()
    maintenance_beds = Bed.query.filter_by(status='maintenance').count()
    
    overall_occupancy_rate = round((occupied_beds / total_beds * 100), 1) if total_beds > 0 else 0
    
    today_admissions = Admission.query.filter(Admission.admitted_at >= today_start).count()
    today_discharges = Admission.query.filter(
        Admission.actual_discharge_date >= today_start,
        Admission.status == 'discharged'
    ).count()

    active_admissions = Admission.query.filter_by(status='admitted').order_by(Admission.admitted_at.desc()).all()
    recent_admissions = active_admissions[:6]

    return render_template(
        'inpatient/dashboard.html',
        wards=wards,
        total_beds=total_beds,
        occupied_beds=occupied_beds,
        available_beds=available_beds,
        cleaning_beds=cleaning_beds,
        maintenance_beds=maintenance_beds,
        overall_occupancy_rate=overall_occupancy_rate,
        today_admissions=today_admissions,
        today_discharges=today_discharges,
        active_admissions=active_admissions,
        recent_admissions=recent_admissions
    )


# =================== 2. ACTIVE ADMITTED INPATIENTS DIRECTORY ===================
@inpatient_bp.route('/admissions', methods=['GET'])
def admissions():
    ward_filter = request.args.get('ward_id', type=int)
    search_q = request.args.get('q', '').strip()
    
    query = Admission.query.filter_by(status='admitted')
    
    if ward_filter:
        query = query.filter_by(ward_id=ward_filter)
        
    if search_q:
        query = query.join(Patient).filter(
            db.or_(
                Patient.full_name.ilike(f'%{search_q}%'),
                Patient.hospital_id.ilike(f'%{search_q}%'),
                Admission.admission_number.ilike(f'%{search_q}%'),
                Admission.admitting_diagnosis.ilike(f'%{search_q}%')
            )
        )
        
    active_admissions = query.order_by(Admission.admitted_at.desc()).all()
    wards = Ward.query.filter_by(is_active=True).all()
    
    # Calculate statistics
    avg_los = 0
    if active_admissions:
        total_days = sum(a.length_of_stay_days for a in active_admissions)
        avg_los = round(total_days / len(active_admissions), 1)
        
    isolation_count = sum(1 for a in active_admissions if a.isolation_required)

    return render_template(
        'inpatient/admissions.html',
        admissions=active_admissions,
        wards=wards,
        selected_ward=ward_filter,
        search_q=search_q,
        avg_los=avg_los,
        isolation_count=isolation_count
    )


# =================== 3. PATIENT ADMISSION INTAKE ===================
@inpatient_bp.route('/admit', methods=['GET', 'POST'])
def admit():
    patient_id = request.args.get('patient_id', type=int)
    selected_patient = db.session.get(Patient, patient_id) if patient_id else None

    if request.method == 'POST':
        p_id = request.form.get('patient_id', type=int)
        ward_id = request.form.get('ward_id', type=int)
        bed_id = request.form.get('bed_id', type=int)
        admitting_doctor = request.form.get('admitting_doctor', '').strip()
        admitting_diagnosis = request.form.get('admitting_diagnosis', '').strip()
        icd10_code = request.form.get('icd10_code', '').strip()
        admission_type = request.form.get('admission_type', 'Emergency Admission')
        expected_date_str = request.form.get('expected_discharge_date', '')
        dietary_plan = request.form.get('dietary_plan', 'Normal Hospital Diet')
        isolation_required = bool(request.form.get('isolation_required'))
        nursing_acuity = request.form.get('nursing_acuity', 'Moderate Care (Level 2)')
        deposit_amount = float(request.form.get('deposit_amount') or 0.0)
        
        emergency_name = request.form.get('emergency_contact_name', '').strip()
        emergency_phone = request.form.get('emergency_contact_phone', '').strip()
        emergency_relation = request.form.get('emergency_contact_relation', '').strip()

        if not p_id or not ward_id or not bed_id or not admitting_doctor or not admitting_diagnosis:
            flash('Patient, Ward, Bed, Admitting Doctor, and Diagnosis are required fields.', 'error')
            return redirect(url_for('inpatient.admit', patient_id=p_id))

        patient = db.session.get(Patient, p_id)
        bed = db.session.get(Bed, bed_id)
        ward = db.session.get(Ward, ward_id)

        if not patient or not bed or not ward:
            flash('Invalid patient, ward, or bed selection.', 'error')
            return redirect(url_for('inpatient.admit'))

        if bed.status != 'available':
            flash(f'Bed {bed.bed_number} is currently {bed.status}. Please choose an available bed.', 'error')
            return redirect(url_for('inpatient.admit', patient_id=p_id))

        # Check if patient already has an active admission
        existing_adm = Admission.query.filter_by(patient_id=p_id, status='admitted').first()
        if existing_adm:
            flash(f'{patient.full_name} is already admitted in {existing_adm.ward.name} (Bed {existing_adm.bed.bed_number}).', 'warning')
            return redirect(url_for('inpatient.patient_chart', admission_id=existing_adm.id))

        expected_date = None
        if expected_date_str:
            try:
                expected_date = datetime.strptime(expected_date_str, '%Y-%m-%d').date()
            except ValueError:
                pass

        # Generate Admission Number: ADM-YYYY-XXXX
        total_admissions_count = Admission.query.count() + 1
        admission_number = f"ADM-{datetime.utcnow().year}-{total_admissions_count:04d}"

        admission = Admission(
            admission_number=admission_number,
            patient_id=p_id,
            ward_id=ward_id,
            bed_id=bed_id,
            admitting_doctor=admitting_doctor,
            admitting_diagnosis=admitting_diagnosis,
            icd10_code=icd10_code,
            admission_type=admission_type,
            admitted_at=datetime.utcnow(),
            expected_discharge_date=expected_date,
            status='admitted',
            dietary_plan=dietary_plan,
            isolation_required=isolation_required,
            nursing_acuity=nursing_acuity,
            deposit_amount=deposit_amount,
            emergency_contact_name=emergency_name or patient.emergency_contact_name,
            emergency_contact_phone=emergency_phone or patient.emergency_contact_phone,
            emergency_contact_relation=emergency_relation or patient.emergency_contact_relation
        )

        # Mark Bed as Occupied
        bed.status = 'occupied'

        db.session.add(admission)
        db.session.commit()

        log_inpatient_audit(
            'patient_admitted',
            'admission',
            admission.id,
            f"Admitted {patient.full_name} to {ward.name} Bed {bed.bed_number}. Diagnosis: {admitting_diagnosis}."
        )
        db.session.commit()

        flash(f"Successfully admitted {patient.full_name} to {ward.name} ({bed.bed_number}). Admission Ref: {admission_number}", 'success')
        return redirect(url_for('inpatient.patient_chart', admission_id=admission.id))

    wards = Ward.query.filter_by(is_active=True).all()
    available_beds = Bed.query.filter_by(status='available').all()
    recent_patients = Patient.query.order_by(Patient.created_at.desc()).limit(20).all()

    return render_template(
        'inpatient/admit.html',
        selected_patient=selected_patient,
        wards=wards,
        available_beds=available_beds,
        recent_patients=recent_patients,
        doctors=DOCTORS_LIST,
        icd10_presets=ICD10_ADMISSION_PRESETS
    )


# =================== 4. 360° INPATIENT CLINICAL CHART ===================
@inpatient_bp.route('/patient/<int:admission_id>', methods=['GET'])
def patient_chart(admission_id):
    admission = Admission.query.get_or_404(admission_id)
    patient = admission.patient
    
    # Fetch recent outpatient/inpatient vitals
    vitals_history = VitalsRecord.query.filter_by(patient_id=patient.id).order_by(VitalsRecord.created_at.desc()).limit(10).all()
    
    # Fetch available beds for transfer modal
    available_beds = Bed.query.filter_by(status='available').all()
    wards = Ward.query.filter_by(is_active=True).all()

    return render_template(
        'inpatient/patient_chart.html',
        admission=admission,
        patient=patient,
        vitals_history=vitals_history,
        available_beds=available_beds,
        wards=wards,
        doctors=DOCTORS_LIST,
        now=datetime.utcnow()
    )


# =================== 5. RECORD SHIFT NURSING NOTE ===================
@inpatient_bp.route('/patient/<int:admission_id>/nursing-note', methods=['POST'])
def add_nursing_note(admission_id):
    admission = Admission.query.get_or_404(admission_id)
    actor = get_current_user()
    
    nurse_name = request.form.get('nurse_name', '').strip() or (actor.full_name if actor else 'Nurse Joyce Chebet')
    shift = request.form.get('shift', 'Morning Shift')
    subjective = request.form.get('subjective_assessment', '').strip()
    interventions = request.form.get('nursing_interventions', '').strip()
    vitals_summary = request.form.get('vital_signs_summary', '').strip()
    intake_output = request.form.get('intake_output_notes', '').strip()
    medications = request.form.get('medications_administered', '').strip()
    iv_infusions = request.form.get('iv_infusions', '').strip()
    handover = request.form.get('handover_instructions', '').strip()

    if not interventions:
        flash('Nursing interventions & care summary cannot be blank.', 'error')
        return redirect(url_for('inpatient.patient_chart', admission_id=admission.id))

    note = NursingNote(
        admission_id=admission.id,
        patient_id=admission.patient_id,
        nurse_name=nurse_name,
        shift=shift,
        subjective_assessment=subjective,
        nursing_interventions=interventions,
        vital_signs_summary=vitals_summary,
        intake_output_notes=intake_output,
        medications_administered=medications,
        iv_infusions=iv_infusions,
        handover_instructions=handover,
        created_at=datetime.utcnow()
    )

    db.session.add(note)
    db.session.commit()

    log_inpatient_audit(
        'nursing_note_added',
        'nursing_note',
        note.id,
        f"Logged {shift} nursing care note for {admission.patient.full_name} ({admission.admission_number})."
    )
    db.session.commit()

    flash(f"Shift nursing note successfully charted by {nurse_name}.", 'success')
    return redirect(url_for('inpatient.patient_chart', admission_id=admission.id))


# =================== 6. RECORD DOCTOR DAILY WARD ROUND ===================
@inpatient_bp.route('/patient/<int:admission_id>/ward-round', methods=['POST'])
def add_ward_round(admission_id):
    admission = Admission.query.get_or_404(admission_id)
    actor = get_current_user()

    doctor_name = request.form.get('doctor_name', '').strip() or (actor.full_name if actor else 'Dr. Sarah Kamau')
    clinical_progress = request.form.get('clinical_progress', '').strip()
    lab_review = request.form.get('lab_radiology_review', '').strip()
    treatment_plan = request.form.get('treatment_plan_changes', '').strip()
    discharge_readiness = request.form.get('discharge_readiness', 'Continue Inpatient Care')

    if not clinical_progress or not treatment_plan:
        flash('Clinical findings and treatment plan modifications are required for ward rounds.', 'error')
        return redirect(url_for('inpatient.patient_chart', admission_id=admission.id))

    round_note = WardRoundNote(
        admission_id=admission.id,
        patient_id=admission.patient_id,
        doctor_name=doctor_name,
        round_date=datetime.utcnow(),
        clinical_progress=clinical_progress,
        lab_radiology_review=lab_review,
        treatment_plan_changes=treatment_plan,
        discharge_readiness=discharge_readiness,
        created_at=datetime.utcnow()
    )

    db.session.add(round_note)
    db.session.commit()

    log_inpatient_audit(
        'ward_round_recorded',
        'ward_round_note',
        round_note.id,
        f"Doctor ward round documented for {admission.patient.full_name} by {doctor_name} ({discharge_readiness})."
    )
    db.session.commit()

    flash(f"Ward round progress note saved successfully by {doctor_name}.", 'success')
    return redirect(url_for('inpatient.patient_chart', admission_id=admission.id))


# =================== 7. INTER-WARD & BED TRANSFER ===================
@inpatient_bp.route('/patient/<int:admission_id>/transfer', methods=['POST'])
def transfer_bed(admission_id):
    admission = Admission.query.get_or_404(admission_id)
    actor = get_current_user()

    to_ward_id = request.form.get('to_ward_id', type=int)
    to_bed_id = request.form.get('to_bed_id', type=int)
    reason = request.form.get('transfer_reason', '').strip()
    transferred_by = request.form.get('transferred_by', '').strip() or (actor.full_name if actor else 'Ward Nurse')

    if not to_ward_id or not to_bed_id or not reason:
        flash('Destination Ward, Destination Bed, and Transfer Reason are required.', 'error')
        return redirect(url_for('inpatient.patient_chart', admission_id=admission.id))

    new_bed = db.session.get(Bed, to_bed_id)
    new_ward = db.session.get(Ward, to_ward_id)
    old_bed = admission.bed
    old_ward = admission.ward

    if not new_bed or not new_ward:
        flash('Invalid destination ward or bed.', 'error')
        return redirect(url_for('inpatient.patient_chart', admission_id=admission.id))

    if new_bed.status != 'available':
        flash(f'Bed {new_bed.bed_number} is not available.', 'error')
        return redirect(url_for('inpatient.patient_chart', admission_id=admission.id))

    # Free previous bed & occupy new bed
    old_bed.status = 'cleaning'
    new_bed.status = 'occupied'

    # Create transfer record
    transfer_log = BedTransfer(
        admission_id=admission.id,
        patient_id=admission.patient_id,
        from_ward_id=old_ward.id,
        from_bed_id=old_bed.id,
        to_ward_id=new_ward.id,
        to_bed_id=new_bed.id,
        transfer_reason=reason,
        transferred_by=transferred_by,
        transferred_at=datetime.utcnow()
    )

    admission.ward_id = new_ward.id
    admission.bed_id = new_bed.id

    db.session.add(transfer_log)
    db.session.commit()

    log_inpatient_audit(
        'bed_transfer',
        'bed_transfer',
        transfer_log.id,
        f"Transferred {admission.patient.full_name} from {old_ward.name} ({old_bed.bed_number}) to {new_ward.name} ({new_bed.bed_number}). Reason: {reason}"
    )
    db.session.commit()

    flash(f"Patient successfully transferred to {new_ward.name} - Bed {new_bed.bed_number}.", 'success')
    return redirect(url_for('inpatient.patient_chart', admission_id=admission.id))


# =================== 8. PATIENT DISCHARGE & BILLING INTEGRATION ===================
@inpatient_bp.route('/patient/<int:admission_id>/discharge', methods=['GET', 'POST'])
def discharge(admission_id):
    admission = Admission.query.get_or_404(admission_id)
    patient = admission.patient

    if admission.status == 'discharged':
        flash('This patient has already been discharged.', 'info')
        return redirect(url_for('inpatient.print_discharge_summary', admission_id=admission.id))

    if request.method == 'POST':
        actor = get_current_user()
        discharge_type = request.form.get('discharge_type', 'Routine Medical Clearance')
        condition = request.form.get('condition_on_discharge', 'Recovered / Stable')
        summary = request.form.get('discharge_summary', '').strip()
        instructions = request.form.get('discharge_instructions', '').strip()
        followup_date_str = request.form.get('followup_date', '')
        followup_clinic = request.form.get('followup_clinic', 'General OPD')
        discharged_by = request.form.get('discharged_by', '').strip() or (actor.full_name if actor else 'Dr. Sarah Kamau')
        
        meds_json_str = request.form.get('discharge_medications_json', '[]')
        try:
            meds_list = json.loads(meds_json_str) if meds_json_str else []
        except Exception:
            meds_list = []

        if not summary or not instructions:
            flash('Discharge clinical summary and homecare instructions are required.', 'error')
            return redirect(url_for('inpatient.discharge', admission_id=admission.id))

        followup_date = None
        if followup_date_str:
            try:
                followup_date = datetime.strptime(followup_date_str, '%Y-%m-%d').date()
            except ValueError:
                pass

        # Update Admission
        admission.status = 'discharged'
        admission.actual_discharge_date = datetime.utcnow()
        admission.discharge_type = discharge_type
        admission.condition_on_discharge = condition
        admission.discharge_summary = summary
        admission.discharge_instructions = instructions
        admission.discharge_medications = meds_list
        admission.followup_date = followup_date
        admission.followup_clinic = followup_clinic
        admission.discharged_by = discharged_by

        # Release Bed to Cleaning
        bed = admission.bed
        if bed:
            bed.status = 'cleaning'

        # Stage Inpatient Bed Accommodation Charges into Billing Folio
        los_days = admission.length_of_stay_days
        rate = bed.daily_rate if bed else 1500.0
        total_bed_charge = los_days * rate

        # Check for open patient invoice or create one
        invoice = Invoice.query.filter_by(patient_id=patient.id, status='unpaid').order_by(Invoice.created_at.desc()).first()
        if not invoice:
            invoice = Invoice.query.filter_by(patient_id=patient.id, status='partially_paid').order_by(Invoice.created_at.desc()).first()

        if not invoice:
            inv_num = Invoice.generate_invoice_number(db.session)
            invoice = Invoice(
                invoice_number=inv_num,
                patient_id=patient.id,
                subtotal=0.0,
                discount_amount=0.0,
                tax_amount=0.0,
                total_due=0.0,
                amount_paid=0.0,
                balance_due=0.0,
                status='unpaid',
                created_at=datetime.utcnow()
            )
            db.session.add(invoice)
            db.session.flush()

        bed_item = BillingItem(
            patient_id=patient.id,
            invoice_id=invoice.id,
            service_type='bed',
            item_description=f"Inpatient Bed Accommodation: {admission.ward.name} - {bed.bed_number if bed else 'Bed'} ({los_days} Day{'s' if los_days != 1 else ''} @ KES {rate:,.2f}/day)",
            quantity=los_days,
            unit_price=rate,
            total_amount=total_bed_charge,
            status='staged',
            created_at=datetime.utcnow()
        )
        db.session.add(bed_item)

        invoice.subtotal += total_bed_charge
        invoice.total_due = max(0.0, invoice.subtotal - invoice.discount_amount + invoice.tax_amount)
        invoice.balance_due = max(0.0, invoice.total_due - invoice.amount_paid)

        db.session.commit()

        log_inpatient_audit(
            'patient_discharged',
            'admission',
            admission.id,
            f"Discharged {patient.full_name} ({admission.admission_number}). Length of stay: {los_days} days. Bed charge KES {total_bed_charge:,.2f} billed to Invoice #{invoice.invoice_number}."
        )
        db.session.commit()

        flash(f"Patient {patient.full_name} successfully discharged. Bed {bed.bed_number} scheduled for sanitization.", 'success')
        return redirect(url_for('inpatient.print_discharge_summary', admission_id=admission.id))

    return render_template(
        'inpatient/discharge.html',
        admission=admission,
        patient=patient,
        doctors=DOCTORS_LIST,
        now=datetime.utcnow(),
        today=date.today()
    )


# =================== 9. PRINTABLE A4 DISCHARGE SUMMARY CERTIFICATE ===================
@inpatient_bp.route('/patient/<int:admission_id>/discharge-summary/print', methods=['GET'])
def print_discharge_summary(admission_id):
    admission = Admission.query.get_or_404(admission_id)
    patient = admission.patient
    return render_template(
        'inpatient/print_discharge.html',
        admission=admission,
        patient=patient,
        now=datetime.utcnow()
    )


# =================== 10. WARD & BED MANAGEMENT MATRIX ===================
@inpatient_bp.route('/beds', methods=['GET', 'POST'])
def beds():
    if request.method == 'POST':
        bed_id = request.form.get('bed_id', type=int)
        new_status = request.form.get('status')
        
        bed = db.session.get(Bed, bed_id)
        if bed and new_status in ['available', 'cleaning', 'maintenance', 'reserved']:
            if bed.status == 'occupied' and new_status != 'occupied':
                flash('Cannot manually change status of an occupied bed. Discharge or transfer patient first.', 'warning')
            else:
                old_status = bed.status
                bed.status = new_status
                db.session.commit()
                log_inpatient_audit('bed_status_updated', 'bed', bed.id, f"Changed Bed {bed.bed_number} status from {old_status} to {new_status}.")
                db.session.commit()
                flash(f"Bed {bed.bed_number} status updated to {new_status.title()}.", 'success')
        return redirect(url_for('inpatient.beds'))

    wards = Ward.query.filter_by(is_active=True).all()
    all_beds = Bed.query.order_by(Bed.ward_id, Bed.bed_number).all()

    return render_template(
        'inpatient/beds.html',
        wards=wards,
        all_beds=all_beds
    )


# =================== 11. HTMX ENDPOINT: FETCH AVAILABLE BEDS BY WARD ===================
@inpatient_bp.route('/api/available-beds/<int:ward_id>', methods=['GET'])
def api_available_beds(ward_id):
    beds = Bed.query.filter_by(ward_id=ward_id, status='available').order_by(Bed.bed_number).all()
    options_html = '<option value="">-- Choose Bed --</option>'
    for b in beds:
        options_html += f'<option value="{b.id}">{b.bed_number} ({b.bed_type} - KES {b.daily_rate:,.0f}/day)</option>'
    return options_html
