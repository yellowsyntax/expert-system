from typing import List, Dict, Any, Optional
from decimal import Decimal
from .base_calculator import BaseCalculator, CalculationResult
from ..core.models import ClaimProcessingContext
from ..database.repositories.tariff_repository import TariffRepository
import json
import logging

logger = logging.getLogger(__name__)


class InvestigationCalculator(BaseCalculator):
    
    def __init__(self, tariff_repo: TariffRepository, reference_data_path: str = "reference_data/bundling_rules.json"):
        super().__init__()
        self.tariff_repo = tariff_repo
        self.bundling_rules = self._load_bundling_rules(reference_data_path)
    
    def _load_bundling_rules(self, file_path: str) -> Dict[str, Any]:
        try:
            with open(file_path, 'r') as f:
                return json.load(f)
        except Exception as e:
            logger.warning(f"Could not load bundling rules data: {str(e)}")
            return self._get_default_bundling_rules()
    
    def _get_default_bundling_rules(self) -> Dict[str, Any]:
        return {
            "bundled_investigations": {
                "LAB_BASIC": ["CBC", "ESR", "URINALYSIS"],
                "LAB_LIPID": ["CHOLESTEROL", "TRIGLYCERIDES", "HDL", "LDL"],
                "LAB_LFT": ["ALT", "AST", "BILIRUBIN", "ALKALINE_PHOSPHATASE"],
                "LAB_RFT": ["UREA", "CREATININE", "ELECTROLYTES"],
                "IMAGING_CHEST": ["CHEST_XRAY", "CHEST_CT"],
                "IMAGING_ABDOMEN": ["ABDOMINAL_ULTRASOUND", "ABDOMINAL_CT"]
            },
            "separately_billable": {
                "LAB_BASIC": ["BLOOD_CULTURE", "STOOL_CULTURE"],
                "IMAGING_CHEST": ["CHEST_MRI", "CHEST_ANGIOGRAPHY"],
                "IMAGING_ABDOMEN": ["ABDOMINAL_MRI", "MRCP"]
            },
            "bundling_settings": {
                "OPD": "unbundled",
                "IPD": "bundled",
                "A&E": "unbundled"
            }
        }
    
    def calculate(self, context: ClaimProcessingContext, **kwargs) -> CalculationResult:
        try:
            claim = context.claim
            
            if not hasattr(claim, 'investigations') or not claim.investigations:
                return self._create_success_result(
                    amount=Decimal('0'),
                    message="No investigations found - investigation calculation skipped",
                    details={"reason": "no_investigations"}
                )
            
            encounter_setting = getattr(claim, 'encounter_setting', 'OPD')
            bundling_setting = self._get_bundling_setting(encounter_setting)
            
            if bundling_setting == "unbundled":
                return self._calculate_unbundled(claim.investigations, context)
            else:
                return self._calculate_bundled(claim.investigations, context)
            
        except Exception as e:
            logger.error(f"Error in InvestigationCalculator: {str(e)}")
            return self._create_failed_result(
                message=f"Error calculating investigation amounts: {str(e)}",
                details={"error": str(e)}
            )
    
    def _get_bundling_setting(self, encounter_setting: str) -> str:
        bundling_settings = self.bundling_rules.get('bundling_settings', {})
        return bundling_settings.get(encounter_setting.upper(), 'unbundled')
    
    def _calculate_unbundled(self, investigations: List[Dict[str, Any]], context: ClaimProcessingContext) -> CalculationResult:
        investigation_calculations = []
        total_approved = Decimal('0')
        total_denied = Decimal('0')
        
        for investigation in investigations:
            calc_result = self._calculate_single_investigation(investigation)
            investigation_calculations.append(calc_result)
            
            if calc_result['status'] == 'approved':
                total_approved += calc_result['amount']
            elif calc_result['status'] == 'denied':
                total_denied += calc_result['amount']
        
        total_amount = total_approved + total_denied
        
        context.investigation_approved_amount = total_approved
        context.investigation_denied_amount = total_denied
        context.investigation_calculations = investigation_calculations
        
        details = {
            "bundling_mode": "unbundled",
            "total_investigations": len(investigations),
            "approved_amount": float(total_approved),
            "denied_amount": float(total_denied),
            "investigation_calculations": investigation_calculations
        }
        
        if total_denied > 0:
            status = CalculationStatus.PARTIAL
            message = f"Investigation calculation partial - Approved: GHS {total_approved}, Denied: GHS {total_denied}"
        else:
            status = CalculationStatus.SUCCESS
            message = f"All investigations approved - Total: GHS {total_approved}"
        
        return CalculationResult(
            status=status,
            amount=total_amount,
            base_amount=total_amount,
            message=message,
            details=details
        )
    
    def _calculate_bundled(self, investigations: List[Dict[str, Any]], context: ClaimProcessingContext) -> CalculationResult:
        investigation_calculations = []
        total_approved = Decimal('0')
        total_denied = Decimal('0')
        
        # Group investigations by bundle
        bundled_groups = self._group_investigations_by_bundle(investigations)
        
        for investigation in investigations:
            investigation_code = investigation.get('code', '')
            bundle_group = self._find_bundle_group(investigation_code)
            
            if bundle_group and not self._is_separately_billable(investigation_code, bundle_group):
                # Investigation is bundled - check if G-DRG covers it
                if hasattr(context, 'selected_gdrg') and context.selected_gdrg:
                    calc_result = {
                        'investigation_code': investigation_code,
                        'investigation_name': investigation.get('name', ''),
                        'status': 'denied',
                        'amount': Decimal('0'),
                        'reason': 'bundled_in_gdrg',
                        'message': f'Investigation included in G-DRG {context.selected_gdrg}',
                        'bundle_group': bundle_group
                    }
                else:
                    # No G-DRG, calculate normally
                    calc_result = self._calculate_single_investigation(investigation)
                    calc_result['bundle_group'] = bundle_group
            else:
                # Investigation is separately billable
                calc_result = self._calculate_single_investigation(investigation)
                calc_result['separately_billable'] = True
            
            investigation_calculations.append(calc_result)
            
            if calc_result['status'] == 'approved':
                total_approved += calc_result['amount']
            elif calc_result['status'] == 'denied':
                total_denied += calc_result['amount']
        
        total_amount = total_approved + total_denied
        
        context.investigation_approved_amount = total_approved
        context.investigation_denied_amount = total_denied
        context.investigation_calculations = investigation_calculations
        
        details = {
            "bundling_mode": "bundled",
            "total_investigations": len(investigations),
            "approved_amount": float(total_approved),
            "denied_amount": float(total_denied),
            "bundled_groups": bundled_groups,
            "investigation_calculations": investigation_calculations
        }
        
        if total_denied > 0:
            status = CalculationStatus.PARTIAL
            message = f"Investigation calculation partial - Approved: GHS {total_approved}, Denied: GHS {total_denied}"
        else:
            status = CalculationStatus.SUCCESS
            message = f"Investigation calculation complete - Total: GHS {total_approved}"
        
        return CalculationResult(
            status=status,
            amount=total_amount,
            base_amount=total_amount,
            message=message,
            details=details
        )
    
    def _calculate_single_investigation(self, investigation: Dict[str, Any]) -> Dict[str, Any]:
        investigation_code = investigation.get('code', '')
        investigation_name = investigation.get('name', '')
        quantity = self._validate_amount(investigation.get('quantity', 1))
        
        # Get unit price
        unit_price = self._get_unit_price(investigation_code)
        
        if unit_price <= 0:
            return {
                'investigation_code': investigation_code,
                'investigation_name': investigation_name,
                'quantity': float(quantity),
                'status': 'denied',
                'amount': Decimal('0'),
                'reason': 'no_unit_price',
                'message': 'Unit price not found in tariff'
            }
        
        total_amount = unit_price * quantity
        
        return {
            'investigation_code': investigation_code,
            'investigation_name': investigation_name,
            'quantity': float(quantity),
            'unit_price': float(unit_price),
            'total_amount': float(total_amount),
            'status': 'approved',
            'amount': total_amount,
            'reason': 'approved',
            'message': 'Investigation approved'
        }
    
    def _get_unit_price(self, investigation_code: str) -> Decimal:
        try:
            tariff = self.tariff_repo.get_investigation_tariff(investigation_code)
            if tariff and tariff.get('unit_price'):
                return self._validate_amount(tariff['unit_price'])
            return Decimal('0')
        except Exception as e:
            logger.error(f"Error getting unit price for {investigation_code}: {str(e)}")
            return Decimal('0')
    
    def _group_investigations_by_bundle(self, investigations: List[Dict[str, Any]]) -> Dict[str, List[str]]:
        bundled_groups = {}
        bundled_investigations = self.bundling_rules.get('bundled_investigations', {})
        
        for investigation in investigations:
            investigation_code = investigation.get('code', '')
            bundle_group = self._find_bundle_group(investigation_code)
            
            if bundle_group:
                if bundle_group not in bundled_groups:
                    bundled_groups[bundle_group] = []
                bundled_groups[bundle_group].append(investigation_code)
        
        return bundled_groups
    
    def _find_bundle_group(self, investigation_code: str) -> Optional[str]:
        bundled_investigations = self.bundling_rules.get('bundled_investigations', {})
        
        for bundle_group, investigation_list in bundled_investigations.items():
            if investigation_code in investigation_list:
                return bundle_group
        
        return None
    
    def _is_separately_billable(self, investigation_code: str, bundle_group: str) -> bool:
        separately_billable = self.bundling_rules.get('separately_billable', {})
        billable_list = separately_billable.get(bundle_group, [])
        return investigation_code in billable_list