"""
NHIS Expert System - Shared Types and Data Structures
Common types used across multiple modules to avoid circular imports

This module contains the shared enums and dataclasses that are used
by both the master orchestrator and database updater.
"""

from dataclasses import dataclass
from enum import Enum
from datetime import datetime
from typing import Dict, Any, Optional

class ProcessingStage(Enum):
    """Processing stages in the pipeline"""
    INITIAL_PROCESSING = "INITIAL_PROCESSING"
    ENCOUNTER_FLOW = "ENCOUNTER_FLOW"
    CREDENTIALING = "CREDENTIALING"
    GDRG_DETERMINATION = "GDRG_DETERMINATION"
    MEDICINE_VALIDATION = "MEDICINE_VALIDATION"
    FINAL_PROCESSING = "FINAL_PROCESSING"
    DATABASE_UPDATE = "DATABASE_UPDATE"
    COMPLETED = "COMPLETED"

class ValidationResult(Enum):
    """Validation outcomes"""
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    FLAGGED = "FLAGGED"
    PENDING = "PENDING"
    PARTIAL = "PARTIAL"

@dataclass
class ProcessingOutcome:
    """Complete processing result"""
    encounter_id: str
    overall_result: ValidationResult
    processing_stage: ProcessingStage
    reason: str
    details: Dict[str, Any] = None
    timestamp: datetime = None
    processing_time_seconds: float = 0.0
    database_updated: bool = False  
    
    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.now()