from abc import ABC, abstractmethod
from typing import Dict, Any, List, Optional
from enum import Enum
from dataclasses import dataclass
from datetime import datetime


class RuleDecision(Enum):
    APPROVE = "APPROVE"
    REJECT = "REJECT"
    FLAG = "FLAG"
    PEND = "PEND"
    PARTIAL = "PARTIAL"


class RuleSeverity(Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


@dataclass
class RuleResult:
    decision: RuleDecision
    rule_name: str
    rule_category: str
    reason: str
    severity: RuleSeverity = RuleSeverity.MEDIUM
    affected_amount: Optional[float] = None
    data_used: Optional[Dict[str, Any]] = None
    recommendations: Optional[List[str]] = None
    validation_errors: Optional[List[str]] = None
    warnings: Optional[List[str]] = None
    processing_time_ms: Optional[int] = None
    metadata: Optional[Dict[str, Any]] = None
    
    def is_blocking(self) -> bool:
        return self.decision in [RuleDecision.REJECT, RuleDecision.PEND]
    
    def is_approval(self) -> bool:
        return self.decision == RuleDecision.APPROVE
    
    def has_financial_impact(self) -> bool:
        return self.affected_amount is not None and self.affected_amount != 0
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'decision': self.decision.value,
            'rule_name': self.rule_name,
            'rule_category': self.rule_category,
            'reason': self.reason,
            'severity': self.severity.value,
            'affected_amount': self.affected_amount,
            'data_used': self.data_used,
            'recommendations': self.recommendations or [],
            'validation_errors': self.validation_errors or [],
            'warnings': self.warnings or [],
            'processing_time_ms': self.processing_time_ms,
            'metadata': self.metadata or {},
            'is_blocking': self.is_blocking(),
            'has_financial_impact': self.has_financial_impact()
        }

class BaseRule(ABC):
    def __init__(self, db_session, reference_data_manager):
        self.db_session = db_session
        self.reference_data = reference_data_manager
        self.rule_name = self.__class__.__name__
        self.rule_category = self._get_rule_category()
    
    def _get_rule_category(self) -> str:
        module_path = self.__module__
        if 'opd' in module_path:
            return 'OPD'
        elif 'inpatient' in module_path:
            return 'INPATIENT'
        elif 'emergency' in module_path:
            return 'EMERGENCY'
        elif 'gdrg' in module_path:
            return 'GDRG'
        elif 'modifiers' in module_path:
            return 'MODIFIERS'
        elif 'documentation' in module_path:
            return 'DOCUMENTATION'
        else:
            return 'GENERAL'
    
    @abstractmethod
    def validate(self, claim_data: Dict[str, Any], context: Dict[str, Any]) -> RuleResult:
        pass
    
    def get_reference_data(self, data_type: str) -> Dict[str, Any]:
        return self.reference_data.get_data(data_type)
    
    def create_result(self, decision: RuleDecision, reason: str, 
                     severity: RuleSeverity = RuleSeverity.MEDIUM,
                     affected_amount: Optional[float] = None,
                     data_used: Optional[Dict[str, Any]] = None,
                     recommendations: Optional[List[str]] = None,
                     validation_errors: Optional[List[str]] = None,
                     warnings: Optional[List[str]] = None,
                     metadata: Optional[Dict[str, Any]] = None) -> RuleResult:
        return RuleResult(
            decision=decision,
            rule_name=self.rule_name,
            rule_category=self.rule_category,
            reason=reason,
            severity=severity,
            affected_amount=affected_amount,
            data_used=data_used,
            recommendations=recommendations,
            validation_errors=validation_errors,
            warnings=warnings,
            metadata=metadata
        )
    
    def approve(self, reason: str, affected_amount: Optional[float] = None, 
               **kwargs) -> RuleResult:
        return self.create_result(
            decision=RuleDecision.APPROVE,
            reason=reason,
            severity=RuleSeverity.LOW,
            affected_amount=affected_amount,
            **kwargs
        )
    
    def reject(self, reason: str, severity: RuleSeverity = RuleSeverity.HIGH,
              validation_errors: Optional[List[str]] = None, **kwargs) -> RuleResult:
        return self.create_result(
            decision=RuleDecision.REJECT,
            reason=reason,
            severity=severity,
            validation_errors=validation_errors or [],
            **kwargs
        )
    
    def flag(self, reason: str, severity: RuleSeverity = RuleSeverity.MEDIUM,
            warnings: Optional[List[str]] = None, **kwargs) -> RuleResult:
        return self.create_result(
            decision=RuleDecision.FLAG,
            reason=reason,
            severity=severity,
            warnings=warnings or [],
            **kwargs
        )
    
    def pend(self, reason: str, recommendations: Optional[List[str]] = None,
            **kwargs) -> RuleResult:
        return self.create_result(
            decision=RuleDecision.PEND,
            reason=reason,
            severity=RuleSeverity.MEDIUM,
            recommendations=recommendations or [],
            **kwargs
        )
    
    def partial(self, reason: str, affected_amount: float,
               warnings: Optional[List[str]] = None, **kwargs) -> RuleResult:
        return self.create_result(
            decision=RuleDecision.PARTIAL,
            reason=reason,
            severity=RuleSeverity.MEDIUM,
            affected_amount=affected_amount,
            warnings=warnings or [],
            **kwargs
        )
    
    def get_patient_age_years(self, date_of_birth: datetime, reference_date: datetime = None) -> int:
        if reference_date is None:
            reference_date = datetime.utcnow()
        
        age = reference_date.year - date_of_birth.year
        if reference_date.month < date_of_birth.month or (
            reference_date.month == date_of_birth.month and 
            reference_date.day < date_of_birth.day
        ):
            age -= 1
        
        return max(0, age)
    
    def is_child(self, date_of_birth: datetime, reference_date: datetime = None) -> bool:
        return self.get_patient_age_years(date_of_birth, reference_date) < 12
    
    def extract_claim_field(self, claim_data: Dict[str, Any], field_name: str, 
                           default_value: Any = None) -> Any:
        return claim_data.get(field_name, default_value)
    
    def extract_context_field(self, context: Dict[str, Any], field_name: str,
                             default_value: Any = None) -> Any:
        return context.get(field_name, default_value)
    
    def validate_required_fields(self, claim_data: Dict[str, Any], 
                                required_fields: List[str]) -> List[str]:
        missing_fields = []
        for field in required_fields:
            if field not in claim_data or claim_data[field] is None:
                missing_fields.append(field)
        return missing_fields
    
    def get_icd10_category(self, icd10_code: str) -> str:
        if not icd10_code:
            return "UNKNOWN"
        
        code_prefix = icd10_code[:3].upper()
        
        category_map = {
            'A': 'INFECTIOUS', 'B': 'INFECTIOUS',
            'C': 'NEOPLASMS', 'D': 'NEOPLASMS',
            'E': 'ENDOCRINE', 
            'F': 'MENTAL',
            'G': 'NERVOUS',
            'H': 'SENSORY',
            'I': 'CIRCULATORY',
            'J': 'RESPIRATORY',
            'K': 'DIGESTIVE',
            'L': 'SKIN',
            'M': 'MUSCULOSKELETAL',
            'N': 'GENITOURINARY',
            'O': 'PREGNANCY',
            'P': 'PERINATAL',
            'Q': 'CONGENITAL',
            'R': 'SYMPTOMS',
            'S': 'INJURY', 'T': 'INJURY',
            'V': 'EXTERNAL', 'W': 'EXTERNAL', 'X': 'EXTERNAL', 'Y': 'EXTERNAL',
            'Z': 'HEALTH_SERVICES'
        }
        
        return category_map.get(code_prefix[0], "UNKNOWN")
    
    def is_chronic_condition(self, icd10_code: str) -> bool:
        chronic_conditions = self.get_reference_data('chronic_conditions')
        if not chronic_conditions:
            return False
        
        for condition_code in chronic_conditions.keys():
            if icd10_code.startswith(condition_code):
                return True
        
        return False
    
    def is_pregnancy_related(self, icd10_code: str) -> bool:
        pregnancy_codes = ['O', 'Z34', 'Z35', 'Z36', 'Z37', 'Z38', 'Z39']
        for code in pregnancy_codes:
            if icd10_code.startswith(code):
                return True
        return False
    
    def calculate_days_between(self, start_date: datetime, end_date: datetime) -> int:
        if not start_date or not end_date:
            return 0
        return abs((end_date - start_date).days)
    
    def get_service_type_category(self, service_type: str) -> str:
        service_map = {
            'IPD': 'INPATIENT',
            'OPD': 'OUTPATIENT', 
            'A&E': 'EMERGENCY',
            'EMERGENCY': 'EMERGENCY'
        }
        return service_map.get(service_type, 'UNKNOWN')
    
    def log_rule_execution(self, claim_id: str, result: RuleResult, 
                          execution_time_ms: int = None):
        if execution_time_ms:
            result.processing_time_ms = execution_time_ms
        
        if hasattr(self, '_audit_logger'):
            self._audit_logger.log_business_rule_application(
                claim_id=claim_id,
                rule_name=self.rule_name,
                rule_result=result.decision.value,
                rule_data=result.to_dict()
            )

class RuleValidator:
    @staticmethod
    def validate_rule_result(result: RuleResult) -> List[str]:
        validation_errors = []
        
        if not result.rule_name:
            validation_errors.append("Rule name is required")
        
        if not result.reason:
            validation_errors.append("Rule reason is required")
        
        if result.decision == RuleDecision.REJECT and not result.validation_errors:
            validation_errors.append("Rejected rules should provide validation errors")
        
        if result.decision == RuleDecision.PARTIAL and result.affected_amount is None:
            validation_errors.append("Partial decisions must specify affected amount")
        
        return validation_errors
    
    @staticmethod
    def validate_claim_data(claim_data: Dict[str, Any]) -> List[str]:
        validation_errors = []
        
        required_base_fields = ['nhis_number', 'service_type_1', 'provider_id']
        for field in required_base_fields:
            if field not in claim_data or claim_data[field] is None:
                validation_errors.append(f"Required field missing: {field}")
        
        return validation_errors