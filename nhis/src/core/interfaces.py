"""
NHIS Expert System - Core Interfaces

Abstract base classes that define contracts for all system components.
These interfaces ensure consistent behavior across processors, rules, calculators, and repositories.
"""

from abc import ABC, abstractmethod
from typing import Dict, List, Any, Optional, Union
from datetime import datetime

from .models import (
    StandardClaim,
    ClaimDecision,
    ProcessorResult,
    RuleResult,
    CalculationResult,
    ValidationIssue,
)
from .enums import ProcessingStep, ClaimStatus


class BaseProcessor(ABC):
    """
    Abstract base class for all processors in the 5-step pipeline.

    Each processor handles one major step:
    - IntakeProcessor (Step 1)
    - EligibilityProcessor (Step 2)
    - RoutingProcessor (Step 3)
    - CredentialingProcessor (Step 4)
    - BusinessRulesProcessor (Step 5)
    """

    def __init__(self, name: str, processing_step: ProcessingStep):
        self.name = name
        self.processing_step = processing_step
        self.start_time: Optional[datetime] = None
        self.end_time: Optional[datetime] = None

    @abstractmethod
    def process(
        self, claim: StandardClaim, context: Dict[str, Any] = None
    ) -> ProcessorResult:
        """
        Process a claim through this pipeline step.

        Args:
            claim: Standardized claim data
            context: Additional context from previous processing steps

        Returns:
            ProcessorResult with success status, data, errors, and warnings
        """
        pass

    @abstractmethod
    def validate_inputs(
        self, claim: StandardClaim, context: Dict[str, Any] = None
    ) -> List[ValidationIssue]:
        """
        Validate inputs before processing.

        Args:
            claim: Claim to validate
            context: Processing context

        Returns:
            List of validation issues found
        """
        pass

    def _start_processing(self) -> None:
        """Mark start of processing for timing"""
        self.start_time = datetime.utcnow()

    def _end_processing(self) -> float:
        """Mark end of processing and return duration in milliseconds"""
        self.end_time = datetime.utcnow()
        if self.start_time:
            delta = self.end_time - self.start_time
            return delta.total_seconds() * 1000
        return 0.0

    def get_processing_info(self) -> Dict[str, Any]:
        """Get processor metadata"""
        return {
            "name": self.name,
            "processing_step": self.processing_step.value,
            "start_time": self.start_time.isoformat() if self.start_time else None,
            "end_time": self.end_time.isoformat() if self.end_time else None,
        }


class BaseRule(ABC):
    """
    Abstract base class for all business rules.

    Rules are categorized by type:
    - OPD Rules (B1-B5)
    - Inpatient Rules (D1-D3)
    - A&E Rules (C)
    - G-DRG Rules (A1-A4)
    - Modifier Rules
    - Documentation Rules
    """

    def __init__(self, name: str, rule_reference: str = None, description: str = None):
        self.name = name
        self.rule_reference = rule_reference  # Flowchart node (e.g., "B2", "D1")
        self.description = description
        self.execution_start: Optional[datetime] = None
        self.execution_end: Optional[datetime] = None

    @abstractmethod
    def apply(self, claim: StandardClaim, context: Dict[str, Any] = None) -> RuleResult:
        """
        Apply this rule to a claim.

        Args:
            claim: Claim to evaluate
            context: Additional context (reference data, database connections, etc.)

        Returns:
            RuleResult indicating if rule passed/failed and any issues
        """
        pass

    @abstractmethod
    def is_applicable(
        self, claim: StandardClaim, context: Dict[str, Any] = None
    ) -> bool:
        """
        Check if this rule applies to the given claim.

        Args:
            claim: Claim to check
            context: Processing context

        Returns:
            True if rule should be applied to this claim
        """
        pass

    def _start_execution(self) -> None:
        """Mark start of rule execution"""
        self.execution_start = datetime.utcnow()

    def _end_execution(self) -> float:
        """Mark end of execution and return duration in milliseconds"""
        self.execution_end = datetime.utcnow()
        if self.execution_start:
            delta = self.execution_end - self.execution_start
            return delta.total_seconds() * 1000
        return 0.0

    def get_rule_info(self) -> Dict[str, Any]:
        """Get rule metadata"""
        return {
            "name": self.name,
            "rule_reference": self.rule_reference,
            "description": self.description,
            "execution_start": (
                self.execution_start.isoformat() if self.execution_start else None
            ),
            "execution_end": (
                self.execution_end.isoformat() if self.execution_end else None
            ),
        }


class BaseCalculator(ABC):
    """
    Abstract base class for all amount calculators.

    Calculators handle specific aspects of financial calculations:
    - G-DRG Tariff Calculator
    - Medicine Calculator
    - Investigation Calculator
    - Modifier Calculator
    - Final Amount Calculator
    """

    def __init__(self, name: str, calculation_type: str):
        self.name = name
        self.calculation_type = calculation_type

    @abstractmethod
    def calculate(
        self, claim: StandardClaim, context: Dict[str, Any] = None
    ) -> CalculationResult:
        """
        Calculate amounts for this component.

        Args:
            claim: Claim to calculate for
            context: Calculation context (tariff rates, reference data, etc.)

        Returns:
            CalculationResult with amounts and breakdown
        """
        pass

    @abstractmethod
    def validate_calculation_inputs(
        self, claim: StandardClaim, context: Dict[str, Any] = None
    ) -> List[ValidationIssue]:
        """
        Validate inputs before calculation.

        Args:
            claim: Claim to validate
            context: Calculation context

        Returns:
            List of validation issues
        """
        pass

    def get_calculator_info(self) -> Dict[str, Any]:
        """Get calculator metadata"""
        return {"name": self.name, "calculation_type": self.calculation_type}


class BaseValidator(ABC):
    """
    Abstract base class for data validators.

    Validators ensure data quality and completeness:
    - Claim Data Validator
    - Medicine Validator
    - Facility Validator
    - Episode Validator
    - Documentation Validator
    """

    def __init__(self, name: str, validation_scope: str):
        self.name = name
        self.validation_scope = validation_scope

    @abstractmethod
    def validate(
        self, data: Any, context: Dict[str, Any] = None
    ) -> List[ValidationIssue]:
        """
        Validate the provided data.

        Args:
            data: Data to validate (could be claim, medicine, etc.)
            context: Validation context

        Returns:
            List of validation issues found
        """
        pass

    def get_validator_info(self) -> Dict[str, Any]:
        """Get validator metadata"""
        return {"name": self.name, "validation_scope": self.validation_scope}


class BaseRepository(ABC):
    """
    Abstract base class for all data repositories.

    Repositories handle database interactions:
    - ClaimV2Repository
    - ProviderRepository
    - EpisodeRepository
    - AuditRepository
    - TariffRepository
    """

    def __init__(self, name: str, table_name: str = None):
        self.name = name
        self.table_name = table_name

    @abstractmethod
    def get_by_id(self, entity_id: str) -> Optional[Any]:
        """
        Get entity by ID.

        Args:
            entity_id: Unique identifier

        Returns:
            Entity if found, None otherwise
        """
        pass

    @abstractmethod
    def save(self, entity: Any) -> Any:
        """
        Save entity to database.

        Args:
            entity: Entity to save

        Returns:
            Saved entity with updated fields
        """
        pass

    @abstractmethod
    def delete(self, entity_id: str) -> bool:
        """
        Delete entity by ID.

        Args:
            entity_id: ID of entity to delete

        Returns:
            True if deleted successfully
        """
        pass

    def get_repository_info(self) -> Dict[str, Any]:
        """Get repository metadata"""
        return {"name": self.name, "table_name": self.table_name}


class BaseReferenceManager(ABC):
    """
    Abstract base class for reference data management.

    Manages local reference data (JSON files):
    - ICD-10 → G-DRG mappings
    - Medicine formulary
    - Episode limits
    - Documentation requirements
    """

    @abstractmethod
    def load_reference_data(self) -> bool:
        """
        Load all reference data into memory.

        Returns:
            True if loaded successfully
        """
        pass

    @abstractmethod
    def get_mapping(self, mapping_type: str, key: str) -> Optional[Dict[str, Any]]:
        """
        Get a specific mapping from reference data.

        Args:
            mapping_type: Type of mapping (e.g., 'icd10_gdrg', 'medicine_formulary')
            key: Lookup key

        Returns:
            Mapping data if found
        """
        pass

    @abstractmethod
    def is_data_loaded(self) -> bool:
        """
        Check if reference data is loaded.

        Returns:
            True if data is available
        """
        pass


class BaseAuditLogger(ABC):
    """
    Abstract base class for audit logging.

    Logs decision-making process for compliance and debugging.
    """

    @abstractmethod
    def log_decision(
        self, claim_id: str, step: str, decision: str, details: Dict[str, Any] = None
    ) -> None:
        """
        Log a decision point.

        Args:
            claim_id: Claim being processed
            step: Processing step or rule name
            decision: Decision made
            details: Additional context
        """
        pass

    @abstractmethod
    def log_validation_issue(self, claim_id: str, issue: ValidationIssue) -> None:
        """
        Log a validation issue.

        Args:
            claim_id: Claim with the issue
            issue: Validation issue details
        """
        pass

    @abstractmethod
    def log_calculation(
        self, claim_id: str, calculation_type: str, result: CalculationResult
    ) -> None:
        """
        Log a calculation result.

        Args:
            claim_id: Claim being calculated
            calculation_type: Type of calculation
            result: Calculation result
        """
        pass


class BaseClaimAdapter(ABC):
    """
    Abstract base class for claim data adapters.

    Converts between different data formats:
    - ClaimV2 database records → StandardClaim
    - StandardClaim → output formats
    """

    @abstractmethod
    def adapt_from_database(self, db_record: Any) -> StandardClaim:
        """
        Convert database record to StandardClaim.

        Args:
            db_record: Database record (e.g., ClaimV2)

        Returns:
            StandardClaim for processing
        """
        pass

    @abstractmethod
    def adapt_to_output(
        self, claim: StandardClaim, decision: ClaimDecision
    ) -> Dict[str, Any]:
        """
        Convert processing results to output format.

        Args:
            claim: Original claim
            decision: Processing decision

        Returns:
            Output data structure
        """
        pass


class BaseExpertSystem(ABC):
    """
    Abstract base class for the expert system orchestrator.

    Defines the main interface for claim processing.
    """

    @abstractmethod
    def process_claim(self, claim_data: Union[StandardClaim, Any]) -> ClaimDecision:
        """
        Process a single claim through the complete pipeline.

        Args:
            claim_data: Claim to process (StandardClaim or raw data)

        Returns:
            Final claim decision
        """
        pass

    @abstractmethod
    def process_batch(self, batch_id: str) -> List[ClaimDecision]:
        """
        Process all claims in a batch.

        Args:
            batch_id: Batch identifier

        Returns:
            List of claim decisions
        """
        pass

    @abstractmethod
    def get_system_status(self) -> Dict[str, Any]:
        """
        Get current system status.

        Returns:
            System status information
        """
        pass


# Utility mixins for common functionality


class TimingMixin:
    """Mixin to add timing capabilities to any class"""

    def __init__(self):
        self._start_time: Optional[datetime] = None
        self._end_time: Optional[datetime] = None

    def start_timing(self) -> None:
        """Start timing operation"""
        self._start_time = datetime.utcnow()

    def end_timing(self) -> float:
        """End timing and return duration in milliseconds"""
        self._end_time = datetime.utcnow()
        if self._start_time:
            delta = self._end_time - self._start_time
            return delta.total_seconds() * 1000
        return 0.0

    def get_timing_info(self) -> Dict[str, Any]:
        """Get timing information"""
        return {
            "start_time": self._start_time.isoformat() if self._start_time else None,
            "end_time": self._end_time.isoformat() if self._end_time else None,
            "duration_ms": (
                self.end_timing() if self._start_time and self._end_time else None
            ),
        }


class ValidationMixin:
    """Mixin to add validation helper methods"""

    def create_validation_issue(
        self, severity, code: str, message: str, details: Dict[str, Any] = None
    ) -> ValidationIssue:

        from .models import ValidationIssue

        return ValidationIssue(
            severity=severity, code=code, message=message, details=details or {}
        )

    def has_critical_issues(self, issues: List[ValidationIssue]) -> bool:
        """Check if any issues are critical"""
        return any(issue.is_critical() for issue in issues)


class InterfaceRegistry:

    def __init__(self):
        self._implementations: Dict[str, Any] = {}

    def register(self, interface_name: str, implementation: Any) -> None:
        """Register an implementation for an interface"""
        self._implementations[interface_name] = implementation

    def get(self, interface_name: str) -> Any:
        """Get implementation for an interface"""
        return self._implementations.get(interface_name)

    def list_registered(self) -> List[str]:
        """List all registered interfaces"""
        return list(self._implementations.keys())


interface_registry = InterfaceRegistry()
