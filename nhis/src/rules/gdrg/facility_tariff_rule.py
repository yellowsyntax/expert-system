from typing import List, Optional, Dict, Any
from ..base_rule import BaseRule, RuleResult, RuleResultType
from ...core.models import ClaimProcessingContext
from ...database.repositories.tariff_repository import TariffRepository
from ...database.repositories.provider_repository import ProviderRepository
import logging

logger = logging.getLogger(__name__)


class FacilityTariffRule(BaseRule):
    
    def __init__(self, tariff_repo: TariffRepository, provider_repo: ProviderRepository):
        super().__init__(
            rule_id="A4",
            name="Facility Tariff Rule",
            description="Get facility-specific tariff for G-DRG codes"
        )
        self.tariff_repo = tariff_repo
        self.provider_repo = provider_repo
    
    def _get_facility_level(self, facility_id: str) -> Optional[str]:
        try:
            provider = self.provider_repo.get_by_id(facility_id)
            if provider:
                return provider.facility_level
            return None
        except Exception as e:
            logger.error(f"Error getting facility level for {facility_id}: {str(e)}")
            return None
    
    def _lookup_gdrg_tariff(self, gdrg_code: str, facility_level: str) -> Optional[Dict[str, Any]]:
        try:
            tariff = self.tariff_repo.get_gdrg_tariff(gdrg_code, facility_level)
            return tariff
        except Exception as e:
            logger.error(f"Error looking up tariff for G-DRG {gdrg_code}, level {facility_level}: {str(e)}")
            return None
    
    def _find_best_tariff_match(self, gdrg_codes: List[str], facility_level: str) -> Optional[Dict[str, Any]]:
        for gdrg_code in gdrg_codes:
            tariff = self._lookup_gdrg_tariff(gdrg_code, facility_level)
            if tariff:
                return tariff
        return None
    
    def evaluate(self, context: ClaimProcessingContext) -> RuleResult:
        try:
            claim = context.claim
            
            if not claim.facility_id:
                return RuleResult(
                    rule_id=self.rule_id,
                    result_type=RuleResultType.REJECT,
                    message="Missing facility ID for tariff lookup",
                    details={"reason": "facility_id_missing"}
                )
            
            if not context.candidate_gdrgs:
                return RuleResult(
                    rule_id=self.rule_id,
                    result_type=RuleResultType.REJECT,
                    message="No candidate G-DRGs available for tariff lookup",
                    details={"reason": "no_candidate_gdrgs"}
                )
            
            facility_level = self._get_facility_level(claim.facility_id)
            if not facility_level:
                return RuleResult(
                    rule_id=self.rule_id,
                    result_type=RuleResultType.REJECT,
                    message="Cannot determine facility level for tariff lookup",
                    details={
                        "reason": "facility_level_unknown",
                        "facility_id": claim.facility_id
                    }
                )
            
            tariff_match = self._find_best_tariff_match(context.candidate_gdrgs, facility_level)
            
            if not tariff_match:
                return RuleResult(
                    rule_id=self.rule_id,
                    result_type=RuleResultType.REJECT,
                    message="No tariff found for any candidate G-DRGs at facility level",
                    details={
                        "reason": "no_tariff_found",
                        "facility_id": claim.facility_id,
                        "facility_level": facility_level,
                        "candidate_gdrgs": context.candidate_gdrgs
                    }
                )
            
            context.selected_gdrg = tariff_match.get('gdrg_code')
            context.tariff_amount = tariff_match.get('tariff_amount')
            context.facility_level = facility_level
            
            details = {
                "facility_id": claim.facility_id,
                "facility_level": facility_level,
                "candidate_gdrgs": context.candidate_gdrgs,
                "selected_gdrg": context.selected_gdrg,
                "tariff_amount": context.tariff_amount,
                "tariff_effective_date": tariff_match.get('effective_date'),
                "tariff_id": tariff_match.get('id')
            }
            
            return RuleResult(
                rule_id=self.rule_id,
                result_type=RuleResultType.APPROVE,
                message=f"Tariff found: {context.selected_gdrg} = GHS {context.tariff_amount} (Level {facility_level})",
                details=details
            )
            
        except Exception as e:
            logger.error(f"Error in FacilityTariffRule evaluation: {str(e)}")
            return RuleResult(
                rule_id=self.rule_id,
                result_type=RuleResultType.FLAG,
                message=f"Error during tariff lookup: {str(e)}",
                details={"error": str(e)}
            )