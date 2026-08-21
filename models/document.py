import json
import os
from datetime import datetime, date
from .base import db

class ClinicalDocument(db.Model):
    """
    Unified Medical Document & Attachment Registry.
    Stores generated clinical certificates, referral notes, and uploaded patient attachments.
    """
    __tablename__ = 'clinical_documents'

    id = db.Column(db.Integer, primary_key=True)
    document_number = db.Column(db.String(60), unique=True, nullable=False, index=True)  # DOC-2026-0001
    patient_id = db.Column(db.Integer, db.ForeignKey('patients.id'), nullable=False, index=True)
    admission_id = db.Column(db.Integer, db.ForeignKey('admissions.id'), nullable=True)
    consultation_id = db.Column(db.Integer, db.ForeignKey('consultation_notes.id'), nullable=True)

    # Document Classification
    # 'medical_certificate', 'referral_letter', 'prescription_slip', 'lab_report', 'radiology_scan', 'insurance_preauth', 'id_copy', 'discharge_summary', 'other'
    document_type = db.Column(db.String(50), nullable=False, index=True)
    title = db.Column(db.String(255), nullable=False)
    description = db.Column(db.Text, nullable=True)

    # Physical File Attachment Details (if uploaded)
    file_path = db.Column(db.String(255), nullable=True)
    file_name = db.Column(db.String(255), nullable=True)
    file_size = db.Column(db.Integer, nullable=True)  # in bytes
    mime_type = db.Column(db.String(100), nullable=True)

    # Structured Document Payload (sick leave days, referral specs, diagnosis, etc.)
    metadata_json = db.Column(db.Text, nullable=True)

    # Authorship & Signing
    created_by_id = db.Column(db.Integer, nullable=True)
    created_by_name = db.Column(db.String(120), nullable=False, default='Attending Clinician')
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)
    
    is_signed = db.Column(db.Boolean, default=True)
    signed_by = db.Column(db.String(120), nullable=True)
    signed_at = db.Column(db.DateTime, nullable=True)

    # Relationships
    patient = db.relationship('Patient', backref=db.backref('clinical_documents', lazy=True, order_by='ClinicalDocument.created_at.desc()'))
    admission = db.relationship('Admission', backref=db.backref('clinical_documents', lazy=True))
    consultation = db.relationship('ConsultationNote', backref=db.backref('clinical_documents', lazy=True))

    @classmethod
    def generate_document_number(cls, doc_type='DOC', session=None):
        prefix_map = {
            'medical_certificate': 'MED-CERT',
            'referral_letter': 'REF',
            'prescription_slip': 'RX-DOC',
            'lab_report': 'LAB-DOC',
            'radiology_scan': 'RAD-DOC',
            'discharge_summary': 'DIS-DOC'
        }
        prefix = prefix_map.get(doc_type, 'DOC')
        today_str = date.today().strftime('%Y%m')
        sess = session or db.session
        count = sess.query(cls).filter(
            cls.document_number.like(f'{prefix}-{today_str}-%')
        ).count()
        return f"{prefix}-{today_str}-{count + 1:04d}"

    @property
    def metadata_dict(self):
        if self.metadata_json:
            try:
                return json.loads(self.metadata_json)
            except Exception:
                return {}
        return {}

    @metadata_dict.setter
    def metadata_dict(self, val):
        self.metadata_json = json.dumps(val)

    @property
    def is_image(self):
        if self.mime_type:
            return self.mime_type.startswith('image/')
        if self.file_name:
            ext = os.path.splitext(self.file_name)[1].lower()
            return ext in ['.jpg', '.jpeg', '.png', '.gif', '.webp']
        return False

    @property
    def is_pdf(self):
        if self.mime_type:
            return self.mime_type == 'application/pdf'
        if self.file_name:
            return self.file_name.lower().endswith('.pdf')
        return False

    @property
    def formatted_size(self):
        if not self.file_size:
            return 'N/A'
        if self.file_size < 1024:
            return f"{self.file_size} B"
        elif self.file_size < 1024 * 1024:
            return f"{self.file_size / 1024:.1f} KB"
        else:
            return f"{self.file_size / (1024 * 1024):.1f} MB"

    def __repr__(self):
        return f"<ClinicalDocument {self.document_number} [{self.document_type}] Patient={self.patient_id}>"
