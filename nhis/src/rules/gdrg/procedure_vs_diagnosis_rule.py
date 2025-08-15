from typing import Dict, Any, List, Optional
from datetime import datetime
from ..base_rule import BaseRule, RuleResult, RuleDecision, RuleSeverity

class ProcedureVsDiagnosisRule(BaseRule):
    def __init__(self, db_session, reference_data_manager):
        super().__init__(db_session, reference_data_manager)
    
    def validate(self, claim_data: Dict[str, Any], context: Dict[str, Any]) -> RuleResult:
        icd10_diagnosis = claim_data.get('icd10_diagnosis')
        icd10_procedure = claim_data.get('icd10_procedure')
        procedure_name = claim_data.get('procedure_name')
        service_type = claim_data.get('service_type_1')
        
        diagnosis_candidates = context.get('diagnosis_gdrg_candidates', [])
        
        if not icd10_diagnosis:
            return self.pend(
                reason="ICD-10 diagnosis required for A2 procedure vs diagnosis rule",
                recommendations=["Provide primary diagnosis for G-DRG determination"],
                metadata={'step': 'A2_PROCEDURE_VS_DIAGNOSIS', 'missing_data': 'icd10_diagnosis'}
            )
        
        if not icd10_procedure:
            return self._handle_diagnosis_only_path(
                icd10_diagnosis, diagnosis_candidates, service_type, claim_data
            )
        
        try:
            return self._determine_dominant_path(
                icd10_diagnosis, icd10_procedure, procedure_name, 
                diagnosis_candidates, service_type, claim_data
            )
            
        except Exception as e:
            return self.reject(
                reason="Error during procedure vs diagnosis determination",
                severity=RuleSeverity.CRITICAL,
                validation_errors=[f"Path determination failed: {str(e)}"],
                metadata={'error_type': 'path_determination_error', 'step': 'A2_PROCEDURE_VS_DIAGNOSIS'}
            )
    
    def _handle_diagnosis_only_path(self, icd10_diagnosis: str, diagnosis_candidates: List[Dict[str, Any]],
                                   service_type: str, claim_data: Dict[str, Any]) -> RuleResult:
        
        if not diagnosis_candidates:
            return self.reject(
                reason="No G-DRG candidates from A1 diagnosis mapping",
                severity=RuleSeverity.HIGH,
                validation_errors=["No diagnosis-based G-DRG candidates available"],
                recommendations=["Verify A1 rule executed successfully and found valid G-DRG candidates"]
            )
        
        primary_candidate = diagnosis_candidates[0] if diagnosis_candidates else None
        
        return self.approve(
            reason=f"Diagnosis path selected: No procedures present, using diagnosis-based G-DRG {primary_candidate.get('gdrg_code')}",
            metadata={
                'step': 'A2_PROCEDURE_VS_DIAGNOSIS',
                'determination': 'DIAGNOSIS_PATH',
                'selected_gdrg': primary_candidate.get('gdrg_code'),
                'selected_gdrg_name': primary_candidate.get('gdrg_name'),
                'path_reason': 'NO_PROCEDURES_PRESENT',
                'diagnosis_code': icd10_diagnosis,
                'candidate_count': len(diagnosis_candidates)
            }
        )
    
    def _determine_dominant_path(self, icd10_diagnosis: str, icd10_procedure: str, 
                               procedure_name: str, diagnosis_candidates: List[Dict[str, Any]],
                               service_type: str, claim_data: Dict[str, Any]) -> RuleResult:
        
        procedure_gdrg_mapping = self._find_procedure_gdrg_mapping(icd10_procedure, procedure_name)
        
        if not procedure_gdrg_mapping:
            return self._handle_procedure_not_mapped(
                icd10_diagnosis, icd10_procedure, procedure_name, 
                diagnosis_candidates, service_type, claim_data
            )
        
        procedure_candidates = procedure_gdrg_mapping.get('candidates', [])
        
        if not procedure_candidates:
            return self._handle_diagnosis_path_with_unmapped_procedure(
                icd10_diagnosis, icd10_procedure, diagnosis_candidates, claim_data
            )
        
        path_determination = self._evaluate_procedure_vs_diagnosis_priority(
            diagnosis_candidates, procedure_candidates, service_type, claim_data
        )
        
        return self._create_path_determination_result(
            path_determination, icd10_diagnosis, icd10_procedure, 
            procedure_name, claim_data
        )
    
    def _find_procedure_gdrg_mapping(self, icd10_procedure: str, procedure_name: str) -> Optional[Dict[str, Any]]:
        procedure_gdrg_mapping = self.get_reference_data('procedure_gdrg_mapping')
        
        if not procedure_gdrg_mapping:
            return None
        
        candidates = []
        
        for mapping_key, mapping_info in procedure_gdrg_mapping.items():
            if self._procedure_matches_mapping(icd10_procedure, procedure_name, mapping_key, mapping_info):
                candidates.append({
                    'gdrg_code': mapping_info.get('gdrg_code'),
                    'gdrg_name': mapping_info.get('gdrg_name', ''),
                    'mapping_source': mapping_key,
                    'match_type': self._get_procedure_match_type(icd10_procedure, mapping_key),
                    'procedure_priority': mapping_info.get('priority', 1),
                    'dominant_over_diagnosis': mapping_info.get('dominant_over_diagnosis', True),
                    'level_of_care': mapping_info.get('level_of_care', {}),
                    'estimated_tariff': mapping_info.get('estimated_tariff', 0)
                })
        
        if candidates:
            sorted_candidates = sorted(candidates, key=lambda x: (x['procedure_priority'], -len(x['mapping_source'])))
            return {
                'procedure_code': icd10_procedure,
                'procedure_name': procedure_name,
                'candidates': sorted_candidates,
                'primary_candidate': sorted_candidates[0]
            }
        
        return None
    
    def _procedure_matches_mapping(self, icd10_procedure: str, procedure_name: str,
                                 mapping_key: str, mapping_info: Dict[str, Any]) -> bool:
        
        proc_upper = icd10_procedure.upper().strip()
        mapping_key_upper = mapping_key.upper().strip()
        
        if proc_upper == mapping_key_upper or proc_upper.startswith(mapping_key_upper):
            return True
        
        alternative_codes = mapping_info.get('alternative_codes', [])
        for alt_code in alternative_codes:
            if proc_upper == alt_code.upper() or proc_upper.startswith(alt_code.upper()):
                return True
        
        if procedure_name:
            procedure_keywords = mapping_info.get('procedure_keywords', [])
            procedure_name_lower = procedure_name.lower()
            for keyword in procedure_keywords:
                if keyword.lower() in procedure_name_lower:
                    return True
        
        return False
    
    def _get_procedure_match_type(self, icd10_procedure: str, mapping_key: str) -> str:
        if icd10_procedure.upper() == mapping_key.upper():
            return 'EXACT'
        elif icd10_procedure.upper().startswith(mapping_key.upper()):
            return 'PREFIX'
        else:
            return 'KEYWORD'
    
    def _evaluate_procedure_vs_diagnosis_priority(self, diagnosis_candidates: List[Dict[str, Any]],
                                                procedure_candidates: List[Dict[str, Any]],
                                                service_type: str, claim_data: Dict[str, Any]) -> Dict[str, Any]:
        
        gdrg_hierarchy_rules = self.get_reference_data('bundling_rules').get('gdrg_hierarchy', {})
        
        primary_procedure = procedure_candidates[0] if procedure_candidates else None
        primary_diagnosis = diagnosis_candidates[0] if diagnosis_candidates else None
        
        determination = {
            'dominant_path': 'PROCEDURE_PATH',
            'selected_candidate': primary_procedure,
            'alternative_candidate': primary_diagnosis,
            'determination_reasons': [],
            'confidence_level': 'HIGH'
        }
        
        if not primary_procedure.get('dominant_over_diagnosis', True):
            determination.update({
                'dominant_path': 'DIAGNOSIS_PATH',
                'selected_candidate': primary_diagnosis,
                'alternative_candidate': primary_procedure,
                'determination_reasons': ['Procedure G-DRG configured as non-dominant over diagnosis']
            })
            return determination
        
        if service_type == 'OPD':
            procedure_appropriateness = self._evaluate_procedure_appropriateness_opd(
                primary_procedure, claim_data
            )
            if not procedure_appropriateness['is_appropriate']:
                determination.update({
                    'dominant_path': 'DIAGNOSIS_PATH',
                    'selected_candidate': primary_diagnosis,
                    'alternative_candidate': primary_procedure,
                    'determination_reasons': [
                        'Procedure may not be appropriate for OPD setting',
                        procedure_appropriateness.get('reason', '')
                    ],
                    'confidence_level': 'MEDIUM'
                })
                return determination
        
        procedure_complexity = self._assess_procedure_complexity(primary_procedure, claim_data)
        diagnosis_specificity = self._assess_diagnosis_specificity(primary_diagnosis, claim_data)
        
        if procedure_complexity['score'] >= diagnosis_specificity['score']:
            determination['determination_reasons'].extend([
                f"Procedure complexity score: {procedure_complexity['score']}",
                f"Diagnosis specificity score: {diagnosis_specificity['score']}",
                "Procedure path provides more specific G-DRG determination"
            ])
        else:
            determination.update({
                'dominant_path': 'DIAGNOSIS_PATH',
                'selected_candidate': primary_diagnosis,
                'alternative_candidate': primary_procedure,
                'determination_reasons': [
                    f"Diagnosis specificity score ({diagnosis_specificity['score']}) higher than procedure complexity ({procedure_complexity['score']})",
                    "Diagnosis provides more accurate G-DRG classification"
                ],
                'confidence_level': 'MEDIUM'
            })
        
        return determination
    
    def _evaluate_procedure_appropriateness_opd(self, procedure_candidate: Dict[str, Any],
                                              claim_data: Dict[str, Any]) -> Dict[str, Any]:
        
        level_of_care = procedure_candidate.get('level_of_care', {})
        opd_appropriate = level_of_care.get('opd_appropriate', True)
        
        if not opd_appropriate:
            return {
                'is_appropriate': False,
                'reason': 'Procedure marked as not appropriate for OPD setting'
            }
        
        complexity_indicators = level_of_care.get('complexity_indicators', {})
        requires_anesthesia = complexity_indicators.get('requires_general_anesthesia', False)
        requires_icu = complexity_indicators.get('requires_icu_monitoring', False)
        estimated_duration = complexity_indicators.get('estimated_duration_hours', 1)
        
        if requires_anesthesia or requires_icu or estimated_duration > 4:
            return {
                'is_appropriate': False,
                'reason': f'Procedure complexity may require inpatient setting (anesthesia: {requires_anesthesia}, ICU: {requires_icu}, duration: {estimated_duration}h)'
            }
        
        return {'is_appropriate': True, 'reason': 'Procedure appropriate for OPD setting'}
    
    def _assess_procedure_complexity(self, procedure_candidate: Dict[str, Any], 
                                   claim_data: Dict[str, Any]) -> Dict[str, Any]:
        
        complexity_score = 0
        factors = []
        
        level_of_care = procedure_candidate.get('level_of_care', {})
        complexity_indicators = level_of_care.get('complexity_indicators', {})
        
        if complexity_indicators.get('requires_specialist', False):
            complexity_score += 3
            factors.append('Requires specialist')
        
        if complexity_indicators.get('requires_general_anesthesia', False):
            complexity_score += 4
            factors.append('Requires general anesthesia')
        
        if complexity_indicators.get('requires_special_equipment', False):
            complexity_score += 2
            factors.append('Requires special equipment')
        
        estimated_duration = complexity_indicators.get('estimated_duration_hours', 1)
        if estimated_duration > 2:
            complexity_score += min(3, estimated_duration - 1)
            factors.append(f'Duration: {estimated_duration}h')
        
        estimated_tariff = procedure_candidate.get('estimated_tariff', 0)
        if estimated_tariff > 1000:
            complexity_score += 2
            factors.append('High-value procedure')
        
        return {
            'score': complexity_score,
            'factors': factors,
            'assessment': 'HIGH' if complexity_score >= 8 else 'MEDIUM' if complexity_score >= 4 else 'LOW'
        }
    
    def _assess_diagnosis_specificity(self, diagnosis_candidate: Dict[str, Any],
                                    claim_data: Dict[str, Any]) -> Dict[str, Any]:
        
        specificity_score = 0
        factors = []
        
        match_type = diagnosis_candidate.get('match_type', 'EXACT')
        if match_type == 'EXACT':
            specificity_score += 4
            factors.append('Exact ICD-10 match')
        elif match_type == 'SUBCATEGORY':
            specificity_score += 3
            factors.append('Subcategory match')
        elif match_type == 'CATEGORY':
            specificity_score += 2
            factors.append('Category match')
        else:
            specificity_score += 1
            factors.append('Prefix/alternative match')
        
        gdrg_code = diagnosis_candidate.get('gdrg_code', '')
        if gdrg_code and len(gdrg_code) >= 6:
            specificity_score += 2
            factors.append('Specific G-DRG code')
        
        estimated_tariff = diagnosis_candidate.get('estimated_tariff', 0)
        if estimated_tariff > 500:
            specificity_score += 1
            factors.append('Significant diagnosis')
        
        return {
            'score': specificity_score,
            'factors': factors,
            'assessment': 'HIGH' if specificity_score >= 6 else 'MEDIUM' if specificity_score >= 4 else 'LOW'
        }
    
    def _handle_procedure_not_mapped(self, icd10_diagnosis: str, icd10_procedure: str,
                                   procedure_name: str, diagnosis_candidates: List[Dict[str, Any]],
                                   service_type: str, claim_data: Dict[str, Any]) -> RuleResult:
        
        primary_diagnosis = diagnosis_candidates[0] if diagnosis_candidates else None
        
        return self.flag(
            reason=f"Procedure {icd10_procedure} not mapped to G-DRG - using diagnosis path",
            severity=RuleSeverity.LOW,
            warnings=[
                f"Procedure code {icd10_procedure} not found in G-DRG mapping",
                f"Procedure name: {procedure_name or 'Not provided'}",
                "Falling back to diagnosis-based G-DRG determination"
            ],
            recommendations=[
                "Verify procedure code is correct and in standard format",
                "Check if procedure should map to specific G-DRG",
                "Consider updating procedure coding if more specific code available"
            ],
            metadata={
                'step': 'A2_PROCEDURE_VS_DIAGNOSIS',
                'determination': 'DIAGNOSIS_PATH',
                'selected_gdrg': primary_diagnosis.get('gdrg_code') if primary_diagnosis else None,
                'path_reason': 'PROCEDURE_NOT_MAPPED',
                'unmapped_procedure': icd10_procedure,
                'procedure_name': procedure_name
            }
        )
    
    def _handle_diagnosis_path_with_unmapped_procedure(self, icd10_diagnosis: str, icd10_procedure: str,
                                                     diagnosis_candidates: List[Dict[str, Any]],
                                                     claim_data: Dict[str, Any]) -> RuleResult:
        
        primary_diagnosis = diagnosis_candidates[0] if diagnosis_candidates else None
        
        return self.approve(
            reason=f"Diagnosis path selected: Procedure {icd10_procedure} found but no valid G-DRG candidates",
            metadata={
                'step': 'A2_PROCEDURE_VS_DIAGNOSIS',
                'determination': 'DIAGNOSIS_PATH',
                'selected_gdrg': primary_diagnosis.get('gdrg_code') if primary_diagnosis else None,
                'path_reason': 'PROCEDURE_NO_GDRG_CANDIDATES',
                'procedure_code': icd10_procedure,
                'diagnosis_code': icd10_diagnosis
            }
        )
    
    def _create_path_determination_result(self, determination: Dict[str, Any], 
                                        icd10_diagnosis: str, icd10_procedure: str,
                                        procedure_name: str, claim_data: Dict[str, Any]) -> RuleResult:
        
        dominant_path = determination['dominant_path']
        selected_candidate = determination['selected_candidate']
        alternative_candidate = determination['alternative_candidate']
        reasons = determination['determination_reasons']
        confidence = determination['confidence_level']
        
        metadata = {
            'step': 'A2_PROCEDURE_VS_DIAGNOSIS',
            'determination': dominant_path,
            'selected_gdrg': selected_candidate.get('gdrg_code') if selected_candidate else None,
            'selected_gdrg_name': selected_candidate.get('gdrg_name') if selected_candidate else None,
            'alternative_gdrg': alternative_candidate.get('gdrg_code') if alternative_candidate else None,
            'determination_reasons': reasons,
            'confidence_level': confidence,
            'diagnosis_code': icd10_diagnosis,
            'procedure_code': icd10_procedure,
            'procedure_name': procedure_name
        }
        
        if confidence == 'MEDIUM':
            return self.flag(
                reason=f"{dominant_path.replace('_', ' ').title()} selected with medium confidence",
                severity=RuleSeverity.LOW,
                warnings=[
                    f"G-DRG determination confidence: {confidence}",
                    f"Selected: {selected_candidate.get('gdrg_code')} via {dominant_path.replace('_', ' ').lower()}",
                    f"Alternative: {alternative_candidate.get('gdrg_code')} available"
                ],
                recommendations=[
                    "Review clinical documentation for accuracy",
                    "Verify procedure and diagnosis coding alignment",
                    "Consider clinical appropriateness of selected G-DRG"
                ],
                metadata=metadata
            )
        
        return self.approve(
            reason=f"{dominant_path.replace('_', ' ').title()} selected: {selected_candidate.get('gdrg_code')}",
            metadata=metadata
        )