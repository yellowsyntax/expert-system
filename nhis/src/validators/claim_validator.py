from typing import Dict, Any, List
from datetime import datetime, date
from .base_validator import BaseValidator, ValidationResult
from ..utils.constants import EncounterSetting, FacilityLevel, VALIDATION_PATTERNS
from ..utils.helpers import validate_icd10_code, validate_facility_id, calculate_age_in_years


class ClaimValidator(BaseValidator):
    
    def __init__(self):
        super().__init__()
        self.max_claim_amount = 100000.0
        self.max_medicine_items = 50
        self.max_procedure_items = 20
        self.max_investigation_items = 30
    
    def validate(self, claim_data: Dict[str, Any]) -> ValidationResult:
        result = self._create_result()
        
        self._validate_basic_fields(result, claim_data)
        self._validate_patient_data(result, claim_data)
        self._validate_facility_data(result, claim_data)
        self._validate_clinical_data(result, claim_data)
        self._validate_financial_data(result, claim_data)
        self._validate_service_items(result, claim_data)
        self._validate_business_logic(result, claim_data)
        
        return result
    
    def _validate_basic_fields(self, result: ValidationResult, data: Dict[str, Any]):
        required_fields = [
            ('claim_id', 'Claim ID'),
            ('facility_id', 'Facility ID'),
            ('patient_id', 'Patient ID'),
            ('service_date', 'Service Date'),
            ('encounter_setting', 'Encounter Setting')
        ]
        
        for field, display_name in required_fields:
            self._validate_required_field(result, data, field, display_name)
        
        if 'claim_id' in data:
            self._validate_pattern(result, data['claim_id'], 'claim_id', 
                                 VALIDATION_PATTERNS['claim_id'], 'be a valid claim ID format')
        
        if 'facility_id' in data:
            if not validate_facility_id(data['facility_id']):
                result.add_error('facility_id', 'Invalid facility ID format', 
                               'INVALID_FACILITY_ID_FORMAT', data['facility_id'])
        
        if 'patient_id' in data:
            self._validate_pattern(result, data['patient_id'], 'patient_id',
                                 VALIDATION_PATTERNS['patient_id'], 'be a valid patient ID format')
        
        if 'encounter_setting' in data:
            valid_settings = [setting.value for setting in EncounterSetting]
            self._validate_enum_value(result, data['encounter_setting'], 'encounter_setting', valid_settings)
    
    def _validate_patient_data(self, result: ValidationResult, data: Dict[str, Any]):
        if 'patient_birth_date' in data:
            birth_date = data['patient_birth_date']
            
            if isinstance(birth_date, str):
                if not self._validate_date_format(result, birth_date, 'patient_birth_date'):
                    return
                birth_date = datetime.strptime(birth_date, '%Y-%m-%d').date()
            
            if isinstance(birth_date, date):
                today = date.today()
                if birth_date > today:
                    result.add_error('patient_birth_date', 'Birth date cannot be in the future', 
                                   'FUTURE_BIRTH_DATE', birth_date)
                
                age = calculate_age_in_years(birth_date, today)
                if age > 150:
                    result.add_warning('patient_birth_date', f'Patient age ({age}) seems unusually high', 
                                     'HIGH_AGE', age)
        
        if 'nhis_number' in data and data['nhis_number']:
            self._validate_pattern(result, data['nhis_number'], 'nhis_number',
                                 VALIDATION_PATTERNS['nhis_number'], 'be a valid NHIS number format')
        
        if 'patient_gender' in data:
            self._validate_enum_value(result, data['patient_gender'], 'patient_gender', 
                                    ['M', 'F', 'Male', 'Female'], case_sensitive=False)
    
    def _validate_facility_data(self, result: ValidationResult, data: Dict[str, Any]):
        if 'facility_level' in data:
            valid_levels = [level.value for level in FacilityLevel]
            self._validate_enum_value(result, data['facility_level'], 'facility_level', valid_levels)
        
        if 'provider_id' in data and data['provider_id']:
            self._validate_pattern(result, data['provider_id'], 'provider_id',
                                 VALIDATION_PATTERNS['provider_id'], 'be a valid provider ID format')
    
    def _validate_clinical_data(self, result: ValidationResult, data: Dict[str, Any]):
        if 'primary_diagnosis' in data and data['primary_diagnosis']:
            if not validate_icd10_code(data['primary_diagnosis']):
                result.add_error('primary_diagnosis', 'Invalid ICD-10 diagnosis code format', 
                               'INVALID_ICD10_FORMAT', data['primary_diagnosis'])
        
        if 'secondary_diagnoses' in data and data['secondary_diagnoses']:
            if isinstance(data['secondary_diagnoses'], list):
                for i, diagnosis in enumerate(data['secondary_diagnoses']):
                    if not validate_icd10_code(diagnosis):
                        result.add_error(f'secondary_diagnoses[{i}]', 
                                       f'Invalid ICD-10 diagnosis code format: {diagnosis}',
                                       'INVALID_ICD10_FORMAT', diagnosis)
        
        if 'admission_date' in data and 'discharge_date' in data:
            admission = data['admission_date']
            discharge = data['discharge_date']
            
            if admission and discharge:
                if isinstance(admission, str):
                    admission = datetime.strptime(admission, '%Y-%m-%d').date()
                if isinstance(discharge, str):
                    discharge = datetime.strptime(discharge, '%Y-%m-%d').date()
                
                if discharge < admission:
                    result.add_error('discharge_date', 'Discharge date cannot be before admission date',
                                   'INVALID_DATE_SEQUENCE')
                
                length_of_stay = (discharge - admission).days
                if length_of_stay > 365:
                    result.add_warning('discharge_date', f'Very long length of stay: {length_of_stay} days',
                                     'LONG_STAY', length_of_stay)
    
    def _validate_financial_data(self, result: ValidationResult, data: Dict[str, Any]):
        if 'total_amount' in data:
            if not self._validate_numeric_range(result, data['total_amount'], 'total_amount', 0.01, self.max_claim_amount):
                return
            
            total_amount = float(data['total_amount'])
            if total_amount > 50000:
                result.add_warning('total_amount', f'High claim amount: GHS {total_amount:,.2f}',
                                 'HIGH_CLAIM_AMOUNT', total_amount)
        
        financial_fields = ['medicine_amount', 'investigation_amount', 'procedure_amount']
        for field in financial_fields:
            if field in data and data[field] is not None:
                self._validate_numeric_range(result, data[field], field, 0.0)
    
    def _validate_service_items(self, result: ValidationResult, data: Dict[str, Any]):
        if 'medicines' in data and data['medicines']:
            self._validate_medicines(result, data['medicines'])
        
        if 'procedures' in data and data['procedures']:
            self._validate_procedures(result, data['procedures'])
        
        if 'investigations' in data and data['investigations']:
            self._validate_investigations(result, data['investigations'])
    
    def _validate_medicines(self, result: ValidationResult, medicines: List[Dict[str, Any]]):
        if not self._validate_list_items(result, medicines, 'medicines', max_items=self.max_medicine_items):
            return
        
        for i, medicine in enumerate(medicines):
            if not isinstance(medicine, dict):
                result.add_error(f'medicines[{i}]', 'Medicine item must be an object', 'INVALID_TYPE')
                continue
            
            if 'code' not in medicine or not medicine['code']:
                result.add_error(f'medicines[{i}].code', 'Medicine code is required', 'REQUIRED_FIELD_MISSING')
            
            if 'quantity' in medicine:
                if not self._validate_numeric_range(result, medicine['quantity'], f'medicines[{i}].quantity', 0.01, 1000):
                    continue
            
            if 'days_supply' in medicine:
                if not self._validate_numeric_range(result, medicine['days_supply'], f'medicines[{i}].days_supply', 1, 90):
                    continue
    
    def _validate_procedures(self, result: ValidationResult, procedures: List[Dict[str, Any]]):
        if not self._validate_list_items(result, procedures, 'procedures', max_items=self.max_procedure_items):
            return
        
        for i, procedure in enumerate(procedures):
            if not isinstance(procedure, dict):
                result.add_error(f'procedures[{i}]', 'Procedure item must be an object', 'INVALID_TYPE')
                continue
            
            if 'code' not in procedure or not procedure['code']:
                result.add_error(f'procedures[{i}].code', 'Procedure code is required', 'REQUIRED_FIELD_MISSING')
            
            if 'code' in procedure and procedure['code']:
                if not self._validate_pattern(result, procedure['code'], f'procedures[{i}].code',
                                            VALIDATION_PATTERNS['procedure_code'], 'be a valid procedure code format'):
                    continue
    
    def _validate_investigations(self, result: ValidationResult, investigations: List[Dict[str, Any]]):
        if not self._validate_list_items(result, investigations, 'investigations', max_items=self.max_investigation_items):
            return
        
        for i, investigation in enumerate(investigations):
            if not isinstance(investigation, dict):
                result.add_error(f'investigations[{i}]', 'Investigation item must be an object', 'INVALID_TYPE')
                continue
            
            if 'code' not in investigation or not investigation['code']:
                result.add_error(f'investigations[{i}].code', 'Investigation code is required', 'REQUIRED_FIELD_MISSING')
    
    def _validate_business_logic(self, result: ValidationResult, data: Dict[str, Any]):
        encounter_setting = data.get('encounter_setting')
        
        if encounter_setting == 'IPD':
            if 'admission_date' not in data or not data['admission_date']:
                result.add_error('admission_date', 'Admission date is required for inpatient claims',
                               'REQUIRED_FOR_IPD')
            
            if 'discharge_date' not in data or not data['discharge_date']:
                result.add_warning('discharge_date', 'Discharge date is recommended for inpatient claims',
                                 'RECOMMENDED_FOR_IPD')
        
        elif encounter_setting == 'A&E':
            if 'emergency_classification' in data:
                valid_classifications = ['OPD_LIKE', 'DETENTION', 'ADMISSION']
                self._validate_enum_value(result, data['emergency_classification'], 
                                        'emergency_classification', valid_classifications)
        
        if 'total_amount' in data and 'medicines' in data and data['medicines']:
            total_amount = float(data['total_amount'])
            medicine_count = len(data['medicines'])
            
            if total_amount > 1000 and medicine_count == 0:
                result.add_warning('medicines', 'High-value claim with no medicines seems unusual',
                                 'UNUSUAL_PATTERN')
        
        service_date = data.get('service_date')
        if service_date:
            if isinstance(service_date, str):
                service_date = datetime.strptime(service_date, '%Y-%m-%d').date()
            
            today = date.today()
            if service_date > today:
                result.add_error('service_date', 'Service date cannot be in the future',
                               'FUTURE_SERVICE_DATE', service_date)
            
            days_ago = (today - service_date).days
            if days_ago > 365:
                result.add_warning('service_date', f'Service date is {days_ago} days old',
                                 'OLD_SERVICE_DATE', days_ago)
    
    def validate_claim_for_processing(self, claim_data: Dict[str, Any]) -> ValidationResult:
        result = self.validate(claim_data)
        
        processing_required_fields = [
            'primary_diagnosis',
            'total_amount'
        ]
        
        for field in processing_required_fields:
            if field not in claim_data or not claim_data[field]:
                result.add_error(field, f'{field} is required for claim processing',
                               'REQUIRED_FOR_PROCESSING')
        
        return result