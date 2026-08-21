import os
import json
import time
from datetime import datetime, date, timedelta
from flask import Flask, redirect, url_for, session, request, flash, send_from_directory
from config import Config
from models import (
    db, Patient, QueueEntry, Appointment, VitalsRecord,
    ConsultationNote, LabOrder, Prescription, BillingItem,
    MedicationItem, DrugBatch, DispensationRecord, StockTransaction,
    Invoice, Payment, ShiftRegister, User, AuditLog,
    Ward, Bed, Admission, BedTransfer, NursingNote, WardRoundNote,
    SecuritySetting, Permission, RolePermission, ClinicalDocument
)
from auth import auth_bp
from reception import reception_bp
from triage import triage_bp
from doctor import doctor_bp
from pharmacy import pharmacy_bp
from billing import billing_bp
from admin import admin_bp
from inpatient import inpatient_bp

def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)

    # Ensure upload folders exist
    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
    os.makedirs(os.path.join(app.root_path, 'static', 'uploads', 'documents'), exist_ok=True)
    os.makedirs(os.path.join(app.root_path, 'static', 'dist'), exist_ok=True)
    os.makedirs(os.path.join(app.root_path, 'static', 'js'), exist_ok=True)
    os.makedirs(os.path.join(app.root_path, 'static', 'images'), exist_ok=True)

    # Initialize extensions
    db.init_app(app)

    # Register blueprints
    app.register_blueprint(auth_bp)
    app.register_blueprint(reception_bp)
    app.register_blueprint(triage_bp)
    app.register_blueprint(doctor_bp)
    app.register_blueprint(pharmacy_bp)
    app.register_blueprint(billing_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(inpatient_bp)

    # Sliding Session Inactivity Middleware
    @app.before_request
    def enforce_session_security():
        # Exclude static assets and authentication endpoints
        if request.endpoint and (request.endpoint.startswith('static') or request.endpoint.startswith('auth.')):
            return

        if 'user_id' in session:
            now_ts = time.time()
            last_active = session.get('last_active', now_ts)
            
            try:
                settings = SecuritySetting.get_settings()
                timeout_seconds = (settings.session_timeout_minutes or 30) * 60
            except Exception:
                timeout_seconds = 1800

            if (now_ts - last_active) > timeout_seconds:
                user_portal = session.get('portal', 'reception')
                from auth.decorators import logout_user
                logout_user()
                flash('Your clinical session has expired due to inactivity. Please sign in again.', 'warning')
                return redirect(url_for('auth.login', portal=user_portal))
            
            # Renew sliding activity timestamp
            session['last_active'] = now_ts

    @app.route('/')
    def index():
        from auth.decorators import is_authenticated, get_current_user
        if is_authenticated():
            user = get_current_user()
            if user:
                if user.role == 'admin':
                    return redirect(url_for('admin.dashboard'))
                elif user.portal == 'doctor':
                    return redirect(url_for('doctor.dashboard'))
                elif user.portal == 'triage':
                    return redirect(url_for('triage.dashboard'))
                elif user.portal == 'inpatient':
                    return redirect(url_for('inpatient.dashboard'))
                elif user.portal == 'pharmacy':
                    return redirect(url_for('pharmacy.dashboard'))
                elif user.portal == 'billing':
                    return redirect(url_for('billing.pos'))
                else:
                    return redirect(url_for('reception.dashboard'))
        return redirect(url_for('auth.login', portal='reception'))

    # Universal Document Viewer & Streamer
    @app.route('/documents/view/<int:doc_id>')
    def view_document(doc_id):
        doc = ClinicalDocument.query.get_or_404(doc_id)
        if doc.file_path:
            file_dir = os.path.join(app.root_path, 'static')
            return send_from_directory(file_dir, doc.file_path)
        elif doc.document_type == 'medical_certificate':
            return redirect(url_for('doctor.print_medical_certificate', patient_id=doc.patient_id, doc_id=doc.id))
        elif doc.document_type == 'referral_letter':
            return redirect(url_for('doctor.print_referral_letter', patient_id=doc.patient_id, doc_id=doc.id))
        elif doc.document_type == 'discharge_summary' and doc.admission_id:
            return redirect(url_for('inpatient.print_discharge_summary', admission_id=doc.admission_id))
        flash('This document has no uploaded file attachment.', 'info')
        return redirect(request.referrer or url_for('doctor.dashboard'))

    def get_network_base_url():
        """Detect LAN IP / base URL for network sharing of onboarding links."""
        env_base = os.getenv('HMS_BASE_URL')
        if env_base:
            return env_base.rstrip('/')
        
        # Check if host in current request is already a network domain/IP
        try:
            from flask import request as req
            host = req.host
            if host and not host.startswith(('127.0.0.1', 'localhost')):
                scheme = req.scheme or 'http'
                return f"{scheme}://{host}"
        except Exception:
            pass
        
        # Auto-detect machine LAN IP on the local network (e.g. 192.168.x.x)
        import socket
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(('8.8.8.8', 80))
            lan_ip = s.getsockname()[0]
        except Exception:
            lan_ip = '127.0.0.1'
        finally:
            s.close()
        
        port = 5000
        try:
            from flask import request as req
            if req and req.host and ':' in req.host:
                port = req.host.split(':')[1]
        except Exception:
            pass

        return f"http://{lan_ip}:{port}"

    # Context processors for global template helpers
    @app.context_processor
    def inject_global_data():
        today_start = datetime.combine(date.today(), datetime.min.time())
        try:
            waiting_count = QueueEntry.query.filter(
                QueueEntry.checked_in_at >= today_start,
                QueueEntry.status == 'waiting'
            ).count()
            triage_waiting_count = QueueEntry.query.filter(
                QueueEntry.checked_in_at >= today_start,
                QueueEntry.stage == 'triage',
                QueueEntry.status.in_(['waiting', 'in_progress'])
            ).count()
            consultation_waiting_count = QueueEntry.query.filter(
                QueueEntry.checked_in_at >= today_start,
                QueueEntry.stage == 'consultation',
                QueueEntry.status.in_(['waiting', 'in_progress'])
            ).count()
            pharmacy_waiting_count = Prescription.query.filter(
                Prescription.status.in_(['pending_dispense', 'partially_dispensed'])
            ).count()
            unpaid_invoices_count = Invoice.query.filter(
                Invoice.status.in_(['unpaid', 'partially_paid'])
            ).count()
            today_app_count = Appointment.query.filter(
                Appointment.scheduled_date == date.today()
            ).count()
        except Exception:
            waiting_count = 0
            triage_waiting_count = 0
            consultation_waiting_count = 0
            pharmacy_waiting_count = 0
            unpaid_invoices_count = 0
            today_app_count = 0

        def get_user_onboarding_url(target_user):
            token = target_user.get_2fa_onboarding_token(app.config['SECRET_KEY'])
            base = get_network_base_url()
            return f"{base}/auth/onboard-2fa/{token}"

        return {
            'now': datetime.utcnow(),
            'today': date.today(),
            'facility_name': app.config.get('FACILITY_NAME', 'Apex Regional Medical Center'),
            'facility_code': app.config.get('FACILITY_CODE', 'HSP-2026'),
            'global_waiting_count': waiting_count,
            'global_triage_waiting': triage_waiting_count,
            'global_waiting_consultation': consultation_waiting_count,
            'global_pharmacy_waiting': pharmacy_waiting_count,
            'global_unpaid_invoices': unpaid_invoices_count,
            'global_today_app_count': today_app_count,
            'get_user_onboarding_url': get_user_onboarding_url,
            'network_base_url': get_network_base_url()
        }

    # Custom Jinja filters
    @app.template_filter('datetime_format')
    def datetime_format_filter(value, format='%d %b %Y, %H:%M'):
        if not value:
            return '-'
        return value.strftime(format)

    @app.template_filter('date_format')
    def date_format_filter(value, format='%d %b %Y'):
        if not value:
            return '-'
        return value.strftime(format)

    with app.app_context():
        upgrade_db_schema()
        db.create_all()
        seed_initial_data()

    return app

def upgrade_db_schema():
    """
    Ensures missing columns in existing SQLite tables are dynamically added without data loss.
    """
    with db.engine.connect() as conn:
        # Check users table
        try:
            res = conn.execute(db.text("PRAGMA table_info(users)"))
            cols = {row[1] for row in res.fetchall()}
            if cols:
                user_alterations = [
                    ("is_2fa_enabled", "BOOLEAN DEFAULT 0"),
                    ("totp_secret", "VARCHAR(64)"),
                    ("backup_codes_json", "TEXT"),
                    ("failed_login_attempts", "INTEGER DEFAULT 0"),
                    ("locked_until", "DATETIME"),
                    ("password_changed_at", "DATETIME"),
                    ("force_password_change", "BOOLEAN DEFAULT 0"),
                    ("last_activity_at", "DATETIME"),
                    ("custom_permissions_json", "TEXT")
                ]
                for col_name, col_type in user_alterations:
                    if col_name not in cols:
                        conn.execute(db.text(f"ALTER TABLE users ADD COLUMN {col_name} {col_type}"))
                        conn.commit()
        except Exception:
            pass

        # Check audit_logs table
        try:
            res = conn.execute(db.text("PRAGMA table_info(audit_logs)"))
            cols = {row[1] for row in res.fetchall()}
            if cols:
                audit_alterations = [
                    ("ip_address", "VARCHAR(64)"),
                    ("user_agent", "VARCHAR(255)"),
                    ("severity", "VARCHAR(30) DEFAULT 'info'"),
                    ("details_json", "TEXT")
                ]
                for col_name, col_type in audit_alterations:
                    if col_name not in cols:
                        conn.execute(db.text(f"ALTER TABLE audit_logs ADD COLUMN {col_name} {col_type}"))
                        conn.commit()
        except Exception:
            pass

def seed_initial_data():
    """
    Seeds initial realistic clinical staff user accounts, patient records, queue entries,
    historical vitals, EMR encounters, Pharmacy inventory with FEFO batches, and Billing folios.
    """
    today_start = datetime.combine(date.today(), datetime.min.time())

    # 0. Seed or Sync Clinical Staff User Accounts
    users_seed = [
        {
            "username": "reception",
            "password": "Reception@2026",
            "full_name": "Mary Wanjiku",
            "staff_id": "STF-REC-01",
            "role": "receptionist",
            "portal": "reception",
            "department": "Patient Registration & Intake Unit",
            "email": "reception@apexmedical.org",
            "phone": "+254 711 000 001"
        },
        {
            "username": "nurse",
            "password": "Triage@2026",
            "full_name": "Nurse Mercy Akinyi",
            "staff_id": "STF-TRG-01",
            "role": "nurse",
            "portal": "triage",
            "department": "Clinical Triage & Emergency Assessment",
            "email": "nurse.mercy@apexmedical.org",
            "phone": "+254 722 000 002"
        },
        {
            "username": "doctor",
            "password": "Doctor@2026",
            "full_name": "Dr. Sarah Kamau",
            "staff_id": "STF-DOC-01",
            "role": "doctor",
            "portal": "doctor",
            "department": "General Outpatient & Clinical EMR",
            "email": "dr.kamau@apexmedical.org",
            "phone": "+254 733 000 003"
        },
        {
            "username": "pharmacy",
            "password": "Pharm@2026",
            "full_name": "Pharm. Evans Omondi",
            "staff_id": "STF-PHM-01",
            "role": "pharmacist",
            "portal": "pharmacy",
            "department": "Central Pharmacy & Dispensation",
            "email": "pharm.evans@apexmedical.org",
            "phone": "+254 744 000 004"
        },
        {
            "username": "cashier",
            "password": "Billing@2026",
            "full_name": "Cashier Joyce Wambui",
            "staff_id": "STF-BIL-01",
            "role": "cashier",
            "portal": "billing",
            "department": "Revenue Operations & POS Settlement",
            "email": "cashier.joyce@apexmedical.org",
            "phone": "+254 755 000 005"
        },
        {
            "username": "nurse_ward",
            "password": "Ward@2026",
            "full_name": "Nurse Joyce Chebet",
            "staff_id": "STF-WRD-01",
            "role": "nurse",
            "portal": "inpatient",
            "department": "Inpatient Admissions & Ward Services",
            "email": "nurse.joyce@apexmedical.org",
            "phone": "+254 766 000 006"
        },
        {
            "username": "admin",
            "password": "Admin@2026",
            "full_name": "Dr. Robert Odhiambo",
            "staff_id": "STF-ADM-00",
            "role": "admin",
            "portal": "all",
            "department": "Hospital Directorate & Executive",
            "email": "admin@apexmedical.org",
            "phone": "+254 700 000 000"
        }
    ]

    for u_data in users_seed:
        raw_password = u_data.pop("password")
        existing_user = User.query.filter_by(username=u_data["username"]).first()
        if not existing_user:
            user = User(**u_data)
            user.set_password(raw_password)
            db.session.add(user)
        else:
            existing_user.full_name = u_data["full_name"]
            existing_user.staff_id = u_data["staff_id"]
            existing_user.role = u_data["role"]
            existing_user.portal = u_data["portal"]
            existing_user.department = u_data["department"]
            existing_user.status = 'active'

    db.session.commit()
    print("Clinical staff user accounts verified and synchronized successfully.")

    # 1. Seed Pharmacy Inventory if empty
    if MedicationItem.query.count() == 0:
        medications_seed = [
            {
                "name": "Amoxicillin 500mg Capsules",
                "generic_name": "Amoxicillin",
                "category": "Antibiotic",
                "form": "Capsule",
                "strength": "500mg",
                "current_stock": 140,
                "reorder_level": 30,
                "unit_price": 30.0,
                "cost_price": 18.0,
                "location_shelf": "Shelf A-01",
                "batches": [
                    {"batch_number": "BAT-2026-081", "qty": 80, "exp_days": 25}, # Critical <30d
                    {"batch_number": "BAT-2026-094", "qty": 60, "exp_days": 240} # Safe
                ]
            },
            {
                "name": "Augmentin 625mg Tablets",
                "generic_name": "Amoxicillin / Clavulanate",
                "category": "Antibiotic",
                "form": "Tablet",
                "strength": "625mg",
                "current_stock": 18, # Low stock alert!
                "reorder_level": 25,
                "unit_price": 120.0,
                "cost_price": 85.0,
                "location_shelf": "Shelf A-02",
                "batches": [
                    {"batch_number": "BAT-2026-052", "qty": 18, "exp_days": 55} # Warning <60d
                ]
            },
            {
                "name": "Paracetamol 500mg Tablets",
                "generic_name": "Paracetamol",
                "category": "Analgesic & Antipyretic",
                "form": "Tablet",
                "strength": "500mg",
                "current_stock": 420,
                "reorder_level": 50,
                "unit_price": 10.0,
                "cost_price": 4.0,
                "location_shelf": "Shelf B-01",
                "batches": [
                    {"batch_number": "BAT-2026-011", "qty": 120, "exp_days": 80}, # Caution <90d
                    {"batch_number": "BAT-2026-065", "qty": 300, "exp_days": 360} # Safe
                ]
            },
            {
                "name": "Ibuprofen 400mg Tablets",
                "generic_name": "Ibuprofen",
                "category": "Analgesic & NSAID",
                "form": "Tablet",
                "strength": "400mg",
                "current_stock": 110,
                "reorder_level": 30,
                "unit_price": 15.0,
                "cost_price": 8.0,
                "location_shelf": "Shelf B-02",
                "batches": [
                    {"batch_number": "BAT-2026-044", "qty": 110, "exp_days": 300}
                ]
            },
            {
                "name": "Omeprazole 20mg Capsules",
                "generic_name": "Omeprazole",
                "category": "GI / Antacid",
                "form": "Capsule",
                "strength": "20mg",
                "current_stock": 85,
                "reorder_level": 25,
                "unit_price": 25.0,
                "cost_price": 14.0,
                "location_shelf": "Shelf C-01",
                "batches": [
                    {"batch_number": "BAT-2026-078", "qty": 85, "exp_days": 180}
                ]
            },
            {
                "name": "Metformin 500mg Tablets",
                "generic_name": "Metformin",
                "category": "Antidiabetic",
                "form": "Tablet",
                "strength": "500mg",
                "current_stock": 250,
                "reorder_level": 40,
                "unit_price": 15.0,
                "cost_price": 7.5,
                "location_shelf": "Shelf D-01",
                "batches": [
                    {"batch_number": "BAT-2026-033", "qty": 250, "exp_days": 420}
                ]
            },
            {
                "name": "Amlodipine 5mg Tablets",
                "generic_name": "Amlodipine",
                "category": "Antihypertensive",
                "form": "Tablet",
                "strength": "5mg",
                "current_stock": 160,
                "reorder_level": 30,
                "unit_price": 20.0,
                "cost_price": 10.0,
                "location_shelf": "Shelf D-02",
                "batches": [
                    {"batch_number": "BAT-2026-029", "qty": 160, "exp_days": 320}
                ]
            },
            {
                "name": "Cetirizine 10mg Tablets",
                "generic_name": "Cetirizine",
                "category": "Antihistamine",
                "form": "Tablet",
                "strength": "10mg",
                "current_stock": 70,
                "reorder_level": 20,
                "unit_price": 20.0,
                "cost_price": 9.0,
                "location_shelf": "Shelf E-01",
                "batches": [
                    {"batch_number": "BAT-2026-091", "qty": 70, "exp_days": 210}
                ]
            },
            {
                "name": "Coartem (Artemether/Lumefantrine 20/120)",
                "generic_name": "Artemether / Lumefantrine",
                "category": "Antimalarial",
                "form": "Tablet",
                "strength": "20/120mg",
                "current_stock": 12, # Low stock alert!
                "reorder_level": 20,
                "unit_price": 800.0,
                "cost_price": 550.0,
                "location_shelf": "Shelf F-01",
                "batches": [
                    {"batch_number": "BAT-2026-015", "qty": 12, "exp_days": 28} # Critical <30d
                ]
            }
        ]

        for m_data in medications_seed:
            batches_list = m_data.pop("batches")
            med = MedicationItem(**m_data)
            db.session.add(med)
            db.session.flush()

            for b_data in batches_list:
                exp_date = date.today() + timedelta(days=b_data["exp_days"])
                batch = DrugBatch(
                    medication_id=med.id,
                    batch_number=b_data["batch_number"],
                    quantity_received=b_data["qty"],
                    quantity_remaining=b_data["qty"],
                    expiry_date=exp_date,
                    supplier="Apex Central Medical Supplies",
                    status="active"
                )
                db.session.add(batch)
                db.session.flush()

                st = StockTransaction(
                    medication_id=med.id,
                    batch_id=batch.id,
                    transaction_type="restock",
                    quantity_change=b_data["qty"],
                    previous_stock=0,
                    new_stock=b_data["qty"],
                    notes="Initial inventory intake",
                    recorded_by="Pharm. Evans Omondi"
                )
                db.session.add(st)

        db.session.commit()

    # 2. Seed Initial Cashier Shift Register if none active
    if ShiftRegister.query.count() == 0:
        shift1 = ShiftRegister(
            shift_code="SHF-20260817-01",
            cashier_name="Cashier Joyce Wambui (Lead Cashier)",
            counter_number="POS-01",
            opened_at=datetime.utcnow() - timedelta(hours=4),
            opening_float=5000.0,
            cash_collected=4500.0,
            mpesa_collected=7800.0,
            insurance_billed=12500.0,
            card_collected=0.0,
            total_revenue=24800.0,
            status="open"
        )
        db.session.add(shift1)
        db.session.commit()

    # 3. Seed Patients and Outpatient workflow if empty
    if Patient.query.count() == 0:
        patients_data = [
            {
                "first_name": "James",
                "last_name": "Mwangi",
                "full_name": "James Mwangi",
                "national_id": "28491043",
                "phone": "0712 345 678",
                "date_of_birth": date(1986, 4, 12),
                "gender": "Male",
                "blood_group": "O+",
                "allergies": "Penicillin (Moderate rash)",
                "primary_payer": "Insurance",
                "insurance_company": "Jubilee Health Insurance",
                "insurance_policy_number": "JUB-882910-A",
                "next_of_kin_name": "Grace Mwangi",
                "next_of_kin_phone": "0723 456 789",
                "next_of_kin_relation": "Spouse",
                "residential_address": "House 14, Kilimani Ring Rd, Nairobi"
            },
            {
                "first_name": "Sarah",
                "last_name": "Achieng",
                "full_name": "Sarah Achieng",
                "national_id": "31904281",
                "phone": "0734 567 890",
                "date_of_birth": date(1994, 9, 23),
                "gender": "Female",
                "blood_group": "A+",
                "allergies": "None known",
                "primary_payer": "Cash",
                "next_of_kin_name": "David Achieng",
                "next_of_kin_phone": "0745 678 901",
                "next_of_kin_relation": "Parent",
                "residential_address": "Apex Court, Apt 3B, Parklands"
            },
            {
                "first_name": "Patrick",
                "last_name": "Kiprono",
                "full_name": "Patrick Kiprono",
                "national_id": "22910455",
                "phone": "0756 789 012",
                "date_of_birth": date(1978, 1, 15),
                "gender": "Male",
                "blood_group": "B+",
                "allergies": "Sulfonamides (Severe Anaphylaxis)",
                "primary_payer": "Insurance",
                "insurance_company": "Social Health Authority (SHA)",
                "insurance_policy_number": "SHA-902184-B",
                "next_of_kin_name": "Mary Kiprono",
                "next_of_kin_phone": "0767 890 123",
                "next_of_kin_relation": "Spouse",
                "residential_address": "Estate 4, Karen West, Nairobi"
            },
            {
                "first_name": "Fatima",
                "last_name": "Hassan",
                "full_name": "Fatima Hassan",
                "national_id": "35819024",
                "phone": "0778 901 234",
                "date_of_birth": date(2001, 11, 8),
                "gender": "Female",
                "blood_group": "O-",
                "allergies": "None known",
                "primary_payer": "Corporate",
                "insurance_company": "AAR Healthcare",
                "insurance_policy_number": "AAR-771029",
                "next_of_kin_name": "Omar Hassan",
                "next_of_kin_phone": "0789 012 345",
                "next_of_kin_relation": "Parent",
                "residential_address": "South C, Plainsview Rd, Block C"
            },
            {
                "first_name": "Ezekiel",
                "last_name": "Mutua",
                "full_name": "Ezekiel Mutua",
                "national_id": "18402911",
                "phone": "0790 123 456",
                "date_of_birth": date(1965, 6, 30),
                "gender": "Male",
                "blood_group": "AB+",
                "allergies": "Aspirin / NSAIDs",
                "primary_payer": "Cash",
                "next_of_kin_name": "John Mutua",
                "next_of_kin_phone": "0701 234 567",
                "next_of_kin_relation": "Child",
                "residential_address": "P.O. Box 102, Machakos Town"
            }
        ]

        saved_patients = []
        for p_data in patients_data:
            h_id = Patient.generate_hospital_id(db.session)
            patient = Patient(hospital_id=h_id, **p_data)
            db.session.add(patient)
            db.session.flush()
            saved_patients.append(patient)

        # Seed queue entries
        ticket1 = QueueEntry.generate_daily_ticket(db.session)
        q1 = QueueEntry(
            ticket_number=ticket1,
            patient_id=saved_patients[0].id,
            stage='billing',
            priority='urgent',
            status='waiting',
            chief_complaint='Acute persistent chest tightness and shortness of breath x 2 hrs',
            destination_department='General OPD',
            assigned_doctor='Dr. Sarah Kamau (General OPD)'
        )
        db.session.add(q1)

        ticket2 = QueueEntry.generate_daily_ticket(db.session)
        q2 = QueueEntry(
            ticket_number=ticket2,
            patient_id=saved_patients[1].id,
            stage='triage',
            priority='normal',
            status='waiting',
            chief_complaint='Follow-up for routine blood pressure check and prescription refill',
            destination_department='General OPD'
        )
        db.session.add(q2)

        # Seed sample historical vitals
        v1 = VitalsRecord(
            patient_id=saved_patients[0].id,
            systolic_bp=142,
            diastolic_bp=92,
            pulse_rate=94,
            temperature=37.2,
            respiratory_rate=18,
            spo2=96.0,
            weight_kg=82.0,
            height_cm=175.0,
            bmi=26.8,
            bmi_category='Overweight',
            triage_category='yellow',
            chief_complaint='Hypertension screening',
            allergies=saved_patients[0].allergies,
            recorded_by='Nurse Mercy',
            assigned_doctor='Dr. Sarah Kamau',
            destination_clinic='General OPD',
            created_at=datetime.utcnow() - timedelta(days=20)
        )
        db.session.add(v1)

        # Seed appointments
        app1 = Appointment(
            patient_id=saved_patients[2].id,
            scheduled_date=date.today(),
            scheduled_time="10:30",
            department="Cardiology Clinic",
            doctor_name="Dr. Njoroge",
            reason="Bi-annual echocardiogram and cardiology consultation",
            status="scheduled"
        )
        db.session.add(app1)

        # Seed sample pending prescription
        sample_meds = [
            {
                "drug": "Amoxicillin 500mg Capsules",
                "dosage": "500mg",
                "frequency": "1 cap TID (8-hourly)",
                "duration": "5 days",
                "quantity": 15,
                "instructions": "Take after food with plenty of water",
                "cost": 450.0
            },
            {
                "drug": "Paracetamol 500mg Tablets",
                "dosage": "1g",
                "frequency": "2 tabs TID PRN pain",
                "duration": "3 days",
                "quantity": 18,
                "instructions": "Take when needed for fever or headache",
                "cost": 180.0
            }
        ]
        rx_new = Prescription(
            rx_number=Prescription.generate_rx_number(db.session),
            patient_id=saved_patients[0].id,
            queue_entry_id=q1.id,
            doctor_name="Dr. Sarah Kamau (General OPD)",
            medications_json=json.dumps(sample_meds),
            notes="Patient has mild penicillin allergy; monitor for cutaneous reactions",
            total_cost=630.0,
            status="dispensed",
            created_at=datetime.utcnow() - timedelta(hours=1)
        )
        db.session.add(rx_new)
        db.session.flush()

        # Seed Staged Billing Items for Patient 1 (Consultation + Lab Tests + Dispensed Pharmacy + Procedure)
        inv1_num = Invoice.generate_invoice_number(db.session)
        inv1 = Invoice(
            invoice_number=inv1_num,
            patient_id=saved_patients[0].id,
            queue_entry_id=q1.id,
            subtotal=5530.0,
            discount_amount=0.0,
            tax_amount=0.0,
            total_due=5530.0,
            amount_paid=0.0,
            balance_due=5530.0,
            status='unpaid',
            cashier_name='Cashier Joyce Wambui (Lead Cashier)'
        )
        db.session.add(inv1)
        db.session.flush()

        b_items = [
            BillingItem(patient_id=saved_patients[0].id, invoice_id=inv1.id, queue_entry_id=q1.id, service_type='consultation', item_description='General OPD Doctor Consultation', quantity=1, unit_price=1500.0, total_amount=1500.0, status='staged'),
            BillingItem(patient_id=saved_patients[0].id, invoice_id=inv1.id, queue_entry_id=q1.id, service_type='lab', item_description='Full Blood Count (FBC/CBC)', quantity=1, unit_price=1200.0, total_amount=1200.0, status='staged'),
            BillingItem(patient_id=saved_patients[0].id, invoice_id=inv1.id, queue_entry_id=q1.id, service_type='radiology', item_description='Chest X-Ray PA Radiograph', quantity=1, unit_price=2200.0, total_amount=2200.0, status='staged'),
            BillingItem(patient_id=saved_patients[0].id, invoice_id=inv1.id, queue_entry_id=q1.id, service_type='pharmacy', item_description='Amoxicillin 500mg & Paracetamol Dispensation', quantity=1, unit_price=630.0, total_amount=630.0, status='staged'),
        ]
        db.session.add_all(b_items)

        # Seed Sample Historical Settled Payment for Patient 3 (Patrick Kiprono - SHA Insurance Claim)
        inv2_num = Invoice.generate_invoice_number(db.session)
        inv2 = Invoice(
            invoice_number=inv2_num,
            patient_id=saved_patients[2].id,
            subtotal=7200.0,
            discount_amount=200.0,
            tax_amount=0.0,
            total_due=7000.0,
            amount_paid=7000.0,
            balance_due=0.0,
            status='paid',
            paid_at=datetime.utcnow() - timedelta(hours=2),
            cashier_name='Cashier Joyce Wambui'
        )
        db.session.add(inv2)
        db.session.flush()

        b_items_p3 = [
            BillingItem(patient_id=saved_patients[2].id, invoice_id=inv2.id, service_type='consultation', item_description='Cardiology Specialist Review', quantity=1, unit_price=3000.0, total_amount=3000.0, status='paid'),
            BillingItem(patient_id=saved_patients[2].id, invoice_id=inv2.id, service_type='lab', item_description='Liver Function Tests (LFTs)', quantity=1, unit_price=2800.0, total_amount=2800.0, status='paid'),
            BillingItem(patient_id=saved_patients[2].id, invoice_id=inv2.id, service_type='procedure', item_description='Echocardiogram & Doppler Screening', quantity=1, unit_price=1400.0, total_amount=1400.0, status='paid'),
        ]
        db.session.add_all(b_items_p3)

        pay1 = Payment(
            receipt_number=Payment.generate_receipt_number(db.session),
            invoice_id=inv2.id,
            patient_id=saved_patients[2].id,
            total_amount_paid=7000.0,
            payment_method_summary="M-Pesa [QHD89X72K1] (KES 2,000.00) + Insurance Claim [SHA] (KES 5,000.00)",
            cash_amount=0.0,
            mpesa_amount=2000.0,
            mpesa_reference="QHD89X72K1",
            mpesa_phone="0756789012",
            insurance_amount=5000.0,
            insurance_company="Social Health Authority (SHA)",
            insurance_policy_number="SHA-902184-B",
            insurance_claim_number="AUTH-SHA-2026-9921",
            cashier_name="Cashier Joyce Wambui (Lead Cashier)",
            shift_code="SHF-20260817-01",
            created_at=datetime.utcnow() - timedelta(hours=2)
        )
        db.session.add(pay1)

    # 4. Seed Inpatient Wards & Beds if empty
    if Ward.query.count() == 0:
        wards_data = [
            {
                "name": "Male Medical Ward",
                "code": "MMW",
                "gender_category": "Male",
                "floor": "1st Floor, East Wing",
                "wing": "St. Luke Wing",
                "daily_nurse_in_charge": "Nurse Joyce Chebet",
                "beds": [
                    {"bed_number": "MMW-B01", "bed_type": "Standard General", "rate": 1500.0},
                    {"bed_number": "MMW-B02", "bed_type": "Standard General", "rate": 1500.0},
                    {"bed_number": "MMW-B03", "bed_type": "Semi-Private", "rate": 3000.0},
                    {"bed_number": "MMW-B04", "bed_type": "Private Suite", "rate": 5500.0},
                ]
            },
            {
                "name": "Female Surgical Ward",
                "code": "FSW",
                "gender_category": "Female",
                "floor": "1st Floor, West Wing",
                "wing": "St. Teresa Wing",
                "daily_nurse_in_charge": "Nurse Sharon Otieno",
                "beds": [
                    {"bed_number": "FSW-B01", "bed_type": "Standard General", "rate": 1500.0},
                    {"bed_number": "FSW-B02", "bed_type": "Standard General", "rate": 1500.0},
                    {"bed_number": "FSW-B03", "bed_type": "Semi-Private", "rate": 3000.0},
                    {"bed_number": "FSW-B04", "bed_type": "Private Suite", "rate": 5500.0},
                ]
            },
            {
                "name": "Pediatric & Neonatal Ward",
                "code": "PED",
                "gender_category": "Pediatric",
                "floor": "Ground Floor, South Wing",
                "wing": "Children's Wing",
                "daily_nurse_in_charge": "Nurse Faith Mutua",
                "beds": [
                    {"bed_number": "PED-B01", "bed_type": "Pediatric Crib", "rate": 1200.0},
                    {"bed_number": "PED-B02", "bed_type": "Pediatric Standard", "rate": 1500.0},
                    {"bed_number": "PED-B03", "bed_type": "Isolation Suite", "rate": 4000.0},
                ]
            },
            {
                "name": "Maternity & Labor Ward",
                "code": "MAT",
                "gender_category": "Female",
                "floor": "2nd Floor, North Wing",
                "wing": "Maternal Center",
                "daily_nurse_in_charge": "Midwife Everlyne Kerubo",
                "beds": [
                    {"bed_number": "MAT-B01", "bed_type": "Antenatal Bed", "rate": 2000.0},
                    {"bed_number": "MAT-B02", "bed_type": "Postnatal Recovery", "rate": 2500.0},
                    {"bed_number": "MAT-B03", "bed_type": "Private Maternity Suite", "rate": 6000.0},
                ]
            },
            {
                "name": "Intensive Care Unit (ICU / HDU)",
                "code": "ICU",
                "gender_category": "Mixed",
                "floor": "2nd Floor, Critical Care Wing",
                "wing": "Trauma & ICU Center",
                "daily_nurse_in_charge": "Nurse Brenda Wairimu (ICU Lead)",
                "beds": [
                    {"bed_number": "ICU-B01", "bed_type": "ICU Ventilator Bed", "rate": 12000.0},
                    {"bed_number": "ICU-B02", "bed_type": "ICU Ventilator Bed", "rate": 12000.0},
                    {"bed_number": "HDU-B01", "bed_type": "High Dependency Unit", "rate": 8000.0},
                ]
            }
        ]

        created_wards = []
        created_beds = []
        for w_data in wards_data:
            beds_list = w_data.pop("beds")
            ward = Ward(**w_data)
            db.session.add(ward)
            db.session.flush()
            created_wards.append(ward)

            for b_data in beds_list:
                bed = Bed(
                    ward_id=ward.id,
                    bed_number=b_data["bed_number"],
                    bed_type=b_data["bed_type"],
                    daily_rate=b_data["rate"],
                    status="available"
                )
                db.session.add(bed)
                created_beds.append(bed)

        db.session.flush()

        # Seed sample active inpatient admission
        all_patients = Patient.query.all()
        if len(all_patients) > 0 and len(created_beds) > 0:
            target_patient = all_patients[0]
            target_bed = created_beds[0] # MMW-B01
            target_ward = created_wards[0]

            target_bed.status = 'occupied'
            adm1 = Admission(
                admission_number="ADM-2026-0001",
                patient_id=target_patient.id,
                ward_id=target_ward.id,
                bed_id=target_bed.id,
                admitting_doctor="Dr. Sarah Kamau (Lead Physician)",
                admitting_diagnosis="Severe Community-Acquired Pneumonia with moderate hypoxemia",
                icd10_code="J18.9",
                admission_type="Emergency Admission",
                admitted_at=datetime.utcnow() - timedelta(days=2, hours=4),
                expected_discharge_date=date.today() + timedelta(days=2),
                status="admitted",
                dietary_plan="High Protein, Low Salt Hospital Diet",
                isolation_required=False,
                nursing_acuity="Moderate Care (Level 2)",
                deposit_amount=5000.0,
                emergency_contact_name=target_patient.next_of_kin_name,
                emergency_contact_phone=target_patient.next_of_kin_phone,
                emergency_contact_relation=target_patient.next_of_kin_relation
            )
            db.session.add(adm1)
            db.session.flush()

            # Add sample nursing notes for this patient
            nn1 = NursingNote(
                admission_id=adm1.id,
                patient_id=target_patient.id,
                nurse_name="Nurse Joyce Chebet",
                shift="Morning Shift (07:00 - 15:00)",
                subjective_assessment="Patient reports improved breathing ease after morning nebulization. Mild dry cough persists.",
                nursing_interventions="Administered IV Ceftriaxone 1g, salbutamol nebulization 2.5mg given. Assisted with personal hygiene. Vitals charted.",
                vital_signs_summary="BP 122/78, Pulse 76, Temp 36.8°C, SpO2 98% on room air",
                intake_output_notes="Oral intake 1200ml, IV fluids 500ml / Urine output 1400ml clear",
                medications_administered="IV Ceftriaxone 1g, Oral Paracetamol 1g, IV Normal Saline 500ml",
                iv_infusions="Left forearm 20G cannula patent, infusing Normal Saline @ 60ml/hr",
                handover_instructions="Repeat afternoon SpO2 checks. Encourage deep breathing and ambulation.",
                created_at=datetime.utcnow() - timedelta(hours=3)
            )
            db.session.add(nn1)

            # Add sample doctor ward round
            wr1 = WardRoundNote(
                admission_id=adm1.id,
                patient_id=target_patient.id,
                doctor_name="Dr. Sarah Kamau",
                round_date=datetime.utcnow() - timedelta(hours=4),
                clinical_progress="Patient afebrile for 36 hours. Chest auscultation reveals clearing bronchial breath sounds on right lower lobe. Respiratory rate steady at 18 bpm.",
                lab_radiology_review="Repeat CBC shows WBC decreased from 14.2 to 7.8 (normalized).",
                treatment_plan_changes="Step down from IV Ceftriaxone to Oral Augmentin 625mg BD starting tonight. Discontinue IV infusion. Patient may be cleared for discharge tomorrow if stable.",
                discharge_readiness="Plan Discharge Tomorrow",
                created_at=datetime.utcnow() - timedelta(hours=4)
            )
            db.session.add(wr1)

    # =================== SEED SECURITY SETTINGS & RBAC PERMISSIONS ===================
    if not SecuritySetting.query.first():
        sec_settings = SecuritySetting(
            require_2fa_for_all=False,
            require_2fa_for_admin_doctor=True,
            session_timeout_minutes=30,
            max_failed_attempts=5,
            lockout_duration_minutes=15,
            password_min_length=8,
            require_special_chars=True
        )
        db.session.add(sec_settings)

    # Canonical System Permissions
    canonical_permissions = [
        # Patient Records
        ("patient:view", "View Patient Records & History", "Patients", "Access demographic profiles and outpatient history"),
        ("patient:register", "Register New Patients", "Patients", "Create new patient records and allocate hospital IDs"),
        ("patient:edit", "Edit Patient Demographics", "Patients", "Modify patient contact info and insurance particulars"),
        
        # Clinical Consultation & EMR
        ("clinical:consult", "Perform Medical Consultations", "Clinical", "Document clinical notes, examinations, and diagnoses"),
        ("clinical:prescribe", "Prescribe Medications (Rx)", "Clinical", "Generate electronic prescriptions sent to pharmacy"),
        ("clinical:order_labs", "Order Diagnostic Tests", "Clinical", "Request lab tests and radiology imaging"),
        
        # Clinical Documents
        ("documents:generate_cert", "Issue Medical Sick-Off Certificates", "Documents", "Generate stamped clinical sick leave notes"),
        ("documents:generate_referral", "Issue Specialist Referral Letters", "Documents", "Draft official hospital referral documents"),
        ("documents:upload", "Upload & Manage Patient Attachments", "Documents", "Upload radiological scans, PDFs, and ID records"),
        
        # Inpatient Care & Wards
        ("inpatient:admit", "Admit Patient to Wards", "Inpatient", "Assign ward beds and document intake clinical orders"),
        ("inpatient:transfer", "Execute Inter-Ward Bed Transfers", "Inpatient", "Reassign beds and log transfer rationale"),
        ("inpatient:chart", "Document Nursing & Ward Rounds", "Inpatient", "Record shift nursing notes and daily doctor progress"),
        ("inpatient:discharge", "Clinical Inpatient Discharge", "Inpatient", "Finalize discharge clearance and generate certificates"),
        
        # Pharmacy & Dispensing
        ("pharmacy:dispense", "Dispense Prescriptions", "Pharmacy", "Clear and dispense pharmaceutical orders with counseling"),
        ("pharmacy:manage_stock", "Manage Drug Inventory & Batches", "Pharmacy", "Adjust stock, manage batches, and log purchase entries"),
        
        # Billing & Financials
        ("billing:create_invoice", "Create & Stage Invoices", "Billing", "Compile invoices and apply departmental fee schedules"),
        ("billing:collect_payment", "Collect Tender Payments", "Billing", "Process cash, M-Pesa, card, and insurance settlements"),
        ("billing:waive_discount", "Waive Charges & Authorize Discounts", "Billing", "Grant authorized discounts and fee waivers"),
        
        # Hospital Administration & Security
        ("admin:manage_users", "Manage Staff User Accounts", "Admin", "Create, edit, suspend, and reset staff credentials"),
        ("admin:security_config", "Configure Security Policies & 2FA", "Admin", "Manage global 2FA and password requirements"),
        ("admin:view_audit", "Access Immutable Audit Trail", "Admin", "Inspect all clinical and financial activity logs")
    ]

    for code, name, cat, desc in canonical_permissions:
        if not Permission.query.filter_by(code=code).first():
            p = Permission(code=code, name=name, category=cat, description=desc)
            db.session.add(p)

    db.session.flush()

    # Seed Default Role-Permission Mappings if not configured
    if RolePermission.query.count() == 0:
        default_role_matrix = {
            'doctor': [
                'patient:view', 'clinical:consult', 'clinical:prescribe', 'clinical:order_labs',
                'documents:generate_cert', 'documents:generate_referral', 'documents:upload',
                'inpatient:chart', 'inpatient:discharge'
            ],
            'nurse': [
                'patient:view', 'clinical:order_labs', 'inpatient:admit', 'inpatient:transfer',
                'inpatient:chart', 'documents:upload'
            ],
            'pharmacist': [
                'patient:view', 'pharmacy:dispense', 'pharmacy:manage_stock', 'documents:upload'
            ],
            'cashier': [
                'patient:view', 'billing:create_invoice', 'billing:collect_payment', 'billing:waive_discount'
            ],
            'receptionist': [
                'patient:view', 'patient:register', 'patient:edit', 'documents:upload'
            ]
        }

        for role, perm_list in default_role_matrix.items():
            for p_code in perm_list:
                rp = RolePermission(role=role, permission_code=p_code)
                db.session.add(rp)

    # Seed Sample Clinical Document (Medical Certificate for James Mwangi)
    if ClinicalDocument.query.count() == 0:
        target_p = Patient.query.first()
        if target_p:
            sample_doc = ClinicalDocument(
                document_number="MED-CERT-202608-0001",
                patient_id=target_p.id,
                document_type="medical_certificate",
                title="Medical Sick-Off Certificate (3 Days Rest)",
                description="Severe Bronchitis - Bed rest recommended.",
                created_by_name="Dr. Sarah Kamau (OPD Lead)",
                is_signed=True,
                signed_by="Dr. Sarah Kamau",
                signed_at=datetime.utcnow() - timedelta(days=1)
            )
            sample_doc.metadata_dict = {
                'addressed_to': 'To Whom It May Concern',
                'diagnosis': 'Acute Exacerbation of Bronchitis with Pyrexia',
                'start_date': (date.today() - timedelta(days=1)).strftime('%Y-%m-%d'),
                'days_excused': 3,
                'fit_to_resume_date': (date.today() + timedelta(days=2)).strftime('%Y-%m-%d'),
                'fitness_status': 'Total Bed Rest & Temporary Unfitness',
                'clinical_remarks': 'Patient attended outpatient clinic and received nebulization and oral antibiotics. Advised strict rest.',
                'doctor_name': 'Dr. Sarah Kamau (KMPDC-A9842)'
            }
            db.session.add(sample_doc)

    db.session.commit()
    print("Initial clinical, EMR, Pharmacy, Billing, Inpatient Ward, and RBAC Security seed data initialized successfully.")

if __name__ == '__main__':
    app = create_app()
    app.run(host='0.0.0.0', port=5000, debug=True)
