from typing import Dict, Any, List
from datetime import datetime, timedelta
from ..base_rule import BaseRule, RuleResult, RuleDecision, RuleSeverity
from ...database.queries import EpisodeTrackingQueries

class PhysiotherapyRule(BaseRule):
    def __init__(self, db_session, reference_data_manager):
        super().__init__(db_session, reference_data_manager)
        self.episode_queries = EpisodeTrackingQueries(db_session)
    
    def validate(self, claim_data: Dict[str, Any], context: Dict[str, Any]) -> RuleResult:
        procedure_code = claim_data.get('icd10_procedure')
        procedure_name = claim_data.get('procedure_name', '')
        icd10_diagnosis = claim_data.get('icd10_diagnosis')
        nhis_number = claim_data.get('nhis_number')
        service_type = claim_data.get('service_type_1')
        
        if not self._is_physiotherapy_procedure(procedure_code, procedure_name):
            return self.approve(
                reason="Not a physiotherapy procedure - rule not applicable",
                metadata={'procedure_code': procedure_code, 'is_physio': False, 'rule_applied': False}
            )
        
        if not nhis_number:
            return self.reject(
                reason="NHIS number required for physiotherapy session validation",
                validation_errors=["Missing NHIS number"]
            )
        
        if not icd10_diagnosis:
            return self.reject(
                reason="Diagnosis code required for physiotherapy eligibility validation",
                validation_errors=["Missing ICD-10 diagnosis code"],
                recommendations=[
                    "Provide primary diagnosis justifying physiotherapy treatment",
                    "Ensure diagnosis supports medical necessity for physiotherapy"
                ]
            )
        
        try:
            return self._validate_physiotherapy_claim(
                nhis_number, icd10_diagnosis, procedure_code, claim_data
            )
            
        except Exception as e:
            return self.reject(
                reason="Error during physiotherapy validation",
                severity=RuleSeverity.CRITICAL,
                validation_errors=[f"Validation failed: {str(e)}"],
                metadata={'error_type': 'validation_error'}
            )
    
    def _is_physiotherapy_procedure(self, procedure_code: str, procedure_name: str) -> bool:
        if procedure_code:
            physio_codes = ['ZOOM04', 'PHYS01', 'PHYS02', 'PHYS03', 'PHYS04', 'PHYS05']
            if any(procedure_code.upper().startswith(code) for code in physio_codes):
                return True
        
        if procedure_name:
            physio_keywords = [
                'physiotherapy', 'physical therapy', 'rehabilitation', 
                'exercise therapy', 'mobility training', 'therapeutic exercise'
            ]
            procedure_lower = procedure_name.lower()
            return any(keyword in procedure_lower for keyword in physio_keywords)
        
        return False
    
    def _validate_physiotherapy_claim(self, nhis_number: str, icd10_diagnosis: str, 
                                    procedure_code: str, claim_data: Dict[str, Any]) -> RuleResult:
        
        eligibility_result = self._validate_condition_eligibility(icd10_diagnosis)
        if not eligibility_result['is_eligible']:
            return self._handle_ineligible_condition(icd10_diagnosis, eligibility_result, claim_data)
        
        session_validation = self.episode_queries.validate_physiotherapy_limits(
            nhis_number=nhis_number,
            condition_icd10=icd10_diagnosis
        )
        
        if not session_validation.get('is_within_limit', False):
            return self._handle_session_limit_exceeded(
                nhis_number, icd10_diagnosis, session_validation, claim_data
            )
        
        documentation_result = self._validate_documentation_requirements(claim_data)
        
        return self._approve_physiotherapy_session(
            nhis_number, icd10_diagnosis, procedure_code, eligibility_result, 
            session_validation, documentation_result, claim_data
        )
    
    def _validate_condition_eligibility(self, icd10_diagnosis: str) -> Dict[str, Any]:
        physio_conditions = self.get_reference_data('physiotherapy_conditions')
        
        if not physio_conditions:
            return {
                'is_eligible': False,
                'reason': 'Physiotherapy conditions reference data not available',
                'condition_details': None
            }
        
        for condition_code, condition_data in physio_conditions.items():
            if icd10_diagnosis.startswith(condition_code):
                return {
                    'is_eligible': True,
                    'condition_code': condition_code,
                    'condition_name': condition_data.get('name', 'Unknown condition'),
                    'max_sessions': condition_data.get('max_sessions_per_year', 12),
                    'session_duration': condition_data.get('typical_session_duration', 60),
                    'requires_referral': condition_data.get('requires_specialist_referral', False),
                    'condition_category': condition_data.get('category', 'General'),
                    'treatment_goals': condition_data.get('treatment_goals', [])
                }
        
        return {
            'is_eligible': False,
            'reason': f'Diagnosis {icd10_diagnosis} not found in NHIS physiotherapy eligible conditions',
            'condition_details': None,
            'suggested_conditions': self._get_similar_conditions(icd10_diagnosis, physio_conditions)
        }
    
    def _get_similar_conditions(self, icd10_diagnosis: str, physio_conditions: Dict[str, Any]) -> List[str]:
        diagnosis_category = self.get_icd10_category(icd10_diagnosis)
        similar_conditions = []
        
        for condition_code, condition_data in physio_conditions.items():
            condition_category = self.get_icd10_category(condition_code)
            if condition_category == diagnosis_category:
                similar_conditions.append(f"{condition_code} - {condition_data.get('name', 'Unknown')}")
        
        return similar_conditions[:3]
    
    def _validate_documentation_requirements(self, claim_data: Dict[str, Any]) -> Dict[str, Any]:
        doc_requirements = self.get_reference_data('documentation_requirements').get('physiotherapy', {})
        
        documentation_result = {
            'has_referral': self._has_physio_referral(claim_data),
            'has_assessment': self._has_initial_assessment(claim_data),
            'has_treatment_plan': self._has_treatment_plan(claim_data),
            'has_progress_notes': self._has_progress_notes(claim_data),
            'documentation_score': 0,
            'missing_documents': [],
            'recommendations': []
        }
        
        required_docs = [
            ('referral', 'has_referral', 'Specialist referral or prescription'),
            ('assessment', 'has_assessment', 'Initial physiotherapy assessment'),
            ('treatment_plan', 'has_treatment_plan', 'Treatment plan and goals'),
            ('progress_notes', 'has_progress_notes', 'Progress notes or attendance record')
        ]
        
        for doc_type, check_field, description in required_docs:
            if documentation_result[check_field]:
                documentation_result['documentation_score'] += 1
            else:
                documentation_result['missing_documents'].append(description)
        
        if documentation_result['documentation_score'] < 2:
            documentation_result['recommendations'].append(
                "Minimum 2 documentation requirements should be met for physiotherapy claims"
            )
        
        return documentation_result
    
    def _has_physio_referral(self, claim_data: Dict[str, Any]) -> bool:
        referral_fields = [
            'referral_notes', 'physio_referral', 'specialist_referral',
            'doctor_prescription', 'treatment_prescription'
        ]
        return any(claim_data.get(field) for field in referral_fields)
    
    def _has_initial_assessment(self, claim_data: Dict[str, Any]) -> bool:
        assessment_fields = [
            'initial_assessment', 'physio_assessment', 'baseline_assessment',
            'functional_assessment', 'assessment_notes'
        ]
        return any(claim_data.get(field) for field in assessment_fields)
    
    def _has_treatment_plan(self, claim_data: Dict[str, Any]) -> bool:
        plan_fields = [
            'treatment_plan', 'physio_plan', 'care_plan',
            'therapy_goals', 'treatment_goals'
        ]
        return any(claim_data.get(field) for field in plan_fields)
    
    def _has_progress_notes(self, claim_data: Dict[str, Any]) -> bool:
        progress_fields = [
            'progress_notes', 'session_notes', 'treatment_notes',
            'attendance_record', 'therapy_progress'
        ]
        return any(claim_data.get(field) for field in progress_fields)
    
    def _handle_ineligible_condition(self, icd10_diagnosis: str, 
                                   eligibility_result: Dict[str, Any], 
                                   claim_data: Dict[str, Any]) -> RuleResult:
        
        suggested_conditions = eligibility_result.get('suggested_conditions', [])
        
        validation_errors = [
            f"Diagnosis {icd10_diagnosis} is not eligible for NHIS physiotherapy coverage",
            eligibility_result.get('reason', 'Condition not in approved list')
        ]
        
        recommendations = [
            "Review diagnosis coding for accuracy",
            "Consider if alternative treatment modalities are more appropriate",
            "Verify patient condition meets NHIS physiotherapy criteria"
        ]
        
        if suggested_conditions:
            recommendations.append(
                f"Similar eligible conditions include: {', '.join(suggested_conditions)}"
            )
        
        return self.reject(
            reason=f"Physiotherapy not covered for diagnosis {icd10_diagnosis}",
            severity=RuleSeverity.HIGH,
            validation_errors=validation_errors,
            recommendations=recommendations,
            metadata={
                'diagnosis_code': icd10_diagnosis,
                'eligibility_status': 'NOT_ELIGIBLE',
                'suggested_conditions': suggested_conditions
            }
        )
    
    def _handle_session_limit_exceeded(self, nhis_number: str, icd10_diagnosis: str,
                                     session_validation: Dict[str, Any], 
                                     claim_data: Dict[str, Any]) -> RuleResult:
        
        current_sessions = session_validation.get('current_sessions', 0)
        max_sessions = session_validation.get('max_sessions', 0)
        sessions_remaining = session_validation.get('sessions_remaining', 0)
        will_exceed = session_validation.get('will_exceed_if_approved', False)
        
        if will_exceed:
            return self.reject(
                reason=f"Physiotherapy session limit exceeded for diagnosis {icd10_diagnosis}",
                severity=RuleSeverity.MEDIUM,
                validation_errors=[
                    f"Patient has {current_sessions} physiotherapy sessions in past 12 months",
                    f"Maximum allowed for this condition is {max_sessions} sessions per year",
                    "Approving this session would exceed the annual limit"
                ],
                recommendations=[
                    "Review treatment progress and outcomes",
                    "Consider if additional sessions are medically necessary",
                    "Evaluate alternative treatment approaches",
                    "Specialist review may be required for extended treatment"
                ],
                metadata={
                    'nhis_number': nhis_number,
                    'diagnosis_code': icd10_diagnosis,
                    'current_sessions': current_sessions,
                    'max_sessions': max_sessions,
                    'limit_status': 'EXCEEDED'
                }
            )
        
        return self.approve(
            reason=f"Physiotherapy session within limits for {icd10_diagnosis}",
            metadata={
                'nhis_number': nhis_number,
                'diagnosis_code': icd10_diagnosis,
                'current_sessions': current_sessions,
                'max_sessions': max_sessions,
                'sessions_remaining': sessions_remaining,
                'limit_status': 'WITHIN_LIMIT'
            }
        )
    
    def _approve_physiotherapy_session(self, nhis_number: str, icd10_diagnosis: str, 
                                     procedure_code: str, eligibility_result: Dict[str, Any],
                                     session_validation: Dict[str, Any], 
                                     documentation_result: Dict[str, Any],
                                     claim_data: Dict[str, Any]) -> RuleResult:
        
        sessions_remaining = session_validation.get('sessions_remaining', 0)
        max_sessions = eligibility_result.get('max_sessions', 12)
        current_sessions = session_validation.get('current_sessions', 0)
        documentation_score = documentation_result.get('documentation_score', 0)
        missing_docs = documentation_result.get('missing_documents', [])
        
        metadata = {
            'nhis_number': nhis_number,
            'diagnosis_code': icd10_diagnosis,
            'procedure_code': procedure_code,
            'condition_name': eligibility_result.get('condition_name'),
            'condition_category': eligibility_result.get('condition_category'),
            'current_sessions': current_sessions,
            'max_sessions': max_sessions,
            'sessions_remaining': sessions_remaining,
            'documentation_score': documentation_score,
            'requires_referral': eligibility_result.get('requires_referral', False)
        }
        
        warnings = []
        recommendations = []
        
        if sessions_remaining <= 2:
            warnings.append(
                f"Approaching physiotherapy session limit: {sessions_remaining} sessions remaining this year"
            )
            recommendations.append(
                "Consider treatment progress review before next session"
            )
        
        if documentation_score < 3:
            warnings.append(
                f"Documentation incomplete: {len(missing_docs)} recommended documents missing"
            )
            recommendations.extend([
                f"Consider providing: {', '.join(missing_docs)}",
                "Complete documentation supports treatment continuity"
            ])
        
        if eligibility_result.get('requires_referral') and not documentation_result.get('has_referral'):
            warnings.append(
                "Specialist referral recommended for this condition"
            )
        
        if warnings:
            return self.flag(
                reason=f"Physiotherapy session approved for {eligibility_result.get('condition_name', icd10_diagnosis)} with recommendations",
                severity=RuleSeverity.LOW,
                warnings=warnings,
                recommendations=recommendations,
                metadata=metadata
            )
        
        return self.approve(
            reason=f"Physiotherapy session approved for eligible condition {eligibility_result.get('condition_name', icd10_diagnosis)}",
            metadata=metadata
        )
    
    def get_physiotherapy_summary(self, nhis_number: str, months_back: int = 12) -> Dict[str, Any]:
        try:
            physio_sessions = self.episode_queries.get_physiotherapy_sessions(nhis_number, months_back)
            session_count = self.episode_queries.count_physiotherapy_sessions(nhis_number, months_back)
            
            return {
                'nhis_number': nhis_number,
                'total_sessions': session_count,
                'sessions_detail': physio_sessions,
                'period_months': months_back
            }
            
        except Exception as e:
            return {
                'error': f"Failed to retrieve physiotherapy summary: {str(e)}",
                'nhis_number': nhis_number
            }