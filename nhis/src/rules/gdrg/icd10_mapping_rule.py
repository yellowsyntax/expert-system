from typing import Dict, Any, List, Optional
from datetime import datetime
from ..base_rule import BaseRule, RuleResult, RuleDecision, RuleSeverity


class ICD10MappingRule(BaseRule):
    def __init__(self, db_session, reference_data_manager):
        super().__init__(db_session, reference_data_manager)
    
    def validate(self, claim_data: Dict[str, Any], context: Dict[str, Any]) -> RuleResult:
        icd10_diagnosis = claim_data.get('icd10_diagnosis')
        diagnosis_name = claim_data.get('diagnosis_name')
        service_type = claim_data.get('service_type_1')
        
        if not icd10_diagnosis:
            return self.pend(
                reason="ICD-10 diagnosis code is required for G-DRG determination",
                recommendations=[
                    "Provide primary diagnosis with valid ICD-10 code",
                    "Ensure diagnosis is coherent with clinical narrative",
                    "Verify ICD-10 coding standards compliance"
                ],
                metadata={
                    'step': 'A1_ICD10_MAPPING',
                    'missing_data': 'icd10_diagnosis'
                }
            )
        
        try:
            return self._map_icd10_to_gdrg(icd10_diagnosis, diagnosis_name, service_type, claim_data)
            
        except Exception as e:
            return self.reject(
                reason="Error during ICD-10 to G-DRG mapping",
                severity=RuleSeverity.CRITICAL,
                validation_errors=[f"Mapping failed: {str(e)}"],
                metadata={'error_type': 'mapping_error', 'step': 'A1_ICD10_MAPPING'}
            )
    
    def _map_icd10_to_gdrg(self, icd10_code: str, diagnosis_name: str, 
                          service_type: str, claim_data: Dict[str, Any]) -> RuleResult:
        
        icd10_gdrg_mapping = self.get_reference_data('icd10_gdrg_mapping')
        
        if not icd10_gdrg_mapping:
            return self.reject(
                reason="ICD-10 to G-DRG mapping reference data not available",
                severity=RuleSeverity.CRITICAL,
                validation_errors=["Reference data missing"],
                recommendations=["Contact system administrator to load reference data"]
            )
        
        candidate_gdrgs = self._find_candidate_gdrgs(icd10_code, icd10_gdrg_mapping)
        
        if not candidate_gdrgs:
            return self._handle_no_gdrg_candidates(icd10_code, diagnosis_name, icd10_gdrg_mapping)
        
        filtered_candidates = self._filter_by_service_type(candidate_gdrgs, service_type)
        
        if not filtered_candidates:
            return self._handle_service_type_mismatch(
                icd10_code, service_type, candidate_gdrgs, diagnosis_name
            )
        
        validated_candidates = self._validate_gdrg_candidates(filtered_candidates, claim_data)
        
        return self._create_mapping_result(
            icd10_code, diagnosis_name, validated_candidates, service_type, claim_data
        )
    
    def _find_candidate_gdrgs(self, icd10_code: str, mapping_data: Dict[str, Any]) -> List[Dict[str, Any]]:
        candidates = []
        
        for mapping_key, mapping_info in mapping_data.items():
            if self._icd10_matches_mapping(icd10_code, mapping_key, mapping_info):
                gdrg_code = mapping_info.get('gdrg_code')
                if gdrg_code:
                    candidates.append({
                        'gdrg_code': gdrg_code,
                        'gdrg_name': mapping_info.get('gdrg_name', ''),
                        'mapping_source': mapping_key,
                        'match_type': self._get_match_type(icd10_code, mapping_key),
                        'level_of_care': mapping_info.get('level_of_care', {}),
                        'estimated_tariff': mapping_info.get('estimated_tariff', 0),
                        'mapping_priority': mapping_info.get('priority', 1)
                    })
        
        return sorted(candidates, key=lambda x: (x['mapping_priority'], -len(x['mapping_source'])))
    
    def _icd10_matches_mapping(self, icd10_code: str, mapping_key: str, mapping_info: Dict[str, Any]) -> bool:
        icd10_upper = icd10_code.upper().strip()
        mapping_key_upper = mapping_key.upper().strip()
        
        if icd10_upper == mapping_key_upper:
            return True
        
        if icd10_upper.startswith(mapping_key_upper):
            return True
        
        alternative_codes = mapping_info.get('alternative_codes', [])
        for alt_code in alternative_codes:
            if icd10_upper == alt_code.upper() or icd10_upper.startswith(alt_code.upper()):
                return True
        
        return False
    
    def _get_match_type(self, icd10_code: str, mapping_key: str) -> str:
        if icd10_code.upper() == mapping_key.upper():
            return 'EXACT'
        elif icd10_code.upper().startswith(mapping_key.upper()):
            if len(mapping_key) >= 4:
                return 'SUBCATEGORY'
            elif len(mapping_key) == 3:
                return 'CATEGORY'
            else:
                return 'PREFIX'
        else:
            return 'ALTERNATIVE'
    
    def _filter_by_service_type(self, candidates: List[Dict[str, Any]], service_type: str) -> List[Dict[str, Any]]:
        service_type_mapping = {
            'IPD': ['INPATIENT', 'IPD', 'HOSPITAL'],
            'OPD': ['OUTPATIENT', 'OPD', 'AMBULATORY'],
            'A&E': ['EMERGENCY', 'AE', 'URGENT'],
            'EMERGENCY': ['EMERGENCY', 'AE', 'URGENT']
        }
        
        valid_service_types = service_type_mapping.get(service_type, [service_type])
        
        filtered = []
        for candidate in candidates:
            level_of_care = candidate.get('level_of_care', {})
            
            if not level_of_care:
                filtered.append(candidate)
                continue
            
            applicable_services = level_of_care.get('applicable_services', [])
            if not applicable_services:
                filtered.append(candidate)
                continue
            
            if any(service.upper() in [s.upper() for s in valid_service_types] for service in applicable_services):
                filtered.append(candidate)
        
        return filtered
    
    def _validate_gdrg_candidates(self, candidates: List[Dict[str, Any]], 
                                 claim_data: Dict[str, Any]) -> List[Dict[str, Any]]:
        
        validated_candidates = []
        
        for candidate in candidates:
            validation_result = self._validate_single_gdrg(candidate, claim_data)
            candidate.update(validation_result)
            validated_candidates.append(candidate)
        
        return validated_candidates
    
    def _validate_single_gdrg(self, candidate: Dict[str, Any], claim_data: Dict[str, Any]) -> Dict[str, Any]:
        gdrg_code = candidate.get('gdrg_code')
        level_of_care = candidate.get('level_of_care', {})
        
        validation = {
            'is_valid': True,
            'validation_warnings': [],
            'validation_notes': []
        }
        
        facility_level = claim_data.get('healthcare_level', 'C')
        if level_of_care:
            facility_restrictions = level_of_care.get('facility_levels', [])
            if facility_restrictions and facility_level not in facility_restrictions:
                validation['validation_warnings'].append(
                    f"G-DRG {gdrg_code} may not be authorized for facility level {facility_level}"
                )
        
        age_restrictions = level_of_care.get('age_restrictions', {})
        if age_restrictions:
            patient_dob = claim_data.get('date_of_birth')
            if patient_dob:
                patient_age = self.get_patient_age_years(patient_dob)
                min_age = age_restrictions.get('min_age', 0)
                max_age = age_restrictions.get('max_age', 150)
                
                if patient_age < min_age or patient_age > max_age:
                    validation['validation_warnings'].append(
                        f"Patient age ({patient_age}) outside typical range for G-DRG {gdrg_code}"
                    )
        
        gender_restrictions = level_of_care.get('gender_specific', [])
        if gender_restrictions:
            patient_gender = claim_data.get('gender', '').upper()
            if patient_gender and patient_gender not in [g.upper() for g in gender_restrictions]:
                validation['validation_warnings'].append(
                    f"G-DRG {gdrg_code} may be gender-specific (patient: {patient_gender})"
                )
        
        return validation
    
    def _handle_no_gdrg_candidates(self, icd10_code: str, diagnosis_name: str, 
                                  mapping_data: Dict[str, Any]) -> RuleResult:
        
        similar_codes = self._find_similar_icd10_codes(icd10_code, mapping_data)
        
        return self.reject(
            reason=f"No G-DRG mapping found for ICD-10 code {icd10_code}",
            severity=RuleSeverity.HIGH,
            validation_errors=[
                f"ICD-10 code {icd10_code} not found in G-DRG mapping",
                f"Diagnosis: {diagnosis_name or 'Not provided'}"
            ],
            recommendations=[
                "Verify ICD-10 code is correct and properly formatted",
                "Check if newer or alternative ICD-10 code should be used",
                "Review diagnosis coding guidelines",
                "Contact coding specialist if diagnosis is complex"
            ] + ([f"Similar codes found: {', '.join(similar_codes[:5])}"] if similar_codes else []),
            metadata={
                'icd10_code': icd10_code,
                'diagnosis_name': diagnosis_name,
                'similar_codes': similar_codes[:10],
                'step': 'A1_ICD10_MAPPING',
                'mapping_status': 'NO_CANDIDATES_FOUND'
            }
        )
    
    def _handle_service_type_mismatch(self, icd10_code: str, service_type: str,
                                    all_candidates: List[Dict[str, Any]], 
                                    diagnosis_name: str) -> RuleResult:
        
        return self.flag(
            reason=f"G-DRG candidates found for {icd10_code} but not applicable to {service_type}",
            severity=RuleSeverity.MEDIUM,
            warnings=[
                f"ICD-10 {icd10_code} has G-DRG mappings for other service types",
                f"Current service type: {service_type}",
                "Available G-DRGs may be for different care settings"
            ],
            recommendations=[
                "Verify service type classification is correct",
                "Check if diagnosis is appropriate for current care setting",
                "Consider if different service type classification applies",
                "Review clinical documentation for service type justification"
            ],
            metadata={
                'icd10_code': icd10_code,
                'service_type': service_type,
                'available_candidates': [
                    {
                        'gdrg_code': c['gdrg_code'],
                        'applicable_services': c.get('level_of_care', {}).get('applicable_services', [])
                    }
                    for c in all_candidates
                ],
                'step': 'A1_ICD10_MAPPING',
                'mapping_status': 'SERVICE_TYPE_MISMATCH'
            }
        )
    
    def _find_similar_icd10_codes(self, icd10_code: str, mapping_data: Dict[str, Any]) -> List[str]:
        similar_codes = []
        
        code_prefix = icd10_code[:3]
        code_category = icd10_code[:1]
        
        for mapping_key in mapping_data.keys():
            if mapping_key.startswith(code_prefix) and mapping_key != icd10_code:
                similar_codes.append(mapping_key)
            elif mapping_key.startswith(code_category) and len(similar_codes) < 10:
                similar_codes.append(mapping_key)
        
        return sorted(similar_codes)
    
    def _create_mapping_result(self, icd10_code: str, diagnosis_name: str,
                             candidates: List[Dict[str, Any]], service_type: str,
                             claim_data: Dict[str, Any]) -> RuleResult:
        
        candidate_count = len(candidates)
        primary_candidate = candidates[0] if candidates else None
        
        warnings = []
        recommendations = []
        all_validation_warnings = []
        
        for candidate in candidates:
            all_validation_warnings.extend(candidate.get('validation_warnings', []))
        
        if candidate_count > 1:
            warnings.append(f"Multiple G-DRG candidates found ({candidate_count}) - will require A2 procedure vs diagnosis rule")
            recommendations.append("Ensure procedure codes are provided for accurate G-DRG determination")
        
        if all_validation_warnings:
            warnings.extend(all_validation_warnings[:3])
        
        metadata = {
            'icd10_code': icd10_code,
            'diagnosis_name': diagnosis_name,
            'service_type': service_type,
            'candidate_count': candidate_count,
            'candidates': [
                {
                    'gdrg_code': c['gdrg_code'],
                    'gdrg_name': c['gdrg_name'],
                    'match_type': c['match_type'],
                    'mapping_priority': c['mapping_priority'],
                    'validation_warnings': c.get('validation_warnings', [])
                }
                for c in candidates
            ],
            'primary_candidate': {
                'gdrg_code': primary_candidate['gdrg_code'],
                'gdrg_name': primary_candidate['gdrg_name'],
                'match_type': primary_candidate['match_type']
            } if primary_candidate else None,
            'step': 'A1_ICD10_MAPPING',
            'mapping_status': 'CANDIDATES_FOUND'
        }
        
        if warnings:
            return self.flag(
                reason=f"ICD-10 {icd10_code} mapped to G-DRG candidates with considerations",
                severity=RuleSeverity.LOW,
                warnings=warnings,
                recommendations=recommendations,
                metadata=metadata
            )
        
        return self.approve(
            reason=f"ICD-10 {icd10_code} successfully mapped to {candidate_count} G-DRG candidate(s)",
            metadata=metadata
        )
    
    def get_gdrg_mapping_details(self, icd10_code: str) -> Dict[str, Any]:
        try:
            icd10_gdrg_mapping = self.get_reference_data('icd10_gdrg_mapping')
            
            if not icd10_gdrg_mapping:
                return {'error': 'ICD-10 to G-DRG mapping data not available'}
            
            candidates = self._find_candidate_gdrgs(icd10_code, icd10_gdrg_mapping)
            
            return {
                'icd10_code': icd10_code,
                'candidates_found': len(candidates),
                'candidates': candidates,
                'mapping_available': len(candidates) > 0
            }
            
        except Exception as e:
            return {
                'error': f"Failed to retrieve G-DRG mapping details: {str(e)}",
                'icd10_code': icd10_code
            }