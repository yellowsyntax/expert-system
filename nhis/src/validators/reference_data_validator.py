from typing import Dict, Any, List
from .base_validator import BaseValidator, ValidationResult
from ..utils.constants import REFERENCE_DATA_FILES
from ..utils.helpers import validate_icd10_code, validate_gdrg_code


class ReferenceDataValidator(BaseValidator):
    
    def __init__(self):
        super().__init__()
        self.file_validators = {
            'icd10_gdrg_mapping': self._validate_icd10_gdrg_mapping,
            'medicine_formulary': self._validate_medicine_formulary,
            'chronic_conditions': self._validate_chronic_conditions,
            'documentation_requirements': self._validate_documentation_requirements,
            'episode_limits': self._validate_episode_limits,
            'facility_credentialing': self._validate_facility_credentialing,
            'physiotherapy_conditions': self._validate_physiotherapy_conditions,
            'exclusions': self._validate_exclusions,
            'bundling_rules': self._validate_bundling_rules,
            'modifier_rules': self._validate_modifier_rules
        }
    
    def validate(self, file_key: str, data: Dict[str, Any]) -> ValidationResult:
        result = self._create_result()
        
        if file_key not in REFERENCE_DATA_FILES:
            result.add_error('file_key', f'Unknown reference data file key: {file_key}',
                           'UNKNOWN_FILE_KEY', file_key)
            return result
        
        self._validate_common_metadata(result, data)
        
        if file_key in self.file_validators:
            self.file_validators[file_key](result, data)
        else:
            result.add_warning('validation', f'No specific validator for {file_key}',
                             'NO_SPECIFIC_VALIDATOR')
        
        return result
    
    def _validate_common_metadata(self, result: ValidationResult, data: Dict[str, Any]):
        required_metadata = ['version', 'last_updated']
        
        for field in required_metadata:
            self._validate_required_field(result, data, field)
        
        if 'version' in data:
            self._validate_string_length(result, data['version'], 'version', min_length=1, max_length=20)
        
        if 'last_updated' in data:
            if not self._validate_date_format(result, data['last_updated'], 'last_updated', '%Y-%m-%dT%H:%M:%S'):
                self._validate_date_format(result, data['last_updated'], 'last_updated', '%Y-%m-%d')
    
    def _validate_icd10_gdrg_mapping(self, result: ValidationResult, data: Dict[str, Any]):
        if not self._validate_required_field(result, data, 'mappings'):
            return
        
        mappings = data['mappings']
        if not isinstance(mappings, dict):
            result.add_error('mappings', 'Mappings must be a dictionary', 'INVALID_TYPE')
            return
        
        for icd10_code, gdrg_codes in mappings.items():
            if not validate_icd10_code(icd10_code):
                result.add_error(f'mappings.{icd10_code}', f'Invalid ICD-10 code: {icd10_code}',
                               'INVALID_ICD10_CODE', icd10_code)
            
            if isinstance(gdrg_codes, str):
                gdrg_codes = [gdrg_codes]
            
            if isinstance(gdrg_codes, list):
                for gdrg_code in gdrg_codes:
                    if not validate_gdrg_code(gdrg_code):
                        result.add_error(f'mappings.{icd10_code}', f'Invalid G-DRG code: {gdrg_code}',
                                       'INVALID_GDRG_CODE', gdrg_code)
            else:
                result.add_error(f'mappings.{icd10_code}', 'G-DRG codes must be string or list',
                               'INVALID_GDRG_FORMAT')
    
    def _validate_medicine_formulary(self, result: ValidationResult, data: Dict[str, Any]):
        if not self._validate_required_field(result, data, 'medicines'):
            return
        
        medicines = data['medicines']
        if not isinstance(medicines, dict):
            result.add_error('medicines', 'Medicines must be a dictionary', 'INVALID_TYPE')
            return
        
        for med_code, med_info in medicines.items():
            if not isinstance(med_info, dict):
                result.add_error(f'medicines.{med_code}', 'Medicine info must be a dictionary',
                               'INVALID_TYPE')
                continue
            
            required_fields = ['name', 'unit_price']
            for field in required_fields:
                if field not in med_info:
                    result.add_error(f'medicines.{med_code}.{field}', f'{field} is required',
                                   'REQUIRED_FIELD_MISSING')
            
            if 'unit_price' in med_info:
                self._validate_numeric_range(result, med_info['unit_price'], 
                                           f'medicines.{med_code}.unit_price', 0.01, 10000)
            
            if 'strength' in med_info and med_info['strength']:
                self._validate_string_length(result, med_info['strength'], 
                                           f'medicines.{med_code}.strength', max_length=50)
    
    def _validate_chronic_conditions(self, result: ValidationResult, data: Dict[str, Any]):
        if not self._validate_required_field(result, data, 'conditions'):
            return
        
        conditions = data['conditions']
        if not isinstance(conditions, dict):
            result.add_error('conditions', 'Conditions must be a dictionary', 'INVALID_TYPE')
            return
        
        for condition_code, condition_info in conditions.items():
            if not validate_icd10_code(condition_code):
                result.add_error(f'conditions.{condition_code}', f'Invalid ICD-10 code: {condition_code}',
                               'INVALID_ICD10_CODE', condition_code)
            
            if isinstance(condition_info, dict):
                if 'description' not in condition_info:
                    result.add_error(f'conditions.{condition_code}.description', 'Description is required',
                                   'REQUIRED_FIELD_MISSING')
                
                if 'max_visits_per_year' in condition_info:
                    self._validate_numeric_range(result, condition_info['max_visits_per_year'],
                                               f'conditions.{condition_code}.max_visits_per_year', 1, 365)
    
    def _validate_documentation_requirements(self, result: ValidationResult, data: Dict[str, Any]):
        expected_sections = ['icd10_coherence', 'preauthorization', 'specialty_documentation', 'endoscopy_documentation']
        
        for section in expected_sections:
            if section not in data:
                result.add_warning(section, f'Missing documentation section: {section}',
                                 'MISSING_SECTION')
        
        if 'preauthorization' in data:
            preauth = data['preauthorization']
            if isinstance(preauth, dict):
                if 'required_procedures' in preauth:
                    self._validate_list_items(result, preauth['required_procedures'], 
                                            'preauthorization.required_procedures')
                
                if 'high_cost_threshold' in preauth:
                    self._validate_numeric_range(result, preauth['high_cost_threshold'],
                                               'preauthorization.high_cost_threshold', 100, 100000)
    
    def _validate_episode_limits(self, result: ValidationResult, data: Dict[str, Any]):
        expected_episode_types = ['acute', 'chronic', 'antenatal', 'postnatal']
        
        for episode_type in expected_episode_types:
            if episode_type not in data:
                result.add_error(episode_type, f'Missing episode limit for: {episode_type}',
                               'MISSING_EPISODE_LIMIT')
                continue
            
            episode_limit = data[episode_type]
            if not isinstance(episode_limit, dict):
                result.add_error(episode_type, f'Episode limit must be a dictionary',
                               'INVALID_TYPE')
                continue
            
            required_fields = ['visits', 'days']
            for field in required_fields:
                if field not in episode_limit:
                    result.add_error(f'{episode_type}.{field}', f'{field} is required',
                                   'REQUIRED_FIELD_MISSING')
                else:
                    self._validate_numeric_range(result, episode_limit[field],
                                               f'{episode_type}.{field}', 1, 1000)
    
    def _validate_facility_credentialing(self, result: ValidationResult, data: Dict[str, Any]):
        if not self._validate_required_field(result, data, 'facility_levels'):
            return
        
        facility_levels = data['facility_levels']
        if not isinstance(facility_levels, dict):
            result.add_error('facility_levels', 'Facility levels must be a dictionary', 'INVALID_TYPE')
            return
        
        for level, level_info in facility_levels.items():
            if not isinstance(level_info, dict):
                result.add_error(f'facility_levels.{level}', 'Level info must be a dictionary',
                               'INVALID_TYPE')
                continue
            
            if 'authorized_procedures' in level_info:
                if not isinstance(level_info['authorized_procedures'], list):
                    result.add_error(f'facility_levels.{level}.authorized_procedures',
                                   'Authorized procedures must be a list', 'INVALID_TYPE')
    
    def _validate_physiotherapy_conditions(self, result: ValidationResult, data: Dict[str, Any]):
        if not self._validate_required_field(result, data, 'eligible_conditions'):
            return
        
        conditions = data['eligible_conditions']
        if not isinstance(conditions, dict):
            result.add_error('eligible_conditions', 'Eligible conditions must be a dictionary',
                           'INVALID_TYPE')
            return
        
        for condition_code, condition_info in conditions.items():
            if not validate_icd10_code(condition_code):
                result.add_error(f'eligible_conditions.{condition_code}',
                               f'Invalid ICD-10 code: {condition_code}',
                               'INVALID_ICD10_CODE', condition_code)
            
            if isinstance(condition_info, dict):
                if 'max_sessions' in condition_info:
                    self._validate_numeric_range(result, condition_info['max_sessions'],
                                               f'eligible_conditions.{condition_code}.max_sessions', 1, 100)
    
    def _validate_exclusions(self, result: ValidationResult, data: Dict[str, Any]):
        if not self._validate_required_field(result, data, 'excluded_services'):
            return
        
        excluded_services = data['excluded_services']
        if not isinstance(excluded_services, list):
            result.add_error('excluded_services', 'Excluded services must be a list', 'INVALID_TYPE')
            return
        
        for i, service in enumerate(excluded_services):
            if not isinstance(service, dict):
                result.add_error(f'excluded_services[{i}]', 'Service must be a dictionary',
                               'INVALID_TYPE')
                continue
            
            required_fields = ['code', 'reason']
            for field in required_fields:
                if field not in service:
                    result.add_error(f'excluded_services[{i}].{field}', f'{field} is required',
                                   'REQUIRED_FIELD_MISSING')
    
    def _validate_bundling_rules(self, result: ValidationResult, data: Dict[str, Any]):
        required_sections = ['bundled_investigations', 'separately_billable', 'bundling_settings']
        
        for section in required_sections:
            if not self._validate_required_field(result, data, section):
                continue
            
            section_data = data[section]
            
            if section == 'bundling_settings':
                if not isinstance(section_data, dict):
                    result.add_error(section, f'{section} must be a dictionary', 'INVALID_TYPE')
                    continue
                
                valid_settings = ['bundled', 'unbundled']
                for setting_key, setting_value in section_data.items():
                    self._validate_enum_value(result, setting_value, f'{section}.{setting_key}',
                                            valid_settings)
            else:
                if not isinstance(section_data, dict):
                    result.add_error(section, f'{section} must be a dictionary', 'INVALID_TYPE')
    
    def _validate_modifier_rules(self, result: ValidationResult, data: Dict[str, Any]):
        expected_modifiers = ['bilateral_surgery', 'dental_multi_tooth', 'emergency_modifiers']
        
        for modifier_type in expected_modifiers:
            if modifier_type not in data:
                result.add_warning(modifier_type, f'Missing modifier rules for: {modifier_type}',
                                 'MISSING_MODIFIER_RULES')
                continue
            
            modifier_data = data[modifier_type]
            if not isinstance(modifier_data, dict):
                result.add_error(modifier_type, f'{modifier_type} must be a dictionary',
                               'INVALID_TYPE')
                continue
            
            if modifier_type == 'bilateral_surgery':
                if 'modifier_percentage' in modifier_data:
                    self._validate_numeric_range(result, modifier_data['modifier_percentage'],
                                               f'{modifier_type}.modifier_percentage', 100, 200)
            
            elif modifier_type == 'dental_multi_tooth':
                if 'modifier_tiers' in modifier_data:
                    if not isinstance(modifier_data['modifier_tiers'], list):
                        result.add_error(f'{modifier_type}.modifier_tiers',
                                       'Modifier tiers must be a list', 'INVALID_TYPE')
    
    def validate_all_reference_files(self, reference_data: Dict[str, Dict[str, Any]]) -> Dict[str, ValidationResult]:
        results = {}
        
        for file_key in REFERENCE_DATA_FILES.keys():
            if file_key in reference_data:
                results[file_key] = self.validate(file_key, reference_data[file_key])
            else:
                result = self._create_result()
                result.add_error('file', f'Reference file {file_key} is missing',
                               'MISSING_REFERENCE_FILE')
                results[file_key] = result
        
        return results
    
    def get_validation_summary(self, validation_results: Dict[str, ValidationResult]) -> Dict[str, Any]:
        total_files = len(validation_results)
        valid_files = sum(1 for result in validation_results.values() if result.is_valid)
        invalid_files = total_files - valid_files
        
        total_errors = sum(len(result.errors) for result in validation_results.values())
        total_warnings = sum(len(result.warnings) for result in validation_results.values())
        
        return {
            'total_files': total_files,
            'valid_files': valid_files,
            'invalid_files': invalid_files,
            'validation_rate': (valid_files / total_files * 100) if total_files > 0 else 0,
            'total_errors': total_errors,
            'total_warnings': total_warnings,
            'files_with_errors': [file_key for file_key, result in validation_results.items() if result.has_errors],
            'files_with_warnings': [file_key for file_key, result in validation_results.items() if result.has_warnings]
        }