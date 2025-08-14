from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Index, JSON, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
import datetime
import uuid

from . import Base


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    claim_id = Column(
        UUID(as_uuid=True),
        ForeignKey("claims_v2.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )

    event_type = Column(String(50), nullable=False, index=True)
    processor_name = Column(String(100), nullable=True)
    step_number = Column(Integer, nullable=True)

    decision = Column(String(50), nullable=True)
    decision_reason = Column(String(500), nullable=True)
    event_description = Column(Text, nullable=False)

    rule_name = Column(String(100), nullable=True)
    rules_applied = Column(JSON, nullable=True)
    validation_criteria = Column(JSON, nullable=True)

    input_data = Column(JSON, nullable=True)
    output_data = Column(JSON, nullable=True)

    error_type = Column(String(100), nullable=True)
    error_message = Column(Text, nullable=True)

    processing_time_ms = Column(Integer, nullable=True)

    created_at = Column(
        DateTime, default=datetime.datetime.utcnow, nullable=False, index=True
    )

    claim = relationship("ClaimV2", back_populates="audit_logs")

    __table_args__ = (
        Index("idx_audit_log_claim_id", "claim_id"),
        Index("idx_audit_log_event_type", "event_type"),
        Index("idx_audit_log_processor_name", "processor_name"),
        Index("idx_audit_log_step_number", "step_number"),
        Index("idx_audit_log_decision", "decision"),
        Index("idx_audit_log_rule_name", "rule_name"),
        Index("idx_audit_log_error_type", "error_type"),
        Index("idx_audit_log_created_at", "created_at"),
        Index("idx_audit_log_claim_step", "claim_id", "step_number"),
        Index("idx_audit_log_event_processor", "event_type", "processor_name"),
        Index("idx_audit_log_processing_chain", "claim_id", "created_at"),
        Index("idx_audit_log_error_analysis", "error_type", "processor_name"),
        Index("idx_audit_log_rule_effectiveness", "rule_name", "decision"),
        Index("idx_audit_log_performance", "processor_name", "processing_time_ms"),
    )
