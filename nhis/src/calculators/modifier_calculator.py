from typing import List, Dict, Any, Optional
from decimal import Decimal
from .base_calculator import BaseCalculator, CalculationResult
from ..core.models import ClaimProcessingContext
import json
import logging

logger = logging.getLogger(__name__)


class ModifierCalculator(BaseCalculator):
    
    def __init__(self, reference_data_path: str = "reference_data/modifier_rules.json"):
        super().__init__()
        self.modifier_rules = self._load_modifier_rules(reference_data_path)
    
    def _load_modifier_rules(self, file_path: str) -> Dict[str, Any]:
        try:
            with open(file_path, 'r') as f:
                return json.load(f)
        except Exception as e:
            logger.warning(f"Could not load modifier rules data: {str(e)}")
            return self._get_default_modifier_rules()
    
    def _get_default_modifier_rules(self) -> Dict[str, Any]:
        return {
            "bilateral_surgery": {
                "modifier_percentage": 120,
                "eligible_procedures": ["SURG001", "SURG002", "ORTHO001"]
            },
            "dental_multi_tooth": {
                "modifier_tiers": [
                    {"min_teeth": 1, "max_teeth": 1, "modifier_percentage": 100},
                    {"min_teeth": 2, "max_teeth": 3, "modifier_percentage": 150},
                    {"min_teeth": 4, "max_teeth": 6, "modifier_percentage": 200}
                ]
            },
            "emergency_modifiers": {
                "after_hours_modifier": 150,
                "weekend_modifier": 130,
                "holiday_modifier": 150
            },
            "age_modifiers": {
                "pediatric": {"age_limit": 12, "modifier_percentage": 110},
                "geriatric": {"age_limit": 65, "modifier_percentage": 105}
            }
        }
    
    def calculate(self, context: ClaimProcessingContext, **kwargs) -> CalculationResult:
        try:
            # Get base amounts from context
            base_amounts = self._get_base_amounts(context)
            
            if not base_amounts or sum(base_amounts.values()) == 0:
                return self._create_success_result(
                    amount=Decimal('0'),
                    message="No base amounts available for modifier calculation",
                    details={"reason": "no_base_amounts"}
                )
            
            # Apply all applicable modifiers
            modifier_calculations = []
            total_modifier_amount = Decimal('0')
            
            # Apply modifiers that were determined by business rules
            if hasattr(context, 'applied_modifiers') and context.applied_modifiers:
                for modifier_info in context.applied_modifiers:
                    modifier_type = modifier_info.get('modifier_type')
                    modifier_amount = self._validate_amount(modifier_info.get('modifier_amount', 0))
                    
                    modifier_calculations.append({
                        'modifier_type': modifier_type,
                        'modifier_amount': float(modifier_amount),
                        'procedures_affected': modifier_info.get('procedures_affected', []),
                        'source': 'business_rules'
                    })
                    
                    total_modifier_amount += modifier_amount
            
            # Apply age-based modifiers if not already applied
            age_modifier = self._calculate_age_modifier(context, base_amounts)
            if age_modifier['amount'] > 0:
                modifier_calculations.append(age_modifier)
                total_modifier_amount += age_modifier['amount']
            
            # Apply any additional context-specific modifiers
            additional_modifiers = self._calculate_additional_modifiers(context, base_amounts)
            for modifier in additional_modifiers:
                modifier_calculations.append(modifier)
                total_modifier_amount += modifier['amount']
            
            # Update context with modifier calculations
            context.total_modifier_amount = total_modifier_amount
            context.modifier_calculations = modifier_calculations
            
            details = {
                "base_amounts": {k: float(v) for k, v in base_amounts.items()},
                "modifier_calculations": modifier_calculations,
                "total_modifier_amount": float(total_modifier_amount),
                "total_modifiers_applied": len(modifier_calculations)
            }
            
            if total_modifier_amount > 0:
                message = f"Modifiers applied - Total adjustment: +GHS {total_modifier_amount}"
                status = CalculationStatus.SUCCESS
            else:
                message = "No modifiers applicable"
                status = CalculationStatus.SUCCESS
            
            return CalculationResult(
                status=status,
                amount=total_modifier_amount,
                base_amount=Decimal('0'),
                adjustments={'total_modifiers': total_modifier_amount},
                message=message,
                details=details
            )
            
        except Exception as e:
            logger.error(f"Error in ModifierCalculator: {str(e)}")
            return self._create_failed_result(
                message=f"Error calculating modifiers: {str(e)}",
                details={"error": str(e)}
            )
    
    def _get_base_amounts(self, context: ClaimProcessingContext) -> Dict[str, Decimal]:
        base_amounts = {}
        
        # G-DRG amount
        if hasattr(context, 'gdrg_final_amount'):
            base_amounts['gdrg'] = self._validate_amount(context.gdrg_final_amount)
        
        # Medicine amounts
        if hasattr(context, 'medicine_approved_amount'):
            base_amounts['medicine'] = self._validate_amount(context.medicine_approved_amount)
        
        # Investigation amounts
        if hasattr(context, 'investigation_approved_amount'):
            base_amounts['investigation'] = self._validate_amount(context.investigation_approved_amount)
        
        # Procedure amounts (if any procedures have individual tariffs)
        if hasattr(context.claim, 'procedures') and context.claim.procedures:
            procedure_total = Decimal('0')
            for procedure in context.claim.procedures:
                procedure_amount = self._validate_amount(procedure.get('amount', 0))
                procedure_total += procedure_amount
            
            if procedure_total > 0:
                base_amounts['procedures'] = procedure_total
        
        return base_amounts
    
    def _calculate_age_modifier(self, context: ClaimProcessingContext, base_amounts: Dict[str, Decimal]) -> Dict[str, Any]:
        claim = context.claim
        
        if not hasattr(claim, 'patient_birth_date') or not claim.patient_birth_date:
            return {'modifier_type': 'age', 'amount': Decimal('0'), 'reason': 'no_birth_date'}
        
        if not hasattr(claim, 'service_date') or not claim.service_date:
            return {'modifier_type': 'age', 'amount': Decimal('0'), 'reason': 'no_service_date'}
        
        # Calculate age
        age_years = (claim.service_date - claim.patient_birth_date).days // 365
        
        age_modifiers = self.modifier_rules.get('age_modifiers', {})
        
        # Check pediatric modifier
        pediatric_rules = age_modifiers.get('pediatric', {})
        if age_years < pediatric_rules.get('age_limit', 12):
            modifier_percentage = pediatric_rules.get('modifier_percentage', 110)
            base_total = sum(base_amounts.values())
            modifier_amount = base_total * (Decimal(str(modifier_percentage)) - Decimal('100')) / Decimal('100')
            
            return {
                'modifier_type': 'pediatric_age',
                'amount': modifier_amount,
                'modifier_percentage': modifier_percentage,
                'patient_age': age_years,
                'base_amount': float(base_total),
                'reason': f'Pediatric patient (age {age_years})'
            }
        
        # Check geriatric modifier
        geriatric_rules = age_modifiers.get('geriatric', {})
        if age_years >= geriatric_rules.get('age_limit', 65):
            modifier_percentage = geriatric_rules.get('modifier_percentage', 105)
            base_total = sum(base_amounts.values())
            modifier_amount = base_total * (Decimal(str(modifier_percentage)) - Decimal('100')) / Decimal('100')
            
            return {
                'modifier_type': 'geriatric_age',
                'amount': modifier_amount,
                'modifier_percentage': modifier_percentage,
                'patient_age': age_years,
                'base_amount': float(base_total),
                'reason': f'Geriatric patient (age {age_years})'
            }
        
        return {'modifier_type': 'age', 'amount': Decimal('0'), 'reason': 'no_age_modifier_applicable'}
    
    def _calculate_additional_modifiers(self, context: ClaimProcessingContext, base_amounts: Dict[str, Decimal]) -> List[Dict[str, Any]]:
        additional_modifiers = []
        
        # Teaching hospital modifier
        if hasattr(context.claim, 'facility_type') and context.claim.facility_type:
            if 'teaching' in context.claim.facility_type.lower():
                teaching_modifier = 1.05  # 5% increase
                base_total = sum(base_amounts.values())
                modifier_amount = base_total * (Decimal(str(teaching_modifier)) - Decimal('1'))
                
                additional_modifiers.append({
                    'modifier_type': 'teaching_hospital',
                    'amount': modifier_amount,
                    'modifier_percentage': 105,
                    'base_amount': float(base_total),
                    'reason': 'Teaching hospital facility'
                })
        
        # Rural facility modifier
        if hasattr(context.claim, 'facility_location') and context.claim.facility_location:
            if 'rural' in context.claim.facility_location.lower():
                rural_modifier = 1.03  # 3% increase
                base_total = sum(base_amounts.values())
                modifier_amount = base_total * (Decimal(str(rural_modifier)) - Decimal('1'))
                
                additional_modifiers.append({
                    'modifier_type': 'rural_facility',
                    'amount': modifier_amount,
                    'modifier_percentage': 103,
                    'base_amount': float(base_total),
                    'reason': 'Rural facility location'
                })
        
        # Complex case modifier (if multiple specialties involved)
        if hasattr(context, 'validated_specialties') and len(context.validated_specialties) > 1:
            complex_modifier = 1.02  # 2% increase
            base_total = sum(base_amounts.values())
            modifier_amount = base_total * (Decimal(str(complex_modifier)) - Decimal('1'))
            
            additional_modifiers.append({
                'modifier_type': 'complex_case',
                'amount': modifier_amount,
                'modifier_percentage': 102,
                'base_amount': float(base_total),
                'specialties_involved': context.validated_specialties,
                'reason': f'Complex case involving {len(context.validated_specialties)} specialties'
            })
        
        return additional_modifiers
    
    def get_modifier_summary(self, context: ClaimProcessingContext) -> Dict[str, Any]:
        if not hasattr(context, 'modifier_calculations'):
            return {'total_modifiers': 0, 'total_amount': 0, 'modifiers': []}
        
        return {
            'total_modifiers': len(context.modifier_calculations),
            'total_amount': float(getattr(context, 'total_modifier_amount', 0)),
            'modifiers': context.modifier_calculations
        }