"""
Base Processor Implementation

Provides common functionality for all processors in the 5-step pipeline.
Implements timing, logging, and error handling shared across processors.
"""

import time
from typing import Dict, List, Any, Optional
from abc import abstractmethod

from ..core import (
    BaseProcessor, StandardClaim, ProcessorResult, ValidationIssue,
    ValidationSeverity, ProcessingStep, BaseReferenceManager
)


class ProcessorBase(BaseProcessor):
    """
    Base implementation for all processors.
    
    Provides common functionality:
    - Timing and performance tracking
    - Standardized error handling
    - Reference data access
    - Validation utilities
    """
    
    def __init__(self, name: str, processing_step: ProcessingStep):
        super().__init__(name, processing_step)
        self.reference_manager: Optional[BaseReferenceManager] = None
        
    def process(self, claim: StandardClaim, context: Dict[str, Any] = None) -> ProcessorResult:
        """
        Main processing method with timing and error handling.
        
        Args:
            claim: Standardized claim data
            context: Processing context from previous steps
            
        Returns:
            ProcessorResult with success status and data
        """
        
        # Initialize context if not provided
        if context is None:
            context = {}
        
        # Extract reference manager from context
        self.reference_manager = context.get('reference_manager')
        
        # Start timing
        self._start_processing()
        
        # Create result object
        result = ProcessorResult(
            success=False,
            processing_step=self.processing_step
        )
        
        try:
            # Validate inputs first
            validation_issues = self.validate_inputs(claim, context)
            
            # Add validation issues to result
            for issue in validation_issues:
                if issue.severity == ValidationSeverity.CRITICAL:
                    result.errors.append(issue)
                else:
                    result.warnings.append(issue)
            
            # Check if critical errors prevent processing
            if result.has_critical_errors():
                result.success = False
                result.processing_time_ms = self._end_processing()
                return result
            
            # Execute the actual processing logic
            processing_data = self._execute_processing(claim, context)
            
            # Update result with processing data
            result.data.update(processing_data)
            result.success = True
            
        except Exception as e:
            # Handle unexpected errors
            error_issue = ValidationIssue(
                severity=ValidationSeverity.CRITICAL,
                code=f"{self.processing_step.value}_PROCESSING_ERROR",
                message=f"Unexpected error in {self.name}: {str(e)}",
                processing_step=self.processing_step
            )
            result.errors.append(error_issue)
            result.success = False
        
        finally:
            # Record processing time
            result.processing_time_ms = self._end_processing()
        
        return result
    
    @abstractmethod
    def _execute_processing(self, claim: StandardClaim, context: Dict[str, Any]) -> Dict[str, Any]:
        """
        Execute the specific processing logic for this processor.
        
        This method must be implemented by each concrete processor.
        
        Args:
            claim: Claim to process
            context: Processing context
            
        Returns:
            Dictionary of processing results to add to context
        """
        pass
    
    def validate_inputs(self, claim: StandardClaim, context: Dict[str, Any] = None) -> List[ValidationIssue]:
        """
        Validate inputs before processing.
        
        Default implementation provides basic validation.
        Processors can override for specific validation needs.
        
        Args:
            claim: Claim to validate
            context: Processing context
            
        Returns:
            List of validation issues found
        """
        
        issues = []
        
        # Basic claim validation
        if not claim.claim_id:
            issues.append(self._create_validation_issue(
                ValidationSeverity.CRITICAL,
                "MISSING_CLAIM_ID",
                "Claim ID is required"
            ))
        
        if not claim.facility_id:
            issues.append(self._create_validation_issue(
                ValidationSeverity.CRITICAL,
                "MISSING_FACILITY_ID", 
                "Facility ID is required"
            ))
        
        if not claim.icd10_diagnosis:
            issues.append(self._create_validation_issue(
                ValidationSeverity.CRITICAL,
                "MISSING_ICD10_DIAGNOSIS",
                "ICD-10 diagnosis is required"
            ))
        
        # Check reference manager availability
        if not self.reference_manager:
            issues.append(self._create_validation_issue(
                ValidationSeverity.CRITICAL,
                "MISSING_REFERENCE_MANAGER",
                "Reference manager not available"
            ))
        elif not self.reference_manager.is_data_loaded():
            issues.append(self._create_validation_issue(
                ValidationSeverity.CRITICAL,
                "REFERENCE_DATA_NOT_LOADED",
                "Reference data not loaded"
            ))
        
        return issues
    
    def _create_validation_issue(self, severity: ValidationSeverity, code: str, 
                               message: str, details: Dict[str, Any] = None) -> ValidationIssue:
        """
        Helper method to create validation issues.
        
        Args:
            severity: Issue severity
            code: Error code
            message: Error message
            details: Additional details
            
        Returns:
            ValidationIssue object
        """
        
        return ValidationIssue(
            severity=severity,
            code=code,
            message=message,
            details=details or {},
            processing_step=self.processing_step,
            rule_reference=self.name
        )
    
    def _check_reference_data_available(self) -> bool:
        """Check if reference data is available for use"""
        return (self.reference_manager is not None and 
                self.reference_manager.is_data_loaded())
    
    def _get_reference_mapping(self, mapping_type: str, key: str) -> Optional[Dict[str, Any]]:
        """
        Get reference data mapping with error handling.
        
        Args:
            mapping_type: Type of mapping
            key: Lookup key
            
        Returns:
            Mapping data or None if not found
        """
        
        if not self._check_reference_data_available():
            return None
        
        try:
            return self.reference_manager.get_mapping(mapping_type, key)
        except Exception:
            return None
    
    def _validate_encounter_type(self, claim: StandardClaim) -> List[ValidationIssue]:
        """Validate encounter type is supported"""
        
        issues = []
        
        valid_encounter_types = ['OPD', 'IPD', 'A&E', 'EMERGENCY', 'CASUALTY']
        
        if claim.encounter_type.value not in valid_encounter_types:
            issues.append(self._create_validation_issue(
                ValidationSeverity.CRITICAL,
                "INVALID_ENCOUNTER_TYPE",
                f"Unsupported encounter type: {claim.encounter_type.value}",
                {"encounter_type": claim.encounter_type.value}
            ))
        
        return issues
    
    def _validate_patient_age(self, claim: StandardClaim) -> List[ValidationIssue]:
        """Validate patient age is reasonable"""
        
        issues = []
        
        if claim.patient_age < 0 or claim.patient_age > 150:
            issues.append(self._create_validation_issue(
                ValidationSeverity.MAJOR,
                "INVALID_PATIENT_AGE",
                f"Patient age seems invalid: {claim.patient_age}",
                {"patient_age": claim.patient_age}
            ))
        
        return issues
    
    def _validate_facility_id_format(self, claim: StandardClaim) -> List[ValidationIssue]:
        """Validate facility ID format"""
        
        issues = []
        
        # Basic facility ID validation - could be enhanced based on actual format requirements
        if len(claim.facility_id) < 3:
            issues.append(self._create_validation_issue(
                ValidationSeverity.MINOR,
                "INVALID_FACILITY_ID_FORMAT",
                f"Facility ID seems too short: {claim.facility_id}",
                {"facility_id": claim.facility_id}
            ))
        
        return issues
    
    def _log_processing_step(self, step: str, message: str, details: Dict[str, Any] = None) -> None:
        """
        Log processing step information.
        
        Args:
            step: Processing step name
            message: Log message  
            details: Additional details
        """
        
        # For now, just print - could be enhanced with proper logging
        log_entry = f"[{self.name}] {step}: {message}"
        if details:
            log_entry += f" - {details}"
        
        # Could integrate with audit logger here
        pass
    
    def get_processor_metadata(self) -> Dict[str, Any]:
        """Get processor metadata and configuration"""
        
        return {
            "name": self.name,
            "processing_step": self.processing_step.value,
            "reference_manager_available": self._check_reference_data_available(),
            "processor_info": self.get_processing_info()
        }