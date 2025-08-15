from datetime import datetime, date
from typing import List, Optional
from ..base_rule import BaseRule, RuleResult, RuleResultType
from ...core.models import ClaimProcessingContext
import logging

logger = logging.getLogger(__name__)


class AgeSplitRule(BaseRule):
    
    def __init__(self):
        super().__init__(
            rule_id="A3",
            name="Age Split Rule",
            description="Apply age-based suffix (A/C) to G-DRG codes"
        )
        
        self.childhood_cancer_codes = self._load_childhood_cancer_codes()
    
    def _load_childhood_cancer_codes(self) -> set:
        cancer_prefixes = [
            'C00', 'C01', 'C02', 'C03', 'C04', 'C05', 'C06', 'C07', 'C08', 'C09',
            'C10', 'C11', 'C12', 'C13', 'C14', 'C15', 'C16', 'C17', 'C18', 'C19',
            'C20', 'C21', 'C22', 'C23', 'C24', 'C25', 'C26', 'C30', 'C31', 'C32',
            'C33', 'C34', 'C37', 'C38', 'C39', 'C40', 'C41', 'C43', 'C44', 'C45',
            'C46', 'C47', 'C48', 'C49', 'C50', 'C51', 'C52', 'C53', 'C54', 'C55',
            'C56', 'C57', 'C58', 'C60', 'C61', 'C62', 'C63', 'C64', 'C65', 'C66',
            'C67', 'C68', 'C69', 'C70', 'C71', 'C72', 'C73', 'C74', 'C75', 'C76',
            'C77', 'C78', 'C79', 'C80', 'C81', 'C82', 'C83', 'C84', 'C85', 'C88',
            'C90', 'C91', 'C92', 'C93', 'C94', 'C95', 'C96', 'C97'
        ]
        return set(cancer_prefixes)
    
    def _calculate_age_in_years(self, birth_date: date, service_date: date) -> int:
        age = service_date.year - birth_date.year
        if service_date.month < birth_date.month or (
            service_date.month == birth_date.month and service_date.day < birth_date.day
        ):
            age -= 1
        return age
    
    def _is_childhood_cancer(self, icd10_code: str) -> bool:
        if not icd10_code:
            return False
        
        icd10_prefix = icd10_code[:3].upper()
        return icd10_prefix in self.childhood_cancer_codes
    
    def _determine_age_suffix(self, age_years: int, is_cancer: bool) -> str:
        if is_cancer and age_years < 19:
            return 'C'
        elif age_years < 12:
            return 'C'
        else:
            return 'A'
    
    def _apply_suffix_to_gdrg(self, gdrg_code: str, suffix: str) -> str:
        if not gdrg_code:
            return gdrg_code
            
        if gdrg_code.endswith('A') or gdrg_code.endswith('C'):
            return gdrg_code[:-1] + suffix
        else:
            return gdrg_code + suffix
    
    def evaluate(self, context: ClaimProcessingContext) -> RuleResult:
        try:
            claim = context.claim
            
            if not claim.patient_birth_date:
                return RuleResult(
                    rule_id=self.rule_id,
                    result_type=RuleResultType.PEND,
                    message="Missing patient birth date for age calculation",
                    details={"reason": "birth_date_missing"}
                )
            
            if not claim.service_date:
                return RuleResult(
                    rule_id=self.rule_id,
                    result_type=RuleResultType.PEND,
                    message="Missing service date for age calculation",
                    details={"reason": "service_date_missing"}
                )
            
            if not context.candidate_gdrgs:
                return RuleResult(
                    rule_id=self.rule_id,
                    result_type=RuleResultType.FLAG,
                    message="No candidate G-DRGs available for age split",
                    details={"reason": "no_candidate_gdrgs"}
                )
            
            age_years = self._calculate_age_in_years(claim.patient_birth_date, claim.service_date)
            
            is_cancer = False
            if claim.primary_diagnosis:
                is_cancer = self._is_childhood_cancer(claim.primary_diagnosis)
            
            age_suffix = self._determine_age_suffix(age_years, is_cancer)
            
            age_split_gdrgs = []
            for gdrg in context.candidate_gdrgs:
                age_adjusted_gdrg = self._apply_suffix_to_gdrg(gdrg, age_suffix)
                age_split_gdrgs.append(age_adjusted_gdrg)
            
            context.candidate_gdrgs = age_split_gdrgs
            
            details = {
                "patient_age_years": age_years,
                "age_suffix_applied": age_suffix,
                "is_childhood_cancer": is_cancer,
                "original_gdrgs": context.candidate_gdrgs,
                "age_adjusted_gdrgs": age_split_gdrgs
            }
            
            if is_cancer and age_years < 19:
                message = f"Applied 'C' suffix for childhood cancer patient (age {age_years})"
            elif age_years < 12:
                message = f"Applied 'C' suffix for child patient (age {age_years})"
            else:
                message = f"Applied 'A' suffix for adult patient (age {age_years})"
            
            return RuleResult(
                rule_id=self.rule_id,
                result_type=RuleResultType.APPROVE,
                message=message,
                details=details
            )
            
        except Exception as e:
            logger.error(f"Error in AgeSplitRule evaluation: {str(e)}")
            return RuleResult(
                rule_id=self.rule_id,
                result_type=RuleResultType.FLAG,
                message=f"Error during age split evaluation: {str(e)}",
                details={"error": str(e)}
            )