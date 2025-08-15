from typing import Optional, Dict, Any
from decimal import Decimal
from .base_calculator import BaseCalculator, CalculationResult
from ..core.models import ClaimProcessingContext
from ..database.repositories.tariff_repository import TariffRepository
import logging

logger = logging.getLogger(__name__)


class GDRGTariffCalculator(BaseCalculator):
    
    def __init__(self, tariff_repo: TariffRepository):
        super().__init__()
        self.tariff_repo = tariff_repo
    
    def calculate(self, context: ClaimProcessingContext, **kwargs) -> CalculationResult:
        try:
            claim = context.claim
            
            if not hasattr(context, 'selected_gdrg') or not context.selected_gdrg:
                return self._create_failed_result(
                    message="No G-DRG selected for tariff calculation",
                    details={"reason": "missing_selected_gdrg"}
                )
            
            if not hasattr(context, 'facility_level') or not context.facility_level:
                return self._create_failed_result(
                    message="No facility level available for tariff calculation",
                    details={"reason": "missing_facility_level"}
                )
            
            tariff = self._get_gdrg_tariff(context.selected_gdrg, context.facility_level)
            
            if not tariff:
                return self._create_failed_result(
                    message=f"No tariff found for G-DRG {context.selected_gdrg} at facility level {context.facility_level}",
                    details={
                        "reason": "tariff_not_found",
                        "gdrg_code": context.selected_gdrg,
                        "facility_level": context.facility_level
                    }
                )
            
            base_amount = self._validate_amount(tariff.get('tariff_amount', 0))
            
            if base_amount <= 0:
                return self._create_failed_result(
                    message=f"Invalid tariff amount for G-DRG {context.selected_gdrg}",
                    details={
                        "reason": "invalid_tariff_amount",
                        "tariff_amount": tariff.get('tariff_amount')
                    }
                )
            
            # Apply any G-DRG specific adjustments
            adjustments = self._calculate_gdrg_adjustments(context, tariff)
            final_amount = base_amount + sum(adjustments.values())
            
            # Store calculated amounts in context
            context.gdrg_base_amount = base_amount
            context.gdrg_final_amount = final_amount
            
            details = {
                "gdrg_code": context.selected_gdrg,
                "facility_level": context.facility_level,
                "base_tariff": base_amount,
                "adjustments": {k: float(v) for k, v in adjustments.items()},
                "final_amount": final_amount,
                "tariff_effective_date": tariff.get('effective_date'),
                "tariff_version": tariff.get('version', '1.0')
            }
            
            return self._create_success_result(
                amount=final_amount,
                base_amount=base_amount,
                adjustments=adjustments,
                message=f"G-DRG tariff calculated: {context.selected_gdrg} = GHS {final_amount}",
                details=details
            )
            
        except Exception as e:
            logger.error(f"Error in GDRGTariffCalculator: {str(e)}")
            return self._create_failed_result(
                message=f"Error calculating G-DRG tariff: {str(e)}",
                details={"error": str(e)}
            )
    
    def _get_gdrg_tariff(self, gdrg_code: str, facility_level: str) -> Optional[Dict[str, Any]]:
        try:
            return self.tariff_repo.get_gdrg_tariff(gdrg_code, facility_level)
        except Exception as e:
            logger.error(f"Error retrieving G-DRG tariff: {str(e)}")
            return None
    
    def _calculate_gdrg_adjustments(self, context: ClaimProcessingContext, tariff: Dict[str, Any]) -> Dict[str, Decimal]:
        adjustments = {}
        
        # Case mix adjustment
        case_mix_index = tariff.get('case_mix_index', 1.0)
        if case_mix_index != 1.0:
            base_amount = self._validate_amount(tariff.get('tariff_amount', 0))
            case_mix_adjustment = base_amount * (Decimal(str(case_mix_index)) - Decimal('1'))
            adjustments['case_mix'] = case_mix_adjustment
        
        # Length of stay adjustment (for inpatient)
        if hasattr(context.claim, 'length_of_stay') and context.claim.length_of_stay:
            los_adjustment = self._calculate_los_adjustment(context, tariff)
            if los_adjustment != 0:
                adjustments['length_of_stay'] = los_adjustment
        
        # Teaching hospital adjustment
        if hasattr(context.claim, 'facility_type') and context.claim.facility_type:
            if 'teaching' in context.claim.facility_type.lower():
                teaching_multiplier = tariff.get('teaching_adjustment', 1.1)
                if teaching_multiplier != 1.0:
                    base_amount = self._validate_amount(tariff.get('tariff_amount', 0))
                    teaching_adjustment = base_amount * (Decimal(str(teaching_multiplier)) - Decimal('1'))
                    adjustments['teaching_hospital'] = teaching_adjustment
        
        return adjustments
    
    def _calculate_los_adjustment(self, context: ClaimProcessingContext, tariff: Dict[str, Any]) -> Decimal:
        try:
            actual_los = int(context.claim.length_of_stay)
            expected_los = tariff.get('expected_los', 0)
            
            if expected_los <= 0:
                return Decimal('0')
            
            los_threshold = tariff.get('los_threshold', 1.5)
            per_diem_rate = self._validate_amount(tariff.get('per_diem_rate', 0))
            
            if actual_los > (expected_los * los_threshold):
                excess_days = actual_los - int(expected_los * los_threshold)
                return per_diem_rate * Decimal(str(excess_days))
            
            return Decimal('0')
            
        except (ValueError, TypeError):
            return Decimal('0')
    
    def get_tariff_info(self, gdrg_code: str, facility_level: str) -> Optional[Dict[str, Any]]:
        return self._get_gdrg_tariff(gdrg_code, facility_level)
    
    def calculate_base_amount_only(self, gdrg_code: str, facility_level: str) -> Decimal:
        tariff = self._get_gdrg_tariff(gdrg_code, facility_level)
        if tariff:
            return self._validate_amount(tariff.get('tariff_amount', 0))
        return Decimal('0')