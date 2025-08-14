

from enum import Enum, auto


class ClaimStatus(Enum):
    """Final claim processing status"""
    APPROVED = "APPROVED"
    PARTIALLY_APPROVED = "PARTIALLY_APPROVED"
    REJECTED = "REJECTED"
    PENDING = "PENDING"


class ValidationSeverity(Enum):
    """Severity levels for validation issues"""
    CRITICAL = "CRITICAL"    # Causes claim rejection
    MAJOR = "MAJOR"          # Causes partial approval or flagging
    MINOR = "MINOR"          # Warning only, doesn't affect approval


class EncounterType(Enum):
    """Types of healthcare encounters (from service_type fields)"""
    OPD = "OPD"              # Outpatient Department
    IPD = "IPD"              # Inpatient Department  
    AE = "A&E"               # Accident & Emergency
    EMERGENCY = "EMERGENCY"   # Emergency (alternative name)
    CASUALTY = "CASUALTY"     # Casualty (alternative name)


class EpisodeType(Enum):
    """Episode types for visit limit tracking (Node B2)"""
    ACUTE = "ACUTE"           # Max 3 visits in 14 days
    CHRONIC = "CHRONIC"       # Max 6 visits in 12 months
    ANTENATAL = "ANTENATAL"   # Max 6 visits per pregnancy
    POSTNATAL = "POSTNATAL"   # Max 3 visits in 6 weeks


class GDRGDeterminationMethod(Enum):
    """How G-DRG was determined (Node A2)"""
    PROCEDURE = "PROCEDURE"   # Dominant procedure determines G-DRG
    DIAGNOSIS = "DIAGNOSIS"   # Primary diagnosis determines G-DRG


class AgeSuffix(Enum):
    """Age-based G-DRG suffixes (Node A3)"""
    ADULT = "A"              # 12+ years old
    CHILD = "C"              # Under 12 years old (or <19 for childhood cancer)


class FacilityLevel(Enum):
    """Healthcare facility levels"""
    A = "A"                  # CHPS/Community level
    B1 = "B1"                # Health Center
    B2 = "B2"                # Polyclinic  
    C = "C"                  # District Hospital
    D1 = "D1"                # Regional Hospital
    D2 = "D2"                # Regional Hospital (specialized)
    M = "M"                  # Municipal Hospital
    T = "T"                  # Teaching Hospital


class PrescriberLevel(Enum):
    """Prescriber authorization levels"""
    A = "A"                  # Community Health Officer
    B2 = "B2"                # Medical Assistant/Physician Assistant
    C = "C"                  # General Practitioner
    D1 = "D1"                # Specialist
    D2 = "D2"                # Consultant


class ModifierType(Enum):
    """Types of tariff modifiers"""
    BILATERAL_SURGERY = "BILATERAL_SURGERY"        # 120% for bilateral procedures
    DENTAL_MULTI_TOOTH = "DENTAL_MULTI_TOOTH"    # 100% + 20% for additional teeth
    MULTIPLE_PROCEDURES = "MULTIPLE_PROCEDURES"   # 100% + 20% + 20% for 2nd/3rd procedures
    EMERGENCY = "EMERGENCY"                       # Emergency-specific modifiers
    AGE_BASED = "AGE_BASED"                      # Age-specific adjustments
    ZOOM_CODES = "ZOOM_CODES"                    # Special procedure codes


class BundlingType(Enum):
    """Investigation bundling rules"""
    ALL_INCLUSIVE = "ALL_INCLUSIVE"              # Investigations included in G-DRG
    UNBUNDLED = "UNBUNDLED"                      # All investigations billable separately
    SELECTIVE = "SELECTIVE"                      # Some investigations separately billable


class DecisionReason(Enum):
    """Reasons for claim decisions (maps to flowchart rejection/approval nodes)"""
    
    # Rejection Reasons
    MISSING_REQUIRED_FIELDS = "MISSING_REQUIRED_FIELDS"
    INVALID_INPUT_DATA = "INVALID_INPUT_DATA"
    NO_VALID_GDRGS = "NO_VALID_GDRGS"
    SERVICE_EXCLUDED = "SERVICE_EXCLUDED"
    NOT_IN_BENEFIT_PACKAGE = "NOT_IN_BENEFIT_PACKAGE"
    FACILITY_NOT_AUTHORIZED = "FACILITY_NOT_AUTHORIZED"
    MISSING_ACCREDITATION = "MISSING_ACCREDITATION"
    
    # Episode/Visit Limit Violations
    ACUTE_VISIT_LIMIT_EXCEEDED = "ACUTE_VISIT_LIMIT_EXCEEDED"
    CHRONIC_VISIT_LIMIT_EXCEEDED = "CHRONIC_VISIT_LIMIT_EXCEEDED"
    ANC_VISIT_LIMIT_EXCEEDED = "ANC_VISIT_LIMIT_EXCEEDED"
    PNC_VISIT_LIMIT_EXCEEDED = "PNC_VISIT_LIMIT_EXCEEDED"
    
    # Physiotherapy Rejections
    PHYSIO_CONDITION_NOT_ELIGIBLE = "PHYSIO_CONDITION_NOT_ELIGIBLE"
    PHYSIO_SESSION_LIMIT_EXCEEDED = "PHYSIO_SESSION_LIMIT_EXCEEDED"
    MISSING_PHYSIO_DOCUMENTATION = "MISSING_PHYSIO_DOCUMENTATION"
    
    # Inpatient Rejections
    MISSING_DISCHARGE_DATE = "MISSING_DISCHARGE_DATE"
    PREMATURE_BILLING = "PREMATURE_BILLING"
    EMERGENCY_READMISSION_VIOLATION = "EMERGENCY_READMISSION_VIOLATION"
    
    # Medicine/Investigation Issues
    NON_FORMULARY_MEDICINE = "NON_FORMULARY_MEDICINE"
    INVALID_PRESCRIBER_LEVEL = "INVALID_PRESCRIBER_LEVEL"
    EXCESSIVE_MEDICINE_OVERSUPPLY = "EXCESSIVE_MEDICINE_OVERSUPPLY"
    INVESTIGATION_BUNDLED_IN_GDRG = "INVESTIGATION_BUNDLED_IN_GDRG"
    
    # Documentation Issues
    ICD10_NOT_COHERENT = "ICD10_NOT_COHERENT"
    MISSING_PREAUTHORIZATION = "MISSING_PREAUTHORIZATION"
    MISSING_SPECIALTY_DOCUMENTATION = "MISSING_SPECIALTY_DOCUMENTATION"
    
    # Approval Reasons
    ALL_VALIDATIONS_PASSED = "ALL_VALIDATIONS_PASSED"
    PARTIAL_APPROVAL_WITH_DENIALS = "PARTIAL_APPROVAL_WITH_DENIALS"


class DocumentationType(Enum):
    """Types of required documentation"""
    ECG = "ECG"
    CARDIAC_ENZYMES = "cardiac_enzymes"
    DOCTOR_REFERRAL = "doctor_referral"
    PHYSIOTHERAPY_ATTENDANCE_FORM = "physiotherapy_attendance_form"
    ENDOSCOPY_REQUEST_FORM = "endoscopy_request_form"
    REASON_FOR_ENDOSCOPY = "reason_for_endoscopy"
    PROVISIONAL_DIAGNOSIS = "provisional_diagnosis"
    PREAUTHORIZATION = "preauthorization"
    DISCHARGE_SUMMARY = "discharge_summary"


class AEClassification(Enum):
    """A&E case classification (Node C)"""
    MANAGED_AS_OPD = "MANAGED_AS_OPD"            # Use OPD rules and tariff
    DETENTION_UNDER_24H = "DETENTION_UNDER_24H"  # Use ZOOM02A tariff
    REQUIRES_ADMISSION = "REQUIRES_ADMISSION"     # Use inpatient rules and tariff


class ZoomCode(Enum):
    """Special ZOOM procedure codes"""
    ZOOM02A = "ZOOM02A"      # Detention <24 hours
    ZOOM03A = "ZOOM03A"      # Other ZOOM procedures
    ZOOM04A = "ZOOM04A"      # Other ZOOM procedures


class MedicineFrequency(Enum):
    """Medicine dosing frequency"""
    OD = "OD"                # Once daily
    BD = "BD"                # Twice daily  
    TID = "TID"              # Three times daily
    QID = "QID"              # Four times daily
    PRN = "PRN"              # As needed
    STAT = "STAT"            # Immediately


class ProcessingStep(Enum):
    """Main processing steps (corresponds to flowchart steps)"""
    INTAKE_NORMALIZATION = "INTAKE_NORMALIZATION"        # Step 1
    ELIGIBILITY_COVERAGE = "ELIGIBILITY_COVERAGE"        # Step 2
    SETTING_ROUTER = "SETTING_ROUTER"                    # Step 3
    CREDENTIALING_CHECK = "CREDENTIALING_CHECK"          # Step 4
    BUSINESS_RULES_CALCULATION = "BUSINESS_RULES_CALCULATION"  # Step 5


class RuleCategory(Enum):
    """Categories of business rules"""
    GDRG_DETERMINATION = "GDRG_DETERMINATION"            # A1-A4
    OPD_RULES = "OPD_RULES"                              # B1-B5
    AE_RULES = "AE_RULES"                                # C
    INPATIENT_RULES = "INPATIENT_RULES"                  # D1-D3
    MODIFIER_RULES = "MODIFIER_RULES"                    # E
    DOCUMENTATION_RULES = "DOCUMENTATION_RULES"          # F


class LineItemType(Enum):
    """Types of line items in calculation breakdown"""
    GDRG_TARIFF = "GDRG_TARIFF"
    MEDICINE = "MEDICINE"
    INVESTIGATION = "INVESTIGATION"
    PROCEDURE = "PROCEDURE"
    MODIFIER = "MODIFIER"
    ADJUSTMENT = "ADJUSTMENT"


class LineItemStatus(Enum):
    """Status of individual line items"""
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    PENDING = "PENDING"
    PARTIAL = "PARTIAL"


# Utility functions for enum operations
def get_encounter_types() -> list[str]:
    """Get all valid encounter type values"""
    return [e.value for e in EncounterType]


def get_facility_levels() -> list[str]:
    """Get all valid facility level values"""
    return [f.value for f in FacilityLevel]


def get_prescriber_levels() -> list[str]:
    """Get all valid prescriber level values"""
    return [p.value for p in PrescriberLevel]


def is_emergency_encounter(encounter_type: str) -> bool:
    """Check if encounter type is emergency/A&E"""
    emergency_types = {
        EncounterType.AE.value,
        EncounterType.EMERGENCY.value,
        EncounterType.CASUALTY.value
    }
    return encounter_type.upper() in emergency_types


def get_age_suffix(age: int, is_childhood_cancer: bool = False) -> AgeSuffix:
    """Determine age suffix based on age and condition"""
    if is_childhood_cancer and age < 19:
        return AgeSuffix.CHILD
    elif age < 12:
        return AgeSuffix.CHILD
    else:
        return AgeSuffix.ADULT