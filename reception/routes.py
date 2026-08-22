from datetime import datetime, date, timedelta
from flask import render_template, request, redirect, url_for, flash, jsonify, current_app
from sqlalchemy import or_, and_, desc, func

from models import db, Patient, QueueEntry, Appointment, DoctorSchedule, AuditLog
from . import reception_bp
from .utils import save_webcam_or_uploaded_photo, parse_dob

@reception_bp.route('/')
@reception_bp.route('/dashboard')
def dashboard():
    today_start = datetime.combine(date.today(), datetime.min.time())
    
    # Active waiting queue entries
    active_queue = QueueEntry.query.filter(
        QueueEntry.checked_in_at >= today_start,
        QueueEntry.status.in_(['waiting', 'in_progress'])
    ).order_by(
        # Emergency first, then Urgent, then Normal
        db.case(
            (QueueEntry.priority == 'emergency', 1),
            (QueueEntry.priority == 'urgent', 2),
            else_=3
        ),
        QueueEntry.checked_in_at.asc()
    ).all()

    # Metrics
    total_checked_in_today = QueueEntry.query.filter(QueueEntry.checked_in_at >= today_start).count()
    waiting_count = len([q for q in active_queue if q.status == 'waiting'])
    emergency_count = len([q for q in active_queue if q.priority in ['emergency', 'urgent']])
    
    # Today's Appointments
    today_appointments = Appointment.query.filter(
        Appointment.scheduled_date == date.today()
    ).order_by(Appointment.scheduled_time.asc()).all()

    # Recent Registrations
    recent_patients = Patient.query.order_by(Patient.created_at.desc()).limit(6).all()

    return render_template(
        'reception/dashboard.html',
        active_queue=active_queue,
        total_checked_in_today=total_checked_in_today,
        waiting_count=waiting_count,
        emergency_count=emergency_count,
        today_appointments=today_appointments,
        recent_patients=recent_patients,
        current_date=date.today().strftime('%A, %d %B %Y')
    )

@reception_bp.route('/quick-search')
def quick_search():
    query = request.args.get('q', '').strip()
    if not query or len(query) < 1:
        return render_template('reception/partials/search_results.html', patients=[], query=query)

    search_term = f"%{query}%"
    patients = Patient.query.filter(
        or_(
            Patient.full_name.ilike(search_term),
            Patient.hospital_id.ilike(search_term),
            Patient.phone.ilike(search_term),
            Patient.national_id.ilike(search_term)
        )
    ).order_by(Patient.created_at.desc()).limit(8).all()

    return render_template('reception/partials/search_results.html', patients=patients, query=query)

@reception_bp.route('/search')
def search():
    query = request.args.get('q', '').strip()
    payer_filter = request.args.get('payer', 'all').strip()
    gender_filter = request.args.get('gender', 'all').strip()
    sort_by = request.args.get('sort', 'recent').strip()
    is_htmx = request.headers.get('HX-Request') == 'true'

    # If an HTMX request comes from the quick search bar targeting a dropdown
    target = request.headers.get('HX-Target', '')
    if target in ['search-results', 'header-search-results', 'quick-search-results']:
        return quick_search()

    # Base patient query for Directory
    patient_query = Patient.query

    # Search filter
    if query:
        search_term = f"%{query}%"
        patient_query = patient_query.filter(
            or_(
                Patient.full_name.ilike(search_term),
                Patient.hospital_id.ilike(search_term),
                Patient.phone.ilike(search_term),
                Patient.national_id.ilike(search_term)
            )
        )

    # Payer filter
    if payer_filter in ['Cash', 'Insurance', 'Corporate']:
        patient_query = patient_query.filter(Patient.primary_payer == payer_filter)

    # Gender filter
    if gender_filter in ['Male', 'Female', 'Other']:
        patient_query = patient_query.filter(Patient.gender == gender_filter)

    # Sorting
    if sort_by == 'name':
        patient_query = patient_query.order_by(Patient.full_name.asc())
    elif sort_by == 'id':
        patient_query = patient_query.order_by(Patient.hospital_id.asc())
    else:
        patient_query = patient_query.order_by(Patient.created_at.desc())

    patients = patient_query.limit(100).all()

    # Overall Directory Stats
    today_start = datetime.combine(date.today(), datetime.min.time())
    total_patients = Patient.query.count()
    insured_count = Patient.query.filter(Patient.primary_payer.in_(['Insurance', 'Corporate'])).count()
    today_registered = Patient.query.filter(Patient.created_at >= today_start).count()

    # Only return table partial if specifically targeting the table container
    if is_htmx and target == 'directory-table-container':
        return render_template(
            'reception/partials/directory_table.html', 
            patients=patients, 
            query=query, 
            payer=payer_filter,
            gender=gender_filter,
            sort=sort_by,
            total_count=len(patients)
        )

    return render_template(
        'reception/search_page.html', 
        patients=patients, 
        query=query,
        payer=payer_filter,
        gender=gender_filter,
        sort=sort_by,
        total_patients=total_patients,
        insured_count=insured_count,
        today_registered=today_registered,
        results_count=len(patients)
    )


@reception_bp.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        first_name = request.form.get('first_name', '').strip()
        last_name = request.form.get('last_name', '').strip()
        phone = request.form.get('phone', '').strip()
        dob_str = request.form.get('date_of_birth', '').strip()
        gender = request.form.get('gender', 'Male').strip()
        national_id = request.form.get('national_id', '').strip() or None
        blood_group = request.form.get('blood_group', '').strip() or None
        allergies = request.form.get('allergies', '').strip() or None
        residential_address = request.form.get('residential_address', '').strip() or None
        
        # Payer / Insurance
        primary_payer = request.form.get('primary_payer', 'Cash').strip()
        insurance_company = request.form.get('insurance_company', '').strip() or None
        insurance_policy_number = request.form.get('insurance_policy_number', '').strip() or None

        # Next of Kin
        next_of_kin_name = request.form.get('next_of_kin_name', '').strip()
        next_of_kin_phone = request.form.get('next_of_kin_phone', '').strip()
        next_of_kin_relation = request.form.get('next_of_kin_relation', 'Spouse').strip()

        # Immediate Check-in checkbox
        auto_checkin = request.form.get('auto_checkin') == 'on'
        priority = request.form.get('checkin_priority', 'normal')
        department = request.form.get('checkin_department', 'General OPD')
        chief_complaint = request.form.get('chief_complaint', '').strip()

        # Basic Validation
        if not first_name or not last_name or not phone or not dob_str or not next_of_kin_name or not next_of_kin_phone:
            flash("Please fill in all mandatory registration fields (Name, Phone, DOB, Next of Kin).", "error")
            return render_template('reception/register.html', form_data=request.form)

        dob = parse_dob(dob_str)
        if not dob:
            flash("Invalid Date of Birth format. Please use YYYY-MM-DD.", "error")
            return render_template('reception/register.html', form_data=request.form)

        # Check for photo payload (webcam base64 or file upload)
        webcam_data = request.form.get('webcam_image')
        uploaded_file = request.files.get('photo_file')
        photo_payload = webcam_data if (webcam_data and webcam_data.startswith('data:image')) else uploaded_file
        
        photo_filename = save_webcam_or_uploaded_photo(
            photo_payload, 
            current_app.config['UPLOAD_FOLDER']
        )

        full_name = f"{first_name} {last_name}"
        hospital_id = Patient.generate_hospital_id(db.session)

        new_patient = Patient(
            hospital_id=hospital_id,
            first_name=first_name,
            last_name=last_name,
            full_name=full_name,
            national_id=national_id,
            phone=phone,
            date_of_birth=dob,
            gender=gender,
            blood_group=blood_group,
            allergies=allergies,
            residential_address=residential_address,
            primary_payer=primary_payer,
            insurance_company=insurance_company,
            insurance_policy_number=insurance_policy_number,
            next_of_kin_name=next_of_kin_name,
            next_of_kin_phone=next_of_kin_phone,
            next_of_kin_relation=next_of_kin_relation,
            photo_filename=photo_filename
        )

        db.session.add(new_patient)
        db.session.flush()  # assign new_patient.id

        # If staff opted for instant check-in
        ticket_number = None
        if auto_checkin:
            ticket_number = QueueEntry.generate_daily_ticket(db.session)
            queue_entry = QueueEntry(
                ticket_number=ticket_number,
                patient_id=new_patient.id,
                stage='triage',
                priority=priority,
                status='waiting',
                chief_complaint=chief_complaint,
                destination_department=department
            )
            db.session.add(queue_entry)

        db.session.commit()

        if auto_checkin:
            flash(f"Patient {full_name} registered ({hospital_id}) & queued as {ticket_number} [{priority.upper()}].", "success")
        else:
            flash(f"Patient {full_name} registered successfully with ID: {hospital_id}.", "success")

        return redirect(url_for('reception.patient_detail', patient_id=new_patient.id))

    # Pre-calculate next hospital ID for display
    preview_id = Patient.generate_hospital_id(db.session)
    return render_template('reception/register.html', preview_id=preview_id, form_data={})

@reception_bp.route('/patients/<int:patient_id>')
def patient_detail(patient_id):
    patient = Patient.query.get_or_404(patient_id)
    today_start = datetime.combine(date.today(), datetime.min.time())
    
    # Check if patient already has active queue ticket today
    active_ticket = QueueEntry.query.filter(
        QueueEntry.patient_id == patient.id,
        QueueEntry.checked_in_at >= today_start,
        QueueEntry.status.in_(['waiting', 'in_progress'])
    ).first()

    return render_template(
        'reception/patient_detail.html',
        patient=patient,
        active_ticket=active_ticket
    )

@reception_bp.route('/patients/<int:patient_id>/edit', methods=['GET', 'POST'])
def edit_patient(patient_id):
    patient = Patient.query.get_or_404(patient_id)
    
    if request.method == 'POST':
        patient.first_name = request.form.get('first_name', patient.first_name).strip()
        patient.last_name = request.form.get('last_name', patient.last_name).strip()
        patient.full_name = f"{patient.first_name} {patient.last_name}"
        patient.phone = request.form.get('phone', patient.phone).strip()
        patient.gender = request.form.get('gender', patient.gender).strip()
        patient.national_id = request.form.get('national_id', '').strip() or None
        patient.blood_group = request.form.get('blood_group', '').strip() or None
        patient.allergies = request.form.get('allergies', '').strip() or None
        patient.residential_address = request.form.get('residential_address', '').strip() or None
        
        dob_str = request.form.get('date_of_birth')
        if dob_str:
            parsed = parse_dob(dob_str)
            if parsed:
                patient.date_of_birth = parsed

        patient.primary_payer = request.form.get('primary_payer', patient.primary_payer).strip()
        patient.insurance_company = request.form.get('insurance_company', '').strip() or None
        patient.insurance_policy_number = request.form.get('insurance_policy_number', '').strip() or None

        patient.next_of_kin_name = request.form.get('next_of_kin_name', patient.next_of_kin_name).strip()
        patient.next_of_kin_phone = request.form.get('next_of_kin_phone', patient.next_of_kin_phone).strip()
        patient.next_of_kin_relation = request.form.get('next_of_kin_relation', patient.next_of_kin_relation).strip()

        # Update photo if new one provided
        webcam_data = request.form.get('webcam_image')
        uploaded_file = request.files.get('photo_file')
        photo_payload = webcam_data if (webcam_data and webcam_data.startswith('data:image')) else uploaded_file
        
        if photo_payload:
            new_photo = save_webcam_or_uploaded_photo(photo_payload, current_app.config['UPLOAD_FOLDER'])
            if new_photo:
                patient.photo_filename = new_photo

        db.session.commit()
        flash(f"Patient records for {patient.full_name} updated successfully.", "success")
        return redirect(url_for('reception.patient_detail', patient_id=patient.id))

    return render_template('reception/edit_patient.html', patient=patient)

@reception_bp.route('/patients/<int:patient_id>/print-card')
def print_card(patient_id):
    patient = Patient.query.get_or_404(patient_id)
    return render_template(
        'reception/card_print.html', 
        patient=patient,
        facility=current_app.config
    )

@reception_bp.route('/checkin/<int:patient_id>', methods=['GET', 'POST'])
def checkin(patient_id):
    patient = Patient.query.get_or_404(patient_id)
    is_htmx = request.headers.get('HX-Request') == 'true'
    today_start = datetime.combine(date.today(), datetime.min.time())

    # Check if already in queue
    existing_ticket = QueueEntry.query.filter(
        QueueEntry.patient_id == patient.id,
        QueueEntry.checked_in_at >= today_start,
        QueueEntry.status.in_(['waiting', 'in_progress'])
    ).first()

    if request.method == 'POST':
        priority = request.form.get('priority', 'normal').strip()
        department = request.form.get('destination_department', 'General OPD').strip()
        chief_complaint = request.form.get('chief_complaint', '').strip()
        assigned_doctor = request.form.get('assigned_doctor', '').strip() or None

        if existing_ticket:
            msg = f"Patient {patient.full_name} already has an active queue ticket: {existing_ticket.ticket_number}."
            if is_htmx:
                return render_template('reception/partials/checkin_modal.html', patient=patient, active_ticket=existing_ticket, error=msg)
            flash(msg, "warning")
            return redirect(url_for('reception.dashboard'))

        ticket_number = QueueEntry.generate_daily_ticket(db.session)
        queue_entry = QueueEntry(
            ticket_number=ticket_number,
            patient_id=patient.id,
            stage='triage',
            priority=priority,
            status='waiting',
            chief_complaint=chief_complaint,
            destination_department=department,
            assigned_doctor=assigned_doctor
        )
        db.session.add(queue_entry)

        # Mark any scheduled appointment today as checked-in
        app_today = Appointment.query.filter(
            Appointment.patient_id == patient.id,
            Appointment.scheduled_date == date.today(),
            Appointment.status == 'scheduled'
        ).first()
        if app_today:
            app_today.status = 'checked_in'

        db.session.commit()

        success_msg = f"Checked in {patient.full_name} as {ticket_number} ({priority.upper()})."
        
        if is_htmx:
            # Refresh queue table directly
            active_queue = QueueEntry.query.filter(
                QueueEntry.checked_in_at >= today_start,
                QueueEntry.status.in_(['waiting', 'in_progress'])
            ).order_by(QueueEntry.checked_in_at.asc()).all()
            
            response = render_template('reception/partials/checkin_success.html', patient=patient, queue_entry=queue_entry)
            # Send HX-Trigger to notify other components to refresh
            return response, 200, {'HX-Trigger': 'queueUpdated'}

        flash(success_msg, "success")
        return redirect(url_for('reception.dashboard'))

    # GET request - return modal / form partial
    if is_htmx:
        return render_template(
            'reception/partials/checkin_modal.html', 
            patient=patient, 
            active_ticket=existing_ticket
        )

    return render_template(
        'reception/checkin_page.html', 
        patient=patient, 
        active_ticket=existing_ticket
    )

@reception_bp.route('/queue/live')
def live_queue():
    is_htmx = request.headers.get('HX-Request') == 'true'
    status_filter = request.args.get('status', 'active')
    today_start = datetime.combine(date.today(), datetime.min.time())

    query = QueueEntry.query.filter(QueueEntry.checked_in_at >= today_start)
    if status_filter == 'active':
        query = query.filter(QueueEntry.status.in_(['waiting', 'in_progress']))
    elif status_filter in ['waiting', 'in_progress', 'completed', 'cancelled']:
        query = query.filter(QueueEntry.status == status_filter)

    queue_entries = query.order_by(
        db.case(
            (QueueEntry.priority == 'emergency', 1),
            (QueueEntry.priority == 'urgent', 2),
            else_=3
        ),
        QueueEntry.checked_in_at.asc()
    ).all()

    target = request.headers.get('HX-Target', '')
    if is_htmx and target == 'queue-table-container':
        return render_template('reception/partials/queue_table.html', queue_entries=queue_entries, filter=status_filter)

    return render_template('reception/queue_full.html', queue_entries=queue_entries, filter=status_filter)

@reception_bp.route('/queue/<int:queue_id>/cancel', methods=['POST'])
def cancel_queue(queue_id):
    entry = QueueEntry.query.get_or_404(queue_id)
    entry.status = 'cancelled'
    entry.completed_at = datetime.utcnow()
    db.session.commit()

    is_htmx = request.headers.get('HX-Request') == 'true'
    if is_htmx:
        today_start = datetime.combine(date.today(), datetime.min.time())
        active_queue = QueueEntry.query.filter(
            QueueEntry.checked_in_at >= today_start,
            QueueEntry.status.in_(['waiting', 'in_progress'])
        ).order_by(QueueEntry.checked_in_at.asc()).all()
        return render_template('reception/partials/queue_table.html', queue_entries=active_queue, filter='active')

    flash(f"Ticket {entry.ticket_number} cancelled.", "info")
    return redirect(url_for('reception.dashboard'))

@reception_bp.route('/appointments', methods=['GET', 'POST'])
def appointments():
    """
    Reception Appointments Hub:
    - Doctor Availability, Shifts & Slot Capacity Matrix
    - Interactive Booking Engine with Auto-Numbering
    - Multi-Channel Reminders (SMS & WhatsApp dispatch)
    - Cancellation & Rescheduling Governance
    - 1-Click Fast-Track Queue Check-In
    """
    selected_date_str = request.args.get('date', date.today().strftime('%Y-%m-%d'))
    status_filter = request.args.get('status', 'all')
    doctor_filter = request.args.get('doctor', 'all')

    try:
        filter_date = datetime.strptime(selected_date_str, '%Y-%m-%d').date()
    except ValueError:
        filter_date = date.today()

    if request.method == 'POST':
        patient_id = request.form.get('patient_id', type=int)
        scheduled_date_str = request.form.get('scheduled_date', '').strip()
        scheduled_time = request.form.get('scheduled_time', '').strip()
        department = request.form.get('department', 'General OPD').strip()
        doctor_name = request.form.get('doctor_name', '').strip() or None
        reason = request.form.get('reason', '').strip()

        if not patient_id or not scheduled_date_str or not scheduled_time:
            flash("Please specify a patient, date, and time slot for the appointment.", "error")
            return redirect(url_for('reception.appointments', date=selected_date_str))

        parsed_date = parse_dob(scheduled_date_str)
        if not parsed_date:
            flash("Invalid appointment date format.", "error")
            return redirect(url_for('reception.appointments', date=selected_date_str))

        patient = Patient.query.get(patient_id)
        if not patient:
            flash("Patient record not found.", "error")
            return redirect(url_for('reception.appointments', date=selected_date_str))

        # Check doctor slot capacity if doctor specified
        if doctor_name:
            doc_schedule = DoctorSchedule.query.filter_by(doctor_name=doctor_name).first()
            if doc_schedule:
                current_booked = Appointment.query.filter(
                    Appointment.doctor_name == doctor_name,
                    Appointment.scheduled_date == parsed_date,
                    Appointment.status.in_(['scheduled', 'confirmed', 'checked_in'])
                ).count()
                if current_booked >= doc_schedule.max_patients_per_day:
                    flash(f"Slot capacity reached! {doctor_name} already has {current_booked}/{doc_schedule.max_patients_per_day} patients booked on {parsed_date}.", "error")
                    return redirect(url_for('reception.appointments', date=selected_date_str))

        new_app = Appointment(
            appointment_number=Appointment.generate_appointment_number(db.session),
            patient_id=patient.id,
            scheduled_date=parsed_date,
            scheduled_time=scheduled_time,
            department=department,
            doctor_name=doctor_name,
            reason=reason,
            status='scheduled'
        )
        db.session.add(new_app)
        db.session.commit()

        AuditLog.log_event(
            'appointment_booked',
            'appointment',
            new_app.id,
            f"Appointment {new_app.appointment_number} booked for {patient.full_name} with {doctor_name or 'General OPD'} on {parsed_date} at {scheduled_time}."
        )

        flash(f"Appointment {new_app.appointment_number} booked for {patient.full_name} on {parsed_date} at {scheduled_time}.", "success")
        return redirect(url_for('reception.appointments', date=parsed_date.strftime('%Y-%m-%d')))

    # Fetch appointments for the filtered date
    query = Appointment.query.filter(Appointment.scheduled_date == filter_date)
    if status_filter != 'all':
        query = query.filter(Appointment.status == status_filter)
    if doctor_filter != 'all':
        query = query.filter(Appointment.doctor_name == doctor_filter)

    day_appointments = query.order_by(Appointment.scheduled_time.asc()).all()

    # Upcoming appointments (next 7 days)
    upcoming_appointments = Appointment.query.filter(
        Appointment.scheduled_date > date.today(),
        Appointment.scheduled_date <= date.today() + timedelta(days=7),
        Appointment.status.in_(['scheduled', 'confirmed'])
    ).order_by(Appointment.scheduled_date.asc(), Appointment.scheduled_time.asc()).all()

    # Doctor Roster & Slot Capacity Matrix for the selected date
    all_schedules = DoctorSchedule.query.filter_by(is_available=True).all()
    today_start = datetime.combine(date.today(), datetime.min.time())
    
    doctor_capacity_cards = []
    for sched in all_schedules:
        booked_for_date = Appointment.query.filter(
            Appointment.doctor_name == sched.doctor_name,
            Appointment.scheduled_date == filter_date,
            Appointment.status.in_(['scheduled', 'confirmed', 'checked_in', 'completed'])
        ).count()

        # Live caseload today in waiting/consultation room
        live_caseload = QueueEntry.query.filter(
            QueueEntry.assigned_doctor == sched.doctor_name,
            QueueEntry.checked_in_at >= today_start,
            QueueEntry.status.in_(['waiting', 'in_progress'])
        ).count()

        remaining_slots = max(0, sched.max_patients_per_day - booked_for_date)
        is_full = booked_for_date >= sched.max_patients_per_day

        doctor_capacity_cards.append({
            'schedule': sched,
            'booked_count': booked_for_date,
            'max_capacity': sched.max_patients_per_day,
            'remaining_slots': remaining_slots,
            'is_full': is_full,
            'live_caseload': live_caseload
        })

    all_patients = Patient.query.order_by(Patient.full_name.asc()).all()
    selected_patient_id = request.args.get('patient_id', type=int)

    # Key metrics
    total_day_appointments = len(day_appointments)
    confirmed_count = sum(1 for a in day_appointments if a.status == 'confirmed')
    checked_in_count = sum(1 for a in day_appointments if a.status == 'checked_in')
    cancelled_count = sum(1 for a in day_appointments if a.status == 'cancelled')

    return render_template(
        'reception/appointments.html',
        filter_date=filter_date,
        day_appointments=day_appointments,
        upcoming_appointments=upcoming_appointments,
        doctor_capacity_cards=doctor_capacity_cards,
        all_patients=all_patients,
        selected_patient_id=selected_patient_id,
        status_filter=status_filter,
        doctor_filter=doctor_filter,
        total_day_appointments=total_day_appointments,
        confirmed_count=confirmed_count,
        checked_in_count=checked_in_count,
        cancelled_count=cancelled_count,
        today=date.today(),
        prev_date=filter_date - timedelta(days=1),
        next_date=filter_date + timedelta(days=1)
    )


@reception_bp.route('/appointments/<int:appointment_id>/confirm', methods=['POST'])
def confirm_appointment(appointment_id):
    app_entry = Appointment.query.get_or_404(appointment_id)
    app_entry.status = 'confirmed'
    db.session.commit()
    flash(f"Appointment {app_entry.appointment_number or app_entry.id} confirmed for {app_entry.patient.full_name}.", "success")
    return redirect(url_for('reception.appointments', date=app_entry.scheduled_date.strftime('%Y-%m-%d')))


@reception_bp.route('/appointments/<int:appointment_id>/cancel', methods=['POST'])
def cancel_appointment(appointment_id):
    app_entry = Appointment.query.get_or_404(appointment_id)
    reason = request.form.get('cancellation_reason', 'Patient requested cancellation').strip()
    
    app_entry.status = 'cancelled'
    app_entry.cancellation_reason = reason
    app_entry.cancelled_at = datetime.utcnow()
    app_entry.cancelled_by = 'Reception Desk'
    db.session.commit()

    AuditLog.log_event(
        'appointment_cancelled',
        'appointment',
        app_entry.id,
        f"Appointment {app_entry.appointment_number or app_entry.id} cancelled. Reason: {reason}",
        severity='warning'
    )
    flash(f"Appointment cancelled for {app_entry.patient.full_name}.", "info")
    return redirect(url_for('reception.appointments', date=app_entry.scheduled_date.strftime('%Y-%m-%d')))


@reception_bp.route('/appointments/<int:appointment_id>/send-reminder', methods=['POST'])
def send_appointment_reminder(appointment_id):
    """
    Multi-Channel Reminder Engine: Dispatches simulated SMS & WhatsApp reminders.
    """
    app_entry = Appointment.query.get_or_404(appointment_id)
    channel = request.form.get('channel', 'both')  # 'sms', 'whatsapp', 'both'
    patient = app_entry.patient

    app_entry.last_reminder_at = datetime.utcnow()
    if channel in ['sms', 'both']:
        app_entry.reminder_sent_sms = True
    if channel in ['whatsapp', 'both']:
        app_entry.reminder_sent_whatsapp = True

    AuditLog.log_event(
        'appointment_reminder_dispatched',
        'appointment',
        app_entry.id,
        f"Dispatched {channel.upper()} reminder to {patient.phone} for appointment on {app_entry.scheduled_date} at {app_entry.scheduled_time}."
    )
    db.session.commit()

    msg = f"✓ Reminder successfully sent to {patient.full_name} ({patient.phone}) via {channel.upper()}!"
    flash(msg, "success")
    return redirect(url_for('reception.appointments', date=app_entry.scheduled_date.strftime('%Y-%m-%d')))


@reception_bp.route('/appointments/<int:appointment_id>/checkin', methods=['POST'])
def checkin_from_appointment(appointment_id):
    app_entry = Appointment.query.get_or_404(appointment_id)
    patient = app_entry.patient

    today_start = datetime.combine(date.today(), datetime.min.time())
    existing_ticket = QueueEntry.query.filter(
        QueueEntry.patient_id == patient.id,
        QueueEntry.checked_in_at >= today_start,
        QueueEntry.status.in_(['waiting', 'in_progress'])
    ).first()

    if existing_ticket:
        flash(f"Patient {patient.full_name} is already in the queue ({existing_ticket.ticket_number}).", "warning")
        return redirect(url_for('reception.appointments', date=app_entry.scheduled_date.strftime('%Y-%m-%d')))

    ticket_number = QueueEntry.generate_daily_ticket(db.session)
    queue_entry = QueueEntry(
        ticket_number=ticket_number,
        patient_id=patient.id,
        stage='triage',
        priority='normal',
        status='waiting',
        chief_complaint=f"Booked Appointment: {app_entry.reason or 'Consultation'}",
        destination_department=app_entry.department,
        assigned_doctor=app_entry.doctor_name
    )
    db.session.add(queue_entry)
    app_entry.status = 'checked_in'
    db.session.commit()

    AuditLog.log_event(
        'appointment_checked_in',
        'appointment',
        app_entry.id,
        f"Checked in patient {patient.full_name} from appointment {app_entry.appointment_number or app_entry.id} as ticket {ticket_number} (Assigned: {app_entry.doctor_name or 'General OPD'})."
    )

    flash(f"Checked in {patient.full_name} from appointment as ticket {ticket_number}.", "success")
    return redirect(url_for('reception.dashboard'))

