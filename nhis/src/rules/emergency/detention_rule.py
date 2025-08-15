from datetime import datetime, timedelta
from typing import Optional, Dict, Any
from ..base_rule import BaseRule, RuleResult, RuleResultType
from ...core.models import ClaimProcessingContext
import logging

logger = logging.getLogger(__name__)


class DetentionRule(BaseRule):
    
    def __init__(self):
        super().__init__(
            rule_id="AE_DETENTION",
            name="A&E Detention Rule",
            description="Validate ZOOM02A detention criteria and duration"
        )
        
        self.zoom02a_code = 'ZOOM02A'
        self.min_detention_hours = 1
        self.max_detention_hours = 24
    
    def _calculate_detention_hours(self, start_time: datetime, end_time: datetime) -> float:
        if not start_time or not end_time:
            return 0
        
        duration = end_time - start_time
        return duration.total_seconds() / 3600
    
    def _has_zoom02a_procedure(self, claim) -> bool:
        if not hasattr(claim, 'procedures') or not claim.procedures:
            return False
        
        for procedure in claim.procedures:
            if procedure.get('code') == self.zoom02a_code:
                return True
        
        return False
    
    def _validate_detention_duration(self, claim) -> tuple[bool, float, str]:
        detention_hours = 0
        
        if hasattr(claim, 'observation_hours') and claim.observation_hours:
            try:
                detention_hours = float(claim.observation_hours)
            except (ValueError, TypeError):
                return False, 0, "Invalid observation hours format"
        
        elif hasattr(claim, 'ae_start_time') and hasattr(claim, 'ae_end_time'):
            if claim.ae_start_time and claim.ae_end_time:
                detention_hours = self._calculate_detention_hours(claim.ae_start_time, claim.ae_end_time)
        
        elif hasattr(claim, 'service_date') and hasattr(claim, 'discharge_time'):
            if claim.service_date and claim.discharge_time:
                start_datetime = datetime.combine(claim.service_date, datetime.min.time())
                if isinstance(claim.discharge_time, datetime):
                    detention_hours = self._calculate_detention_hours(start_datetime, claim.discharge_time)
        
        if detention_hours < self.min_detention_hours:
            return False, detention_hours, f"Detention period too short: {detention_hours} hours (minimum: {self.min_detention_hours})"
        
        if detention_hours >= self.max_detention_hours:
            return False, detention_hours, f"Detention period too long: {detention_hours} hours (maximum: {self.max_detention_hours})"
        
        return True, detention_hours, "Valid detention duration"
    
    def _validate_detention_documentation(self, claim) -> tuple[bool, str]:
        required_docs = ['ae_notes', 'observation_chart', 'detention_reason']
        missing_docs = []
        
        for doc in required_docs:
            if not hasattr(claim, doc) or not getattr(claim, doc):
                missing_docs.append(doc)
        
        if missing_docs:
            return False, f"Missing required detention documentation: {', '.join(missing_docs)}"
        
        return True, "All required detention documentation present"
    
    def evaluate(self, context: ClaimProcessingContext) -> RuleResult:
        try:
            claim = context.claim
            
            if not hasattr(context, 'ae_classification') or context.ae_classification != 'DETENTION':
                return RuleResult(
                    rule_id=self.rule_id,
                    result_type=RuleResultType.APPROVE,
                    message="Not classified as detention - rule skipped",
                    details={"reason": "not_detention_classification"}
                )
            
            if not self._has_zoom02a_procedure(claim):
                return RuleResult(
                    rule_id=self.rule_id,
                    result_type=RuleResultType.REJECT,
                    message="ZOOM02A procedure code required for detention classification",
                    details={"reason": "missing_zoom02a_code"}
                )
            
            duration_valid, detention_hours, duration_message = self._validate_detention_duration(claim)
            
            if not duration_valid:
                return RuleResult(
                    rule_id=self.rule_id,
                    result_type=RuleResultType.REJECT,
                    message=duration_message,
                    details={
                        "reason": "invalid_detention_duration",
                        "detention_hours": detention_hours,
                        "min_hours": self.min_detention_hours,
                        "max_hours": self.max_detention_hours
                    }
                )
            
            docs_valid, docs_message = self._validate_detention_documentation(claim)
            
            if not docs_valid:
                return RuleResult(
                    rule_id=self.rule_id,
                    result_type=RuleResultType.PEND,
                    message=docs_message,
                    details={"reason": "missing_documentation"}
                )
            
            context.zoom02a_validated = True
            context.detention_hours = detention_hours
            
            details = {
                "zoom02a_present": True,
                "detention_hours": detention_hours,
                "duration_valid": duration_valid,
                "documentation_complete": docs_valid,
                "min_hours": self.min_detention_hours,
                "max_hours": self.max_detention_hours
            }
            
            return RuleResult(
                rule_id=self.rule_id,
                result_type=RuleResultType.APPROVE,
                message=f"Valid A&E detention: {detention_hours:.1f} hours with ZOOM02A",
                details=details
            )
            
        except Exception as e:
            logger.error(f"Error in DetentionRule evaluation: {str(e)}")
            return RuleResult(
                rule_id=self.rule_id,
                result_type=RuleResultType.FLAG,
                message=f"Error during detention validation: {str(e)}",
                details={"error": str(e)}
            )