from sqlalchemy import Column, Integer, String, DateTime, JSON, Index
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
import datetime
import uuid

from . import Base

class ProviderProfile(Base):
    __tablename__ = "provider_profiles"
    
    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    facility_name = Column(String, nullable=False)
    provider_id = Column(UUID(as_uuid=True), unique=True, nullable=False, default=uuid.uuid4)
    facility_type = Column(String, nullable=False)
    prescribing_level = Column(String, nullable=True)
    contact_person_name = Column(String, nullable=False)
    contact_person_role = Column(String, nullable=False)
    contact_person_email = Column(String, nullable=False)
    phone_number = Column(String, nullable=False)
    org_email = Column(String, nullable=False)
    physical_address = Column(String, nullable=False)
    district = Column(String, nullable=False)
    region = Column(String, nullable=False)
    gps_coordinates = Column(JSON, nullable=True)
    credential_status = Column(String, nullable=False, index=True, default="Pending")
    credential_id = Column(String, unique=True, nullable=True, index=True)
    issue_date = Column(DateTime, nullable=True)
    expiry_date = Column(DateTime, nullable=True)
    credential_document_url = Column(String, nullable=True)
    last_updated_date = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow, nullable=False)
    
    claim_batches = relationship("ClaimBatch", back_populates="facility", cascade="all, delete-orphan")
    claims_v2 = relationship("ClaimV2", back_populates="provider_profile")
    claim_counts = relationship("ClaimStatusCount", back_populates="provider_profile", uselist=False)
    
    __table_args__ = (
        Index('idx_provider_profile_provider_id', 'provider_id'),
        Index('idx_provider_profile_facility_name', 'facility_name'),
        Index('idx_provider_profile_credential_status', 'credential_status'),
        Index('idx_provider_profile_credential_id', 'credential_id'),
        Index('idx_provider_profile_district', 'district'),
        Index('idx_provider_profile_region', 'region'),
        Index('idx_provider_profile_facility_type', 'facility_type'),
        Index('idx_provider_profile_prescribing_level', 'prescribing_level'),
        Index('idx_provider_profile_expiry_date', 'expiry_date'),
        Index('idx_provider_profile_active_credentials', 'credential_status', 'expiry_date'),
        Index('idx_provider_profile_region_type', 'region', 'facility_type'),
    )