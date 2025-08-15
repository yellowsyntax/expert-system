from typing import Dict, Any
from datetime import datetime, timedelta
from ..base_rule import BaseRule, RuleResult, RuleDecision, RuleSeverity

class BillingTimingRule(BaseRule):
    def __init__(self, db_session, reference_data_manager):
        super().__init__(db_session, reference_data_manager)
    
    def validate(self, claim_data: Dict[str, Any], context: Dict[str, Any]) -> RuleResult:
        service_type = claim_data.get('service_type_1')
        admission_date = claim_data.get('admission_date')
        discharge_date = claim_data.get('discharge_date')
        created_at = claim_data.get('created_at')
        encounter_id = claim_data.get('encounter_id')
        
        if service_type != 'IPD':
            return self.approve(
                reason="Billing timing rule only applies to inpatient (IPD) claims",
                metadata={'service_type': service_type, 'rule_applied': False}
            )
        
        if not admission_date:
            return self.reject(
                reason="IPD claims must have admission date",
                severity=RuleSeverity.HIGH,
                validation_errors=["Missing admission date for inpatient claim"],
                recommendations=[
                    "Provide valid admission date for IPD claim",
                    "Verify patient was actually admitted to facility"
                ]
            )
        
        if not discharge_date:
            return self.reject(
                reason="IPD claims must have discharge date before billing",
                severity=RuleSeverity.HIGH,
                validation_errors=[
                    "Missing discharge date for inpatient claim",
                    "Cannot bill for ongoing inpatient stay"
                ],
                recommendations=[
                    "Wait until patient is discharged before submitting claim",
                    "Provide valid discharge date and time",
                    "Ensure discharge documentation is complete"
                ],
                metadata={
                    'admission_date': admission_date.isoformat() if admission_date else None,
                    'billing_status': 'PREMATURE_BILLING'
                }
            )
        
        if not created_at:
            created_at = datetime.utcnow()
        
        return self._validate_billing_timing(
            admission_date, discharge_date, created_at, encounter_id, claim_data
        )
    
    def _validate_billing_timing(self, admission_date: datetime, discharge_date: datetime,
                                bill_submission_date: datetime, encounter_id: str,
                                claim_data: Dict[str, Any]) -> RuleResult:
        
        if discharge_date > bill_submission_date:
            hours_until_discharge = (discharge_date - bill_submission_date).total_seconds() / 3600
            
            return self.reject(
                reason="Cannot bill before patient discharge",
                severity=RuleSeverity.HIGH,
                validation_errors=[
                    f"Claim submitted before discharge date",
                    f"Discharge scheduled for {discharge_date.isoformat()}",
                    f"Claim submitted at {bill_submission_date.isoformat()}",
                    f"Patient still admitted for {hours_until_discharge:.1f} more hours"
                ],
                recommendations=[
                    "Wait until after patient discharge to submit claim",
                    "Verify discharge date and time are accurate",
                    "Ensure all discharge procedures are completed",
                    "Submit claim only after patient has left facility"
                ],
                metadata={
                    'admission_date': admission_date.isoformat(),
                    'discharge_date': discharge_date.isoformat(),
                    'bill_submission_date': bill_submission_date.isoformat(),
                    'hours_until_discharge': hours_until_discharge,
                    'billing_status': 'PREMATURE_BILLING',
                    'encounter_id': encounter_id
                }
            )
        
        if admission_date >= discharge_date:
            return self.reject(
                reason="Invalid admission/discharge dates",
                severity=RuleSeverity.HIGH,
                validation_errors=[
                    f"Discharge date ({discharge_date.isoformat()}) must be after admission date ({admission_date.isoformat()})",
                    "Admission and discharge dates are logically inconsistent"
                ],
                recommendations=[
                    "Verify admission date is correct",
                    "Verify discharge date is correct", 
                    "Ensure dates reflect actual patient timeline",
                    "Check for data entry errors"
                ],
                metadata={
                    'admission_date': admission_date.isoformat(),
                    'discharge_date': discharge_date.isoformat(),
                    'date_relationship': 'INVALID_SEQUENCE'
                }
            )
        
        length_of_stay = (discharge_date - admission_date).days
        hours_after_discharge = (bill_submission_date - discharge_date).total_seconds() / 3600
        
        warnings = []
        recommendations = []
        flags = []
        
        if length_of_stay == 0:
            same_day_hours = (discharge_date - admission_date).total_seconds() / 3600
            if same_day_hours < 6:
                warnings.append(
                    f"Very short stay ({same_day_hours:.1f} hours) - verify IPD classification is appropriate"
                )
                recommendations.append(
                    "Consider if this should be classified as OPD or A&E visit instead"
                )
                flags.append("SHORT_STAY_VERIFICATION_NEEDED")
        
        if length_of_stay > 30:
            warnings.append(
                f"Extended stay ({length_of_stay} days) - may require additional documentation"
            )
            recommendations.append(
                "Extended stays may require clinical justification for continued admission"
            )
            flags.append("EXTENDED_STAY_REVIEW")
        
        billing_timing_rules = self.get_reference_data('bundling_rules').get('billing_timing', {})
        max_days_after_discharge = billing_timing_rules.get('max_days_after_discharge', 30)
        
        if hours_after_discharge > (max_days_after_discharge * 24):
            warnings.append(
                f"Late billing submission ({hours_after_discharge/24:.1f} days after discharge)"
            )
            recommendations.append(
                f"Claims should be submitted within {max_days_after_discharge} days of discharge"
            )
            flags.append("LATE_BILLING_SUBMISSION")
        
        weekends_included = self._check_weekend_discharge(discharge_date, bill_submission_date)
        if weekends_included:
            recommendations.append(
                "Consider weekend/holiday impacts on billing timeline"
            )
        
        metadata = {
            'admission_date': admission_date.isoformat(),
            'discharge_date': discharge_date.isoformat(),
            'bill_submission_date': bill_submission_date.isoformat(),
            'length_of_stay_days': length_of_stay,
            'hours_after_discharge': round(hours_after_discharge, 2),
            'billing_status': 'VALID_TIMING',
            'encounter_id': encounter_id,
            'flags': flags,
            'weekends_in_billing_period': weekends_included
        }
        
        if warnings:
            return self.flag(
                reason=f"IPD billing timing valid but requires attention (LOS: {length_of_stay} days)",
                severity=RuleSeverity.LOW if length_of_stay <= 7 else RuleSeverity.MEDIUM,
                warnings=warnings,
                recommendations=recommendations,
                metadata=metadata
            )
        
        return self.approve(
            reason=f"IPD billing timing valid - billed {hours_after_discharge:.1f} hours after discharge (LOS: {length_of_stay} days)",
            metadata=metadata
        )
    
    def _check_weekend_discharge(self, discharge_date: datetime, bill_date: datetime) -> bool:
        current_date = discharge_date.date()
        bill_date_only = bill_date.date()
        
        while current_date <= bill_date_only:
            if current_date.weekday() >= 5:  # 5=Saturday, 6=Sunday
                return True
            current_date += timedelta(days=1)
        
        return False
    
    def validate_discharge_documentation(self, claim_data: Dict[str, Any]) -> Dict[str, Any]:
        documentation_status = {
            'has_discharge_summary': bool(claim_data.get('discharge_summary')),
            'has_final_diagnosis': bool(claim_data.get('icd10_diagnosis')),
            'has_discharge_date': bool(claim_data.get('discharge_date')),
            'has_service_outcome': bool(claim_data.get('service_outcome')),
            'documentation_score': 0,
            'missing_elements': [],
            'recommendations': []
        }
        
        required_elements = [
            ('discharge_summary', 'Discharge summary or notes'),
            ('icd10_diagnosis', 'Final diagnosis with ICD-10 code'),
            ('discharge_date', 'Discharge date and time'),
            ('service_outcome', 'Service outcome (recovered, referred, etc.)')
        ]
        
        for field, description in required_elements:
            if documentation_status[f'has_{field}']:
                documentation_status['documentation_score'] += 1
            else:
                documentation_status['missing_elements'].append(description)
        
        if documentation_status['documentation_score'] < 3:
            documentation_status['recommendations'].append(
                "Incomplete discharge documentation may delay claim processing"
            )
        
        return documentation_status
    
    def get_length_of_stay_analysis(self, admission_date: datetime, discharge_date: datetime) -> Dict[str, Any]:
        if not admission_date or not discharge_date:
            return {'error': 'Both admission and discharge dates required'}
        
        total_hours = (discharge_date - admission_date).total_seconds() / 3600
        total_days = (discharge_date - admission_date).days
        
        stay_category = "UNKNOWN"
        if total_hours < 24:
            if total_hours < 6:
                stay_category = "VERY_SHORT"
            else:
                stay_category = "SAME_DAY"
        elif total_days <= 3:
            stay_category = "SHORT_STAY"
        elif total_days <= 7:
            stay_category = "STANDARD_STAY"
        elif total_days <= 14:
            stay_category = "MEDIUM_STAY"
        elif total_days <= 30:
            stay_category = "LONG_STAY"
        else:
            stay_category = "EXTENDED_STAY"
        
        return {
            'admission_date': admission_date.isoformat(),
            'discharge_date': discharge_date.isoformat(),
            'total_hours': round(total_hours, 2),
            'total_days': total_days,
            'stay_category': stay_category,
            'is_same_day': total_hours < 24,
            'requires_justification': total_days > 14 or total_hours < 6
        }