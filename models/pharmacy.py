import json
from datetime import datetime, date, timedelta
from models.base import db

class MedicationItem(db.Model):
    """
    Pharmacy Formulary & Inventory Drug Item.
    """
    __tablename__ = 'medication_items'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(150), unique=True, nullable=False)
    generic_name = db.Column(db.String(120), nullable=True)
    category = db.Column(db.String(80), nullable=False) # Antibiotic, Analgesic, Antihypertensive, Antidiabetic, etc.
    form = db.Column(db.String(50), default='Tablet') # Tablet, Capsule, Syrup, Suspension, Injection, Ointment
    strength = db.Column(db.String(50), nullable=True) # 500mg, 20mg, 100ml
    current_stock = db.Column(db.Integer, default=0, nullable=False)
    reorder_level = db.Column(db.Integer, default=25, nullable=False)
    unit_price = db.Column(db.Float, default=0.0, nullable=False) # Selling price per unit
    cost_price = db.Column(db.Float, default=0.0, nullable=False) # Purchase price per unit
    location_shelf = db.Column(db.String(50), default='A-01')
    barcode = db.Column(db.String(60), nullable=True)
    indication = db.Column(db.String(255), nullable=True)
    default_dosage = db.Column(db.String(100), nullable=True)
    default_freq = db.Column(db.String(100), nullable=True)
    default_dur = db.Column(db.String(50), nullable=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    batches = db.relationship('DrugBatch', back_populates='medication', cascade='all, delete-orphan', lazy=True)
    transactions = db.relationship('StockTransaction', back_populates='medication', lazy=True)

    @property
    def is_low_stock(self):
        return self.current_stock <= self.reorder_level

    @property
    def is_out_of_stock(self):
        return self.current_stock <= 0

    @property
    def stock_status(self):
        if self.current_stock <= 0:
            return 'out_of_stock'
        elif self.current_stock <= (self.reorder_level / 2):
            return 'critical'
        elif self.current_stock <= self.reorder_level:
            return 'low'
        return 'adequate'

    @property
    def total_valuation(self):
        return self.current_stock * self.unit_price

    @property
    def active_batches(self):
        return [b for b in self.batches if b.quantity_remaining > 0 and b.status == 'active']

    def __repr__(self):
        return f"<MedicationItem {self.name} Stock={self.current_stock}>"


class DrugBatch(db.Model):
    """
    Inventory Batch with Expiry Tracking (FEFO - First Expired First Out).
    """
    __tablename__ = 'drug_batches'

    id = db.Column(db.Integer, primary_key=True)
    medication_id = db.Column(db.Integer, db.ForeignKey('medication_items.id'), nullable=False)
    batch_number = db.Column(db.String(60), nullable=False)
    quantity_received = db.Column(db.Integer, nullable=False)
    quantity_remaining = db.Column(db.Integer, nullable=False)
    expiry_date = db.Column(db.Date, nullable=False)
    received_date = db.Column(db.Date, default=date.today, nullable=False)
    supplier = db.Column(db.String(120), default='Apex Central Medical Supplies')
    status = db.Column(db.String(30), default='active') # active, depleted, expired, quarantined

    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    # Relationships
    medication = db.relationship('MedicationItem', back_populates='batches')
    transactions = db.relationship('StockTransaction', back_populates='batch', lazy=True)

    @property
    def days_to_expiry(self):
        if not self.expiry_date:
            return 999
        delta = self.expiry_date - date.today()
        return delta.days

    @property
    def expiry_status(self):
        days = self.days_to_expiry
        if days < 0:
            return 'expired'
        elif days <= 30:
            return 'critical_30d'
        elif days <= 60:
            return 'warning_60d'
        elif days <= 90:
            return 'caution_90d'
        return 'safe'

    def __repr__(self):
        return f"<DrugBatch {self.batch_number} Med={self.medication_id} Rem={self.quantity_remaining} Exp={self.expiry_date}>"


class DispensationRecord(db.Model):
    """
    Confirmed Dispensation Audit Log.
    """
    __tablename__ = 'dispensation_records'

    id = db.Column(db.Integer, primary_key=True)
    dispensation_number = db.Column(db.String(60), unique=True, nullable=False)
    prescription_id = db.Column(db.Integer, db.ForeignKey('prescriptions.id'), nullable=False)
    patient_id = db.Column(db.Integer, db.ForeignKey('patients.id'), nullable=False)
    queue_entry_id = db.Column(db.Integer, db.ForeignKey('queue_entries.id'), nullable=True)

    pharmacist_name = db.Column(db.String(120), nullable=False)
    dispensed_items_json = db.Column(db.Text, nullable=False) # JSON array of [{ "drug": "...", "batch_number": "...", "quantity": 15, "cost": 450.0, "instructions": "..." }]
    counseling_notes = db.Column(db.Text, nullable=True)
    total_amount = db.Column(db.Float, default=0.0, nullable=False)

    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    # Relationships
    prescription = db.relationship('Prescription', backref='dispensation_records', lazy=True)
    patient = db.relationship('Patient', backref='dispensations', lazy=True)
    queue_entry = db.relationship('QueueEntry', backref='dispensation', lazy=True)

    @classmethod
    def generate_dispensation_number(cls, session=None):
        today_str = date.today().strftime('%Y%m%d')
        sess = session or db.session
        count = sess.query(cls).filter(
            cls.dispensation_number.like(f'DSP-{today_str}-%')
        ).count()
        return f"DSP-{today_str}-{count + 1:04d}"

    @property
    def dispensed_items(self):
        try:
            return json.loads(self.dispensed_items_json)
        except Exception:
            return []


class StockTransaction(db.Model):
    """
    Ledger of inventory stock movements (dispenses, replenishments, write-offs).
    """
    __tablename__ = 'stock_transactions'

    id = db.Column(db.Integer, primary_key=True)
    medication_id = db.Column(db.Integer, db.ForeignKey('medication_items.id'), nullable=False)
    batch_id = db.Column(db.Integer, db.ForeignKey('drug_batches.id'), nullable=True)

    transaction_type = db.Column(db.String(30), nullable=False) # dispense, restock, adjustment, writeoff
    quantity_change = db.Column(db.Integer, nullable=False) # e.g. -15 or +100
    previous_stock = db.Column(db.Integer, nullable=False)
    new_stock = db.Column(db.Integer, nullable=False)
    reference_id = db.Column(db.String(60), nullable=True) # e.g. RX-20260817-0001
    notes = db.Column(db.String(255), nullable=True)
    recorded_by = db.Column(db.String(120), nullable=False)

    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    # Relationships
    medication = db.relationship('MedicationItem', back_populates='transactions')
    batch = db.relationship('DrugBatch', back_populates='transactions')
