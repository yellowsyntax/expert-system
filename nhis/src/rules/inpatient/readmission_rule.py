from typing import Dict, Any, List
from datetime import datetime, timedelta
from ..base_rule import BaseRule, RuleResult, RuleDecision, RuleSeverity
from ...database.queries import ReadmissionQueries

class ReadmissionRule(BaseRule):
    def __init__(self, db_session, reference_data_manager):
        super().__init__(db_session, reference_data_manager)
        self.readmission_queries = ReadmissionQueries(db_session)
    
    def validate(self, claim_data: Dict[str, Any], context: Dict[str, Any]) -> RuleResult:
        service_type = claim_data.get('service_type_1')
        nhis_number = claim_data.get('nhis_number')
        admission_date = claim_data.get('admission_date')
        icd10_diagnosis = claim_data.get('icd10_diagnosis')
        provider_id = claim_data.get('provider_id')
        
        if service_type != 'IPD':
            return self.approve(
                reason="Emergency readmission rule only applies to inpatient (IPD) claims",
                metadata={'service_type': service_type, 'rule_applied': False}
            )
        
        if not nhis_number:
            return self.reject(
                reason="NHIS number required for readmission validation",
                validation_errors=["Missing NHIS number"]
            )
        
        if not admission_date:
            return self.reject(
                reason="Admission date required for readmission validation",
                validation_errors=["Missing admission date"],
                recommendations=[
                    "Provide valid admission date for readmission analysis",
                    "Ensure admission date reflects actual patient admission time"
                ]
            )
        
        if not icd10_diagnosis:
            return self.flag(
                reason="Diagnosis missing - limited readmission analysis possible",
                severity=RuleSeverity.LOW,
                warnings=["Diagnosis code missing for readmission correlation analysis"],
                recommendations=["Provide ICD-10 diagnosis for complete readmission validation"]
            )
        
        try:
            return self._validate_readmission(
                nhis_number, admission_date, icd10_diagnosis, provider_id, claim_data
            )
            
        except Exception as e:
            return self.reject(
                reason="Error during readmission validation",
                severity=RuleSeverity.CRITICAL,
                validation_errors=[f"Readmission validation failed: {str(e)}"],
                metadata={'error_type': 'validation_error'}
            )
    
    def _validate_readmission(self, nhis_number: str, current_admission: datetime,
                            current_diagnosis: str, facility_id: str, 
                            claim_data: Dict[str, Any]) -> RuleResult:
        
        readmission_validation = self.readmission_queries.validate_emergency_readmission_rule(
            nhis_number=nhis_number,
            current_admission=current_admission,
            current_diagnosis=current_diagnosis or '',
            facility_id=facility_id
        )
        
        has_violation = readmission_validation.get('has_violation', False)
        highest_risk = readmission_validation.get('highest_risk_level', 'NO_RISK')
        recent_readmissions = readmission_validation.get('recent_readmissions', [])
        readmission_count = readmission_validation.get('readmission_count', 0)
        
        if not has_violation and readmission_count == 0:
            return self.approve(
                reason="No recent readmissions found - emergency readmission rule compliant",
                metadata={
                    'nhis_number': nhis_number,
                    'readmission_count': 0,
                    'rule_status': 'COMPLIANT',
                    'risk_level': 'NO_RISK'
                }
            )
        
        if has_violation:
            return self._handle_readmission_violation(
                readmission_validation, current_diagnosis, claim_data
            )
        
        return self._handle_readmission_warning(
            readmission_validation, current_diagnosis, claim_data
        )
    
    def _handle_readmission_violation(self, validation_result: Dict[str, Any],
                                    current_diagnosis: str, claim_data: Dict[str, Any]) -> RuleResult:
        
        recent_readmissions = validation_result.get('recent_readmissions', [])
        highest_risk = validation_result.get('highest_risk_level', 'HIGH_RISK')
        
        violation_readmissions = [r for r in recent_readmissions if r.get('days_between', 999) <= 30]
        
        if not violation_readmissions:
            return self.approve(
                reason="No 30-day readmission violations found",
                metadata=validation_result
            )
        
        primary_violation = violation_readmissions[0]
        days_between = primary_violation.get('days_between', 0)
        previous_diagnosis = primary_violation.get('previous_diagnosis', 'Unknown')
        diagnosis_relationship = primary_violation.get('diagnosis_relationship', 'UNKNOWN')
        facility_relationship = primary_violation.get('facility_relationship', 'UNKNOWN')
        
        readmission_rules = self.get_reference_data('bundling_rules').get('readmission', {})
        
        if self._is_planned_readmission(current_diagnosis, previous_diagnosis, claim_data):
            return self.flag(
                reason=f"Planned readmission within 30 days (may be clinically appropriate)",
                severity=RuleSeverity.LOW,
                warnings=[
                    f"Readmission {days_between} days after previous discharge",
                    f"Previous diagnosis: {previous_diagnosis}",
                    f"Current diagnosis: {current_diagnosis}",
                    "Appears to be planned procedure or staged treatment"
                ],
                recommendations=[
                    "Verify this is a planned readmission or staged procedure",
                    "Provide clinical justification for readmission timing",
                    "Consider if procedures could be combined in single admission"
                ],
                metadata={
                    **validation_result,
                    'readmission_type': 'PLANNED',
                    'requires_justification': True
                }
            )
        
        if diagnosis_relationship == 'SAME_DIAGNOSIS' and days_between <= 7:
            return self.reject(
                reason=f"Emergency readmission violation - same condition within {days_between} days",
                severity=RuleSeverity.HIGH,
                validation_errors=[
                    f"Patient readmitted {days_between} days after discharge",
                    f"Same diagnosis: {current_diagnosis}",
                    "Indicates potential premature discharge or inadequate treatment",
                    "Emergency readmission rule violation (≤30 days same condition)"
                ],
                recommendations=[
                    "Review adequacy of initial treatment and discharge planning",
                    "Investigate if initial admission length was appropriate",
                    "Provide clinical justification for readmission necessity",
                    "Consider quality improvement measures"
                ],
                metadata={
                    **validation_result,
                    'violation_severity': 'HIGH',
                    'days_between_admissions': days_between,
                    'clinical_review_required': True
                }
            )
        
        if diagnosis_relationship == 'RELATED_DIAGNOSIS' and days_between <= 14:
            return self.flag(
                reason=f"Related condition readmission within {days_between} days - requires justification",
                severity=RuleSeverity.MEDIUM,
                warnings=[
                    f"Readmission for related condition {days_between} days after discharge",
                    f"Previous: {previous_diagnosis}, Current: {current_diagnosis}",
                    "May indicate complications or incomplete initial treatment"
                ],
                recommendations=[
                    "Provide clinical justification for readmission",
                    "Review if complications could have been anticipated",
                    "Document medical necessity for separate admission",
                    "Consider quality assurance review"
                ],
                metadata={
                    **validation_result,
                    'requires_justification': True,
                    'clinical_review_recommended': True
                }
            )
        
        return self.flag(
            reason=f"Readmission within 30 days detected - monitoring required",
            severity=RuleSeverity.LOW,
            warnings=[
                f"Readmission {days_between} days after previous discharge",
                f"Different diagnosis: {previous_diagnosis} → {current_diagnosis}",
                "Within 30-day monitoring period"
            ],
            recommendations=[
                "Document clinical necessity for readmission",
                "Ensure diagnoses are accurately coded",
                "Monitor readmission patterns for quality improvement"
            ],
            metadata={
                **validation_result,
                'monitoring_flag': True
            }
        )
    
    def _handle_readmission_warning(self, validation_result: Dict[str, Any],
                                  current_diagnosis: str, claim_data: Dict[str, Any]) -> RuleResult:
        
        recent_readmissions = validation_result.get('recent_readmissions', [])
        readmission_count = len(recent_readmissions)
        
        if readmission_count >= 2:
            return self.flag(
                reason=f"Multiple recent readmissions detected ({readmission_count} in past 120 days)",
                severity=RuleSeverity.MEDIUM,
                warnings=[
                    f"Patient has {readmission_count} readmissions in past 4 months",
                    "Pattern may indicate chronic condition or quality issues"
                ],
                recommendations=[
                    "Review patient's overall care management",
                    "Consider case management or care coordination",
                    "Evaluate discharge planning effectiveness",
                    "Monitor for potential quality concerns"
                ],
                metadata={
                    **validation_result,
                    'pattern_analysis_recommended': True
                }
            )
        
        return self.approve(
            reason=f"Readmission detected but outside violation parameters ({readmission_count} recent readmissions)",
            metadata={
                **validation_result,
                'monitoring_recommended': True
            }
        )
    
    def _is_planned_readmission(self, current_diagnosis: str, previous_diagnosis: str,
                              claim_data: Dict[str, Any]) -> bool:
        
        planned_readmission_indicators = self.get_reference_data('bundling_rules').get(
            'planned_readmission_indicators', {}
        )
        
        planned_diagnosis_pairs = planned_readmission_indicators.get('diagnosis_pairs', [])
        
        for pair in planned_diagnosis_pairs:
            if (current_diagnosis.startswith(pair.get('first', '')) and 
                previous_diagnosis.startswith(pair.get('second', ''))):
                return True
        
        planned_procedure_categories = [
            'staged cardiac procedures',
            'cancer treatment phases',
            'orthopedic reconstructions',
            'planned surgical revisions'
        ]
        
        procedure_name = claim_data.get('procedure_name', '').lower()
        for category in planned_procedure_categories:
            if category in procedure_name:
                return True
        
        if current_diagnosis.startswith('Z51'):  # Encounter for other aftercare
            return True
        
        if 'staged' in procedure_name or 'phase' in procedure_name or 'revision' in procedure_name:
            return True
        
        return False
    
    def get_patient_readmission_history(self, nhis_number: str, months_back: int = 12) -> Dict[str, Any]:
        try:
            readmission_patterns = self.readmission_queries.get_readmission_patterns(
                days_back=months_back * 30,
                min_readmissions=1,
                limit=1
            )
            
            patient_pattern = None
            for pattern in readmission_patterns:
                if pattern.get('nhis_number') == nhis_number:
                    patient_pattern = pattern
                    break
            
            if patient_pattern:
                return {
                    'nhis_number': nhis_number,
                    'has_readmission_history': True,
                    'total_readmissions': patient_pattern.get('total_readmissions', 0),
                    'violations_30_days': patient_pattern.get('violations_30_days', 0),
                    'readmissions_90_days': patient_pattern.get('readmissions_90_days', 0),
                    'avg_days_between': patient_pattern.get('avg_days_between', 0),
                    'shortest_interval': patient_pattern.get('shortest_interval', 0),
                    'facilities_involved': patient_pattern.get('facilities_involved', 0),
                    'risk_category': patient_pattern.get('risk_category', 'MONITOR'),
                    'readmission_details': patient_pattern.get('readmission_details', [])
                }
            else:
                return {
                    'nhis_number': nhis_number,
                    'has_readmission_history': False,
                    'total_readmissions': 0,
                    'risk_category': 'NO_RISK'
                }
                
        except Exception as e:
            return {
                'error': f"Failed to retrieve readmission history: {str(e)}",
                'nhis_number': nhis_number
            }
    
    def get_facility_readmission_metrics(self, facility_id: str, months_back: int = 6) -> Dict[str, Any]:
        try:
            facility_rates = self.readmission_queries.get_facility_readmission_rates(
                months_back=months_back,
                limit=None
            )
            
            facility_metrics = None
            for metrics in facility_rates:
                if metrics.get('provider_id') == facility_id:
                    facility_metrics = metrics
                    break
            
            return facility_metrics or {
                'provider_id': facility_id,
                'no_data': True,
                'reason': 'Insufficient admission volume or no readmissions data'
            }
            
        except Exception as e:
            return {
                'error': f"Failed to retrieve facility readmission metrics: {str(e)}",
                'provider_id': facility_id
            }