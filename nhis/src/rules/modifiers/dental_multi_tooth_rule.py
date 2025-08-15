from typing import List, Dict, Any, Optional
from ..base_rule import BaseRule, RuleResult, RuleResultType
from ...core.models import ClaimProcessingContext
import json
import re
import logging

logger = logging.getLogger(__name__)


class DentalMultiToothRule(BaseRule):
    
    def __init__(self, reference_data_path: str = "reference_data/modifier_rules.json"):
        super().__init__(
            rule_id="MOD_DENTAL",
            name="Dental Multi-Tooth Rule",
            description="Apply dental multi-tooth modifiers based on number of teeth treated"
        )
        self.reference_data = self._load_dental_modifiers(reference_data_path)
    
    def _load_dental_modifiers(self, file_path: str) -> Dict[str, Any]:
        try:
            with open(file_path, 'r') as f:
                data = json.load(f)
                return data.get('dental_multi_tooth', {})
        except Exception as e:
            logger.warning(f"Could not load dental modifier reference data: {str(e)}")
            return self._get_default_dental_data()
    
    def _get_default_dental_data(self) -> Dict[str, Any]:
        return {
            "eligible_procedures": [
                "DENT001", "DENT002", "DENT003", "DENT004", "DENT005",
                "EXTRACT", "FILLING", "CROWN", "ROOT_CANAL", "SCALING"
            ],
            "modifier_tiers": [
                {"min_teeth": 1, "max_teeth": 1, "modifier_percentage": 100, "description": "Single tooth"},
                {"min_teeth": 2, "max_teeth": 3, "modifier_percentage": 150, "description": "2-3 teeth"},
                {"min_teeth": 4, "max_teeth": 6, "modifier_percentage": 200, "description": "4-6 teeth"},
                {"min_teeth": 7, "max_teeth": 10, "modifier_percentage": 250, "description": "7-10 teeth"},
                {"min_teeth": 11, "max_teeth": 999, "modifier_percentage": 300, "description": "Full mouth"}
            ],
            "tooth_number_patterns": [
                r"\b(\d{1,2})\s*teeth?\b",
                r"\b(\d{1,2})\s*tooth\b",
                r"teeth?\s*#?\s*(\d{1,2})",
                r"(\d{1,2})\s*units?"
            ]
        }
    
    def _is_dental_procedure(self, procedure_code: str) -> bool:
        eligible_procedures = self.reference_data.get('eligible_procedures', [])
        return procedure_code in eligible_procedures
    
    def _extract_tooth_count(self, procedure: Dict[str, Any]) -> int:
        description = procedure.get('description', '')
        notes = procedure.get('notes', '')
        quantity = procedure.get('quantity', 1)
        
        text_to_search = f"{description} {notes}".lower()
        
        patterns = self.reference_data.get('tooth_number_patterns', [])
        
        for pattern in patterns:
            matches = re.findall(pattern, text_to_search, re.IGNORECASE)
            if matches:
                try:
                    return int(matches[0])
                except (ValueError, IndexError):
                    continue
        
        if isinstance(quantity, (int, float)) and quantity > 1:
            return int(quantity)
        
        keywords = ['multiple', 'several', 'many']
        if any(keyword in text_to_search for keyword in keywords):
            return 4
        
        return 1
    
    def _get_modifier_for_tooth_count(self, tooth_count: int) -> Optional[Dict[str, Any]]:
        modifier_tiers = self.reference_data.get('modifier_tiers', [])
        
        for tier in modifier_tiers:
            if tier['min_teeth'] <= tooth_count <= tier['max_teeth']:
                return tier
        
        return None
    
    def _apply_dental_modifier(self, base_amount: float, modifier_percentage: int) -> float:
        return base_amount * (modifier_percentage / 100)
    
    def evaluate(self, context: ClaimProcessingContext) -> RuleResult:
        try:
            claim = context.claim
            
            if not hasattr(claim, 'procedures') or not claim.procedures:
                return RuleResult(
                    rule_id=self.rule_id,
                    result_type=RuleResultType.APPROVE,
                    message="No procedures found - dental modifier not applicable",
                    details={"reason": "no_procedures"}
                )
            
            dental_procedures = []
            total_modifier_amount = 0
            
            for procedure in claim.procedures:
                procedure_code = procedure.get('code', '')
                
                if not self._is_dental_procedure(procedure_code):
                    continue
                
                tooth_count = self._extract_tooth_count(procedure)
                modifier_tier = self._get_modifier_for_tooth_count(tooth_count)
                
                if not modifier_tier:
                    continue
                
                base_amount = procedure.get('amount', 0)
                if base_amount <= 0:
                    continue
                
                modified_amount = self._apply_dental_modifier(base_amount, modifier_tier['modifier_percentage'])
                modifier_amount = modified_amount - base_amount
                
                dental_procedures.append({
                    'procedure_code': procedure_code,
                    'description': procedure.get('description', ''),
                    'tooth_count': tooth_count,
                    'base_amount': base_amount,
                    'modified_amount': modified_amount,
                    'modifier_amount': modifier_amount,
                    'modifier_percentage': modifier_tier['modifier_percentage'],
                    'modifier_description': modifier_tier['description']
                })
                
                total_modifier_amount += modifier_amount
            
            if not dental_procedures:
                return RuleResult(
                    rule_id=self.rule_id,
                    result_type=RuleResultType.APPROVE,
                    message="No dental multi-tooth procedures found",
                    details={"reason": "no_dental_procedures"}
                )
            
            context.dental_modifier_applied = True
            context.dental_modifier_amount = total_modifier_amount
            
            if not hasattr(context, 'applied_modifiers'):
                context.applied_modifiers = []
            
            context.applied_modifiers.append({
                'modifier_type': 'dental_multi_tooth',
                'modifier_amount': total_modifier_amount,
                'procedures_affected': [p['procedure_code'] for p in dental_procedures]
            })
            
            total_teeth = sum(p['tooth_count'] for p in dental_procedures)
            
            details = {
                "dental_procedures": dental_procedures,
                "total_modifier_amount": total_modifier_amount,
                "total_teeth_treated": total_teeth,
                "procedures_count": len(dental_procedures)
            }
            
            return RuleResult(
                rule_id=self.rule_id,
                result_type=RuleResultType.APPROVE,
                message=f"Dental multi-tooth modifier applied to {len(dental_procedures)} procedures ({total_teeth} teeth, +GHS {total_modifier_amount:.2f})",
                details=details
            )
            
        except Exception as e:
            logger.error(f"Error in DentalMultiToothRule evaluation: {str(e)}")
            return RuleResult(
                rule_id=self.rule_id,
                result_type=RuleResultType.FLAG,
                message=f"Error during dental modifier evaluation: {str(e)}",
                details={"error": str(e)}
            )