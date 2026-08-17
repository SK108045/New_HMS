# 🏥 Apex Regional Medical Center — Hospital Management System (New_HMS)

A modular, multi-portal Hospital Management System (HMS) and Clinical EMR engineered with Flask, SQLAlchemy, Tailwind CSS, Alpine.js, Chart.js, HTMX, and Three.js.

---

## 🌟 Portals & Workflows Built

### 1. 📋 Reception & Front-Desk Portal (`/reception`)
- **Station**: `DESK-01`
- **Features**: Patient master directory, new patient onboarding, live intake queue management, real-time ticket numbering, and clinic appointment scheduling.

### 2. 🩺 Triage & Nursing Station Portal (`/triage`)
- **Station**: `TRIAGE-01`
- **Features**: Live triage queue, rapid vitals entry (BP, Pulse, Temp, RR, SpO₂, Weight, Height, auto-calculated BMI & status), allergy safety alerts, acuity categorization (Green, Yellow, Red), triage multi-chart analytics, and routing to doctors.

### 3. 👨‍⚕️ Doctor & Clinical EMR Portal (`/doctor`)
- **Station**: `ROOM-01`
- **Features**: 360° EMR patient history workspace, **Interactive 3D Anatomical Human Skeleton (Three.js)**, PACS Radiograph Lightbox (Chest X-Ray PA & Brain MRI), SOAP clinical notes with searchable ICD-10 codes, electronic lab order requester, e-prescription pad, and automatic charge staging.

### 4. 💊 Pharmacy & Dispensation Portal (`/pharmacy`)
- **Station**: `PHARM-01`
- **Features**: Live incoming e-prescription queue, dispensation desk with allergy safety alerts, **FEFO (First Expired First Out) batch selector**, automated inventory stock & batch deduction, stock & expiry alert center (<30d, <60d, <90d risk), printable medication pouch/bottle labels, and stock movement ledger.

### 5. 💰 Point-of-Sale (POS) & Billing Portal (`/billing`)
- **Station**: `POS-01`
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

3. **Install Dependencies:**
   ```bash
   pip install -r requirements.txt
   npm install
   ```

4. **Build CSS Styles:**
   ```bash
   npx tailwindcss -i ./static/src/input.css -o ./static/dist/styles.css --minify
   ```

5. **Run the Application:**
   ```bash
   python app.py
   ```

The application will start on `http://localhost:5000`.

---

## 🔒 Security & Architecture
- Isolated station portals with dedicated operator identities and badge designations.
- Neutral, crisp light UI designed for medical environments without visual clutter.
- Transactional database integrity with SQLite / SQLAlchemy.
