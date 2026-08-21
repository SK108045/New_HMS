# 🏥 Apex Regional Medical Center — Hospital Management System (New_HMS)

A modular, multi-portal Hospital Management System (HMS) and Clinical EMR engineered with Flask, SQLAlchemy, Tailwind CSS, Alpine.js, Chart.js, HTMX, and Three.js.

---

## 🔐 Staff Login Credentials & Portal Directory

Each portal features dedicated station authentication, unique color theming, session management, and sample credentials:

| Portal | Station Badge | Color Theme | Staff Member | Username | Password | Role |
|---|---|---|---|---|---|---|
| 📋 **Reception & Front-Desk** | `DESK-01` | Warm Stone | Mary Wanjiku | `reception` | `Reception@2026` | `receptionist` |
| 🩺 **Triage & Nursing** | `TRIAGE-01` | Deep Teal | Nurse Mercy Akinyi | `nurse` | `Triage@2026` | `nurse` |
| 👨‍⚕️ **Doctor & Clinical EMR** | `ROOM-01` | Rich Indigo | Dr. Sarah Kamau | `doctor` | `Doctor@2026` | `doctor` |
| 💊 **Pharmacy & Dispensation** | `PHARM-01` | Forest Emerald | Pharm. Evans Omondi | `pharmacy` | `Pharm@2026` | `pharmacist` |
| 💰 **Point-of-Sale (POS) & Billing** | `POS-01` | Warm Amber | Cashier Joyce Wambui | `cashier` | `Billing@2026` | `cashier` |
| 🛡️ **Hospital Administration** | `HQ-00` | Universal Access | Dr. Robert Odhiambo | `admin` | `Admin@2026` | `admin` |

> 💡 **Demo mode**: Set `HMS_ENABLE_DEMO_LOGIN=true` only in a local demonstration environment to show the one-click sample sign-in button. Keep it disabled for normal use.

---

## 🌟 Portals & Workflows Built

### 0. 🛡️ Hospital Administration Portal (`/admin`)
- **Login URL**: [`/admin/login`](http://localhost:5000/admin/login) or [`/login/admin`](http://localhost:5000/login/admin)
- **Access**: Administrator accounts only. The seeded `admin` account is the initial administrator.
- **Features**: Hospital-wide command dashboard, staff creation and role/portal/status management, operations oversight, finance and shift oversight, medication and expiry governance, and a persistent administrator audit log.

### 1. 📋 Reception & Front-Desk Portal (`/reception`)
- **Login URL**: [`/reception/login`](http://localhost:5000/reception/login) or [`/login/reception`](http://localhost:5000/login/reception)
- **Station**: `DESK-01` &bull; **Operator**: `Mary Wanjiku (STF-REC-01)`
- **Features**: Patient master directory, new patient registration with webcam photo capture, live intake queue management, real-time ticket numbering, and clinic appointment scheduling.

### 2. 🩺 Triage & Nursing Station Portal (`/triage`)
- **Login URL**: [`/triage/login`](http://localhost:5000/triage/login) or [`/login/triage`](http://localhost:5000/login/triage)
- **Station**: `TRIAGE-01` &bull; **Operator**: `Nurse Mercy Akinyi (STF-TRG-01)`
- **Features**: Live triage queue, rapid vitals entry (BP, Pulse, Temp, RR, SpO₂, Weight, Height, auto-calculated BMI & status), allergy safety alerts, acuity categorization (Green, Yellow, Red), triage multi-chart analytics, and routing to doctors.

### 3. 👨‍⚕️ Doctor & Clinical EMR Portal (`/doctor`)
- **Login URL**: [`/doctor/login`](http://localhost:5000/doctor/login) or [`/login/doctor`](http://localhost:5000/login/doctor)
- **Station**: `ROOM-01` &bull; **Operator**: `Dr. Sarah Kamau (STF-DOC-01)`
- **Features**: 360° EMR patient history workspace, **Interactive 3D Anatomical Human Skeleton (Three.js)**, PACS Radiograph Lightbox (Chest X-Ray PA & Brain MRI), SOAP clinical notes with searchable ICD-10 codes, electronic lab order requester, e-prescription pad, and automatic charge staging.

### 4. 💊 Pharmacy & Dispensation Portal (`/pharmacy`)
- **Login URL**: [`/pharmacy/login`](http://localhost:5000/pharmacy/login) or [`/login/pharmacy`](http://localhost:5000/login/pharmacy)
- **Station**: `PHARM-01` &bull; **Operator**: `Pharm. Evans Omondi (STF-PHM-01)`
- **Features**: Live incoming e-prescription queue, dispensation desk with allergy safety alerts, **FEFO (First Expired First Out) batch selector**, automated inventory stock & batch deduction, stock & expiry alert center (<30d, <60d, <90d risk), printable medication pouch/bottle labels, and stock movement ledger.

### 5. 💰 Point-of-Sale (POS) & Billing Portal (`/billing`)
- **Login URL**: [`/billing/login`](http://localhost:5000/billing/login) or [`/login/billing`](http://localhost:5000/login/billing)
- **Station**: `POS-01` &bull; **Operator**: `Cashier Joyce Wambui (STF-BIL-01)`
- **Features**: Dual-panel cashier POS workstation, aggregated clinical encounter folios, **Multi-Tender Split Payment System** (Cash with auto-change calculator, M-Pesa with transaction code validation, Insurance claims, Bank card), **Instant Dual-Format Receipt Generator** (80mm thermal slip & standard A4 tax invoice with KRA PIN), and **Shift Reconciliation (Live X-Reports & Z-Report Register Closeout)**.

---

## 🚀 Getting Started

### Prerequisites
- Python 3.10+
- Node.js & npm (for Tailwind CSS compilation)

### Installation & Setup

1. **Clone the Repository:**
   ```bash
   git clone git@github.com:SK108045/New_HMS.git
   cd New_HMS
   ```

2. **Create and Activate Virtual Environment:**
   ```bash
   python3 -m venv venv
   source venv/bin/activate
   ```

3. **Configure the Application:**
   ```bash
   cp .env.example .env
   # Set SECRET_KEY to a long, unique random value before using real patient data.
   ```

4. **Install Dependencies:**
   ```bash
   pip install -r requirements.txt
   npm install
   ```

5. **Build CSS Styles:**
   ```bash
   npx tailwindcss -i ./static/src/input.css -o ./static/dist/styles.css --minify
   ```

6. **Run the Application:**
   ```bash
   python app.py
   ```

The application will start on `http://localhost:5000`.
