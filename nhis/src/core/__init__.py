"""
NHIS Expert System - Core Module

This module contains the foundational components of the NHIS Expert System:
- Data models and enums
- Base interfaces and abstract classes
- Core exceptions
- Main expert system orchestrator
- Claim data adapter for ClaimV2 conversion

All other modules depend on these core components.
"""

# Import all components from individual files
from .models import (
    ClaimDecision,
    ValidationIssue,
    ProcessorResult,
    RuleResult,
    CalculationResult,
    StandardClaim,
    LineItem,
    create_validation_issue,
    create_line_item
)

from .enums import (
    ClaimStatus,
    ValidationSeverity,
    EncounterType,
    EpisodeType,
    GDRGDeterminationMethod,
    ModifierType,
    DecisionReason,
    ProcessingStep,
    AgeSuffix,
    FacilityLevel,
    PrescriberLevel,
    BundlingType,
    DocumentationType,
    AEClassification,
    ZoomCode,
    MedicineFrequency,
    RuleCategory,
    LineItemType,
    LineItemStatus,
    get_encounter_types,
    get_facility_levels,
    get_prescriber_levels,
    is_emergency_encounter,
    get_age_suffix
)

from .exceptions import (
    NHISExpertSystemError,
    ClaimProcessingError,
    ReferenceDataError,
    DatabaseConnectionError,
    ValidationError,
    ConfigurationError,
    GDRGMappingError,
    TariffCalculationError,
    EpisodeTrackingError,
    DocumentationError,
    handle_exception_gracefully,
    create_claim_rejection_error
)

from .interfaces import (
    BaseProcessor,
    BaseRule,
    BaseCalculator,
    BaseValidator,
    BaseRepository,
    BaseReferenceManager,
    BaseAuditLogger,
    BaseClaimAdapter,
    BaseExpertSystem,
    TimingMixin,
    ValidationMixin,
    InterfaceRegistry,
    interface_registry
)

from .expert_system import (
    NHISExpertSystem,
    create_expert_system,
    create_minimal_expert_system
)

from .claim_adapter import (
    ClaimV2Adapter,
    batch_adapt_claims,
    validate_claim_v2_completeness
)

# Version information
__version__ = "1.0.0"
__author__ = "NHIS Expert System Team"

# Public API - what other modules can import from core
__all__ = [
    # Data Models
    "ClaimDecision",
    "ValidationIssue", 
    "ProcessorResult",
    "RuleResult",
    "CalculationResult",
    "StandardClaim",
    "LineItem",
    "create_validation_issue",
    "create_line_item",
    
    # Enums
    "ClaimStatus",
    "ValidationSeverity",
    "EncounterType", 
    "EpisodeType",
    "GDRGDeterminationMethod",
    "ModifierType",
    "DecisionReason",
    "ProcessingStep",
    "AgeSuffix",
    "FacilityLevel",
    "PrescriberLevel",
    "BundlingType",
    "DocumentationType",
    "AEClassification",
    "ZoomCode",
    "MedicineFrequency",
    "RuleCategory",
    "LineItemType",
    "LineItemStatus",
    "get_encounter_types",
    "get_facility_levels",
    "get_prescriber_levels",
    "is_emergency_encounter",
    "get_age_suffix",
    
    # Exceptions
    "NHISExpertSystemError",
    "ClaimProcessingError",
    "ReferenceDataError", 
    "DatabaseConnectionError",
    "ValidationError",
    "ConfigurationError",
    "GDRGMappingError",
    "TariffCalculationError",
    "EpisodeTrackingError",
    "DocumentationError",
    "handle_exception_gracefully",
    "create_claim_rejection_error",
    
    # Interfaces
    "BaseProcessor",
    "BaseRule",
    "BaseCalculator", 
    "BaseValidator",
    "BaseRepository",
    "BaseReferenceManager",
    "BaseAuditLogger",
    "BaseClaimAdapter",
    "BaseExpertSystem",
    "TimingMixin",
    "ValidationMixin",
    "InterfaceRegistry",
    "interface_registry",
    
    # Main Classes
    "NHISExpertSystem",
    "create_expert_system",
    "create_minimal_expert_system",
    "ClaimV2Adapter",
    "batch_adapt_claims",
    "validate_claim_v2_completeness",
    
    # Module metadata
    "__version__",
    "__author__"
]

# Version information
__version__ = "1.0.0"
__author__ = "NHIS Expert System Team"

# Public API - what other modules can import from core
__all__ = [
    # Data Models
    "ClaimDecision",
    "ValidationIssue", 
    "ProcessorResult",
    "RuleResult",
    "CalculationResult",
    "StandardClaim",
    
    # Enums
    "ClaimStatus",
    "ValidationSeverity",
    "EncounterType", 
    "EpisodeType",
    "GDRGDeterminationMethod",
    "ModifierType",
    "DecisionReason",
    
    
    "NHISExpertSystemError",
    "ClaimProcessingError",
    "ReferenceDataError",
    "DatabaseConnectionError",
    "ValidationError",
    "ConfigurationError",
    
    # Interfaces
    "BaseProcessor",
    "BaseRule",
    "BaseCalculator",
    "BaseValidator",
    "BaseRepository",
    
    # Main Classes
    "NHISExpertSystem",
    "ClaimV2Adapter",
    
    # Module metadata
    "__version__",
    "__author__"
]