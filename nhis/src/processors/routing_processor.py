from typing import Dict, List, Any

from ..core import StandardClaim, ValidationIssue, ValidationSeverity, ProcessingStep
from .base_processor import ProcessorBase


class RoutingProcessor(ProcessorBase):
    
    def __init__(self):
        super().__init__("RoutingProcessor", ProcessingStep.SETTING_ROUTER)
    
    def validate_inputs(self, claim: StandardClaim, context: Dict[str, Any] = None) -> List[ValidationIssue]:
        issues = []
        issues.extend(super().validate_inputs(claim, context))
        
        if context:
            eligibility_status = context.get('eligibility_status')
            if eligibility_status in ['EXCLUDED', 'NOT_COVERED']:
                issues.append(self._create_validation_issue(
                    ValidationSeverity.CRITICAL,
                    "INELIGIBLE_FOR_ROUTING",
                    f"Service not eligible: {eligibility_status}",
                    {"eligibility_status": eligibility_status}
                ))
        
        return issues
    
    def _execute_processing(self, claim: StandardClaim, context: Dict[str, Any]) -> Dict[str, Any]:
        processing_data = {}
        
        encounter_type = claim.encounter_type.value
        
        if encounter_type in ['A&E', 'EMERGENCY', 'CASUALTY']:
            routing_result = self._route_emergency_encounter(claim, context)
        elif encounter_type == 'OPD':
            routing_result = self._route_opd_encounter(claim, context)
        elif encounter_type == 'IPD':
            routing_result = self._route_inpatient_encounter(claim, context)
        else:
            routing_result = {
                'routing_status': 'UNKNOWN_ENCOUNTER_TYPE',
                'routing_decision': 'DEFAULT_OPD',
                'routing_warnings': [f'Unknown encounter type: {encounter_type}']
            }
        
        processing_data.update(routing_result)
        
        self._log_processing_step(
            "ROUTING_COMPLETE",
            f"Routed {encounter_type} to {processing_data.get('routing_decision')}",
            {"encounter_type": encounter_type, "decision": processing_data.get('routing_decision')}
        )
        
        return processing_data
    
    def _route_emergency_encounter(self, claim: StandardClaim, context: Dict[str, Any]) -> Dict[str, Any]:
        result = {
            'routing_status': 'EMERGENCY_ROUTING',
            'ae_classification': None,
            'routing_decision': None,
            'routing_details': {}
        }
        
        detention_hours = claim.modifiers.get('detention_hours', 0)
        requires_admission = claim.modifiers.get('requires_admission', False)
        
        if requires_admission or (claim.admission_date and claim.discharge_date):
            result['ae_classification'] = 'REQUIRES_ADMISSION'
            result['routing_decision'] = 'USE_INPATIENT_RULES'
            result['routing_details'] = {
                'tariff_type': 'INPATIENT',
                'rules_applied': 'INPATIENT_RULES_D1_D3'
            }
        elif detention_hours > 0 and detention_hours < 24:
            result['ae_classification'] = 'DETENTION_UNDER_24H'
            result['routing_decision'] = 'USE_ZOOM02A_TARIFF'
            result['routing_details'] = {
                'tariff_type': 'ZOOM02A',
                'detention_hours': detention_hours,
                'justification_required': True
            }
        else:
            result['ae_classification'] = 'MANAGED_AS_OPD'
            result['routing_decision'] = 'USE_OPD_RULES'
            result['routing_details'] = {
                'tariff_type': 'OPD',
                'rules_applied': 'OPD_RULES_B1_B5'
            }
        
        emergency_imaging_check = self._check_emergency_imaging(claim)
        result['emergency_imaging'] = emergency_imaging_check
        
        return result
    
    def _route_opd_encounter(self, claim: StandardClaim, context: Dict[str, Any]) -> Dict[str, Any]:
        result = {
            'routing_status': 'OPD_ROUTING',
            'routing_decision': 'USE_OPD_RULES',
            'payment_model': 'PER_VISIT',
            'routing_details': {
                'tariff_type': 'OPD',
                'rules_applied': 'OPD_RULES_B1_B5'
            }
        }
        
        episode_classification = self._classify_episode_type(claim)
        result['episode_classification'] = episode_classification
        
        specialty_check = self._check_specialty_requirements(claim)
        result['specialty_requirements'] = specialty_check
        
        procedure_check = self._check_opd_procedures(claim)
        result['procedure_classification'] = procedure_check
        
        return result
    
    def _route_inpatient_encounter(self, claim: StandardClaim, context: Dict[str, Any]) -> Dict[str, Any]:
        result = {
            'routing_status': 'INPATIENT_ROUTING',
            'routing_decision': 'USE_INPATIENT_RULES',
            'payment_model': 'GDRG_BUNDLED',
            'routing_details': {
                'tariff_type': 'INPATIENT',
                'rules_applied': 'INPATIENT_RULES_D1_D3'
            }
        }
        
        admission_validation = self._validate_admission_details(claim)
        result['admission_validation'] = admission_validation
        
        length_of_stay = claim.get_length_of_stay()
        if length_of_stay is not None:
            result['length_of_stay'] = length_of_stay
            result['routing_details']['length_of_stay'] = length_of_stay
        
        return result
    
    def _check_emergency_imaging(self, claim: StandardClaim) -> Dict[str, Any]:
        result = {
            'has_emergency_imaging': False,
            'imaging_procedures': [],
            'justification_required': False,
            'justification_deadline': None
        }
        
        emergency_imaging_codes = ['CT', 'MRI', 'CT_SCAN', 'MRI_SCAN']
        
        for procedure in claim.procedures:
            procedure_name = procedure.get('name', '').upper()
            procedure_code = procedure.get('code', '').upper()
            
            if any(imaging in procedure_name or imaging in procedure_code for imaging in emergency_imaging_codes):
                result['has_emergency_imaging'] = True
                result['imaging_procedures'].append({
                    'name': procedure.get('name'),
                    'code': procedure.get('code')
                })
        
        if result['has_emergency_imaging']:
            result['justification_required'] = True
            from datetime import timedelta
            result['justification_deadline'] = claim.visit_date + timedelta(days=5)
        
        return result
    
    def _classify_episode_type(self, claim: StandardClaim) -> Dict[str, Any]:
        result = {
            'episode_type': 'ACUTE',
            'classification_reason': 'default',
            'visit_limits': {}
        }
        
        if self._check_reference_data_available():
            is_chronic = self.reference_manager.is_chronic_condition(claim.icd10_diagnosis)
            
            if is_chronic:
                result['episode_type'] = 'CHRONIC'
                result['classification_reason'] = 'chronic_condition_detected'
                result['visit_limits'] = {
                    'max_visits': 6,
                    'period_days': 365,
                    'period_description': '6 visits in 12 months'
                }
            else:
                result['visit_limits'] = {
                    'max_visits': 3,
                    'period_days': 14,
                    'period_description': '3 visits in 14 days'
                }
        
        pregnancy_codes = ['O', 'Z34', 'Z35', 'Z36', 'Z37', 'Z38', 'Z39']
        if any(claim.icd10_diagnosis.startswith(code) for code in pregnancy_codes):
            if 'Z39' in claim.icd10_diagnosis or 'postnatal' in (claim.diagnosis_name or '').lower():
                result['episode_type'] = 'POSTNATAL'
                result['classification_reason'] = 'postnatal_care_detected'
                result['visit_limits'] = {
                    'max_visits': 3,
                    'period_days': 42,
                    'period_description': '3 visits in 6 weeks'
                }
            else:
                result['episode_type'] = 'ANTENATAL'
                result['classification_reason'] = 'antenatal_care_detected'
                result['visit_limits'] = {
                    'max_visits': 6,
                    'period_days': 280,
                    'period_description': '6 visits per pregnancy'
                }
        
        return result
    
    def _check_specialty_requirements(self, claim: StandardClaim) -> Dict[str, Any]:
        result = {
            'requires_specialist': False,
            'multiple_specialties': False,
            'specialty_count': 0,
            'specialties': claim.specialties_attended or []
        }
        
        result['specialty_count'] = len(result['specialties'])
        result['multiple_specialties'] = result['specialty_count'] > 1
        
        if self._check_reference_data_available():
            mapping = self.reference_manager.get_gdrg_for_diagnosis(
                claim.icd10_diagnosis, 
                claim.encounter_type.value
            )
            if mapping:
                result['requires_specialist'] = mapping.get('requires_specialist', False)
        
        if result['multiple_specialties']:
            result['multi_specialty_rule'] = 'PAY_HIGHEST_ONLY'
        
        return result
    
    def _check_opd_procedures(self, claim: StandardClaim) -> Dict[str, Any]:
        result = {
            'has_procedures': len(claim.procedures) > 0,
            'procedure_count': len(claim.procedures),
            'procedure_types': [],
            'zoom_procedures': [],
            'regular_procedures': []
        }
        
        for procedure in claim.procedures:
            procedure_code = procedure.get('code', '').upper()
            procedure_name = procedure.get('name', '')
            
            if procedure_code.startswith('ZOOM'):
                result['zoom_procedures'].append({
                    'code': procedure_code,
                    'name': procedure_name,
                    'type': 'ZOOM_PROCEDURE'
                })
                result['procedure_types'].append('ZOOM')
            else:
                result['regular_procedures'].append({
                    'code': procedure_code,
                    'name': procedure_name,
                    'type': 'REGULAR_OP'
                })
                result['procedure_types'].append('REGULAR_OP')
        
        result['procedure_types'] = list(set(result['procedure_types']))
        
        if result['zoom_procedures']:
            result['zoom_validation_required'] = True
            result['zoom_documentation_required'] = True
        
        return result
    
    def _validate_admission_details(self, claim: StandardClaim) -> Dict[str, Any]:
        result = {
            'has_admission_date': claim.admission_date is not None,
            'has_discharge_date': claim.discharge_date is not None,
            'admission_validation_issues': []
        }
        
        if not result['has_admission_date']:
            result['admission_validation_issues'].append('Missing admission date for inpatient claim')
        
        if claim.admission_date and claim.discharge_date:
            if claim.discharge_date < claim.admission_date:
                result['admission_validation_issues'].append('Discharge date before admission date')
            
            length_of_stay = (claim.discharge_date.date() - claim.admission_date.date()).days
            result['calculated_length_of_stay'] = length_of_stay
            
            if length_of_stay < 0:
                result['admission_validation_issues'].append('Negative length of stay')
            elif length_of_stay == 0:
                result['admission_validation_issues'].append('Same day admission and discharge')
            elif length_of_stay > 365:
                result['admission_validation_issues'].append('Length of stay exceeds 1 year')
        
        return result
    
    def get_supported_encounter_types(self) -> List[str]:
        return ['OPD', 'IPD', 'A&E', 'EMERGENCY', 'CASUALTY']
    
    def get_routing_decisions(self) -> List[str]:
        return [
            'USE_OPD_RULES',
            'USE_INPATIENT_RULES', 
            'USE_ZOOM02A_TARIFF',
            'DEFAULT_OPD'
        ]
    
    def get_ae_classifications(self) -> List[str]:
        return [
            'MANAGED_AS_OPD',
            'DETENTION_UNDER_24H',
            'REQUIRES_ADMISSION'
        ]
    
    def get_routing_processor_info(self) -> Dict[str, Any]:
        info = self.get_processor_metadata()
        info.update({
            "supported_encounter_types": self.get_supported_encounter_types(),
            "routing_decisions": self.get_routing_decisions(),
            "ae_classifications": self.get_ae_classifications(),
            "processing_steps": [
                "Classify encounter type",
                "Route to appropriate rule set",
                "Validate encounter-specific requirements",
                "Set payment model and tariff type"
            ],
            "flowchart_nodes": [
                "SettingType",
                "AEClassify"
            ],
            "episode_types": [
                "ACUTE",
                "CHRONIC",
                "ANTENATAL", 
                "POSTNATAL"
            ]
        })
        
        return info