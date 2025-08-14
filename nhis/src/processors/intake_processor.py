

from typing import Dict, List, Any
import re

from ..core import StandardClaim, ValidationIssue, ValidationSeverity, ProcessingStep
from .base_processor import ProcessorBase


class IntakeProcessor(ProcessorBase):
    
    
    def __init__(self):
        super().__init__("IntakeProcessor", ProcessingStep.INTAKE_NORMALIZATION)
    
    def validate_inputs(self, claim: StandardClaim, context: Dict[str, Any] = None) -> List[ValidationIssue]:
        
        
        issues = []
        
        # Call base validation first
        issues.extend(super().validate_inputs(claim, context))
        
        # Intake-specific validations
        issues.extend(self._validate_encounter_type(claim))
        issues.extend(self._validate_patient_age(claim))
        issues.extend(self._validate_facility_id_format(claim))
        issues.extend(self._validate_icd10_format(claim))
        issues.extend(self._validate_visit_date(claim))
        
        return issues
    
    def _execute_processing(self, claim: StandardClaim, context: Dict[str, Any]) -> Dict[str, Any]:
        
        
        processing_data = {}
        
        # Step 1: Normalize ICD-10 code
        normalized_icd10 = self._normalize_icd10_code(claim.icd10_diagnosis)
        processing_data['normalized_icd10'] = normalized_icd10
        
        # Step 2: Map ICD-10 to candidate G-DRGs (MapICD10 flowchart node)
        candidate_gdrgs = self._map_icd10_to_candidate_gdrgs(
            normalized_icd10, 
            claim.encounter_type.value
        )
        
        processing_data['candidate_gdrgs'] = candidate_gdrgs
        processing_data['candidate_gdrg_count'] = len(candidate_gdrgs)
        
        # Step 3: Check if candidates found (CheckCandidates flowchart node)
        if not candidate_gdrgs:
            # This will cause rejection in the expert system
            processing_data['mapping_status'] = 'NO_CANDIDATES_FOUND'
            processing_data['rejection_reason'] = 'NO_VALID_GDRGS'
        else:
            processing_data['mapping_status'] = 'CANDIDATES_FOUND'
            processing_data['primary_gdrg'] = candidate_gdrgs[0] if candidate_gdrgs else None
        
        # Step 4: Extract additional claim metadata
        processing_data.update(self._extract_claim_metadata(claim))
        
        # Step 5: Validate claimed G-DRGs against candidates
        validation_result = self._validate_claimed_gdrgs(claim, candidate_gdrgs)
        processing_data.update(validation_result)
        
        self._log_processing_step(
            "INTAKE_COMPLETE",
            f"Mapped {normalized_icd10} to {len(candidate_gdrgs)} candidate G-DRGs",
            {"candidates": candidate_gdrgs}
        )
        
        return processing_data
    
    def _validate_icd10_format(self, claim: StandardClaim) -> List[ValidationIssue]:
        """Validate ICD-10 code format"""
        
        issues = []
        icd10 = claim.icd10_diagnosis
        
        if not icd10:
            return issues  # Already handled in base validation
        
        # Basic ICD-10 format validation (Letter followed by numbers)
        if not re.match(r'^[A-Z]\d{2}', icd10):
            issues.append(self._create_validation_issue(
                ValidationSeverity.MAJOR,
                "INVALID_ICD10_FORMAT",
                f"ICD-10 code format invalid: {icd10}",
                {"icd10_code": icd10}
            ))
        
        # Check length
        if len(icd10) < 3 or len(icd10) > 7:
            issues.append(self._create_validation_issue(
                ValidationSeverity.MINOR,
                "ICD10_LENGTH_WARNING",
                f"ICD-10 code length unusual: {icd10}",
                {"icd10_code": icd10, "length": len(icd10)}
            ))
        
        return issues
    
    def _validate_visit_date(self, claim: StandardClaim) -> List[ValidationIssue]:
        """Validate visit date is reasonable"""
        
        issues = []
        
        if not claim.visit_date:
            issues.append(self._create_validation_issue(
                ValidationSeverity.CRITICAL,
                "MISSING_VISIT_DATE",
                "Visit date is required"
            ))
        else:
            # Check if visit date is in the future
            from datetime import date
            if claim.visit_date > date.today():
                issues.append(self._create_validation_issue(
                    ValidationSeverity.MAJOR,
                    "FUTURE_VISIT_DATE",
                    f"Visit date is in the future: {claim.visit_date}",
                    {"visit_date": str(claim.visit_date)}
                ))
            
            # Check if visit date is too old (more than 2 years ago)
            from datetime import timedelta
            two_years_ago = date.today() - timedelta(days=730)
            if claim.visit_date < two_years_ago:
                issues.append(self._create_validation_issue(
                    ValidationSeverity.MINOR,
                    "OLD_VISIT_DATE",
                    f"Visit date is very old: {claim.visit_date}",
                    {"visit_date": str(claim.visit_date)}
                ))
        
        return issues
    
    def _normalize_icd10_code(self, icd10_code: str) -> str:
        
        
        if not icd10_code:
            return ""
        
        # Remove whitespace and convert to uppercase
        normalized = icd10_code.strip().upper()
        
        # Remove any non-alphanumeric characters except dots
        normalized = re.sub(r'[^A-Z0-9.]', '', normalized)
        
        return normalized
    
    def _map_icd10_to_candidate_gdrgs(self, icd10_code: str, encounter_type: str) -> List[str]:
        
        
        if not self._check_reference_data_available():
            return []
        
        candidates = []
        
        # Direct lookup first
        mapping = self.reference_manager.get_gdrg_for_diagnosis(icd10_code, encounter_type)
        if mapping:
            candidates.append(mapping['gdrg_code'])
        
        # If no direct match, try prefix matching for more specific codes
        if not candidates:
            candidates = self._try_prefix_matching(icd10_code, encounter_type)
        
        # Remove duplicates while preserving order
        seen = set()
        unique_candidates = []
        for candidate in candidates:
            if candidate not in seen:
                seen.add(candidate)
                unique_candidates.append(candidate)
        
        return unique_candidates
    
    def _try_prefix_matching(self, icd10_code: str, encounter_type: str) -> List[str]:
        
        
        candidates = []
        
        # Try progressively shorter prefixes
        for length in range(len(icd10_code) - 1, 2, -1):  # Down to 3 characters minimum
            prefix = icd10_code[:length]
            mapping = self.reference_manager.get_gdrg_for_diagnosis(prefix, encounter_type)
            if mapping:
                candidates.append(mapping['gdrg_code'])
                break  # Take the first (most specific) match
        
        return candidates
    
    def _extract_claim_metadata(self, claim: StandardClaim) -> Dict[str, Any]:
       
        
        metadata = {
            'has_procedures': len(claim.procedures) > 0,
            'has_medicines': len(claim.medicines) > 0,
            'has_investigations': len(claim.investigations) > 0,
            'procedure_count': len(claim.procedures),
            'medicine_count': len(claim.medicines),
            'investigation_count': len(claim.investigations),
            'is_emergency': claim.is_emergency_encounter(),
            'age_suffix': claim.get_age_suffix(),
            'length_of_stay': claim.get_length_of_stay()
        }
        
        # Check if this is a complex claim
        total_components = metadata['procedure_count'] + metadata['medicine_count'] + metadata['investigation_count']
        metadata['is_complex_claim'] = total_components > 5
        
        # Determine if requires special handling
        metadata['requires_special_handling'] = (
            metadata['is_emergency'] or 
            metadata['is_complex_claim'] or
            claim.patient_age < 2 or 
            claim.patient_age > 85
        )
        
        return metadata
    
    def _validate_claimed_gdrgs(self, claim: StandardClaim, candidate_gdrgs: List[str]) -> Dict[str, Any]:
        
        
        result = {
            'claimed_gdrgs_valid': True,
            'invalid_claimed_gdrgs': [],
            'valid_claimed_gdrgs': [],
            'gdrg_validation_issues': []
        }
        
        for claimed_gdrg in claim.claimed_gdrgs:
            if claimed_gdrg in candidate_gdrgs:
                result['valid_claimed_gdrgs'].append(claimed_gdrg)
            else:
                result['invalid_claimed_gdrgs'].append(claimed_gdrg)
                result['claimed_gdrgs_valid'] = False
                result['gdrg_validation_issues'].append(
                    f"Claimed G-DRG {claimed_gdrg} not valid for {claim.icd10_diagnosis}"
                )
        
        return result
    
    def get_supported_encounter_types(self) -> List[str]:
        """Get list of supported encounter types"""
        return ['OPD', 'IPD', 'A&E', 'EMERGENCY', 'CASUALTY']
    
    def get_intake_processor_info(self) -> Dict[str, Any]:
        """Get processor-specific information"""
        
        info = self.get_processor_metadata()
        info.update({
            "supported_encounter_types": self.get_supported_encounter_types(),
            "validation_rules": [
                "ICD-10 format validation",
                "Visit date validation", 
                "Patient age validation",
                "Facility ID format validation",
                "Reference data availability"
            ],
            "processing_steps": [
                "Normalize ICD-10 code",
                "Map to candidate G-DRGs",
                "Validate claimed G-DRGs",
                "Extract claim metadata"
            ]
        })
        
        return info