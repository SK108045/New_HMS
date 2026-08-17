import os
import json
from datetime import datetime, date, timedelta
from flask import Flask, redirect, url_for
from config import Config
from models import (
    db, Patient, QueueEntry, Appointment, VitalsRecord,
    ConsultationNote, LabOrder, Prescription, BillingItem,
    MedicationItem, DrugBatch, DispensationRecord, StockTransaction,
    Invoice, Payment, ShiftRegister
)
from reception import reception_bp
from triage import triage_bp
from doctor import doctor_bp
from pharmacy import pharmacy_bp
from billing import billing_bp

def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)

    # Ensure upload folder exists
    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
    os.makedirs(os.path.join(app.root_path, 'static', 'dist'), exist_ok=True)
    os.makedirs(os.path.join(app.root_path, 'static', 'js'), exist_ok=True)
    os.makedirs(os.path.join(app.root_path, 'static', 'images'), exist_ok=True)

    # Initialize extensions
    db.init_app(app)

    # Register blueprints
    app.register_blueprint(reception_bp)
    app.register_blueprint(triage_bp)
    app.register_blueprint(doctor_bp)
    app.register_blueprint(pharmacy_bp)
    app.register_blueprint(billing_bp)

    @app.route('/')
    def index():
        return redirect(url_for('reception.dashboard'))

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
            'global_today_app_count': today_app_count
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
        db.create_all()
        seed_initial_data()

    return app

def seed_initial_data():
    """
    Seeds initial realistic patient records, queue entries, historical vitals, EMR encounters,
    Pharmacy inventory with FEFO batches, and Billing staged folios, split payments & shift registers.
    """
    today_start = datetime.combine(date.today(), datetime.min.time())

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

    if Patient.query.first():
        return

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

    db.session.commit()
    print("Initial clinical, EMR, Pharmacy, and Billing seed data initialized successfully.")

if __name__ == '__main__':
    app = create_app()
    app.run(host='0.0.0.0', port=5000, debug=True)
