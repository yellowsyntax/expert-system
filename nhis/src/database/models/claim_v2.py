from sqlalchemy import Column, String, DateTime, ForeignKey, Index
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
import datetime
import uuid

from . import Base

class ClaimV2(Base):
    __tablename__ = "claims_v2"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    provider_id = Column(UUID(as_uuid=True), ForeignKey('provider_profiles.provider_id'), nullable=False, index=True)
    provider_name = Column(String, nullable=True)
    district = Column(String, nullable=True)
    provider_type = Column(String, nullable=True)
    healthcare_level = Column(String, nullable=True)
    prescriber_level = Column(String, nullable=True)
    last_name = Column(String, nullable=True)
    other_names = Column(String, nullable=True)
    date_of_birth = Column(DateTime, nullable=True)
    gender = Column(String, nullable=True)
    nhis_number = Column(String, nullable=True)
    encounter_id = Column(String, nullable=True)
    admission_date = Column(DateTime, nullable=True)
    discharge_date = Column(DateTime, nullable=True)
    service_type_1 = Column(String, nullable=True)
    service_type_2 = Column(String, nullable=True)
    service_outcome = Column(String, nullable=True)
    attendance_type = Column(String, nullable=True)
    specialties_attended = Column(String, nullable=True)
    procedure_name = Column(String, nullable=True)
    g_drg_procedure = Column(String, nullable=True)
    icd10_procedure = Column(String, nullable=True)
    icd10_description_procedure = Column(String, nullable=True)
    level_procedure = Column(String, nullable=True)
    diagnosis_name = Column(String, nullable=True)
    icd10_diagnosis = Column(String, nullable=True)
    g_drg_diagnosis = Column(String, nullable=True)
    medicine_code = Column(String, nullable=True)
    medicine_name = Column(String, nullable=True)
    dosage = Column(String, nullable=True)
    frequency = Column(String, nullable=True)
    duration = Column(String, nullable=True)
    g_drg_inve = Column(String, nullable=True)
    description_inve = Column(String, nullable=True)
    batch_id = Column(UUID(as_uuid=True), ForeignKey('claim_batches.id', ondelete="SET NULL"), nullable=True, index=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, nullable=True)
    
    provider_profile = relationship("ProviderProfile", back_populates="claims_v2")
    batch = relationship("ClaimBatch", back_populates="claims")
    decisions = relationship("ClaimDecision", back_populates="claim", cascade="all, delete-orphan")
    audit_logs = relationship("AuditLog", back_populates="claim", cascade="all, delete-orphan")
    
    __table_args__ = (
        Index('idx_claim_v2_provider_id', 'provider_id'),
        Index('idx_claim_v2_nhis_number', 'nhis_number'),
        Index('idx_claim_v2_encounter_id', 'encounter_id'),
        Index('idx_claim_v2_admission_date', 'admission_date'),
        Index('idx_claim_v2_batch_id', 'batch_id'),
        Index('idx_claim_v2_service_type', 'service_type_1'),
        Index('idx_claim_v2_icd10_diagnosis', 'icd10_diagnosis'),
        Index('idx_claim_v2_icd10_procedure', 'icd10_procedure'),
        Index('idx_claim_v2_created_at', 'created_at'),
        Index('idx_claim_v2_discharge_date', 'discharge_date'),
        Index('idx_claim_v2_patient_visits', 'nhis_number', 'admission_date'),
        Index('idx_claim_v2_episode_tracking', 'nhis_number', 'service_type_1', 'admission_date'),
    )