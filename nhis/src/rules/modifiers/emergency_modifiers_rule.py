from typing import List, Dict, Any, Optional
from datetime import datetime, time
from ..base_rule import BaseRule, RuleResult, RuleResultType
from ...core.models import ClaimProcessingContext
import json
import logging

logger = logging.getLogger(__name__)


class EmergencyModifiersRule(BaseRule):
    
    def __init__(self, reference_data_path: str = "reference_data/modifier_rules.json"):
        super().__init__(
            rule_id="MOD_EMERGENCY",
            name="Emergency Modifiers Rule",
            description="Apply emergency procedure modifiers based on timing and urgency"
        )
        self.reference_data = self._load_emergency_modifiers(reference_data_path)
    
    def _load_emergency_modifiers(self, file_path: str) -> Dict[str, Any]:
        try:
            with open(file_path, 'r') as f:
                data = json.load(f)
                return data.get('emergency_modifiers', {})
        except Exception as e:
            logger.warning(f"Could not load emergency modifier reference data: {str(e)}")
            return self._get_default_emergency_data()
    
    def _get_default_emergency_data(self) -> Dict[str, Any]:
        return {
            "after_hours_modifier": 150,
            "weekend_modifier": 130,
            "holiday_modifier": 150,
            "emergency_surgery_modifier": 125,
            "trauma_modifier": 140,
            "after_hours_start": "18:00",
            "after_hours_end": "08:00",
            "eligible_procedures": [
                "SURG", "EMRG", "TRAUMA", "ZOOM", "ANES"
            ],
            "emergency_keywords": [
                "emergency", "urgent", "trauma", "acute", "critical", "life-threatening"
            ],
            "holidays": [
                "2025-01-01", "2025-03-06", "2025-04-18", "2025-04-21",
                "2025-05-01", "2025-07-01", "2025-08-04", "2025-09-21",
                "2025-12-25", "2025-12-26"
            ]
        }
    
    def _is_emergency_eligible_procedure(self, procedure_code: str) -> bool:
        eligible_procedures = self.reference_data.get('eligible_procedures', [])
        return any(prefix in procedure_code for prefix in eligible_procedures)
    
    def _is_after_hours(self, service_datetime: datetime) -> bool:
        service_time = service_datetime.time()
        
        after_hours_start_str = self.reference_data.get('after_hours_start', '18:00')
        after_hours_end_str = self.reference_data.get('after_hours_end', '08:00')
        
        try:
            after_hours_start = datetime.strptime(after_hours_start_str, '%H:%M').time()
            after_hours_end = datetime.strptime(after_hours_end_str, '%H:%M').time()
        except ValueError:
            after_hours_start = time(18, 0)
            after_hours_end = time(8, 0)
        
        if after_hours_start > after_hours_end:
            return service_time >= after_hours_start or service_time <= after_hours_end
        else:
            return after_hours_start <= service_time <= after_hours_end
    
    def _is_weekend(self, service_datetime: datetime) -> bool:
        return service_datetime.weekday() >= 5
    
    def _is_holiday(self, service_datetime: datetime) -> bool:
        service_date_str = service_datetime.strftime('%Y-%m-%d')
        holidays = self.reference_data.get('holidays', [])
        return service_date_str in holidays
    
    def _has_emergency_keywords(self, procedure: Dict[str, Any]) -> bool:
        emergency_keywords = self.reference_data.get('emergency_keywords', [])
        
        description = procedure.get('description', '').lower()
        notes = procedure.get('notes', '').lower()
        indication = procedure.get('indication', '').lower()
        
        text_to_check = f"{description} {notes} {indication}"
        
        return any(keyword in text_to_check for keyword in emergency_keywords)
    
    def _calculate_emergency_modifier(self, service_datetime: datetime, procedure: Dict[str, Any]) -> tuple[int, List[str]]:
        base_modifier = 100
        applied_modifiers = []
        
        if self._is_after_hours(service_datetime):
            after_hours_mod = self.reference_data.get('after_hours_modifier', 150)
            base_modifier = max(base_modifier, after_hours_mod)
            applied_modifiers.append(f"After hours ({after_hours_mod}%)")
        
        if self._is_weekend(service_datetime):
            weekend_mod = self.reference_data.get('weekend_modifier', 130)
            base_modifier = max(base_modifier, weekend_mod)
            applied_modifiers.append(f"Weekend ({weekend_mod}%)")
        
        if self._is_holiday(service_datetime):
            holiday_mod = self.reference_data.get('holiday_modifier', 150)
            base_modifier = max(base_modifier, holiday_mod)
            applied_modifiers.append(f"Holiday ({holiday_mod}%)")
        
        if self._has_emergency_keywords(procedure):
            if 'trauma' in procedure.get('description', '').lower():
                trauma_mod = self.reference_data.get('trauma_modifier', 140)
                base_modifier = max(base_modifier, trauma_mod)
                applied_modifiers.append(f"Trauma ({trauma_mod}%)")
            else:
                emergency_mod = self.reference_data.get('emergency_surgery_modifier', 125)
                base_modifier = max(base_modifier, emergency_mod)
                applied_modifiers.append(f"Emergency surgery ({emergency_mod}%)")
        
        return base_modifier, applied_modifiers
    
    def _apply_emergency_modifier(self, base_amount: float, modifier_percentage: int) -> float:
        return base_amount * (modifier_percentage / 100)
    
    def evaluate(self, context: ClaimProcessingContext) -> RuleResult:
        try:
            claim = context.claim
            
            if not hasattr(claim, 'procedures') or not claim.procedures:
                return RuleResult(
                    rule_id=self.rule_id,
                    result_type=RuleResultType.APPROVE,
                    message="No procedures found - emergency modifier not applicable",
                    details={"reason": "no_procedures"}
                )
            
            if not claim.service_date:
                return RuleResult(
                    rule_id=self.rule_id,
                    result_type=RuleResultType.FLAG,
                    message="Missing service date - cannot determine emergency modifiers",
                    details={"reason": "missing_service_date"}
                )
            
            service_datetime = claim.service_date
            if hasattr(claim, 'service_time') and claim.service_time:
                service_datetime = datetime.combine(claim.service_date, claim.service_time)
            elif isinstance(claim.service_date, datetime):
                service_datetime = claim.service_date
            else:
                service_datetime = datetime.combine(claim.service_date, time(12, 0))
            
            emergency_procedures = []
            total_modifier_amount = 0
            
            for procedure in claim.procedures:
                procedure_code = procedure.get('code', '')
                
                if not self._is_emergency_eligible_procedure(procedure_code):
                    continue
                
                base_amount = procedure.get('amount', 0)
                if base_amount <= 0:
                    continue
                
                modifier_percentage, applied_modifiers = self._calculate_emergency_modifier(service_datetime, procedure)
                
                if modifier_percentage <= 100:
                    continue
                
                modified_amount = self._apply_emergency_modifier(base_amount, modifier_percentage)
                modifier_amount = modified_amount - base_amount
                
                emergency_procedures.append({
                    'procedure_code': procedure_code,
                    'description': procedure.get('description', ''),
                    'base_amount': base_amount,
                    'modified_amount': modified_amount,
                    'modifier_amount': modifier_amount,
                    'modifier_percentage': modifier_percentage,
                    'applied_modifiers': applied_modifiers
                })
                
                total_modifier_amount += modifier_amount
            
            if not emergency_procedures:
                return RuleResult(
                    rule_id=self.rule_id,
                    result_type=RuleResultType.APPROVE,
                    message="No emergency procedures requiring modifiers found",
                    details={"reason": "no_emergency_procedures"}
                )
            
            context.emergency_modifier_applied = True
            context.emergency_modifier_amount = total_modifier_amount
            
            if not hasattr(context, 'applied_modifiers'):
                context.applied_modifiers = []
            
            context.applied_modifiers.append({
                'modifier_type': 'emergency_procedure',
                'modifier_amount': total_modifier_amount,
                'procedures_affected': [p['procedure_code'] for p in emergency_procedures]
            })
            
            details = {
                "emergency_procedures": emergency_procedures,
                "total_modifier_amount": total_modifier_amount,
                "service_datetime": service_datetime.isoformat(),
                "is_after_hours": self._is_after_hours(service_datetime),
                "is_weekend": self._is_weekend(service_datetime),
                "is_holiday": self._is_holiday(service_datetime),
                "procedures_count": len(emergency_procedures)
            }
            
            return RuleResult(
                rule_id=self.rule_id,
                result_type=RuleResultType.APPROVE,
                message=f"Emergency modifiers applied to {len(emergency_procedures)} procedures (+GHS {total_modifier_amount:.2f})",
                details=details
            )
            
        except Exception as e:
            logger.error(f"Error in EmergencyModifiersRule evaluation: {str(e)}")
            return RuleResult(
                rule_id=self.rule_id,
                result_type=RuleResultType.FLAG,
                message=f"Error during emergency modifier evaluation: {str(e)}",
                details={"error": str(e)}
            )