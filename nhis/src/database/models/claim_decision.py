from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Index, JSON, Text, Numeric
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
import datetime
import uuid

from . import Base

class ClaimDecision(Base):
    __tablename__ = "claim_decisions"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    claim_id = Column(UUID(as_uuid=True), ForeignKey('claims_v2.id', ondelete="CASCADE"), nullable=False, index=True)
    processing_status = Column(String(50), nullable=False, default="PENDING")
    current_step = Column(Integer, default=1, nullable=False)
    
    intake_status = Column(String(50), nullable=True)
    eligibility_status = Column(String(50), nullable=True)
    routing_decision = Column(String(50), nullable=True)
    credentialing_status = Column(String(50), nullable=True)
    final_gdrg = Column(String(20), nullable=True)
    medicine_validation_status = Column(String(50), nullable=True)
    investigation_validation_status = Column(String(50), nullable=True)
    documentation_status = Column(String(50), nullable=True)
    modifiers_applied = Column(JSON, nullable=True)
    
    approved_amount = Column(Numeric(10, 2), default=0, nullable=False)
    denied_amount = Column(Numeric(10, 2), default=0, nullable=False)
    pending_amount = Column(Numeric(10, 2), default=0, nullable=False)
    total_claimed_amount = Column(Numeric(10, 2), default=0, nullable=False)
    base_gdrg_amount = Column(Numeric(10, 2), nullable=True)
    modifier_adjustments = Column(Numeric(10, 2), default=0, nullable=False)
    
    processing_notes = Column(Text, nullable=True)
    error_messages = Column(JSON, nullable=True)
    warning_messages = Column(JSON, nullable=True)
    flags_raised = Column(JSON, nullable=True)
    
    processing_started_at = Column(DateTime, default=datetime.datetime.utcnow, nullable=False)
    processing_completed_at = Column(DateTime, nullable=True)
    total_processing_time_ms = Column(Integer, nullable=True)
    
    created_at = Column(DateTime, default=datetime.datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, onupdate=datetime.datetime.utcnow, nullable=True)
    
    claim = relationship("ClaimV2", back_populates="decisions")
    
    __table_args__ = (
        Index('idx_claim_decision_claim_id', 'claim_id'),
        Index('idx_claim_decision_processing_status', 'processing_status'),
        Index('idx_claim_decision_current_step', 'current_step'),
        Index('idx_claim_decision_final_gdrg', 'final_gdrg'),
        Index('idx_claim_decision_intake_status', 'intake_status'),
        Index('idx_claim_decision_eligibility_status', 'eligibility_status'),
        Index('idx_claim_decision_routing_decision', 'routing_decision'),
        Index('idx_claim_decision_credentialing_status', 'credentialing_status'),
        Index('idx_claim_decision_processing_started', 'processing_started_at'),
        Index('idx_claim_decision_processing_completed', 'processing_completed_at'),
        Index('idx_claim_decision_amounts', 'approved_amount', 'denied_amount'),
        Index('idx_claim_decision_step_status', 'current_step', 'processing_status'),
    )