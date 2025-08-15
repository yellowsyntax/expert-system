from typing import Optional, Dict, Any
from ..base_rule import BaseRule, RuleResult, RuleResultType
from ...core.models import ClaimProcessingContext
import logging

logger = logging.getLogger(__name__)


class ClassificationRule(BaseRule):
    
    def __init__(self):
        super().__init__(
            rule_id="AE_CLASSIFY",
            name="A&E Classification Rule",
            description="Classify A&E encounters for appropriate processing path"
        )
        
        self.admission_indicators = {
            'admission_decision', 'ward_admission', 'icu_admission',
            'surgery_required', 'overnight_stay', 'bed_assigned'
        }
        
        self.detention_procedures = {'ZOOM02A'}
        
        self.opd_like_conditions = {
            'minor_injury', 'consultation_only', 'prescription_only',
            'dressing_change', 'suture_removal', 'follow_up'
        }
    
    def _check_admission_indicators(self, claim) -> bool:
        if hasattr(claim, 'admission_date') and claim.admission_date:
            return True
        
        if hasattr(claim, 'discharge_date') and claim.discharge_date:
            return True
            
        if hasattr(claim, 'encounter_type') and claim.encounter_type:
            if claim.encounter_type.lower() in ['inpatient', 'admission', 'icu']:
                return True
        
        return False
    
    def _check_detention_criteria(self, claim) -> bool:
        if not hasattr(claim, 'procedures') or not claim.procedures:
            return False
            
        for procedure in claim.procedures:
            if procedure.get('code') in self.detention_procedures:
                return True
        
        if hasattr(claim, 'observation_hours') and claim.observation_hours:
            try:
                hours = float(claim.observation_hours)
                return 1 <= hours < 24
            except (ValueError, TypeError):
                pass
        
        return False
    
    def _check_opd_like_criteria(self, claim) -> bool:
        if hasattr(claim, 'encounter_type') and claim.encounter_type:
            if claim.encounter_type.lower() in self.opd_like_conditions:
                return True
        
        if hasattr(claim, 'treatment_type') and claim.treatment_type:
            if claim.treatment_type.lower() in self.opd_like_conditions:
                return True
        
        return False
    
    def _determine_classification(self, claim) -> tuple[str, str]:
        if self._check_admission_indicators(claim):
            return 'ADMISSION', 'Use Inpatient rules and tariff'
        
        if self._check_detention_criteria(claim):
            return 'DETENTION', 'Use ZOOM02A detention tariff'
        
        if self._check_opd_like_criteria(claim):
            return 'OPD_LIKE', 'Use OPD rules and tariff'
        
        return 'OPD_LIKE', 'Default to OPD rules and tariff'
    
    def evaluate(self, context: ClaimProcessingContext) -> RuleResult:
        try:
            claim = context.claim
            
            if not hasattr(claim, 'encounter_setting') or claim.encounter_setting != 'A&E':
                return RuleResult(
                    rule_id=self.rule_id,
                    result_type=RuleResultType.FLAG,
                    message="Claim is not from A&E setting",
                    details={"reason": "not_ae_setting"}
                )
            
            classification, processing_path = self._determine_classification(claim)
            
            context.ae_classification = classification
            context.processing_path = processing_path
            
            details = {
                "ae_classification": classification,
                "processing_path": processing_path,
                "has_admission_indicators": self._check_admission_indicators(claim),
                "has_detention_criteria": self._check_detention_criteria(claim),
                "has_opd_like_criteria": self._check_opd_like_criteria(claim)
            }
            
            if hasattr(claim, 'admission_date'):
                details["admission_date"] = claim.admission_date
            if hasattr(claim, 'discharge_date'):
                details["discharge_date"] = claim.discharge_date
            if hasattr(claim, 'observation_hours'):
                details["observation_hours"] = claim.observation_hours
            
            return RuleResult(
                rule_id=self.rule_id,
                result_type=RuleResultType.APPROVE,
                message=f"A&E classified as: {classification} - {processing_path}",
                details=details
            )
            
        except Exception as e:
            logger.error(f"Error in ClassificationRule evaluation: {str(e)}")
            return RuleResult(
                rule_id=self.rule_id,
                result_type=RuleResultType.FLAG,
                message=f"Error during A&E classification: {str(e)}",
                details={"error": str(e)}
            )