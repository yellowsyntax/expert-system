from typing import Dict, Any, List
from datetime import datetime, date
from .base_validator import BaseValidator, ValidationResult
from .claim_validator import ClaimValidator
from ..utils.constants import BatchStatus, VALIDATION_PATTERNS, SYSTEM_LIMITS
from ..utils.helpers import validate_batch_id, validate_facility_id


class BatchValidator(BaseValidator):
    
    def __init__(self):
        super().__init__()
        self.claim_validator = ClaimValidator()
        self.max_batch_size = SYSTEM_LIMITS['max_batch_size']
        self.min_batch_size = 1
    
    def validate(self, batch_data: Dict[str, Any]) -> ValidationResult:
        result = self._create_result()
        
        self._validate_basic_fields(result, batch_data)
        self._validate_batch_metadata(result, batch_data)
        self._validate_batch_claims(result, batch_data)
        self._validate_batch_totals(result, batch_data)
        self._validate_batch_business_rules(result, batch_data)
        
        return result
    
    def _validate_basic_fields(self, result: ValidationResult, data: Dict[str, Any]):
        required_fields = [
            ('batch_id', 'Batch ID'),
            ('facility_id', 'Facility ID'),
            ('submission_date', 'Submission Date'),
            ('claims', 'Claims')
        ]
        
        for field, display_name in required_fields:
            self._validate_required_field(result, data, field, display_name)
        
        if 'batch_id' in data:
            if not validate_batch_id(data['batch_id']):
                result.add_error('batch_id', 'Invalid batch ID format', 
                               'INVALID_BATCH_ID_FORMAT', data['batch_id'])
        
        if 'facility_id' in data:
            if not validate_facility_id(data['facility_id']):
                result.add_error('facility_id', 'Invalid facility ID format', 
                               'INVALID_FACILITY_ID_FORMAT', data['facility_id'])
        
        if 'status' in data:
            valid_statuses = [status.value for status in BatchStatus]
            self._validate_enum_value(result, data['status'], 'status', valid_statuses)
    
    def _validate_batch_metadata(self, result: ValidationResult, data: Dict[str, Any]):
        if 'submission_date' in data:
            submission_date = data['submission_date']
            
            if isinstance(submission_date, str):
                if not self._validate_date_format(result, submission_date, 'submission_date'):
                    return
                submission_date = datetime.strptime(submission_date, '%Y-%m-%d').date()
            
            if isinstance(submission_date, date):
                today = date.today()
                if submission_date > today:
                    result.add_error('submission_date', 'Submission date cannot be in the future',
                                   'FUTURE_SUBMISSION_DATE', submission_date)
                
                days_ago = (today - submission_date).days
                if days_ago > 90:
                    result.add_warning('submission_date', f'Batch submission is {days_ago} days old',
                                     'OLD_SUBMISSION', days_ago)
        
        if 'processing_month' in data:
            processing_month = data['processing_month']
            if isinstance(processing_month, str):
                if not self._validate_pattern(result, processing_month, 'processing_month',
                                            r'^\d{4}-\d{2}$', 'be in YYYY-MM format'):
                    return
                
                try:
                    year, month = map(int, processing_month.split('-'))
                    if month < 1 or month > 12:
                        result.add_error('processing_month', 'Invalid month in processing_month',
                                       'INVALID_MONTH', processing_month)
                    
                    if year < 2020 or year > 2030:
                        result.add_warning('processing_month', f'Unusual year in processing_month: {year}',
                                         'UNUSUAL_YEAR', year)
                except ValueError:
                    result.add_error('processing_month', 'Invalid processing_month format',
                                   'INVALID_FORMAT', processing_month)
        
        if 'submission_reference' in data and data['submission_reference']:
            self._validate_string_length(result, data['submission_reference'], 'submission_reference',
                                       min_length=5, max_length=50)
    
    def _validate_batch_claims(self, result: ValidationResult, data: Dict[str, Any]):
        claims = data.get('claims', [])
        
        if not isinstance(claims, list):
            result.add_error('claims', 'Claims must be a list', 'INVALID_TYPE', type(claims).__name__)
            return
        
        claim_count = len(claims)
        
        if claim_count < self.min_batch_size:
            result.add_error('claims', f'Batch must contain at least {self.min_batch_size} claim(s)',
                           'BATCH_TOO_SMALL', claim_count)
        
        if claim_count > self.max_batch_size:
            result.add_error('claims', f'Batch cannot contain more than {self.max_batch_size} claims',
                           'BATCH_TOO_LARGE', claim_count)
        
        claim_ids = set()
        patient_visit_combinations = set()
        
        for i, claim in enumerate(claims):
            if not isinstance(claim, dict):
                result.add_error(f'claims[{i}]', 'Claim must be an object', 'INVALID_TYPE')
                continue
            
            claim_result = self.claim_validator.validate(claim)
            
            for error in claim_result.errors:
                result.add_error(f'claims[{i}].{error.field}', error.message, error.code, error.value)
            
            for warning in claim_result.warnings:
                result.add_warning(f'claims[{i}].{warning.field}', warning.message, warning.code, warning.value)
            
            claim_id = claim.get('claim_id')
            if claim_id:
                if claim_id in claim_ids:
                    result.add_error(f'claims[{i}].claim_id', f'Duplicate claim ID in batch: {claim_id}',
                                   'DUPLICATE_CLAIM_ID', claim_id)
                else:
                    claim_ids.add(claim_id)
            
            patient_id = claim.get('patient_id')
            service_date = claim.get('service_date')
            encounter_setting = claim.get('encounter_setting')
            
            if patient_id and service_date and encounter_setting:
                visit_key = f"{patient_id}_{service_date}_{encounter_setting}"
                if visit_key in patient_visit_combinations:
                    result.add_warning(f'claims[{i}]', 
                                      f'Potential duplicate visit: Patient {patient_id} on {service_date} in {encounter_setting}',
                                      'POTENTIAL_DUPLICATE_VISIT', visit_key)
                else:
                    patient_visit_combinations.add(visit_key)
    
    def _validate_batch_totals(self, result: ValidationResult, data: Dict[str, Any]):
        claims = data.get('claims', [])
        
        if not claims:
            return
        
        declared_total_claims = data.get('total_claims')
        declared_total_amount = data.get('total_amount')
        
        actual_claim_count = len(claims)
        actual_total_amount = 0.0
        
        for claim in claims:
            if isinstance(claim, dict) and 'total_amount' in claim:
                try:
                    claim_amount = float(claim['total_amount'])
                    actual_total_amount += claim_amount
                except (ValueError, TypeError):
                    pass
        
        if declared_total_claims is not None:
            if declared_total_claims != actual_claim_count:
                result.add_error('total_claims', 
                               f'Declared total claims ({declared_total_claims}) does not match actual count ({actual_claim_count})',
                               'CLAIM_COUNT_MISMATCH')
        
        if declared_total_amount is not None:
            tolerance = 0.01
            amount_difference = abs(declared_total_amount - actual_total_amount)
            
            if amount_difference > tolerance:
                result.add_error('total_amount',
                               f'Declared total amount (GHS {declared_total_amount:.2f}) does not match calculated total (GHS {actual_total_amount:.2f})',
                               'AMOUNT_MISMATCH')
    
    def _validate_batch_business_rules(self, result: ValidationResult, data: Dict[str, Any]):
        claims = data.get('claims', [])
        facility_id = data.get('facility_id')
        
        if not claims:
            return
        
        facility_ids_in_claims = set()
        service_dates = []
        total_amount = 0.0
        
        for claim in claims:
            if isinstance(claim, dict):
                claim_facility_id = claim.get('facility_id')
                if claim_facility_id:
                    facility_ids_in_claims.add(claim_facility_id)
                    
                    if facility_id and claim_facility_id != facility_id:
                        result.add_error('claims', 
                                       f'Claim facility ID ({claim_facility_id}) does not match batch facility ID ({facility_id})',
                                       'FACILITY_MISMATCH')
                
                service_date = claim.get('service_date')
                if service_date:
                    if isinstance(service_date, str):
                        try:
                            service_date = datetime.strptime(service_date, '%Y-%m-%d').date()
                        except ValueError:
                            continue
                    service_dates.append(service_date)
                
                claim_amount = claim.get('total_amount')
                if claim_amount:
                    try:
                        total_amount += float(claim_amount)
                    except (ValueError, TypeError):
                        pass
        
        if len(facility_ids_in_claims) > 1:
            result.add_error('claims', 
                           f'Batch contains claims from multiple facilities: {", ".join(facility_ids_in_claims)}',
                           'MULTIPLE_FACILITIES')
        
        if service_dates:
            min_date = min(service_dates)
            max_date = max(service_dates)
            date_span = (max_date - min_date).days
            
            if date_span > 31:
                result.add_warning('claims', 
                                 f'Batch spans {date_span} days ({min_date} to {max_date})',
                                 'WIDE_DATE_RANGE')
        
        if total_amount > 1000000:
            result.add_warning('claims', 
                             f'Very high batch total amount: GHS {total_amount:,.2f}',
                             'HIGH_BATCH_AMOUNT', total_amount)
        
        processing_month = data.get('processing_month')
        if processing_month and service_dates:
            try:
                year, month = map(int, processing_month.split('-'))
                processing_year_month = (year, month)
                
                for service_date in service_dates:
                    service_year_month = (service_date.year, service_date.month)
                    
                    if service_year_month != processing_year_month:
                        result.add_warning('claims',
                                         f'Service date {service_date} not in processing month {processing_month}',
                                         'SERVICE_DATE_MONTH_MISMATCH')
                        break
            except (ValueError, AttributeError):
                pass
    
    def validate_for_submission(self, batch_data: Dict[str, Any]) -> ValidationResult:
        result = self.validate(batch_data)
        
        submission_required_fields = [
            'submission_reference',
            'processing_month',
            'total_claims',
            'total_amount'
        ]
        
        for field in submission_required_fields:
            if field not in batch_data or batch_data[field] is None:
                result.add_error(field, f'{field} is required for batch submission',
                               'REQUIRED_FOR_SUBMISSION')
        
        if 'status' in batch_data and batch_data['status'] not in ['submitted', 'processing']:
            result.add_error('status', 'Batch must be in submitted or processing status for submission',
                           'INVALID_STATUS_FOR_SUBMISSION')
        
        return result
    
    def validate_claims_only(self, claims: List[Dict[str, Any]]) -> ValidationResult:
        result = self._create_result()
        
        if not isinstance(claims, list):
            result.add_error('claims', 'Claims must be a list', 'INVALID_TYPE')
            return result
        
        for i, claim in enumerate(claims):
            if not isinstance(claim, dict):
                result.add_error(f'claims[{i}]', 'Claim must be an object', 'INVALID_TYPE')
                continue
            
            claim_result = self.claim_validator.validate_claim_for_processing(claim)
            
            for error in claim_result.errors:
                result.add_error(f'claims[{i}].{error.field}', error.message, error.code, error.value)
            
            for warning in claim_result.warnings:
                result.add_warning(f'claims[{i}].{warning.field}', warning.message, warning.code, warning.value)
        
        return result