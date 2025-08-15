from typing import List, Dict, Any, Optional
from ..base_rule import BaseRule, RuleResult, RuleResultType
from ...core.models import ClaimProcessingContext
import json
import logging

logger = logging.getLogger(__name__)


class BilateralSurgeryRule(BaseRule):
    
    def __init__(self, reference_data_path: str = "reference_data/modifier_rules.json"):
        super().__init__(
            rule_id="MOD_BILATERAL",
            name="Bilateral Surgery Rule",
            description="Apply 120% modifier for bilateral surgical procedures"
        )
        self.reference_data = self._load_bilateral_procedures(reference_data_path)
    
    def _load_bilateral_procedures(self, file_path: str) -> Dict[str, Any]:
        try:
            with open(file_path, 'r') as f:
                data = json.load(f)
                return data.get('bilateral_surgery', {})
        except Exception as e:
            logger.warning(f"Could not load bilateral surgery reference data: {str(e)}")
            return self._get_default_bilateral_data()
    
    def _get_default_bilateral_data(self) -> Dict[str, Any]:
        return {
            "modifier_percentage": 120,
            "eligible_procedures": [
                "SURG001", "SURG002", "SURG003", "SURG004", "SURG005",
                "OPHT001", "OPHT002", "OPHT003",
                "ORTH001", "ORTH002", "ORTH003", "ORTH004",
                "GYNE001", "GYNE002"
            ],
            "bilateral_indicators": [
                "bilateral", "both sides", "left and right", "B/L", "bil"
            ],
            "exclusions": [
                "SURG999", "EMRG001"
            ]
        }
    
    def _is_bilateral_eligible_procedure(self, procedure_code: str) -> bool:
        eligible_procedures = self.reference_data.get('eligible_procedures', [])
        return procedure_code in eligible_procedures
    
    def _is_excluded_procedure(self, procedure_code: str) -> bool:
        exclusions = self.reference_data.get('exclusions', [])
        return procedure_code in exclusions
    
    def _has_bilateral_indicator(self, procedure: Dict[str, Any]) -> bool:
        bilateral_indicators = self.reference_data.get('bilateral_indicators', [])
        
        description = procedure.get('description', '').lower()
        notes = procedure.get('notes', '').lower()
        modifier = procedure.get('modifier', '').lower()
        
        text_to_check = f"{description} {notes} {modifier}"
        
        return any(indicator.lower() in text_to_check for indicator in bilateral_indicators)
    
    def _apply_bilateral_modifier(self, base_amount: float) -> float:
        modifier_percentage = self.reference_data.get('modifier_percentage', 120)
        return base_amount * (modifier_percentage / 100)
    
    def evaluate(self, context: ClaimProcessingContext) -> RuleResult:
        try:
            claim = context.claim
            
            if not hasattr(claim, 'procedures') or not claim.procedures:
                return RuleResult(
                    rule_id=self.rule_id,
                    result_type=RuleResultType.APPROVE,
                    message="No procedures found - bilateral modifier not applicable",
                    details={"reason": "no_procedures"}
                )
            
            bilateral_procedures = []
            total_modifier_amount = 0
            
            for procedure in claim.procedures:
                procedure_code = procedure.get('code', '')
                
                if self._is_excluded_procedure(procedure_code):
                    continue
                
                if not self._is_bilateral_eligible_procedure(procedure_code):
                    continue
                
                if not self._has_bilateral_indicator(procedure):
                    continue
                
                base_amount = procedure.get('amount', 0)
                if base_amount <= 0:
                    continue
                
                modified_amount = self._apply_bilateral_modifier(base_amount)
                modifier_amount = modified_amount - base_amount
                
                bilateral_procedures.append({
                    'procedure_code': procedure_code,
                    'description': procedure.get('description', ''),
                    'base_amount': base_amount,
                    'modified_amount': modified_amount,
                    'modifier_amount': modifier_amount,
                    'modifier_percentage': self.reference_data.get('modifier_percentage', 120)
                })
                
                total_modifier_amount += modifier_amount
            
            if not bilateral_procedures:
                return RuleResult(
                    rule_id=self.rule_id,
                    result_type=RuleResultType.APPROVE,
                    message="No bilateral surgical procedures found",
                    details={"reason": "no_bilateral_procedures"}
                )
            
            context.bilateral_modifier_applied = True
            context.bilateral_modifier_amount = total_modifier_amount
            
            if not hasattr(context, 'applied_modifiers'):
                context.applied_modifiers = []
            
            context.applied_modifiers.append({
                'modifier_type': 'bilateral_surgery',
                'modifier_amount': total_modifier_amount,
                'procedures_affected': [p['procedure_code'] for p in bilateral_procedures]
            })
            
            details = {
                "bilateral_procedures": bilateral_procedures,
                "total_modifier_amount": total_modifier_amount,
                "modifier_percentage": self.reference_data.get('modifier_percentage', 120),
                "procedures_count": len(bilateral_procedures)
            }
            
            return RuleResult(
                rule_id=self.rule_id,
                result_type=RuleResultType.APPROVE,
                message=f"Bilateral surgery modifier applied to {len(bilateral_procedures)} procedures (+GHS {total_modifier_amount:.2f})",
                details=details
            )
            
        except Exception as e:
            logger.error(f"Error in BilateralSurgeryRule evaluation: {str(e)}")
            return RuleResult(
                rule_id=self.rule_id,
                result_type=RuleResultType.FLAG,
                message=f"Error during bilateral surgery modifier evaluation: {str(e)}",
                details={"error": str(e)}
            )