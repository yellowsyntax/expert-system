from typing import Dict, Any, List
from decimal import Decimal
from .base_validator import BaseValidator, ValidationResult
from ..utils.helpers import safe_decimal


class FinancialValidator(BaseValidator):
    
    def __init__(self):
        super().__init__()
        self.max_claim_amount = 100000.0
        self.max_gdrg_amount = 50000.0
        self.max_medicine_amount = 20000.0
        self.max_investigation_amount = 15000.0
        self.max_modifier_percentage = 300.0
        self.min_amount = 0.01
        self.currency_precision = 2
    
    def validate(self, financial_data: Dict[str, Any]) -> ValidationResult:
        result = self._create_result()
        
        self._validate_basic_amounts(result, financial_data)
        self._validate_component_amounts(result, financial_data)
        self._validate_calculation_consistency(result, financial_data)
        self._validate_modifier_amounts(result, financial_data)
        self._validate_business_rules(result, financial_data)
        
        return result
    
    def _validate_basic_amounts(self, result: ValidationResult, data: Dict[str, Any]):
        amount_fields = [
            ('total_amount', 'Total Amount', self.max_claim_amount),
            ('approved_amount', 'Approved Amount', self.max_claim_amount),
            ('denied_amount', 'Denied Amount', self.max_claim_amount),
            ('pending_amount', 'Pending Amount', self.max_claim_amount)
        ]
        
        for field, display_name, max_value in amount_fields:
            if field in data and data[field] is not None:
                amount = data[field]
                
                if not self._validate_numeric_range(result, amount, field, 0.0, max_value):
                    continue
                
                decimal_amount = safe_decimal(amount)
                if not self._validate_decimal_precision(result, decimal_amount, field):
                    continue
                
                if decimal_amount < 0:
                    result.add_error(field, f'{display_name} cannot be negative',
                                   'NEGATIVE_AMOUNT', amount)
    
    def _validate_component_amounts(self, result: ValidationResult, data: Dict[str, Any]):
        component_fields = [
            ('gdrg_amount', 'G-DRG Amount', self.max_gdrg_amount),
            ('medicine_amount', 'Medicine Amount', self.max_medicine_amount),
            ('investigation_amount', 'Investigation Amount', self.max_investigation_amount),
            ('modifier_amount', 'Modifier Amount', self.max_claim_amount)
        ]
        
        component_total = Decimal('0')
        
        for field, display_name, max_value in component_fields:
            if field in data and data[field] is not None:
                amount = safe_decimal(data[field])
                
                if not self._validate_numeric_range(result, float(amount), field, 0.0, max_value):
                    continue
                
                if not self._validate_decimal_precision(result, amount, field):
                    continue
                
                component_total += amount
                
                if amount < 0:
                    result.add_error(field, f'{display_name} cannot be negative',
                                   'NEGATIVE_COMPONENT', float(amount))
        
        if 'total_amount' in data and data['total_amount'] is not None:
            declared_total = safe_decimal(data['total_amount'])
            tolerance = Decimal('0.01')
            
            if abs(component_total - declared_total) > tolerance:
                result.add_error('total_amount',
                               f'Total amount (GHS {declared_total}) does not match sum of components (GHS {component_total})',
                               'COMPONENT_TOTAL_MISMATCH')
    
    def _validate_calculation_consistency(self, result: ValidationResult, data: Dict[str, Any]):
        total_amount = safe_decimal(data.get('total_amount', 0))
        approved_amount = safe_decimal(data.get('approved_amount', 0))
        denied_amount = safe_decimal(data.get('denied_amount', 0))
        pending_amount = safe_decimal(data.get('pending_amount', 0))
        
        calculated_total = approved_amount + denied_amount + pending_amount
        tolerance = Decimal('0.01')
        
        if total_amount > 0 and abs(total_amount - calculated_total) > tolerance:
            result.add_error('financial_consistency',
                           f'Total amount (GHS {total_amount}) does not equal sum of approved + denied + pending (GHS {calculated_total})',
                           'TOTAL_BREAKDOWN_MISMATCH')
        
        if approved_amount > total_amount:
            result.add_error('approved_amount',
                           'Approved amount cannot exceed total amount',
                           'APPROVED_EXCEEDS_TOTAL')
        
        if denied_amount > total_amount:
            result.add_error('denied_amount',
                           'Denied amount cannot exceed total amount',
                           'DENIED_EXCEEDS_TOTAL')
        
        if pending_amount > total_amount:
            result.add_error('pending_amount',
                           'Pending amount cannot exceed total amount',
                           'PENDING_EXCEEDS_TOTAL')
    
    def _validate_modifier_amounts(self, result: ValidationResult, data: Dict[str, Any]):
        if 'modifier_calculations' in data and data['modifier_calculations']:
            modifier_calcs = data['modifier_calculations']
            
            if not isinstance(modifier_calcs, list):
                result.add_error('modifier_calculations',
                               'Modifier calculations must be a list',
                               'INVALID_TYPE')
                return
            
            total_modifier_amount = Decimal('0')
            
            for i, modifier in enumerate(modifier_calcs):
                if not isinstance(modifier, dict):
                    result.add_error(f'modifier_calculations[{i}]',
                                   'Modifier calculation must be a dictionary',
                                   'INVALID_TYPE')
                    continue
                
                if 'modifier_percentage' in modifier:
                    percentage = modifier['modifier_percentage']
                    if not self._validate_numeric_range(result, percentage,
                                                      f'modifier_calculations[{i}].modifier_percentage',
                                                      50.0, self.max_modifier_percentage):
                        continue
                
                if 'amount' in modifier:
                    modifier_amount = safe_decimal(modifier['amount'])
                    total_modifier_amount += modifier_amount
                    
                    if modifier_amount < 0:
                        result.add_warning(f'modifier_calculations[{i}].amount',
                                         'Negative modifier amount detected',
                                         'NEGATIVE_MODIFIER')
            
            declared_modifier_amount = safe_decimal(data.get('modifier_amount', 0))
            tolerance = Decimal('0.01')
            
            if abs(total_modifier_amount - declared_modifier_amount) > tolerance:
                result.add_error('modifier_amount',
                               f'Declared modifier amount (GHS {declared_modifier_amount}) does not match calculated total (GHS {total_modifier_amount})',
                               'MODIFIER_CALCULATION_MISMATCH')
    
    def _validate_business_rules(self, result: ValidationResult, data: Dict[str, Any]):
        total_amount = safe_decimal(data.get('total_amount', 0))
        gdrg_amount = safe_decimal(data.get('gdrg_amount', 0))
        medicine_amount = safe_decimal(data.get('medicine_amount', 0))
        
        if total_amount > 50000:
            result.add_warning('total_amount',
                             f'High value claim: GHS {total_amount}',
                             'HIGH_VALUE_CLAIM', float(total_amount))
        
        if gdrg_amount > 0 and medicine_amount > gdrg_amount * 2:
            result.add_warning('medicine_amount',
                             f'Medicine amount (GHS {medicine_amount}) is unusually high compared to G-DRG (GHS {gdrg_amount})',
                             'HIGH_MEDICINE_TO_GDRG_RATIO')
        
        if 'encounter_setting' in data:
            encounter = data['encounter_setting']
            
            if encounter == 'OPD' and total_amount > 5000:
                result.add_warning('total_amount',
                                 f'High OPD claim amount: GHS {total_amount}',
                                 'HIGH_OPD_AMOUNT', float(total_amount))
            
            elif encounter == 'A&E' and total_amount > 10000:
                result.add_warning('total_amount',
                                 f'High A&E claim amount: GHS {total_amount}',
                                 'HIGH_AE_AMOUNT', float(total_amount))
        
        approved_amount = safe_decimal(data.get('approved_amount', 0))
        approval_rate = (approved_amount / total_amount * 100) if total_amount > 0 else 0
        
        if approval_rate < 50:
            result.add_warning('approved_amount',
                             f'Low approval rate: {approval_rate:.1f}%',
                             'LOW_APPROVAL_RATE', approval_rate)
        
        if 'processing_time_seconds' in data:
            processing_time = data['processing_time_seconds']
            if processing_time > 30:
                result.add_warning('processing_time_seconds',
                                 f'Slow processing time: {processing_time:.2f} seconds',
                                 'SLOW_PROCESSING', processing_time)
    
    def _validate_decimal_precision(self, result: ValidationResult, amount: Decimal, field: str) -> bool:
        decimal_places = abs(amount.as_tuple().exponent)
        
        if decimal_places > self.currency_precision:
            result.add_error(field,
                           f'Amount has too many decimal places ({decimal_places}). Maximum allowed: {self.currency_precision}',
                           'EXCESSIVE_PRECISION', float(amount))
            return False
        
        return True
    
    def validate_claim_financial_data(self, claim_data: Dict[str, Any]) -> ValidationResult:
        result = self.validate(claim_data)
        
        if 'medicines' in claim_data and claim_data['medicines']:
            medicine_result = self._validate_medicine_financial_data(claim_data['medicines'])
            result.merge(medicine_result)
        
        if 'procedures' in claim_data and claim_data['procedures']:
            procedure_result = self._validate_procedure_financial_data(claim_data['procedures'])
            result.merge(procedure_result)
        
        if 'investigations' in claim_data and claim_data['investigations']:
            investigation_result = self._validate_investigation_financial_data(claim_data['investigations'])
            result.merge(investigation_result)
        
        return result
    
    def _validate_medicine_financial_data(self, medicines: List[Dict[str, Any]]) -> ValidationResult:
        result = self._create_result()
        
        for i, medicine in enumerate(medicines):
            if not isinstance(medicine, dict):
                continue
            
            if 'unit_price' in medicine:
                unit_price = safe_decimal(medicine['unit_price'])
                if unit_price <= 0:
                    result.add_error(f'medicines[{i}].unit_price',
                                   'Medicine unit price must be greater than zero',
                                   'INVALID_UNIT_PRICE', float(unit_price))
                elif unit_price > 1000:
                    result.add_warning(f'medicines[{i}].unit_price',
                                     f'High medicine unit price: GHS {unit_price}',
                                     'HIGH_UNIT_PRICE', float(unit_price))
            
            if 'quantity' in medicine and 'unit_price' in medicine:
                quantity = safe_decimal(medicine['quantity'])
                unit_price = safe_decimal(medicine['unit_price'])
                calculated_amount = quantity * unit_price
                
                if 'amount' in medicine:
                    declared_amount = safe_decimal(medicine['amount'])
                    tolerance = Decimal('0.01')
                    
                    if abs(calculated_amount - declared_amount) > tolerance:
                        result.add_error(f'medicines[{i}].amount',
                                       f'Medicine amount mismatch: calculated GHS {calculated_amount}, declared GHS {declared_amount}',
                                       'MEDICINE_AMOUNT_MISMATCH')
        
        return result
    
    def _validate_procedure_financial_data(self, procedures: List[Dict[str, Any]]) -> ValidationResult:
        result = self._create_result()
        
        for i, procedure in enumerate(procedures):
            if not isinstance(procedure, dict):
                continue
            
            if 'amount' in procedure:
                amount = safe_decimal(procedure['amount'])
                if amount <= 0:
                    result.add_error(f'procedures[{i}].amount',
                                   'Procedure amount must be greater than zero',
                                   'INVALID_PROCEDURE_AMOUNT', float(amount))
                elif amount > 20000:
                    result.add_warning(f'procedures[{i}].amount',
                                     f'High procedure amount: GHS {amount}',
                                     'HIGH_PROCEDURE_AMOUNT', float(amount))
        
        return result
    
    def _validate_investigation_financial_data(self, investigations: List[Dict[str, Any]]) -> ValidationResult:
        result = self._create_result()
        
        for i, investigation in enumerate(investigations):
            if not isinstance(investigation, dict):
                continue
            
            if 'amount' in investigation:
                amount = safe_decimal(investigation['amount'])
                if amount <= 0:
                    result.add_error(f'investigations[{i}].amount',
                                   'Investigation amount must be greater than zero',
                                   'INVALID_INVESTIGATION_AMOUNT', float(amount))
                elif amount > 5000:
                    result.add_warning(f'investigations[{i}].amount',
                                     f'High investigation amount: GHS {amount}',
                                     'HIGH_INVESTIGATION_AMOUNT', float(amount))
        
        return result
    
    def validate_batch_financial_summary(self, batch_data: Dict[str, Any]) -> ValidationResult:
        result = self._create_result()
        
        if 'total_approved_amount' in batch_data:
            self._validate_numeric_range(result, batch_data['total_approved_amount'],
                                       'total_approved_amount', 0.0, 10000000.0)
        
        if 'total_denied_amount' in batch_data:
            self._validate_numeric_range(result, batch_data['total_denied_amount'],
                                       'total_denied_amount', 0.0, 10000000.0)
        
        claims = batch_data.get('claims', [])
        if claims:
            calculated_approved = sum(safe_decimal(claim.get('approved_amount', 0)) for claim in claims)
            calculated_denied = sum(safe_decimal(claim.get('denied_amount', 0)) for claim in claims)
            
            declared_approved = safe_decimal(batch_data.get('total_approved_amount', 0))
            declared_denied = safe_decimal(batch_data.get('total_denied_amount', 0))
            
            tolerance = Decimal('0.01')
            
            if abs(calculated_approved - declared_approved) > tolerance:
                result.add_error('total_approved_amount',
                               f'Batch approved amount mismatch: calculated GHS {calculated_approved}, declared GHS {declared_approved}',
                               'BATCH_APPROVED_MISMATCH')
            
            if abs(calculated_denied - declared_denied) > tolerance:
                result.add_error('total_denied_amount',
                               f'Batch denied amount mismatch: calculated GHS {calculated_denied}, declared GHS {declared_denied}',
                               'BATCH_DENIED_MISMATCH')
        
        return result