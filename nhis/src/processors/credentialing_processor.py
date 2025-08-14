"""
Credentialing Processor - Step 4: Credentialing & Level Check

Handles the fourth step of claim processing:
- Validate facility level eligibility for claimed G-DRGs
- Check required accreditations
- Verify provider credentials and authorization levels

Flowchart nodes: CheckFacilityRules, CheckAccreditation
"""

from typing import Dict, List, Any

from ..core import StandardClaim, ValidationIssue, ValidationSeverity, ProcessingStep
from .base_processor import ProcessorBase


class CredentialingProcessor(ProcessorBase):
    """
    Step 4: Credentialing & Level Check Processor
    
    Validates that facilities and providers are properly credentialed
    and authorized to provide the claimed services.
    """
    
    def __init__(self):
        super().__init__("CredentialingProcessor", ProcessingStep.CREDENTIALING_CHECK)
    
    def validate_inputs(self, claim: StandardClaim, context: Dict[str, Any] = None) -> List[ValidationIssue]:
        """
        Validate inputs specific to credentialing processing.
        
        Args:
            claim: Claim to validate
            context: Processing context from previous steps
            
        Returns:
            List of validation issues
        """
        
        issues = []
        
        # Call base validation
        issues.extend(super().validate_inputs(claim, context))
        
        # Check that previous steps were successful
        if context:
            eligibility_status = context.get('eligibility_status')
            if eligibility_status in ['EXCLUDED', 'NOT_COVERED']:
                issues.append(self._create_validation_issue(
                    ValidationSeverity.CRITICAL,
                    "INELIGIBLE_SERVICE",
                    f"Service is not eligible: {eligibility_status}",
                    {"eligibility_status": eligibility_status}
                ))
        
        # Validate facility information
        if not claim.facility_level:
            issues.append(self._create_validation_issue(
                ValidationSeverity.MAJOR,
                "MISSING_FACILITY_LEVEL",
                "Facility level information is missing",
                {"facility_id": claim.facility_id}
            ))
        
        return issues
    
    def _execute_processing(self, claim: StandardClaim, context: Dict[str, Any]) -> Dict[str, Any]:
        """
        Execute credentialing and level check processing.
        
        Args:
            claim: Claim to process
            context: Processing context from previous steps
            
        Returns:
            Processing results
        """
        
        processing_data = {}
        
        # Get candidate G-DRGs from intake processing
        candidate_gdrgs = context.get('candidate_gdrgs', [])
        primary_gdrg = context.get('primary_gdrg')
        
        if not candidate_gdrgs:
            processing_data['credentialing_status'] = 'NO_GDRGS_TO_CHECK'
            processing_data['rejection_reason'] = 'NO_VALID_GDRGS'
            return processing_data
        
        # Step 1: Check facility rules for G-DRGs (CheckFacilityRules flowchart node)
        facility_check_result = self._check_facility_eligibility(claim, candidate_gdrgs)
        processing_data.update(facility_check_result)
        
        if not facility_check_result['facility_eligible']:
            # Facility not authorized - will cause rejection
            processing_data['credentialing_status'] = 'FACILITY_NOT_AUTHORIZED'
            processing_data['rejection_reason'] = 'FACILITY_NOT_AUTHORIZED_FOR_GDRG'
            
            self._log_processing_step(
                "FACILITY_NOT_AUTHORIZED",
                f"Facility {claim.facility_id} not authorized for G-DRGs: {candidate_gdrgs}",
                {"facility_level": claim.facility_level, "gdrgs": candidate_gdrgs}
            )
            
            return processing_data
        
        # Step 2: Check accreditation requirements (CheckAccreditation flowchart node)
        accreditation_result = self._check_accreditation_requirements(claim, candidate_gdrgs, context)
        processing_data.update(accreditation_result)
        
        if not accreditation_result['accreditation_valid']:
            # Missing required accreditation - will cause rejection
            processing_data['credentialing_status'] = 'MISSING_ACCREDITATION'
            processing_data['rejection_reason'] = 'MISSING_REQUIRED_ACCREDITATION'
            
            self._log_processing_step(
                "MISSING_ACCREDITATION",
                f"Missing required accreditation for G-DRGs: {candidate_gdrgs}",
                {"required_accreditations": accreditation_result.get('required_accreditations', [])}
            )
            
            return processing_data
        
        # Step 3: Check prescriber level authorization
        prescriber_check_result = self._check_prescriber_authorization(claim, context)
        processing_data.update(prescriber_check_result)
        
        # Step 4: Perform additional credentialing checks
        additional_checks = self._perform_additional_credentialing_checks(claim, context)
        processing_data.update(additional_checks)
        
        # Step 5: Determine final credentialing status
        if processing_data.get('has_credentialing_warnings', False):
            processing_data['credentialing_status'] = 'CREDENTIALED_WITH_WARNINGS'
        else:
            processing_data['credentialing_status'] = 'FULLY_CREDENTIALED'
        
        self._log_processing_step(
            "CREDENTIALING_APPROVED",
            f"Facility {claim.facility_id} is credentialed for services",
            {"status": processing_data['credentialing_status']}
        )
        
        return processing_data
    
    def _check_facility_eligibility(self, claim: StandardClaim, candidate_gdrgs: List[str]) -> Dict[str, Any]:
        """
        Check if facility is eligible to provide the G-DRG services.
        Implements CheckFacilityRules flowchart node.
        
        Args:
            claim: Claim with facility information
            candidate_gdrgs: List of candidate G-DRG codes
            
        Returns:
            Facility eligibility results
        """
        
        result = {
            'facility_eligible': False,
            'eligible_gdrgs': [],
            'ineligible_gdrgs': [],
            'facility_authorization_details': {}
        }
        
        if not self._check_reference_data_available():
            # If reference data not available, assume eligible
            result['facility_eligible'] = True
            result['eligible_gdrgs'] = candidate_gdrgs
            result['facility_authorization_details']['warning'] = 'Reference data not available for facility check'
            return result
        
        facility_level = claim.facility_level
        
        # Check each candidate G-DRG
        for gdrg_code in candidate_gdrgs:
            is_eligible = self.reference_manager.is_facility_eligible_for_gdrg(gdrg_code, facility_level)
            
            if is_eligible:
                result['eligible_gdrgs'].append(gdrg_code)
            else:
                result['ineligible_gdrgs'].append(gdrg_code)
        
        # Facility is eligible if at least one G-DRG is authorized
        result['facility_eligible'] = len(result['eligible_gdrgs']) > 0
        
        # Get facility authorization details
        result['facility_authorization_details'] = {
            'facility_id': claim.facility_id,
            'facility_level': facility_level,
            'total_gdrgs_checked': len(candidate_gdrgs),
            'authorized_gdrgs_count': len(result['eligible_gdrgs']),
            'unauthorized_gdrgs_count': len(result['ineligible_gdrgs'])
        }
        
        # Add eligible facility levels for reference
        if candidate_gdrgs:
            primary_gdrg = candidate_gdrgs[0]
            eligible_facilities = self.reference_manager.get_eligible_facilities(
                claim.icd10_diagnosis, 
                claim.encounter_type.value
            )
            result['facility_authorization_details']['eligible_facility_levels'] = eligible_facilities
        
        return result
    
    def _check_accreditation_requirements(self, claim: StandardClaim, candidate_gdrgs: List[str],
                                        context: Dict[str, Any]) -> Dict[str, Any]:
        """
        Check accreditation requirements for the services.
        Implements CheckAccreditation flowchart node.
        
        Args:
            claim: Claim data
            candidate_gdrgs: List of candidate G-DRG codes
            context: Processing context
            
        Returns:
            Accreditation check results
        """
        
        result = {
            'accreditation_valid': True,
            'required_accreditations': [],
            'missing_accreditations': [],
            'accreditation_details': {}
        }
        
        # Get coverage details from eligibility processing
        coverage_details = context.get('coverage_details', {})
        
        # Check if specialist care is required
        requires_specialist = coverage_details.get('requires_specialist', False)
        
        if requires_specialist:
            result['required_accreditations'].append('SPECIALIST_ACCREDITATION')
            
            # Check if facility/prescriber has specialist accreditation
            # For now, assume specialist accreditation based on facility level
            specialist_levels = ['D1', 'D2', 'M', 'T']  # Levels that typically have specialists
            
            if claim.facility_level not in specialist_levels:
                result['missing_accreditations'].append('SPECIALIST_ACCREDITATION')
                result['accreditation_valid'] = False
        
        # Check for procedure-specific accreditation requirements
        procedure_accreditations = self._check_procedure_accreditation_requirements(claim, candidate_gdrgs)
        result['required_accreditations'].extend(procedure_accreditations['required'])
        result['missing_accreditations'].extend(procedure_accreditations['missing'])
        
        if procedure_accreditations['missing']:
            result['accreditation_valid'] = False
        
        # Emergency service accreditation
        if claim.is_emergency_encounter():
            result['required_accreditations'].append('EMERGENCY_CARE_ACCREDITATION')
            
            # Assume emergency accreditation based on facility type
            emergency_capable_levels = ['C', 'D1', 'D2', 'M', 'T']
            
            if claim.facility_level not in emergency_capable_levels:
                result['missing_accreditations'].append('EMERGENCY_CARE_ACCREDITATION')
                result['accreditation_valid'] = False
        
        # Set accreditation details
        result['accreditation_details'] = {
            'total_required': len(result['required_accreditations']),
            'total_missing': len(result['missing_accreditations']),
            'requires_specialist': requires_specialist,
            'is_emergency': claim.is_emergency_encounter(),
            'facility_level': claim.facility_level
        }
        
        return result
    
    def _check_procedure_accreditation_requirements(self, claim: StandardClaim, 
                                                   candidate_gdrgs: List[str]) -> Dict[str, Any]:
        """
        Check for procedure-specific accreditation requirements.
        
        Args:
            claim: Claim data
            candidate_gdrgs: List of candidate G-DRG codes
            
        Returns:
            Procedure accreditation requirements
        """
        
        result = {
            'required': [],
            'missing': []
        }
        
        # Check for surgery-related G-DRGs that may need surgical accreditation
        surgical_gdrg_prefixes = ['SURG', 'CARD', 'ORTH', 'NEUR']
        
        for gdrg_code in candidate_gdrgs:
            for prefix in surgical_gdrg_prefixes:
                if gdrg_code.startswith(prefix):
                    required_accreditation = f"{prefix}_ACCREDITATION"
                    if required_accreditation not in result['required']:
                        result['required'].append(required_accreditation)
                    
                    # For now, assume surgical accreditation based on facility level
                    surgical_levels = ['C', 'D1', 'D2', 'M', 'T']
                    if claim.facility_level not in surgical_levels:
                        if required_accreditation not in result['missing']:
                            result['missing'].append(required_accreditation)
        
        # Check for maternity services
        maternity_indicators = ['O', 'Z34', 'Z35', 'Z37']  # ICD-10 codes for pregnancy/birth
        if any(claim.icd10_diagnosis.startswith(code) for code in maternity_indicators):
            result['required'].append('MATERNITY_ACCREDITATION')
            
            # Assume maternity accreditation for certain facility levels
            maternity_levels = ['B2', 'C', 'D1', 'D2', 'M', 'T']
            if claim.facility_level not in maternity_levels:
                result['missing'].append('MATERNITY_ACCREDITATION')
        
        return result
    
    def _check_prescriber_authorization(self, claim: StandardClaim, context: Dict[str, Any]) -> Dict[str, Any]:
        """
        Check prescriber authorization levels for medicines.
        
        Args:
            claim: Claim data
            context: Processing context
            
        Returns:
            Prescriber authorization results
        """
        
        result = {
            'prescriber_authorized': True,
            'unauthorized_medicines': [],
            'prescriber_warnings': [],
            'prescriber_details': {}
        }
        
        if not claim.medicines:
            return result
        
        prescriber_level = claim.prescriber_level
        
        if not prescriber_level:
            result['prescriber_warnings'].append('Prescriber level not specified')
            return result
        
        # Check each medicine against prescriber authorization
        for medicine in claim.medicines:
            medicine_code = medicine.get('code')
            if not medicine_code:
                continue
            
            # Get medicine info from reference data
            if self._check_reference_data_available():
                medicine_info = self.reference_manager.get_medicine_info(medicine_code)
                
                if medicine_info:
                    authorized_levels = medicine_info.get('prescribing_levels', [])
                    
                    if authorized_levels and prescriber_level not in authorized_levels:
                        result['unauthorized_medicines'].append({
                            'medicine_code': medicine_code,
                            'medicine_name': medicine_info.get('name'),
                            'required_levels': authorized_levels,
                            'current_level': prescriber_level
                        })
                        result['prescriber_authorized'] = False
        
        result['prescriber_details'] = {
            'prescriber_level': prescriber_level,
            'total_medicines': len(claim.medicines),
            'unauthorized_count': len(result['unauthorized_medicines'])
        }
        
        return result
    
    def _perform_additional_credentialing_checks(self, claim: StandardClaim,
                                               context: Dict[str, Any]) -> Dict[str, Any]:
        """
        Perform additional credentialing checks.
        
        Args:
            claim: Claim data
            context: Processing context
            
        Returns:
            Additional credentialing results
        """
        
        result = {
            'has_credentialing_warnings': False,
            'credentialing_warnings': [],
            'credentialing_notes': []
        }
        
        # Check for facility type consistency
        if claim.encounter_type.value == 'IPD' and claim.facility_level in ['A', 'B1']:
            result['credentialing_warnings'].append(
                f'Inpatient care at {claim.facility_level} level facility may require review'
            )
            result['has_credentialing_warnings'] = True
        
        # Check for high-risk procedures at lower-level facilities
        if context.get('is_complex_claim', False) and claim.facility_level in ['A', 'B1', 'B2']:
            result['credentialing_warnings'].append(
                'Complex claim at lower-level facility may require additional authorization'
            )
            result['has_credentialing_warnings'] = True
        
        # Check for pediatric care authorization
        if claim.patient_age < 18 and claim.facility_level in ['A', 'B1']:
            result['credentialing_notes'].append('Pediatric care - verify appropriate facilities available')
        
        # Check for geriatric care considerations
        if claim.patient_age >= 65 and len(claim.medicines) > 5:
            result['credentialing_notes'].append('Geriatric polypharmacy - consider medication review')
        
        return result
    
    def get_facility_level_hierarchy(self) -> List[str]:
        """Get facility level hierarchy from lowest to highest capability"""
        return ['A', 'B1', 'B2', 'C', 'D1', 'D2', 'M', 'T']
    
    def get_prescriber_level_hierarchy(self) -> List[str]:
        """Get prescriber level hierarchy from lowest to highest authorization"""
        return ['A', 'B2', 'C', 'D1', 'D2']
    
    def get_credentialing_processor_info(self) -> Dict[str, Any]:
        """Get processor-specific information"""
        
        info = self.get_processor_metadata()
        info.update({
            "facility_levels": self.get_facility_level_hierarchy(),
            "prescriber_levels": self.get_prescriber_level_hierarchy(),
            "processing_steps": [
                "Check facility eligibility for G-DRGs",
                "Verify accreditation requirements",
                "Validate prescriber authorization",
                "Perform additional credentialing checks"
            ],
            "flowchart_nodes": [
                "CheckFacilityRules",
                "CheckAccreditation"
            ],
            "accreditation_types": [
                "SPECIALIST_ACCREDITATION",
                "EMERGENCY_CARE_ACCREDITATION", 
                "SURGICAL_ACCREDITATION",
                "MATERNITY_ACCREDITATION"
            ]
        })
        
        return info