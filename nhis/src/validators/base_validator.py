from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional
from dataclasses import dataclass
from enum import Enum


class ValidationSeverity(Enum):
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


@dataclass
class ValidationError:
    field: str
    message: str
    severity: ValidationSeverity
    code: Optional[str] = None
    value: Optional[Any] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'field': self.field,
            'message': self.message,
            'severity': self.severity.value,
            'code': self.code,
            'value': self.value
        }


@dataclass
class ValidationResult:
    is_valid: bool
    errors: List[ValidationError]
    warnings: List[ValidationError]
    info: List[ValidationError]
    
    def __post_init__(self):
        if self.errors is None:
            self.errors = []
        if self.warnings is None:
            self.warnings = []
        if self.info is None:
            self.info = []
    
    @property
    def has_errors(self) -> bool:
        return len(self.errors) > 0
    
    @property
    def has_warnings(self) -> bool:
        return len(self.warnings) > 0
    
    @property
    def total_issues(self) -> int:
        return len(self.errors) + len(self.warnings) + len(self.info)
    
    def add_error(self, field: str, message: str, code: str = None, value: Any = None):
        self.errors.append(ValidationError(field, message, ValidationSeverity.ERROR, code, value))
        self.is_valid = False
    
    def add_warning(self, field: str, message: str, code: str = None, value: Any = None):
        self.warnings.append(ValidationError(field, message, ValidationSeverity.WARNING, code, value))
    
    def add_info(self, field: str, message: str, code: str = None, value: Any = None):
        self.info.append(ValidationError(field, message, ValidationSeverity.INFO, code, value))
    
    def merge(self, other: 'ValidationResult'):
        self.errors.extend(other.errors)
        self.warnings.extend(other.warnings)
        self.info.extend(other.info)
        
        if other.has_errors:
            self.is_valid = False
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'is_valid': self.is_valid,
            'has_errors': self.has_errors,
            'has_warnings': self.has_warnings,
            'total_issues': self.total_issues,
            'errors': [error.to_dict() for error in self.errors],
            'warnings': [warning.to_dict() for warning in self.warnings],
            'info': [info.to_dict() for info in self.info]
        }


class BaseValidator(ABC):
    
    def __init__(self):
        self.validator_name = self.__class__.__name__
    
    @abstractmethod
    def validate(self, data: Any) -> ValidationResult:
        pass
    
    def _create_result(self) -> ValidationResult:
        return ValidationResult(is_valid=True, errors=[], warnings=[], info=[])
    
    def _validate_required_field(self, result: ValidationResult, data: Dict[str, Any], 
                                field_name: str, field_display_name: str = None):
        display_name = field_display_name or field_name
        
        if field_name not in data:
            result.add_error(field_name, f"{display_name} is required", "REQUIRED_FIELD_MISSING")
            return False
        
        value = data[field_name]
        if value is None or (isinstance(value, str) and not value.strip()):
            result.add_error(field_name, f"{display_name} cannot be empty", "REQUIRED_FIELD_EMPTY", value)
            return False
        
        return True
    
    def _validate_string_length(self, result: ValidationResult, value: str, field_name: str,
                               min_length: int = None, max_length: int = None):
        if not isinstance(value, str):
            result.add_error(field_name, f"{field_name} must be a string", "INVALID_TYPE", value)
            return False
        
        length = len(value.strip())
        
        if min_length is not None and length < min_length:
            result.add_error(field_name, f"{field_name} must be at least {min_length} characters", 
                           "STRING_TOO_SHORT", value)
            return False
        
        if max_length is not None and length > max_length:
            result.add_error(field_name, f"{field_name} must be at most {max_length} characters", 
                           "STRING_TOO_LONG", value)
            return False
        
        return True
    
    def _validate_numeric_range(self, result: ValidationResult, value: Any, field_name: str,
                               min_value: float = None, max_value: float = None):
        try:
            numeric_value = float(value)
        except (ValueError, TypeError):
            result.add_error(field_name, f"{field_name} must be a valid number", "INVALID_NUMBER", value)
            return False
        
        if min_value is not None and numeric_value < min_value:
            result.add_error(field_name, f"{field_name} must be at least {min_value}", 
                           "NUMBER_TOO_SMALL", value)
            return False
        
        if max_value is not None and numeric_value > max_value:
            result.add_error(field_name, f"{field_name} must be at most {max_value}", 
                           "NUMBER_TOO_LARGE", value)
            return False
        
        return True
    
    def _validate_pattern(self, result: ValidationResult, value: str, field_name: str, 
                         pattern: str, pattern_description: str = None):
        import re
        
        if not isinstance(value, str):
            result.add_error(field_name, f"{field_name} must be a string", "INVALID_TYPE", value)
            return False
        
        if not re.match(pattern, value):
            description = pattern_description or f"match pattern {pattern}"
            result.add_error(field_name, f"{field_name} must {description}", "PATTERN_MISMATCH", value)
            return False
        
        return True
    
    def _validate_enum_value(self, result: ValidationResult, value: Any, field_name: str, 
                           valid_values: List[Any], case_sensitive: bool = True):
        if not case_sensitive and isinstance(value, str):
            value = value.lower()
            valid_values = [str(v).lower() for v in valid_values]
        
        if value not in valid_values:
            result.add_error(field_name, f"{field_name} must be one of: {', '.join(map(str, valid_values))}", 
                           "INVALID_ENUM_VALUE", value)
            return False
        
        return True
    
    def _validate_date_format(self, result: ValidationResult, value: Any, field_name: str, 
                             date_format: str = "%Y-%m-%d"):
        from datetime import datetime
        
        if not isinstance(value, str):
            result.add_error(field_name, f"{field_name} must be a date string", "INVALID_DATE_TYPE", value)
            return False
        
        try:
            datetime.strptime(value, date_format)
            return True
        except ValueError:
            result.add_error(field_name, f"{field_name} must be in format {date_format}", 
                           "INVALID_DATE_FORMAT", value)
            return False
    
    def _validate_list_items(self, result: ValidationResult, value: Any, field_name: str,
                           item_validator: callable = None, min_items: int = None, max_items: int = None):
        if not isinstance(value, list):
            result.add_error(field_name, f"{field_name} must be a list", "INVALID_TYPE", value)
            return False
        
        if min_items is not None and len(value) < min_items:
            result.add_error(field_name, f"{field_name} must have at least {min_items} items", 
                           "LIST_TOO_SHORT", value)
            return False
        
        if max_items is not None and len(value) > max_items:
            result.add_error(field_name, f"{field_name} must have at most {max_items} items", 
                           "LIST_TOO_LONG", value)
            return False
        
        if item_validator:
            for i, item in enumerate(value):
                item_result = item_validator(item)
                if isinstance(item_result, ValidationResult):
                    for error in item_result.errors:
                        result.add_error(f"{field_name}[{i}].{error.field}", error.message, error.code, error.value)
                    for warning in item_result.warnings:
                        result.add_warning(f"{field_name}[{i}].{warning.field}", warning.message, warning.code, warning.value)
        
        return True
    
    def _validate_conditional_field(self, result: ValidationResult, data: Dict[str, Any],
                                   field_name: str, condition_field: str, condition_value: Any,
                                   required_when_true: bool = True):
        condition_met = data.get(condition_field) == condition_value
        
        if condition_met and required_when_true:
            return self._validate_required_field(result, data, field_name)
        elif not condition_met and not required_when_true:
            return self._validate_required_field(result, data, field_name)
        
        return True