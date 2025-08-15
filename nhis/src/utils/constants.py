from enum import Enum
from typing import Dict, List


class ClaimStatus(Enum):
    SUBMITTED = "submitted"
    PROCESSING = "processing"
    APPROVED = "approved"
    PARTIALLY_APPROVED = "partially_approved"
    REJECTED = "rejected"
    PENDING_REVIEW = "pending_review"
    CANCELLED = "cancelled"


class BatchStatus(Enum):
    SUBMITTED = "submitted"
    PROCESSING = "processing"
    COMPLETED = "completed"
    COMPLETED_WITH_ERRORS = "completed_with_errors"
    FAILED = "failed"
    CANCELLED = "cancelled"


class EncounterSetting(Enum):
    OPD = "OPD"
    IPD = "IPD"
    AE = "A&E"
    EMERGENCY = "EMERGENCY"


class EpisodeType(Enum):
    ACUTE = "acute"
    CHRONIC = "chronic"
    ANTENATAL = "antenatal"
    POSTNATAL = "postnatal"


class FacilityLevel(Enum):
    CHPS = "CHPS"
    HEALTH_CENTRE = "Health Centre"
    DISTRICT_HOSPITAL = "District Hospital"
    REGIONAL_HOSPITAL = "Regional Hospital"
    TEACHING_HOSPITAL = "Teaching Hospital"
    SPECIALIST_HOSPITAL = "Specialist Hospital"


class ProcessorStep(Enum):
    INTAKE = "intake"
    ELIGIBILITY = "eligibility"
    ROUTING = "routing"
    CREDENTIALING = "credentialing"
    BUSINESS_RULES = "business_rules"


class RuleCategory(Enum):
    OPD = "opd"
    IPD = "ipd"
    EMERGENCY = "emergency"
    GDRG = "gdrg"
    MODIFIERS = "modifiers"
    DOCUMENTATION = "documentation"


EPISODE_LIMITS = {
    EpisodeType.ACUTE.value: {"visits": 3, "days": 14},
    EpisodeType.CHRONIC.value: {"visits": 6, "days": 365},
    EpisodeType.ANTENATAL.value: {"visits": 6, "days": 280},
    EpisodeType.POSTNATAL.value: {"visits": 3, "days": 42}
}


GDRG_AGE_LIMITS = {
    "child_threshold": 12,
    "adult_threshold": 12,
    "childhood_cancer_threshold": 19
}


MODIFIER_PERCENTAGES = {
    "bilateral_surgery": 120,
    "after_hours": 150,
    "weekend": 130,
    "holiday": 150,
    "emergency_surgery": 125,
    "trauma": 140,
    "pediatric": 110,
    "geriatric": 105,
    "teaching_hospital": 105,
    "rural_facility": 103,
    "complex_case": 102
}


PROCESSING_TIMEOUTS = {
    "single_claim_seconds": 30,
    "batch_processing_hours": 4,
    "database_query_seconds": 10,
    "rule_evaluation_seconds": 5
}


SYSTEM_LIMITS = {
    "max_batch_size": 1000,
    "max_parallel_workers": 8,
    "max_retry_attempts": 3,
    "cache_ttl_seconds": 3600,
    "max_audit_retention_days": 2555
}


ERROR_CODES = {
    "CLAIM_NOT_FOUND": "C001",
    "INVALID_CLAIM_DATA": "C002",
    "PROCESSING_TIMEOUT": "C003",
    "DATABASE_ERROR": "D001",
    "RULE_EVALUATION_ERROR": "R001",
    "CALCULATION_ERROR": "F001",
    "BATCH_PROCESSING_ERROR": "B001",
    "AUTHENTICATION_ERROR": "A001",
    "AUTHORIZATION_ERROR": "A002",
    "VALIDATION_ERROR": "V001",
    "SYSTEM_ERROR": "S001"
}


VALIDATION_PATTERNS = {
    "claim_id": r"^CLM\d{10}$",
    "batch_id": r"^BAT\d{8}$",
    "facility_id": r"^FAC\d{6}$",
    "provider_id": r"^PRV\d{6}$",
    "patient_id": r"^PAT\d{8}$",
    "nhis_number": r"^\d{10}$",
    "icd10_code": r"^[A-Z]\d{2}(\.\d{1,2})?$",
    "gdrg_code": r"^[A-Z]\d{2}[AC]?$",
    "procedure_code": r"^[A-Z]{3,4}\d{3}[A-Z]?$"
}


DATABASE_SETTINGS = {
    "connection_pool_size": 10,
    "max_overflow": 20,
    "pool_timeout": 30,
    "pool_recycle": 3600,
    "echo_sql": False
}


CACHE_KEYS = {
    "reference_data": "ref_data",
    "facility_info": "facility",
    "provider_info": "provider",
    "tariff_data": "tariff",
    "episode_limits": "episode_limits"
}


API_SETTINGS = {
    "default_page_size": 50,
    "max_page_size": 1000,
    "rate_limit_per_minute": 1000,
    "request_timeout_seconds": 30
}


NOTIFICATION_TYPES = {
    "CLAIM_APPROVED": "claim_approved",
    "CLAIM_REJECTED": "claim_rejected",
    "CLAIM_PENDING": "claim_pending",
    "BATCH_COMPLETED": "batch_completed",
    "BATCH_FAILED": "batch_failed",
    "SYSTEM_ERROR": "system_error"
}


REFERENCE_DATA_FILES = {
    "icd10_gdrg_mapping": "icd10_gdrg_mapping.json",
    "medicine_formulary": "medicine_formulary.json",
    "chronic_conditions": "chronic_conditions.json",
    "documentation_requirements": "documentation_requirements.json",
    "episode_limits": "episode_limits.json",
    "facility_credentialing": "facility_credentialing.json",
    "physiotherapy_conditions": "physiotherapy_conditions.json",
    "exclusions": "exclusions.json",
    "bundling_rules": "bundling_rules.json",
    "modifier_rules": "modifier_rules.json"
}


REPORT_TYPES = {
    "PROCESSING_SUMMARY": "processing_summary",
    "BATCH_PROCESSING": "batch_processing",
    "FINANCIAL": "financial",
    "AUDIT": "audit",
    "PERFORMANCE": "performance",
    "COMPLIANCE": "compliance"
}