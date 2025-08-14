"""
Eligibility Processor - Step 2: Eligibility & Coverage

Handles the second step of claim processing:
- Check if service is excluded from benefits
- Verify service is in NHIS benefit package
- Validate coverage eligibility

Flowchart nodes: CheckExclusions, CheckBenefits
"""

from typing import Dict, List, Any

from ..core import StandardClaim, ValidationIssue, ValidationSeverity, ProcessingStep
from .base_processor import ProcessorBase


class EligibilityProcessor(ProcessorBase):
    """
    Step 2: Eligibility & Coverage Processor
    
    Determines if a service is eligible for NHIS coverage
    by checking exclusions and benefit package inclusion.
    """
    
    def __init__(self):
        super().__init__("EligibilityProcessor", ProcessingStep.ELIGIBILITY_COVERAGE)
    
    def validate_inputs(self, claim: StandardClaim, context: Dict[str, Any] = None) -> List[ValidationIssue]:
        """
        Validate inputs specific to eligibility processing.
        
        Args:
            claim: Claim to validate
            context: Processing context from intake
            
        Returns:
            List of validation issues
        """
        
        issues = []
        
        # Call base validation
        issues.extend(super().validate_inputs(claim, context))
        
        # Check that intake processing was successful
        if context:
            mapping_status = context.get('mapping_status')
            if mapping_status == 'NO_CANDIDATES_FOUND':
                issues.append(self._create_validation_issue(
                    ValidationSeverity.CRITICAL,
                    "NO_GDRG_CANDIDATES",
                    "No valid G-DRG candidates found during intake",
                    {"icd10_code": claim.icd10_diagnosis}
                ))
        
        return issues
    
    def _execute_processing(self, claim: StandardClaim, context: Dict[str, Any]) -> Dict[str, Any]:
        """
        Execute eligibility and coverage processing.
        
        Args:
            claim: Claim to process
            context: Processing context from intake
            
        Returns:
            Processing results
        """
        
        processing_data = {}
        
        # Get normalized ICD-10 from intake processing
        normalized_icd10 = context.get('normalized_icd10', claim.icd10_diagnosis)
        encounter_type = claim.encounter_type.value
        
        # Step 1: Check service exclusions (CheckExclusions flowchart node)
        exclusion_result = self._check_service_exclusions(normalized_icd10, encounter_type, claim)
        processing_data.update(exclusion_result)
        
        if exclusion_result['is_excluded']:
            # Service is excluded - will cause rejection
            processing_data['eligibility_status'] = 'EXCLUDED'
            processing_data['rejection_reason'] = 'SERVICE_EXCLUDED'
            
            self._log_processing_step(
                "SERVICE_EXCLUDED",
                f"Service {normalized_icd10} is excluded from benefits",
                {"exclusion_reason": exclusion_result['exclusion_reason']}
            )
            
            return processing_data
        
        # Step 2: Check benefit package inclusion (CheckBenefits flowchart node)
        benefit_result = self._check_benefit_package_inclusion(normalized_icd10, encounter_type, claim)
        processing_data.update(benefit_result)
        
        if not benefit_result['is_covered']:
            # Service not in benefit package - will cause rejection
            processing_data['eligibility_status'] = 'NOT_COVERED'
            processing_data['rejection_reason'] = 'NOT_IN_BENEFIT_PACKAGE'
            
            self._log_processing_step(
                "SERVICE_NOT_COVERED",
                f"Service {normalized_icd10} not in NHIS benefit package",
                {"encounter_type": encounter_type}
            )
            
            return processing_data
        
        # Step 3: Additional eligibility checks
        additional_checks = self._perform_additional_eligibility_checks(claim, context)
        processing_data.update(additional_checks)
        
        # Step 4: Determine final eligibility status
        if processing_data.get('has_eligibility_warnings', False):
            processing_data['eligibility_status'] = 'ELIGIBLE_WITH_WARNINGS'
        else:
            processing_data['eligibility_status'] = 'ELIGIBLE'
        
        self._log_processing_step(
            "ELIGIBILITY_CONFIRMED", 
            f"Service {normalized_icd10} is eligible for coverage",
            {"status": processing_data['eligibility_status']}
        )
        
        return processing_data
    
    def _check_service_exclusions(self, icd10_code: str, encounter_type: str, 
                                 claim: StandardClaim) -> Dict[str, Any]:
        """
        Check if service is excluded from NHIS benefits.
        Implements CheckExclusions flowchart node.
        
        Args:
            icd10_code: ICD-10 diagnosis code
            encounter_type: Type of encounter
            claim: Full claim data
            
        Returns:
            Exclusion check results
        """
        
        result = {
            'is_excluded': False,
            'exclusion_reason': None,
            'exclusion_details': {}
        }
        
        if not self._check_reference_data_available():
            # If reference data not available, assume not excluded
            result['exclusion_details']['warning'] = 'Reference data not available for exclusion check'
            return result
        
        # Check using reference manager
        is_excluded = self.reference_manager.is_service_excluded(icd10_code, encounter_type)
        
        if is_excluded:
            result['is_excluded'] = True
            result['exclusion_reason'] = 'Service excluded from NHIS benefit package'
            result['exclusion_details'] = {
                'icd10_code': icd10_code,
                'encounter_type': encounter_type,
                'exclusion_type': 'GENERAL_EXCLUSION'
            }
        
        # Additional exclusion checks based on claim characteristics
        additional_exclusions = self._check_additional_exclusions(claim)
        if additional_exclusions['is_excluded']:
            result.update(additional_exclusions)
        
        return result
    
    def _check_additional_exclusions(self, claim: StandardClaim) -> Dict[str, Any]:
        """
        Check for additional exclusion criteria beyond ICD-10 code.
        
        Args:
            claim: Claim to check
            
        Returns:
            Additional exclusion results
        """
        
        result = {
            'is_excluded': False,
            'exclusion_reason': None,
            'exclusion_details': {}
        }
        
        # Check for cosmetic procedures (example exclusion logic)
        cosmetic_indicators = ['cosmetic', 'aesthetic', 'beauty', 'plastic surgery']
        diagnosis_text = (claim.diagnosis_name or '').lower()
        
        if any(indicator in diagnosis_text for indicator in cosmetic_indicators):
            result['is_excluded'] = True
            result['exclusion_reason'] = 'Cosmetic procedures not covered'
            result['exclusion_details'] = {
                'exclusion_type': 'COSMETIC_PROCEDURE',
                'diagnosis_text': claim.diagnosis_name
            }
            return result
        
        # Check for experimental treatments
        experimental_indicators = ['experimental', 'investigational', 'trial']
        if any(indicator in diagnosis_text for indicator in experimental_indicators):
            result['is_excluded'] = True
            result['exclusion_reason'] = 'Experimental treatments not covered'
            result['exclusion_details'] = {
                'exclusion_type': 'EXPERIMENTAL_TREATMENT',
                'diagnosis_text': claim.diagnosis_name
            }
            return result
        
        # Check age-based exclusions
        if claim.patient_age > 100:
            result['is_excluded'] = True
            result['exclusion_reason'] = 'Patient age exceeds coverage limits'
            result['exclusion_details'] = {
                'exclusion_type': 'AGE_LIMIT_EXCEEDED',
                'patient_age': claim.patient_age
            }
        
        return result
    
    def _check_benefit_package_inclusion(self, icd10_code: str, encounter_type: str,
                                       claim: StandardClaim) -> Dict[str, Any]:
        """
        Check if service is included in NHIS benefit package.
        Implements CheckBenefits flowchart node.
        
        Args:
            icd10_code: ICD-10 diagnosis code
            encounter_type: Type of encounter
            claim: Full claim data
            
        Returns:
            Benefit package inclusion results
        """
        
        result = {
            'is_covered': False,
            'coverage_details': {},
            'coverage_limitations': []
        }
        
        if not self._check_reference_data_available():
            # If reference data not available, assume not covered
            result['coverage_details']['warning'] = 'Reference data not available for coverage check'
            return result
        
        # Check using reference manager
        is_covered = self.reference_manager.is_in_benefit_package(icd10_code, encounter_type)
        
        if is_covered:
            result['is_covered'] = True
            
            # Get coverage details from G-DRG mapping
            mapping = self.reference_manager.get_gdrg_for_diagnosis(icd10_code, encounter_type)
            if mapping:
                result['coverage_details'] = {
                    'gdrg_code': mapping['gdrg_code'],
                    'gdrg_description': mapping.get('gdrg_description'),
                    'eligible_facilities': mapping.get('eligible_facilities', []),
                    'requires_specialist': mapping.get('requires_specialist', False),
                    'is_chronic': mapping.get('is_chronic', False)
                }
                
                # Check for coverage limitations
                limitations = self._check_coverage_limitations(mapping, claim)
                result['coverage_limitations'] = limitations
        
        return result
    
    def _check_coverage_limitations(self, gdrg_mapping: Dict[str, Any], 
                                  claim: StandardClaim) -> List[str]:
        """
        Check for any limitations on coverage for this service.
        
        Args:
            gdrg_mapping: G-DRG mapping information
            claim: Claim data
            
        Returns:
            List of coverage limitations
        """
        
        limitations = []
        
        # Check age restrictions
        age_restrictions = gdrg_mapping.get('age_restrictions')
        if age_restrictions:
            min_age = age_restrictions.get('min_age')
            max_age = age_restrictions.get('max_age')
            
            if min_age and claim.patient_age < min_age:
                limitations.append(f"Patient age {claim.patient_age} below minimum age {min_age}")
            
            if max_age and claim.patient_age > max_age:
                limitations.append(f"Patient age {claim.patient_age} above maximum age {max_age}")
        
        # Check facility level requirements
        eligible_facilities = gdrg_mapping.get('eligible_facilities', [])
        facility_level = claim.facility_level
        
        if facility_level and eligible_facilities and facility_level not in eligible_facilities:
            limitations.append(f"Facility level {facility_level} not authorized for this service")
        
        # Check specialist requirements
        requires_specialist = gdrg_mapping.get('requires_specialist', False)
        if requires_specialist:
            limitations.append("Service requires specialist care")
        
        return limitations
    
    def _perform_additional_eligibility_checks(self, claim: StandardClaim, 
                                             context: Dict[str, Any]) -> Dict[str, Any]:
        """
        Perform additional eligibility checks beyond basic inclusion/exclusion.
        
        Args:
            claim: Claim to check
            context: Processing context
            
        Returns:
            Additional eligibility results
        """
        
        result = {
            'has_eligibility_warnings': False,
            'eligibility_warnings': [],
            'eligibility_notes': []
        }
        
        # Check for complex cases that may need special handling
        if context.get('is_complex_claim', False):
            result['eligibility_warnings'].append('Complex claim may require additional review')
            result['has_eligibility_warnings'] = True
        
        # Check for emergency cases
        if claim.is_emergency_encounter():
            result['eligibility_notes'].append('Emergency encounter - expedited processing')
        
        # Check for chronic condition management
        if self.reference_manager and self.reference_manager.is_chronic_condition(claim.icd10_diagnosis):
            result['eligibility_notes'].append('Chronic condition - subject to visit limits')
        
        # Check for pediatric cases
        if claim.patient_age < 18:
            result['eligibility_notes'].append('Pediatric case - special considerations may apply')
        
        # Check for geriatric cases  
        if claim.patient_age >= 65:
            result['eligibility_notes'].append('Geriatric case - additional coverage may be available')
        
        return result
    
    def get_exclusion_categories(self) -> List[str]:
        """Get list of exclusion categories checked by this processor"""
        return [
            'GENERAL_EXCLUSIONS',
            'COSMETIC_PROCEDURES', 
            'EXPERIMENTAL_TREATMENTS',
            'AGE_LIMIT_EXCLUSIONS',
            'SERVICE_NOT_IN_PACKAGE'
        ]
    
    def get_eligibility_processor_info(self) -> Dict[str, Any]:
        """Get processor-specific information"""
        
        info = self.get_processor_metadata()
        info.update({
            "exclusion_categories": self.get_exclusion_categories(),
            "processing_steps": [
                "Check service exclusions",
                "Verify benefit package inclusion", 
                "Check coverage limitations",
                "Perform additional eligibility checks"
            ],
            "flowchart_nodes": [
                "CheckExclusions",
                "CheckBenefits"
            ]
        })
        
        return info