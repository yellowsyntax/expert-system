from typing import List, Dict, Any, Optional
from decimal import Decimal
from .base_calculator import BaseCalculator, CalculationResult
from ..core.models import ClaimProcessingContext
from ..database.repositories.tariff_repository import TariffRepository
import json
import logging

logger = logging.getLogger(__name__)


class MedicineCalculator(BaseCalculator):
    
    def __init__(self, tariff_repo: TariffRepository, reference_data_path: str = "reference_data/medicine_formulary.json"):
        super().__init__()
        self.tariff_repo = tariff_repo
        self.formulary_data = self._load_formulary_data(reference_data_path)
    
    def _load_formulary_data(self, file_path: str) -> Dict[str, Any]:
        try:
            with open(file_path, 'r') as f:
                return json.load(f)
        except Exception as e:
            logger.warning(f"Could not load medicine formulary data: {str(e)}")
            return self._get_default_formulary_data()
    
    def _get_default_formulary_data(self) -> Dict[str, Any]:
        return {
            "medicines": {},
            "dosage_limits": {},
            "pricing_rules": {
                "markup_percentage": 25,
                "dispensing_fee": 2.0,
                "max_days_supply": 30
            }
        }
    
    def calculate(self, context: ClaimProcessingContext, **kwargs) -> CalculationResult:
        try:
            claim = context.claim
            
            if not hasattr(claim, 'medicines') or not claim.medicines:
                return self._create_success_result(
                    amount=Decimal('0'),
                    message="No medicines found - medicine calculation skipped",
                    details={"reason": "no_medicines"}
                )
            
            medicine_calculations = []
            total_approved = Decimal('0')
            total_denied = Decimal('0')
            total_pending = Decimal('0')
            
            for medicine in claim.medicines:
                calc_result = self._calculate_single_medicine(medicine, context)
                medicine_calculations.append(calc_result)
                
                if calc_result['status'] == 'approved':
                    total_approved += calc_result['amount']
                elif calc_result['status'] == 'denied':
                    total_denied += calc_result['amount']
                elif calc_result['status'] == 'pending':
                    total_pending += calc_result['amount']
            
            total_amount = total_approved + total_denied + total_pending
            
            context.medicine_approved_amount = total_approved
            context.medicine_denied_amount = total_denied
            context.medicine_pending_amount = total_pending
            context.medicine_calculations = medicine_calculations
            
            # Determine overall status
            if total_denied > 0 and total_approved == 0:
                status = CalculationStatus.FAILED
                message = f"All medicines denied - Total: GHS {total_denied}"
            elif total_denied > 0 or total_pending > 0:
                status = CalculationStatus.PARTIAL
                message = f"Medicine calculation partial - Approved: GHS {total_approved}, Denied: GHS {total_denied}, Pending: GHS {total_pending}"
            else:
                status = CalculationStatus.SUCCESS
                message = f"All medicines approved - Total: GHS {total_approved}"
            
            details = {
                "total_medicines": len(claim.medicines),
                "approved_amount": float(total_approved),
                "denied_amount": float(total_denied),
                "pending_amount": float(total_pending),
                "medicine_calculations": medicine_calculations
            }
            
            return CalculationResult(
                status=status,
                amount=total_amount,
                base_amount=total_amount,
                message=message,
                details=details
            )
            
        except Exception as e:
            logger.error(f"Error in MedicineCalculator: {str(e)}")
            return self._create_failed_result(
                message=f"Error calculating medicine amounts: {str(e)}",
                details={"error": str(e)}
            )
    
    def _calculate_single_medicine(self, medicine: Dict[str, Any], context: ClaimProcessingContext) -> Dict[str, Any]:
        medicine_code = medicine.get('code', '')
        medicine_name = medicine.get('name', '')
        quantity = self._validate_amount(medicine.get('quantity', 0))
        days_supply = medicine.get('days_supply', 1)
        
        # Check if medicine is in formulary
        if not self._is_in_formulary(medicine_code, medicine_name):
            return {
                'medicine_code': medicine_code,
                'medicine_name': medicine_name,
                'quantity': float(quantity),
                'status': 'denied',
                'amount': Decimal('0'),
                'reason': 'not_in_formulary',
                'message': 'Medicine not in NHIS formulary'
            }
        
        # Get unit price
        unit_price = self._get_unit_price(medicine_code, medicine_name)
        if unit_price <= 0:
            return {
                'medicine_code': medicine_code,
                'medicine_name': medicine_name,
                'quantity': float(quantity),
                'status': 'pending',
                'amount': Decimal('0'),
                'reason': 'no_unit_price',
                'message': 'Unit price not found in tariff'
            }
        
        # Check dosage limits
        dosage_check = self._check_dosage_limits(medicine_code, quantity, days_supply)
        
        if dosage_check['status'] == 'denied':
            return {
                'medicine_code': medicine_code,
                'medicine_name': medicine_name,
                'quantity': float(quantity),
                'status': 'denied',
                'amount': Decimal('0'),
                'reason': dosage_check['reason'],
                'message': dosage_check['message']
            }
        
        # Calculate base amount
        approved_quantity = dosage_check.get('approved_quantity', quantity)
        base_amount = unit_price * approved_quantity
        
        # Apply pricing rules
        final_amount = self._apply_pricing_rules(base_amount, medicine_code)
        
        status = 'approved'
        if approved_quantity < quantity:
            status = 'partial'
        
        return {
            'medicine_code': medicine_code,
            'medicine_name': medicine_name,
            'requested_quantity': float(quantity),
            'approved_quantity': float(approved_quantity),
            'unit_price': float(unit_price),
            'base_amount': float(base_amount),
            'final_amount': float(final_amount),
            'status': status,
            'amount': final_amount,
            'reason': dosage_check.get('reason', 'approved'),
            'message': dosage_check.get('message', 'Medicine approved')
        }
    
    def _is_in_formulary(self, medicine_code: str, medicine_name: str) -> bool:
        formulary_medicines = self.formulary_data.get('medicines', {})
        
        # Check by code
        if medicine_code in formulary_medicines:
            return True
        
        # Check by name (case insensitive)
        medicine_name_lower = medicine_name.lower()
        for code, med_info in formulary_medicines.items():
            if isinstance(med_info, dict):
                formulary_name = med_info.get('name', '').lower()
                if formulary_name == medicine_name_lower:
                    return True
            elif isinstance(med_info, str) and med_info.lower() == medicine_name_lower:
                return True
        
        return False
    
    def _get_unit_price(self, medicine_code: str, medicine_name: str) -> Decimal:
        try:
            # Try to get from database first
            tariff = self.tariff_repo.get_medicine_tariff(medicine_code)
            if tariff and tariff.get('unit_price'):
                return self._validate_amount(tariff['unit_price'])
            
            # Fallback to formulary data
            formulary_medicines = self.formulary_data.get('medicines', {})
            med_info = formulary_medicines.get(medicine_code, {})
            
            if isinstance(med_info, dict) and 'unit_price' in med_info:
                return self._validate_amount(med_info['unit_price'])
            
            return Decimal('0')
            
        except Exception as e:
            logger.error(f"Error getting unit price for {medicine_code}: {str(e)}")
            return Decimal('0')
    
    def _check_dosage_limits(self, medicine_code: str, quantity: Decimal, days_supply: int) -> Dict[str, Any]:
        dosage_limits = self.formulary_data.get('dosage_limits', {})
        medicine_limits = dosage_limits.get(medicine_code, {})
        
        if not medicine_limits:
            return {
                'status': 'approved',
                'approved_quantity': quantity,
                'reason': 'no_limits_defined',
                'message': 'No dosage limits defined'
            }
        
        max_daily_dose = medicine_limits.get('max_daily_dose')
        max_monthly_dose = medicine_limits.get('max_monthly_dose')
        max_days_supply = medicine_limits.get('max_days_supply', 30)
        
        # Check days supply limit
        if days_supply > max_days_supply:
            return {
                'status': 'denied',
                'approved_quantity': Decimal('0'),
                'reason': 'days_supply_exceeded',
                'message': f'Days supply {days_supply} exceeds maximum {max_days_supply}'
            }
        
        # Check daily dose
        if max_daily_dose:
            daily_dose = quantity / Decimal(str(days_supply))
            if daily_dose > Decimal(str(max_daily_dose)):
                approved_daily = Decimal(str(max_daily_dose))
                approved_quantity = approved_daily * Decimal(str(days_supply))
                
                if approved_quantity < (quantity * Decimal('0.5')):  # More than 50% reduction
                    return {
                        'status': 'denied',
                        'approved_quantity': Decimal('0'),
                        'reason': 'excessive_daily_dose',
                        'message': f'Daily dose too high: {daily_dose} > {max_daily_dose}'
                    }
                else:
                    return {
                        'status': 'partial',
                        'approved_quantity': approved_quantity,
                        'reason': 'daily_dose_reduced',
                        'message': f'Daily dose reduced to maximum allowable'
                    }
        
        # Check monthly dose
        if max_monthly_dose:
            monthly_dose = (quantity / Decimal(str(days_supply))) * Decimal('30')
            if monthly_dose > Decimal(str(max_monthly_dose)):
                approved_monthly = Decimal(str(max_monthly_dose))
                approved_quantity = (approved_monthly / Decimal('30')) * Decimal(str(days_supply))
                
                return {
                    'status': 'partial',
                    'approved_quantity': approved_quantity,
                    'reason': 'monthly_dose_reduced',
                    'message': f'Monthly dose reduced to maximum allowable'
                }
        
        return {
            'status': 'approved',
            'approved_quantity': quantity,
            'reason': 'within_limits',
            'message': 'Dosage within acceptable limits'
        }
    
    def _apply_pricing_rules(self, base_amount: Decimal, medicine_code: str) -> Decimal:
        pricing_rules = self.formulary_data.get('pricing_rules', {})
        
        # Apply markup
        markup_percentage = pricing_rules.get('markup_percentage', 0)
        if markup_percentage > 0:
            markup_amount = base_amount * (Decimal(str(markup_percentage)) / Decimal('100'))
            base_amount += markup_amount
        
        # Add dispensing fee
        dispensing_fee = self._validate_amount(pricing_rules.get('dispensing_fee', 0))
        base_amount += dispensing_fee
        
        return base_amount