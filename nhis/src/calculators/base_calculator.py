from abc import ABC, abstractmethod
from typing import Dict, Any, Optional
from dataclasses import dataclass
from decimal import Decimal
from enum import Enum


class CalculationStatus(Enum):
    SUCCESS = "success"
    PARTIAL = "partial"
    FAILED = "failed"
    PENDING = "pending"


@dataclass
class CalculationResult:
    status: CalculationStatus
    amount: Decimal
    base_amount: Optional[Decimal] = None
    adjustments: Optional[Dict[str, Decimal]] = None
    details: Optional[Dict[str, Any]] = None
    message: Optional[str] = None
    
    def __post_init__(self):
        if self.adjustments is None:
            self.adjustments = {}
        if self.details is None:
            self.details = {}


@dataclass
class AmountBreakdown:
    gdrg_amount: Decimal = Decimal('0')
    medicine_amount: Decimal = Decimal('0')
    investigation_amount: Decimal = Decimal('0')
    modifier_amount: Decimal = Decimal('0')
    total_amount: Decimal = Decimal('0')
    approved_amount: Decimal = Decimal('0')
    denied_amount: Decimal = Decimal('0')
    pending_amount: Decimal = Decimal('0')


class BaseCalculator(ABC):
    
    def __init__(self):
        self.calculation_id = self.__class__.__name__
    
    @abstractmethod
    def calculate(self, context: Any, **kwargs) -> CalculationResult:
        pass
    
    def _validate_amount(self, amount: Any) -> Decimal:
        if amount is None:
            return Decimal('0')
        
        if isinstance(amount, (int, float)):
            return Decimal(str(amount))
        
        if isinstance(amount, str):
            try:
                return Decimal(amount)
            except:
                return Decimal('0')
        
        if isinstance(amount, Decimal):
            return amount
        
        return Decimal('0')
    
    def _create_success_result(self, amount: Decimal, message: str = "", **kwargs) -> CalculationResult:
        return CalculationResult(
            status=CalculationStatus.SUCCESS,
            amount=amount,
            message=message,
            **kwargs
        )
    
    def _create_partial_result(self, amount: Decimal, message: str = "", **kwargs) -> CalculationResult:
        return CalculationResult(
            status=CalculationStatus.PARTIAL,
            amount=amount,
            message=message,
            **kwargs
        )
    
    def _create_failed_result(self, message: str = "", **kwargs) -> CalculationResult:
        return CalculationResult(
            status=CalculationStatus.FAILED,
            amount=Decimal('0'),
            message=message,
            **kwargs
        )
    
    def _create_pending_result(self, message: str = "", **kwargs) -> CalculationResult:
        return CalculationResult(
            status=CalculationStatus.PENDING,
            amount=Decimal('0'),
            message=message,
            **kwargs
        )