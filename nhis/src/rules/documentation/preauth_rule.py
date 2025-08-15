from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta
from ..base_rule import BaseRule, RuleResult, RuleResultType
from ...core.models import ClaimProcessingContext
import json
import logging

logger = logging.getLogger(__name__)


class PreauthRule(BaseRule):
    
    def __init__(self, reference_data_path: str = "reference_data/documentation_requirements.json"):
        super().__init__(
            rule_id="DOC_PREAUTH",
            name="Pre-authorization Rule",
            description="Validate pre-authorization requirements for eligible procedures"
        )
        self.reference_data = self._load_preauth_requirements(reference_data_path)
    
    def _load_preauth_requirements(self, file_path: str) -> Dict[str, Any]:
        try:
            with open(file_path, 'r') as f:
                data = json.load(f)
                return data.get('preauthorization', {})
        except Exception as e:
            logger.warning(f"Could not load pre-authorization reference data: {str(e)}")
            return self._get_default_preauth_data()
    
    def _get_default_preauth_data(self) -> Dict[str, Any]:
        return {
            "required_procedures": [
                "SURG001", "SURG002", "SURG003", "SURG004", "SURG005",
                "ZOOM03A", "ZOOM03B", "ZOOM03C", "ZOOM03D",
                "ORTHO001", "ORTHO002", "ORTHO003",
                "CARDIAC001", "CARDIAC002",
                "NEURO001", "NEURO002"
            ],
            "required_conditions": [
                "C00-C97",  # Cancer codes
                "M00-M25",  # Joint disorders
                "I20-I25",  # Ischemic heart diseases
                "G00-G09"   # Inflammatory CNS diseases
            ],
            "high_cost_threshold": 5000.0,
            "preauth_validity_days": 30,
            "exempted_facilities": ["EMERGENCY", "TRAUMA"],
            "exempted_settings": ["A&E", "EMERGENCY"]
        }
    
    def _requires_preauth_by_procedure(self, procedure_code: str) -> bool:
        required_procedures = self.reference_data.get('required_procedures', [])
        return any(req_proc in procedure_code for req_proc in required_procedures)
    
    def _requires_preauth_by_condition(self, icd10_code: str) -> bool:
        if not icd10_code:
            return False
        
        required_conditions = self.reference_data.get('required_conditions', [])
        icd10_prefix = icd10_code[:3].upper()
        
        for condition_range in required_conditions:
            if '-' in condition_range:
                start_code, end_code = condition_range.split('-')
                if start_code <= icd10_prefix <= end_code:
                    return True
            elif condition_range == icd10_prefix:
                return True
        
        return False
    
    def _requires_preauth_by_cost(self, total_amount: float) -> bool:
        high_cost_threshold = self.reference_data.get('high_cost_threshold', 5000.0)
        return total_amount >= high_cost_threshold
    
    def _is_exempted_facility(self, facility_type: str) -> bool:
        exempted_facilities = self.reference_data.get('exempted_facilities', [])
        return facility_type.upper() in exempted_facilities
    
    def _is_exempted_setting(self, encounter_setting: str) -> bool:
        exempted_settings = self.reference_data.get('exempted_settings', [])
        return encounter_setting.upper() in exempted_settings
    
    def _validate_preauth_document(self, claim) -> tuple[bool, Optional[str], Optional[datetime]]:
        preauth_fields = [
            'preauthorization_number',
            'preauth_number',
            'authorization_code',
            'approval_number'
        ]
        
        for field in preauth_fields:
            if hasattr(claim, field) and getattr(claim, field):
                preauth_number = getattr(claim, field)
                preauth_date = getattr(claim, f'{field}_date', None)
                return True, preauth_number, preauth_date
        
        return False, None, None
    
    def _validate_preauth_timing(self, service_date: datetime, preauth_date: Optional[datetime]) -> tuple[bool, str]:
        if not preauth_date:
            return True, "Pre-authorization date not available for timing validation"
        
        validity_days = self.reference_data.get('preauth_validity_days', 30)
        expiry_date = preauth_date + timedelta(days=validity_days)
        
        if service_date > expiry_date:
            days_expired = (service_date - expiry_date).days
            return False, f"Pre-authorization expired {days_expired} days before service date"
        
        if preauth_date > service_date:
            days_future = (preauth_date - service_date).days
            return False, f"Pre-authorization date is {days_future} days after service date"
        
        return True, "Pre-authorization timing is valid"
    
    def evaluate(self, context: ClaimProcessingContext) -> RuleResult:
        try:
            claim = context.claim
            
            # Check exemptions first
            if hasattr(claim, 'encounter_setting') and self._is_exempted_setting(claim.encounter_setting):
                return RuleResult(
                    rule_id=self.rule_id,
                    result_type=RuleResultType.APPROVE,
                    message=f"Pre-authorization not required for {claim.encounter_setting} setting",
                    details={"reason": "exempted_setting"}
                )
            
            if hasattr(claim, 'facility_type') and self._is_exempted_facility(claim.facility_type):
                return RuleResult(
                    rule_id=self.rule_id,
                    result_type=RuleResultType.APPROVE,
                    message=f"Pre-authorization not required for {claim.facility_type} facility",
                    details={"reason": "exempted_facility"}
                )
            
            # Determine if pre-authorization is required
            requires_preauth = False
            preauth_reasons = []
            
            # Check by procedures
            if hasattr(claim, 'procedures') and claim.procedures:
                for procedure in claim.procedures:
                    procedure_code = procedure.get('code', '')
                    if self._requires_preauth_by_procedure(procedure_code):
                        requires_preauth = True
                        preauth_reasons.append(f"Procedure {procedure_code} requires pre-authorization")
            
            # Check by diagnosis
            if claim.primary_diagnosis and self._requires_preauth_by_condition(claim.primary_diagnosis):
                requires_preauth = True
                preauth_reasons.append(f"Diagnosis {claim.primary_diagnosis} requires pre-authorization")
            
            # Check by cost
            total_amount = getattr(context, 'total_claim_amount', 0)
            if self._requires_preauth_by_cost(total_amount):
                requires_preauth = True
                preauth_reasons.append(f"High cost claim (GHS {total_amount}) requires pre-authorization")
            
            if not requires_preauth:
                return RuleResult(
                    rule_id=self.rule_id,
                    result_type=RuleResultType.APPROVE,
                    message="Pre-authorization not required for this claim",
                    details={"reason": "not_required"}
                )
            
            # Validate pre-authorization documentation
            has_preauth, preauth_number, preauth_date = self._validate_preauth_document(claim)
            
            if not has_preauth:
                return RuleResult(
                    rule_id=self.rule_id,
                    result_type=RuleResultType.PEND,
                    message="Missing required pre-authorization documentation",
                    details={
                        "reason": "missing_preauth",
                        "preauth_reasons": preauth_reasons
                    }
                )
            
            # Validate timing if date is available
            timing_valid, timing_message = self._validate_preauth_timing(claim.service_date, preauth_date)
            
            details = {
                "preauth_required": True,
                "preauth_reasons": preauth_reasons,
                "preauth_number": preauth_number,
                "preauth_date": preauth_date.isoformat() if preauth_date else None,
                "timing_valid": timing_valid,
                "timing_message": timing_message,
                "validity_days": self.reference_data.get('preauth_validity_days', 30)
            }
            
            if not timing_valid:
                return RuleResult(
                    rule_id=self.rule_id,
                    result_type=RuleResultType.PEND,
                    message=f"Pre-authorization timing issue: {timing_message}",
                    details=details
                )
            
            context.preauth_validated = True
            context.preauth_number = preauth_number
            
            return RuleResult(
                rule_id=self.rule_id,
                result_type=RuleResultType.APPROVE,
                message=f"Pre-authorization validated: {preauth_number}",
                details=details
            )
            
        except Exception as e:
            logger.error(f"Error in PreauthRule evaluation: {str(e)}")
            return RuleResult(
                rule_id=self.rule_id,
                result_type=RuleResultType.FLAG,
                message=f"Error during pre-authorization validation: {str(e)}",
                details={"error": str(e)}
            )