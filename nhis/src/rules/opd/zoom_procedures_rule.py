from typing import Dict, Any, List
from datetime import datetime
from ..base_rule import BaseRule, RuleResult, RuleDecision, RuleSeverity
from ...database.repositories import TariffRepository

class ZoomProceduresRule(BaseRule):
    def __init__(self, db_session, reference_data_manager):
        super().__init__(db_session, reference_data_manager)
        self.tariff_repo = TariffRepository(db_session)
    
    def validate(self, claim_data: Dict[str, Any], context: Dict[str, Any]) -> RuleResult:
        service_type = claim_data.get('service_type_1')
        procedure_code = claim_data.get('icd10_procedure')
        procedure_name = claim_data.get('procedure_name')
        facility_level = claim_data.get('healthcare_level', 'C')
        provider_id = claim_data.get('provider_id')
        
        if service_type not in ['OPD', 'IPD', 'A&E', 'EMERGENCY']:
            return self.approve(
                reason="ZOOM procedure validation not applicable to this service type",
                metadata={'service_type': service_type, 'rule_applied': False}
            )
        
        if not procedure_code:
            return self.approve(
                reason="No procedure code provided - ZOOM validation not required",
                metadata={'has_procedure': False, 'rule_applied': False}
            )
        
        if not self._is_zoom_procedure(procedure_code):
            return self.approve(
                reason="Not a ZOOM procedure - standard procedure validation applies",
                metadata={'procedure_code': procedure_code, 'is_zoom': False, 'rule_applied': False}
            )
        
        try:
            return self._validate_zoom_procedure(
                procedure_code, procedure_name, facility_level, provider_id, claim_data
            )
            
        except Exception as e:
            return self.reject(
                reason="Error during ZOOM procedure validation",
                severity=RuleSeverity.CRITICAL,
                validation_errors=[f"Validation failed: {str(e)}"],
                metadata={'error_type': 'validation_error'}
            )
    
    def _is_zoom_procedure(self, procedure_code: str) -> bool:
        return procedure_code and procedure_code.upper().startswith('ZOOM')
    
    def _validate_zoom_procedure(self, procedure_code: str, procedure_name: str, 
                               facility_level: str, provider_id: str, 
                               claim_data: Dict[str, Any]) -> RuleResult:
        
        zoom_tariff = self.tariff_repo.get_zoom_procedure_tariff(procedure_code, facility_level)
        
        if not zoom_tariff:
            return self.reject(
                reason=f"ZOOM procedure {procedure_code} not found in tariff database or not authorized for facility level {facility_level}",
                severity=RuleSeverity.HIGH,
                validation_errors=[
                    f"Procedure code {procedure_code} not in NHIS ZOOM procedure list",
                    f"Facility level {facility_level} may not be authorized for this procedure"
                ],
                recommendations=[
                    "Verify procedure code is correct and properly formatted",
                    "Check if facility has authorization for this ZOOM procedure",
                    "Review facility credentialing for specialized procedures"
                ],
                metadata={
                    'procedure_code': procedure_code,
                    'facility_level': facility_level,
                    'tariff_found': False
                }
            )
        
        zoom_rules = self.get_reference_data('bundling_rules').get('zoom_procedures', {})
        documentation_requirements = self.get_reference_data('documentation_requirements').get('zoom', {})
        
        validation_result = self._validate_zoom_requirements(
            procedure_code, claim_data, zoom_rules, documentation_requirements
        )
        
        if not validation_result['is_valid']:
            return self._handle_zoom_validation_failure(
                procedure_code, zoom_tariff, validation_result, claim_data
            )
        
        return self._approve_zoom_procedure(
            procedure_code, procedure_name, zoom_tariff, validation_result, claim_data
        )
    
    def _validate_zoom_requirements(self, procedure_code: str, claim_data: Dict[str, Any],
                                  zoom_rules: Dict[str, Any], 
                                  doc_requirements: Dict[str, Any]) -> Dict[str, Any]:
        
        validation_result = {
            'is_valid': True,
            'warnings': [],
            'missing_requirements': [],
            'documentation_status': 'COMPLETE',
            'clinical_justification': 'PROVIDED'
        }
        
        procedure_specific_rules = zoom_rules.get(procedure_code, {})
        
        if procedure_code == 'ZOOM02A':
            return self._validate_zoom02a_detention(claim_data, validation_result)
        elif procedure_code.startswith('ZOOM03'):
            return self._validate_zoom_imaging(claim_data, validation_result, procedure_code)
        elif procedure_code == 'ZOOM04':
            return self._validate_zoom_physiotherapy(claim_data, validation_result)
        else:
            return self._validate_general_zoom_procedure(
                procedure_code, claim_data, validation_result, procedure_specific_rules, doc_requirements
            )
    
    def _validate_zoom02a_detention(self, claim_data: Dict[str, Any], 
                                  validation_result: Dict[str, Any]) -> Dict[str, Any]:
        
        admission_date = claim_data.get('admission_date')
        discharge_date = claim_data.get('discharge_date')
        service_type = claim_data.get('service_type_1')
        
        if service_type not in ['A&E', 'EMERGENCY']:
            validation_result['is_valid'] = False
            validation_result['missing_requirements'].append(
                "ZOOM02A (A&E detention) only applicable to A&E/Emergency visits"
            )
        
        if admission_date and discharge_date:
            detention_hours = (discharge_date - admission_date).total_seconds() / 3600
            
            if detention_hours >= 24:
                validation_result['warnings'].append(
                    f"Detention period ({detention_hours:.1f} hours) >= 24 hours - consider IPD classification"
                )
            elif detention_hours < 1:
                validation_result['is_valid'] = False
                validation_result['missing_requirements'].append(
                    f"Detention period too short ({detention_hours:.1f} hours) for ZOOM02A billing"
                )
        else:
            validation_result['missing_requirements'].append(
                "Both admission and discharge dates required for ZOOM02A detention billing"
            )
        
        return validation_result
    
    def _validate_zoom_imaging(self, claim_data: Dict[str, Any], 
                             validation_result: Dict[str, Any], procedure_code: str) -> Dict[str, Any]:
        
        service_type = claim_data.get('service_type_1')
        icd10_diagnosis = claim_data.get('icd10_diagnosis')
        admission_date = claim_data.get('admission_date')
        
        emergency_imaging_codes = ['ZOOM03A', 'ZOOM03B', 'ZOOM03C']
        
        if procedure_code in emergency_imaging_codes and service_type in ['A&E', 'EMERGENCY']:
            if not icd10_diagnosis:
                validation_result['warnings'].append(
                    "Emergency imaging procedure should have supporting diagnosis"
                )
            
            if admission_date:
                current_date = datetime.utcnow()
                days_since_procedure = (current_date - admission_date).days
                
                if days_since_procedure > 5:
                    validation_result['missing_requirements'].append(
                        f"Emergency imaging justification required within 5 days (submitted after {days_since_procedure} days)"
                    )
                    validation_result['documentation_status'] = 'PENDING'
        
        if procedure_code.startswith('ZOOM03') and not self._has_imaging_justification(claim_data):
            validation_result['warnings'].append(
                "Clinical justification for imaging procedure recommended"
            )
        
        return validation_result
    
    def _validate_zoom_physiotherapy(self, claim_data: Dict[str, Any], 
                                   validation_result: Dict[str, Any]) -> Dict[str, Any]:
        
        icd10_diagnosis = claim_data.get('icd10_diagnosis')
        
        if not icd10_diagnosis:
            validation_result['missing_requirements'].append(
                "Diagnosis code required for physiotherapy procedure validation"
            )
            return validation_result
        
        physio_conditions = self.get_reference_data('physiotherapy_conditions')
        
        is_eligible = False
        for condition_code in physio_conditions.keys():
            if icd10_diagnosis.startswith(condition_code):
                is_eligible = True
                break
        
        if not is_eligible:
            validation_result['is_valid'] = False
            validation_result['missing_requirements'].append(
                f"Diagnosis {icd10_diagnosis} not eligible for NHIS physiotherapy coverage"
            )
        
        if not self._has_physio_documentation(claim_data):
            validation_result['warnings'].append(
                "Physiotherapy referral and attendance documentation recommended"
            )
        
        return validation_result
    
    def _validate_general_zoom_procedure(self, procedure_code: str, claim_data: Dict[str, Any],
                                       validation_result: Dict[str, Any], 
                                       procedure_rules: Dict[str, Any],
                                       doc_requirements: Dict[str, Any]) -> Dict[str, Any]:
        
        if procedure_rules:
            required_diagnosis_categories = procedure_rules.get('required_diagnosis_categories', [])
            if required_diagnosis_categories:
                icd10_diagnosis = claim_data.get('icd10_diagnosis')
                if icd10_diagnosis:
                    diagnosis_category = self.get_icd10_category(icd10_diagnosis)
                    if diagnosis_category not in required_diagnosis_categories:
                        validation_result['warnings'].append(
                            f"Diagnosis category {diagnosis_category} may not be typical for {procedure_code}"
                        )
        
        required_docs = doc_requirements.get(procedure_code, [])
        if required_docs:
            missing_docs = []
            for doc_type in required_docs:
                if not self._has_required_documentation(claim_data, doc_type):
                    missing_docs.append(doc_type)
            
            if missing_docs:
                validation_result['warnings'].extend([
                    f"Missing recommended documentation: {', '.join(missing_docs)}"
                ])
                validation_result['documentation_status'] = 'INCOMPLETE'
        
        return validation_result
    
    def _has_imaging_justification(self, claim_data: Dict[str, Any]) -> bool:
        return bool(claim_data.get('clinical_notes') or 
                   claim_data.get('imaging_justification') or
                   claim_data.get('diagnosis_name'))
    
    def _has_physio_documentation(self, claim_data: Dict[str, Any]) -> bool:
        return bool(claim_data.get('referral_notes') or 
                   claim_data.get('physio_prescription') or
                   claim_data.get('treatment_plan'))
    
    def _has_required_documentation(self, claim_data: Dict[str, Any], doc_type: str) -> bool:
        doc_fields = {
            'clinical_notes': ['clinical_notes', 'procedure_notes'],
            'referral': ['referral_notes', 'referral_form'],
            'consent_form': ['consent_form', 'patient_consent'],
            'pre_procedure_assessment': ['pre_assessment', 'assessment_notes'],
            'post_procedure_report': ['post_procedure', 'procedure_report']
        }
        
        fields_to_check = doc_fields.get(doc_type, [doc_type])
        return any(claim_data.get(field) for field in fields_to_check)
    
    def _handle_zoom_validation_failure(self, procedure_code: str, zoom_tariff: float,
                                      validation_result: Dict[str, Any], 
                                      claim_data: Dict[str, Any]) -> RuleResult:
        
        missing_requirements = validation_result.get('missing_requirements', [])
        documentation_status = validation_result.get('documentation_status', 'INCOMPLETE')
        
        if documentation_status == 'PENDING':
            return self.pend(
                reason=f"ZOOM procedure {procedure_code} pending required documentation",
                recommendations=[
                    "Submit required clinical justification documentation",
                    "Ensure all supporting evidence is provided within required timeframe"
                ] + [f"Missing: {req}" for req in missing_requirements],
                metadata={
                    'procedure_code': procedure_code,
                    'tariff_amount': zoom_tariff,
                    'documentation_status': documentation_status,
                    'missing_requirements': missing_requirements
                }
            )
        
        return self.reject(
            reason=f"ZOOM procedure {procedure_code} validation failed",
            severity=RuleSeverity.HIGH,
            validation_errors=missing_requirements,
            recommendations=[
                "Review procedure eligibility criteria",
                "Ensure all clinical requirements are met",
                "Verify procedure coding is appropriate for patient condition"
            ],
            metadata={
                'procedure_code': procedure_code,
                'tariff_amount': zoom_tariff,
                'validation_failures': missing_requirements
            }
        )
    
    def _approve_zoom_procedure(self, procedure_code: str, procedure_name: str, 
                              zoom_tariff: float, validation_result: Dict[str, Any],
                              claim_data: Dict[str, Any]) -> RuleResult:
        
        warnings = validation_result.get('warnings', [])
        documentation_status = validation_result.get('documentation_status', 'COMPLETE')
        
        metadata = {
            'procedure_code': procedure_code,
            'procedure_name': procedure_name,
            'tariff_amount': zoom_tariff,
            'documentation_status': documentation_status,
            'validation_passed': True
        }
        
        if warnings:
            return self.flag(
                reason=f"ZOOM procedure {procedure_code} approved with recommendations",
                severity=RuleSeverity.LOW,
                warnings=warnings,
                affected_amount=zoom_tariff,
                metadata=metadata,
                recommendations=[
                    "Consider addressing documentation recommendations for future claims",
                    "Ensure clinical protocols are followed for specialized procedures"
                ]
            )
        
        return self.approve(
            reason=f"ZOOM procedure {procedure_code} validated and approved",
            affected_amount=zoom_tariff,
            metadata=metadata
        )