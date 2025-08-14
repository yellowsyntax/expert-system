"""
NHIS Expert System - Main Orchestrator

The main expert system class that coordinates all claim processing.
This is the primary interface that users interact with to process claims.
"""

from typing import Dict, List, Any, Optional, Union
from datetime import datetime
import time
import uuid

from .interfaces import (
    BaseExpertSystem, BaseProcessor, BaseReferenceManager, 
    BaseAuditLogger, BaseClaimAdapter
)
from .models import (
    StandardClaim, ClaimDecision, ProcessorResult, ValidationIssue, 
    CalculationResult
)
from .enums import (
    ClaimStatus, ValidationSeverity, ProcessingStep, DecisionReason,
    EncounterType
)
from .exceptions import (
    ClaimProcessingError, ReferenceDataError, DatabaseConnectionError,
    ConfigurationError, NHISExpertSystemError
)
from .claim_adapter import ClaimV2Adapter


class NHISExpertSystem(BaseExpertSystem):
    """
    Main NHIS Expert System orchestrator.
    
    Coordinates the 5-step claim processing pipeline:
    1. Intake & Normalization
    2. Eligibility & Coverage
    3. Setting Router  
    4. Credentialing & Level Check
    5. Business Rules & Calculation
    """
    
    def __init__(self, 
                 processors: Dict[ProcessingStep, BaseProcessor],
                 reference_manager: BaseReferenceManager,
                 audit_logger: Optional[BaseAuditLogger] = None,
                 claim_adapter: Optional[BaseClaimAdapter] = None):
        """
        Initialize the expert system.
        
        Args:
            processors: Dictionary mapping processing steps to processor instances
            reference_manager: Manager for local reference data
            audit_logger: Optional audit logger for decision tracking
            claim_adapter: Optional custom claim adapter (defaults to ClaimV2Adapter)
        """
        self.processors = processors
        self.reference_manager = reference_manager
        self.audit_logger = audit_logger
        self.claim_adapter = claim_adapter or ClaimV2Adapter()
        
        # System state
        self.is_initialized = False
        self.startup_time: Optional[datetime] = None
        self.processed_claims_count = 0
        self.system_errors: List[str] = []
        
        # Validate configuration
        self._validate_configuration()
        
        # Initialize system
        self._initialize_system()
    
    def process_claim(self, claim_data: Union[StandardClaim, Any]) -> ClaimDecision:
        """
        Process a single claim through the complete pipeline.
        
        Args:
            claim_data: Either a StandardClaim object or raw claim data (e.g., ClaimV2)
            
        Returns:
            Final claim decision with status, amounts, and rationale
            
        Raises:
            ClaimProcessingError: If processing fails
        """
        start_time = time.time()
        claim_id = None
        
        try:
            # Step 0: Convert to StandardClaim if needed
            if isinstance(claim_data, StandardClaim):
                standard_claim = claim_data
                claim_id = standard_claim.claim_id
            else:
                # Assume it's a ClaimV2 record that needs adaptation
                standard_claim = self.claim_adapter.adapt_from_database(claim_data)
                claim_id = standard_claim.claim_id
            
            self._log_decision(claim_id, "CLAIM_PROCESSING_STARTED", "Starting claim processing pipeline")
            
            # Initialize decision object
            decision = ClaimDecision(
                claim_id=claim_id,
                status=ClaimStatus.PENDING,
                decision_reason=DecisionReason.ALL_VALIDATIONS_PASSED,
                decision_rationale="Processing in progress",
                calculation_result=CalculationResult()
            )
            
            # Step 1: Intake & Normalization
            intake_result = self._execute_processing_step(
                ProcessingStep.INTAKE_NORMALIZATION,
                standard_claim,
                {}
            )
            decision.processing_steps.append(intake_result)
            
            if not intake_result.success:
                return self._create_rejection_decision(
                    claim_id, DecisionReason.INVALID_INPUT_DATA,
                    "Claim failed intake validation", intake_result.errors,
                    start_time
                )
            
            # Step 2: Eligibility & Coverage
            eligibility_result = self._execute_processing_step(
                ProcessingStep.ELIGIBILITY_COVERAGE,
                standard_claim,
                intake_result.data
            )
            decision.processing_steps.append(eligibility_result)
            
            if not eligibility_result.success:
                return self._create_rejection_decision(
                    claim_id, DecisionReason.SERVICE_EXCLUDED,
                    "Claim not eligible for coverage", eligibility_result.errors,
                    start_time
                )
            
            # Step 3: Setting Router
            routing_result = self._execute_processing_step(
                ProcessingStep.SETTING_ROUTER,
                standard_claim,
                {**intake_result.data, **eligibility_result.data}
            )
            decision.processing_steps.append(routing_result)
            
            if not routing_result.success:
                return self._create_rejection_decision(
                    claim_id, DecisionReason.INVALID_INPUT_DATA,
                    "Claim routing failed", routing_result.errors,
                    start_time
                )
            
            # Step 4: Credentialing & Level Check
            credentialing_result = self._execute_processing_step(
                ProcessingStep.CREDENTIALING_CHECK,
                standard_claim,
                {**intake_result.data, **eligibility_result.data, **routing_result.data}
            )
            decision.processing_steps.append(credentialing_result)
            
            if not credentialing_result.success:
                return self._create_rejection_decision(
                    claim_id, DecisionReason.FACILITY_NOT_AUTHORIZED,
                    "Facility not authorized for claimed services", credentialing_result.errors,
                    start_time
                )
            
            # Step 5: Business Rules & Calculation
            business_rules_result = self._execute_processing_step(
                ProcessingStep.BUSINESS_RULES_CALCULATION,
                standard_claim,
                {**intake_result.data, **eligibility_result.data, 
                 **routing_result.data, **credentialing_result.data}
            )
            decision.processing_steps.append(business_rules_result)
            
            # Create final decision based on business rules result
            decision = self._create_final_decision(
                standard_claim, business_rules_result, decision, start_time
            )
            
            # Update system metrics
            self.processed_claims_count += 1
            
            self._log_decision(claim_id, "CLAIM_PROCESSING_COMPLETED", 
                             f"Final status: {decision.status.value}")
            
            return decision
            
        except Exception as e:
            error_message = f"Unexpected error processing claim: {str(e)}"
            self._log_decision(claim_id, "CLAIM_PROCESSING_ERROR", error_message)
            
            # Create error decision
            return self._create_error_decision(claim_id, error_message, start_time)
    
    def process_batch(self, batch_id: str) -> List[ClaimDecision]:
        """
        Process all claims in a batch.
        
        Args:
            batch_id: Batch identifier
            
        Returns:
            List of claim decisions
        """
        batch_start_time = time.time()
        decisions = []
        
        try:
            self._log_decision(batch_id, "BATCH_PROCESSING_STARTED", f"Starting batch {batch_id}")
            
            # This would typically get claims from database
            # For now, we'll document the interface
            claims_data = self._get_claims_for_batch(batch_id)
            
            for claim_data in claims_data:
                try:
                    decision = self.process_claim(claim_data)
                    decisions.append(decision)
                except Exception as e:
                    # Create error decision for failed claim
                    error_decision = self._create_error_decision(
                        str(getattr(claim_data, 'id', 'unknown')),
                        f"Claim processing failed: {str(e)}",
                        time.time()
                    )
                    decisions.append(error_decision)
            
            batch_duration = (time.time() - batch_start_time) * 1000
            self._log_decision(batch_id, "BATCH_PROCESSING_COMPLETED", 
                             f"Processed {len(decisions)} claims in {batch_duration:.2f}ms")
            
            return decisions
            
        except Exception as e:
            self._log_decision(batch_id, "BATCH_PROCESSING_ERROR", f"Batch processing failed: {str(e)}")
            raise ClaimProcessingError(f"Batch processing failed: {str(e)}", processing_step="batch_processing")
    
    def get_system_status(self) -> Dict[str, Any]:
        """
        Get current system status and health information.
        
        Returns:
            System status dictionary
        """
        return {
            "system_info": {
                "is_initialized": self.is_initialized,
                "startup_time": self.startup_time.isoformat() if self.startup_time else None,
                "uptime_seconds": (datetime.utcnow() - self.startup_time).total_seconds() if self.startup_time else 0
            },
            "processing_stats": {
                "claims_processed": self.processed_claims_count,
                "system_errors_count": len(self.system_errors)
            },
            "component_status": {
                "processors_configured": len(self.processors),
                "reference_data_loaded": self.reference_manager.is_data_loaded() if self.reference_manager else False,
                "audit_logger_enabled": self.audit_logger is not None
            },
            "processor_info": {
                step.value: processor.get_processing_info() 
                for step, processor in self.processors.items()
            },
            "recent_errors": self.system_errors[-10:] if self.system_errors else []
        }
    
    def _execute_processing_step(self, step: ProcessingStep, claim: StandardClaim, 
                                context: Dict[str, Any]) -> ProcessorResult:
        """Execute a single processing step with error handling and logging"""
        
        processor = self.processors.get(step)
        if not processor:
            raise ConfigurationError(f"No processor configured for step: {step.value}")
        
        try:
            self._log_decision(claim.claim_id, f"STEP_{step.value}_STARTED", f"Starting {step.value}")
            
            # Add reference manager to context
            context['reference_manager'] = self.reference_manager
            
            # Execute processor
            result = processor.process(claim, context)
            result.processing_step = step
            
            self._log_decision(claim.claim_id, f"STEP_{step.value}_COMPLETED", 
                             f"Step {step.value} completed - Success: {result.success}")
            
            return result
            
        except Exception as e:
            error_message = f"Step {step.value} failed: {str(e)}"
            self._log_decision(claim.claim_id, f"STEP_{step.value}_ERROR", error_message)
            
            # Create error result
            error_result = ProcessorResult(
                success=False,
                processing_step=step
            )
            error_result.add_error(
                ValidationSeverity.CRITICAL,
                f"PROCESSING_STEP_ERROR_{step.value}",
                error_message
            )
            
            return error_result
    
    def _create_final_decision(self, claim: StandardClaim, business_rules_result: ProcessorResult,
                             decision: ClaimDecision, start_time: float) -> ClaimDecision:
        """Create the final claim decision based on processing results"""
        
        # Extract calculation result from business rules
        calculation_result = business_rules_result.data.get('calculation_result', CalculationResult())
        
        # Determine final status
        if business_rules_result.success and not business_rules_result.has_critical_errors():
            if calculation_result.total_denied > 0:
                status = ClaimStatus.PARTIALLY_APPROVED
                reason = DecisionReason.PARTIAL_APPROVAL_WITH_DENIALS
                rationale = f"Claim partially approved. Approved: {calculation_result.total_approved}, Denied: {calculation_result.total_denied}"
            else:
                status = ClaimStatus.APPROVED
                reason = DecisionReason.ALL_VALIDATIONS_PASSED
                rationale = f"Claim fully approved. Total amount: {calculation_result.total_approved}"
        else:
            status = ClaimStatus.REJECTED
            reason = DecisionReason.INVALID_INPUT_DATA
            rationale = "Claim rejected due to business rule violations"
        
        # Update decision
        decision.status = status
        decision.decision_reason = reason
        decision.decision_rationale = rationale
        decision.calculation_result = calculation_result
        
        # Add validation issues from business rules
        for error in business_rules_result.errors:
            decision.add_validation_issue(error)
        
        for warning in business_rules_result.warnings:
            decision.add_validation_issue(warning)
        
        # Extract G-DRG information
        decision.final_gdrg = business_rules_result.data.get('final_gdrg')
        decision.gdrg_determination_method = business_rules_result.data.get('gdrg_determination_method')
        decision.age_suffix_applied = business_rules_result.data.get('age_suffix_applied')
        
        # Extract required documents
        decision.required_documents = business_rules_result.data.get('required_documents', [])
        
        # Extract episode information
        decision.episode_information = business_rules_result.data.get('episode_information', {})
        
        # Calculate total processing time
        decision.total_processing_time_ms = (time.time() - start_time) * 1000
        
        return decision
    
    def _create_rejection_decision(self, claim_id: str, reason: DecisionReason, 
                                 rationale: str, errors: List[ValidationIssue], 
                                 start_time: float) -> ClaimDecision:
        """Create a rejection decision"""
        
        decision = ClaimDecision(
            claim_id=claim_id,
            status=ClaimStatus.REJECTED,
            decision_reason=reason,
            decision_rationale=rationale,
            calculation_result=CalculationResult(),
            total_processing_time_ms=(time.time() - start_time) * 1000
        )
        
        # Add all errors as validation issues
        for error in errors:
            decision.add_validation_issue(error)
        
        return decision
    
    def _create_error_decision(self, claim_id: str, error_message: str, start_time: float) -> ClaimDecision:
        """Create an error decision for unexpected failures"""
        
        decision = ClaimDecision(
            claim_id=claim_id,
            status=ClaimStatus.REJECTED,
            decision_reason=DecisionReason.INVALID_INPUT_DATA,
            decision_rationale=f"System error: {error_message}",
            calculation_result=CalculationResult(),
            total_processing_time_ms=(time.time() - start_time) * 1000
        )
        
        # Add error as validation issue
        error_issue = ValidationIssue(
            severity=ValidationSeverity.CRITICAL,
            code="SYSTEM_ERROR",
            message=error_message
        )
        decision.add_validation_issue(error_issue)
        
        return decision
    
    def _get_claims_for_batch(self, batch_id: str) -> List[Any]:
        """
        Get claims for a batch. This would typically query the database.
        
        Args:
            batch_id: Batch identifier
            
        Returns:
            List of claim records (ClaimV2 instances)
        """
        # This is a placeholder - in real implementation this would:
        # 1. Get database connection from context
        # 2. Query claims_v2 table by batch_id
        # 3. Return list of ClaimV2 records
        
        # For now, return empty list
        return []
    
    def _validate_configuration(self) -> None:
        """Validate system configuration"""
        
        required_steps = [
            ProcessingStep.INTAKE_NORMALIZATION,
            ProcessingStep.ELIGIBILITY_COVERAGE,
            ProcessingStep.SETTING_ROUTER,
            ProcessingStep.CREDENTIALING_CHECK,
            ProcessingStep.BUSINESS_RULES_CALCULATION
        ]
        
        for step in required_steps:
            if step not in self.processors:
                raise ConfigurationError(f"Missing processor for required step: {step.value}")
        
        if not self.reference_manager:
            raise ConfigurationError("Reference manager is required")
    
    def _initialize_system(self) -> None:
        """Initialize the expert system"""
        
        try:
            # Load reference data
            if not self.reference_manager.load_reference_data():
                raise ReferenceDataError("Failed to load reference data")
            
            # Mark as initialized
            self.is_initialized = True
            self.startup_time = datetime.utcnow()
            
            self._log_decision("SYSTEM", "SYSTEM_INITIALIZED", "Expert system initialized successfully")
            
        except Exception as e:
            error_message = f"System initialization failed: {str(e)}"
            self.system_errors.append(error_message)
            raise ConfigurationError(error_message)
    
    def _log_decision(self, claim_id: str, step: str, decision: str, details: Dict[str, Any] = None) -> None:
        """Log a decision point"""
        
        if self.audit_logger:
            try:
                self.audit_logger.log_decision(claim_id, step, decision, details)
            except Exception as e:
                # Don't fail processing due to logging errors
                self.system_errors.append(f"Audit logging failed: {str(e)}")
    
    def get_expert_system_info(self) -> Dict[str, Any]:
        """Get expert system metadata"""
        return {
            "name": "NHIS Expert System",
            "version": "1.0.0",
            "processors_count": len(self.processors),
            "claim_adapter": self.claim_adapter.get_adapter_info() if hasattr(self.claim_adapter, 'get_adapter_info') else None,
            "reference_manager_available": self.reference_manager is not None,
            "audit_logger_available": self.audit_logger is not None
        }


# Factory functions for creating expert system instances

def create_expert_system(processors: Dict[ProcessingStep, BaseProcessor],
                        reference_manager: BaseReferenceManager,
                        audit_logger: Optional[BaseAuditLogger] = None,
                        claim_adapter: Optional[BaseClaimAdapter] = None) -> NHISExpertSystem:
    """
    Factory function to create a configured expert system instance.
    
    Args:
        processors: Configured processors for each step
        reference_manager: Reference data manager
        audit_logger: Optional audit logger
        claim_adapter: Optional custom claim adapter
        
    Returns:
        Configured NHISExpertSystem instance
    """
    return NHISExpertSystem(
        processors=processors,
        reference_manager=reference_manager,
        audit_logger=audit_logger,
        claim_adapter=claim_adapter
    )


def create_minimal_expert_system() -> NHISExpertSystem:
   
    
    raise NotImplementedError("Minimal expert system creation requires mock implementations")