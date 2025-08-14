from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Index, UniqueConstraint, CheckConstraint, Numeric
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
import uuid

from . import Base

class ClaimBatch(Base):
    __tablename__ = "claim_batches"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    facility_id = Column(UUID(as_uuid=True), ForeignKey('provider_profiles.provider_id', ondelete="CASCADE"), nullable=False, index=True)
    month = Column(Integer, nullable=False)
    year = Column(Integer, nullable=False)
    status = Column(String(50), nullable=False, default="pending")
    submitted_at = Column(DateTime(timezone=True), nullable=True)
    processed_at = Column(DateTime(timezone=True), nullable=True)
    claim_count = Column(Integer, nullable=False, default=0)
    total_amount = Column(Numeric(12, 2), nullable=False, default=0.00)
    nhis_reference = Column(String(255), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    
    facility = relationship("ProviderProfile", back_populates="claim_batches")
    claims = relationship("ClaimV2", back_populates="batch", cascade="all, delete-orphan")
    
    __table_args__ = (
        Index('idx_claim_batches_facility', 'facility_id'),
        Index('idx_claim_batches_status', 'status'),
        Index('idx_claim_batches_month_year', 'month', 'year'),
        Index('idx_claim_batches_submitted_at', 'submitted_at'),
        Index('idx_claim_batches_processed_at', 'processed_at'),
        Index('idx_claim_batches_facility_status', 'facility_id', 'status'),
        Index('idx_claim_batches_period_status', 'year', 'month', 'status'),
        UniqueConstraint('facility_id', 'month', 'year', name='unique_facility_month_year'),
        CheckConstraint('month >= 1 AND month <= 12', name='valid_month'),
        CheckConstraint("status IN ('pending', 'submitted', 'processing', 'processed', 'rejected')", name='valid_status'),
        CheckConstraint('claim_count >= 0', name='non_negative_claim_count'),
        CheckConstraint('total_amount >= 0', name='non_negative_total_amount'),
        CheckConstraint('year >= 2020 AND year <= 2050', name='valid_year_range'),
    )