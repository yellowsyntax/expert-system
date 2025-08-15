import re
import hashlib
from datetime import datetime, date, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any, Optional, Dict, List, Union
from .constants import VALIDATION_PATTERNS


def validate_claim_id(claim_id: str) -> bool:
    if not claim_id:
        return False
    return bool(re.match(VALIDATION_PATTERNS["claim_id"], claim_id))


def validate_batch_id(batch_id: str) -> bool:
    if not batch_id:
        return False
    return bool(re.match(VALIDATION_PATTERNS["batch_id"], batch_id))


def validate_facility_id(facility_id: str) -> bool:
    if not facility_id:
        return False
    return bool(re.match(VALIDATION_PATTERNS["facility_id"], facility_id))


def validate_nhis_number(nhis_number: str) -> bool:
    if not nhis_number:
        return False
    return bool(re.match(VALIDATION_PATTERNS["nhis_number"], nhis_number))


def validate_icd10_code(icd10_code: str) -> bool:
    if not icd10_code:
        return False
    return bool(re.match(VALIDATION_PATTERNS["icd10_code"], icd10_code))


def validate_gdrg_code(gdrg_code: str) -> bool:
    if not gdrg_code:
        return False
    return bool(re.match(VALIDATION_PATTERNS["gdrg_code"], gdrg_code))


def safe_decimal(value: Any) -> Decimal:
    if value is None:
        return Decimal('0')
    
    if isinstance(value, Decimal):
        return value
    
    if isinstance(value, (int, float)):
        return Decimal(str(value))
    
    if isinstance(value, str):
        try:
            return Decimal(value.strip())
        except (InvalidOperation, ValueError):
            return Decimal('0')
    
    return Decimal('0')


def safe_int(value: Any, default: int = 0) -> int:
    if value is None:
        return default
    
    if isinstance(value, int):
        return value
    
    if isinstance(value, (float, Decimal)):
        return int(value)
    
    if isinstance(value, str):
        try:
            return int(float(value.strip()))
        except (ValueError, TypeError):
            return default
    
    return default


def safe_float(value: Any, default: float = 0.0) -> float:
    if value is None:
        return default
    
    if isinstance(value, float):
        return value
    
    if isinstance(value, (int, Decimal)):
        return float(value)
    
    if isinstance(value, str):
        try:
            return float(value.strip())
        except (ValueError, TypeError):
            return default
    
    return default


def safe_str(value: Any, default: str = "") -> str:
    if value is None:
        return default
    
    if isinstance(value, str):
        return value.strip()
    
    return str(value)


def calculate_age_in_years(birth_date: date, reference_date: date = None) -> int:
    if not birth_date:
        return 0
    
    if reference_date is None:
        reference_date = date.today()
    
    age = reference_date.year - birth_date.year
    
    if reference_date.month < birth_date.month or (
        reference_date.month == birth_date.month and reference_date.day < birth_date.day
    ):
        age -= 1
    
    return max(0, age)


def calculate_days_between(start_date: date, end_date: date) -> int:
    if not start_date or not end_date:
        return 0
    
    delta = end_date - start_date
    return delta.days


def format_currency(amount: Union[Decimal, float, int], currency: str = "GHS") -> str:
    decimal_amount = safe_decimal(amount)
    return f"{currency} {decimal_amount:,.2f}"


def format_percentage(value: Union[Decimal, float, int], decimal_places: int = 1) -> str:
    percentage = safe_float(value)
    return f"{percentage:.{decimal_places}f}%"


def generate_hash(data: str) -> str:
    return hashlib.sha256(data.encode('utf-8')).hexdigest()


def generate_claim_hash(claim_data: Dict[str, Any]) -> str:
    hash_components = [
        str(claim_data.get('facility_id', '')),
        str(claim_data.get('patient_id', '')),
        str(claim_data.get('service_date', '')),
        str(claim_data.get('primary_diagnosis', '')),
        str(claim_data.get('total_amount', ''))
    ]
    
    hash_string = '|'.join(hash_components)
    return generate_hash(hash_string)


def clean_string(text: str) -> str:
    if not text:
        return ""
    
    cleaned = re.sub(r'[^\w\s-.]', '', text)
    cleaned = ' '.join(cleaned.split())
    
    return cleaned.strip()


def normalize_diagnosis_code(icd10_code: str) -> str:
    if not icd10_code:
        return ""
    
    code = icd10_code.upper().strip()
    
    if not re.match(r'^[A-Z]\d{2}', code):
        return ""
    
    if '.' not in code and len(code) > 3:
        code = code[:3] + '.' + code[3:]
    
    return code


def extract_numbers(text: str) -> List[int]:
    if not text:
        return []
    
    numbers = re.findall(r'\d+', text)
    return [int(num) for num in numbers]


def is_weekend(check_date: date) -> bool:
    return check_date.weekday() >= 5


def is_after_hours(check_time: datetime, after_hours_start: str = "18:00", after_hours_end: str = "08:00") -> bool:
    time_only = check_time.time()
    
    try:
        start_time = datetime.strptime(after_hours_start, '%H:%M').time()
        end_time = datetime.strptime(after_hours_end, '%H:%M').time()
    except ValueError:
        return False
    
    if start_time > end_time:
        return time_only >= start_time or time_only <= end_time
    else:
        return start_time <= time_only <= end_time


def get_financial_year(reference_date: date = None) -> str:
    if reference_date is None:
        reference_date = date.today()
    
    if reference_date.month >= 4:
        start_year = reference_date.year
        end_year = reference_date.year + 1
    else:
        start_year = reference_date.year - 1
        end_year = reference_date.year
    
    return f"{start_year}-{end_year}"


def chunk_list(data: List[Any], chunk_size: int) -> List[List[Any]]:
    chunks = []
    for i in range(0, len(data), chunk_size):
        chunks.append(data[i:i + chunk_size])
    return chunks


def flatten_dict(d: Dict[str, Any], parent_key: str = '', sep: str = '.') -> Dict[str, Any]:
    items = []
    for k, v in d.items():
        new_key = f"{parent_key}{sep}{k}" if parent_key else k
        if isinstance(v, dict):
            items.extend(flatten_dict(v, new_key, sep=sep).items())
        else:
            items.append((new_key, v))
    return dict(items)


def mask_sensitive_data(data: str, mask_char: str = '*', visible_chars: int = 4) -> str:
    if not data or len(data) <= visible_chars:
        return data
    
    visible_start = visible_chars // 2
    visible_end = visible_chars - visible_start
    
    if visible_end == 0:
        return data[:visible_start] + mask_char * (len(data) - visible_start)
    else:
        return data[:visible_start] + mask_char * (len(data) - visible_chars) + data[-visible_end:]


def sanitize_filename(filename: str) -> str:
    sanitized = re.sub(r'[^\w\s-.]', '', filename)
    sanitized = re.sub(r'[-\s]+', '-', sanitized)
    return sanitized.strip('-.')


def format_duration(seconds: float) -> str:
    if seconds < 1:
        return f"{seconds * 1000:.1f}ms"
    elif seconds < 60:
        return f"{seconds:.2f}s"
    elif seconds < 3600:
        minutes = seconds / 60
        return f"{minutes:.1f}m"
    else:
        hours = seconds / 3600
        return f"{hours:.1f}h"


def get_enum_values(enum_class) -> List[str]:
    return [item.value for item in enum_class]


def safe_get_nested(data: Dict[str, Any], keys: str, default: Any = None) -> Any:
    try:
        result = data
        for key in keys.split('.'):
            if isinstance(result, dict) and key in result:
                result = result[key]
            else:
                return default
        return result
    except (KeyError, TypeError, AttributeError):
        return default


def merge_dicts(*dicts: Dict[str, Any]) -> Dict[str, Any]:
    result = {}
    for d in dicts:
        if isinstance(d, dict):
            result.update(d)
    return result