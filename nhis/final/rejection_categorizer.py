import re
import logging
from typing import Dict, Optional, List, Tuple
from dataclasses import dataclass

logger = logging.getLogger(__name__)

@dataclass
class RejectionCategory:
    category: str
    subcategory: Optional[str] = None
    description: str = ""
    severity: str = "MEDIUM"
    action_required: str = ""

class SmartRejectionCategorizer:
    """
    Advanced rejection reason categorizer that analyzes rejection text to determine
    the actual cause rather than just the stage where it occurred.
    """
    
    def __init__(self):
        self.patterns = self._initialize_patterns()
    
    def _initialize_patterns(self) -> Dict:
        """Initialize regex patterns for different rejection categories"""
        return {
            # Inappropriate prescription - PUT FIRST for specific matching
            'inappropriate_prescription': [
                r'inappropriate.*prescription',
                r'prescription.*not\s+indicated',
                r'medication.*inappropriate',
                r'drug.*contraindicated',
                r'prescription.*not\s+justified',
                r'medicine.*not\s+appropriate',
                r'inappropriate.*medication',
                r'prescription.*invalid.*condition',
                r'medicine.*contraindicated',
                r'drug.*not\s+suitable',
                r'medication.*mismatch',
                r'prescription.*clinically.*inappropriate',
                r'reject:\s*inappropriate\s*prescription',
                r'inappropriate\s*prescription'
            ],
            
            # Age-related rejections
            'age_diagnosis_mismatch': [
                r'age\s+\d+\s+above\s+maximum\s+\d+',
                r'age\s+\d+\s+below\s+minimum\s+\d+',
                r'patient\s+age.*not\s+allowed',
                r'age\s+restriction.*g-drg',
                r'age.*outside.*range'
            ],
            
            # Gender-related rejections
            'gender_diagnosis_mismatch': [
                r'gender\s+\w+\s+not\s+allowed',
                r'patient\s+gender.*not\s+allowed',
                r'gender\s+restriction',
                r'(male|female).*not\s+permitted',
                r'gender.*incompatible'
            ],
            
            # Missing data
            'missing_required_fields': [
                r'missing\s+required\s+fields',
                r'incomplete\s+data',
                r'required\s+field.*missing',
                r'mandatory\s+information.*absent',
                r'essential\s+data.*not\s+provided'
            ],
            
            # Medicine-related
            'medicine_oversupply': [
                r'excessive\s+oversupply',
                r'medicine.*oversupply',
                r'dosage.*exceeded',
                r'quantity.*above\s+limit',
                r'oversupply\s+detected'
            ],
            
            'medicine_not_covered': [
                r'medicine.*not.*formulary',
                r'drug.*not\s+covered',
                r'medication.*not\s+approved',
                r'pharmaceutical.*excluded',
                r'medicine.*not\s+reimbursable'
            ],
            
            # Facility-related
            'facility_accreditation': [
                r'facility.*not\s+accredited',
                r'provider.*not\s+registered',
                r'facility.*credentials',
                r'accreditation.*expired',
                r'facility.*not\s+authorized'
            ],
            
            # G-DRG related
            'gdrg_mapping_error': [
                r'g-drg.*not\s+found',
                r'drg.*mapping.*failed',
                r'diagnosis.*code.*invalid',
                r'icd.*code.*not\s+recognized',
                r'procedure.*code.*invalid'
            ],
            
            'gdrg_tariff_error': [
                r'tariff.*not\s+available',
                r'pricing.*not\s+found',
                r'rate.*not\s+established',
                r'cost.*calculation.*failed'
            ],
            
            # Eligibility issues
            'patient_eligibility': [
                r'patient.*not\s+eligible',
                r'membership.*expired',
                r'coverage.*not\s+active',
                r'subscription.*invalid',
                r'eligibility.*failed'
            ],
            
            # Documentation
            'insufficient_documentation': [
                r'supporting.*documents.*required',
                r'additional.*documentation',
                r'insufficient.*evidence',
                r'clinical.*justification.*required',
                r'documentation.*incomplete'
            ],
            
            # Date/timing issues
            'service_date_issues': [
                r'service.*date.*invalid',
                r'date.*outside.*coverage',
                r'expired.*service',
                r'date.*restriction',
                r'timing.*violation'
            ],
            
            # Duplicate claims
            'duplicate_claim': [
                r'duplicate.*claim',
                r'already.*processed',
                r'previously.*submitted',
                r'duplicate.*encounter',
                r'similar.*claim.*exists'
            ],
            
            # System/technical errors
            'system_error': [
                r'system.*error',
                r'technical.*failure',
                r'processing.*error',
                r'database.*error',
                r'internal.*error'
            ]
        }
    
    def categorize_rejection(self, reason: str, stage: str = None) -> RejectionCategory:
        """
        Categorize a rejection reason into a meaningful business category
        
        Args:
            reason: The rejection reason text
            stage: The stage where rejection occurred (optional)
            
        Returns:
            RejectionCategory with detailed categorization
        """
        if not reason:
            return RejectionCategory(
                category="Unknown",
                description="No rejection reason provided",
                severity="LOW"
            )
        
        reason_lower = reason.lower()
        
        # Check each pattern category
        for category, patterns in self.patterns.items():
            for pattern in patterns:
                if re.search(pattern, reason_lower, re.IGNORECASE):
                    return self._create_category_details(category, reason, stage)
        
        # Fallback to stage-based categorization if no pattern matches
        return self._fallback_categorization(reason, stage)
    
    def _create_category_details(self, category: str, reason: str, stage: str) -> RejectionCategory:
        """Create detailed category information based on the identified category"""
        
        category_mappings = {
            'age_diagnosis_mismatch': RejectionCategory(
                category="Age-Diagnosis Mismatch",
                subcategory="Clinical Validation",
                description="Patient age is outside the acceptable range for the diagnosed condition",
                severity="HIGH",
                action_required="Review diagnosis coding or patient age verification"
            ),
            
            'gender_diagnosis_mismatch': RejectionCategory(
                category="Gender-Diagnosis Mismatch", 
                subcategory="Clinical Validation",
                description="Patient gender is incompatible with the diagnosed condition",
                severity="HIGH",
                action_required="Verify diagnosis coding or patient gender information"
            ),
            
            'missing_required_fields': RejectionCategory(
                category="Missing Required Data",
                subcategory="Data Completeness",
                description="Essential information required for processing is missing",
                severity="MEDIUM",
                action_required="Complete all mandatory fields and resubmit"
            ),
            
            'medicine_oversupply': RejectionCategory(
                category="Medicine Oversupply",
                subcategory="Medicine Validation",
                description="Prescribed medicine quantity exceeds acceptable limits",
                severity="HIGH",
                action_required="Reduce prescribed quantities or provide clinical justification"
            ),
            
            'inappropriate_prescription': RejectionCategory(
                category="Inappropriate Prescription",
                subcategory="Clinical Appropriateness",
                description="Prescribed medicine is not clinically appropriate for the patient's condition",
                severity="HIGH",
                action_required="Review clinical indication and prescribe appropriate medication for the diagnosed condition"
            ),
            
            'facility_accreditation': RejectionCategory(
                category="Facility Accreditation Issues",
                subcategory="Provider Credentialing",
                description="Healthcare facility lacks proper accreditation or registration",
                severity="HIGH",
                action_required="Update facility credentials and accreditation status"
            ),
            
            'gdrg_mapping_error': RejectionCategory(
                category="G-DRG Mapping Error",
                subcategory="Coding Issues",
                description="Diagnosis or procedure codes cannot be mapped to valid G-DRG",
                severity="HIGH", 
                action_required="Review and correct ICD-10 diagnosis and procedure codes"
            ),
            
            'gdrg_tariff_error': RejectionCategory(
                category="G-DRG Tariff Not Found",
                subcategory="Pricing Issues",
                description="No tariff rate established for the determined G-DRG",
                severity="MEDIUM",
                action_required="Contact NHIS for tariff rate clarification"
            ),
            
            'patient_eligibility': RejectionCategory(
                category="Patient Eligibility Issues",
                subcategory="Membership Validation",
                description="Patient is not eligible for NHIS coverage",
                severity="HIGH",
                action_required="Verify patient membership status and coverage dates"
            ),
            
            'insufficient_documentation': RejectionCategory(
                category="Insufficient Documentation",
                subcategory="Clinical Documentation",
                description="Additional supporting documents required for claim approval",
                severity="MEDIUM",
                action_required="Provide required supporting clinical documentation"
            ),
            
            'service_date_issues': RejectionCategory(
                category="Service Date Issues",
                subcategory="Temporal Validation",
                description="Service dates are outside acceptable coverage periods",
                severity="MEDIUM",
                action_required="Verify service dates and coverage periods"
            ),
            
            'duplicate_claim': RejectionCategory(
                category="Duplicate Claim",
                subcategory="Claim Validation",
                description="Similar claim has already been processed",
                severity="LOW",
                action_required="Review for duplicate submission and modify if necessary"
            ),
            
            'system_error': RejectionCategory(
                category="System Processing Error",
                subcategory="Technical Issues",
                description="Technical error occurred during claim processing",
                severity="LOW",
                action_required="Resubmit claim or contact technical support"
            )
        }
        
        return category_mappings.get(category, RejectionCategory(
            category="Other",
            description=f"Unclassified rejection: {reason}",
            severity="MEDIUM"
        ))
    
    def _fallback_categorization(self, reason: str, stage: str) -> RejectionCategory:
        """Fallback categorization based on stage when pattern matching fails"""
        
        stage_fallbacks = {
            'INITIAL_PROCESSING': RejectionCategory(
                category="Data Validation Issues",
                subcategory="Initial Processing",
                description="Basic data validation failed",
                severity="MEDIUM"
            ),
            'ENHANCED_VALIDATIONS': RejectionCategory(
                category="Enhanced Validation Failure", 
                subcategory="Advanced Validation",
                description="Advanced validation checks failed",
                severity="MEDIUM"
            ),
            'CREDENTIALING': RejectionCategory(
                category="Provider Credentialing Issues",
                subcategory="Provider Validation",
                description="Healthcare provider credentialing validation failed",
                severity="HIGH"
            ),
            'GDRG_DETERMINATION': RejectionCategory(
                category="G-DRG Processing Issues",
                subcategory="Clinical Coding",
                description="G-DRG determination process failed",
                severity="HIGH"
            ),
            'MEDICINE_VALIDATION': RejectionCategory(
                category="Medicine Validation Issues",
                subcategory="Pharmaceutical Review",
                description="Medicine validation process failed", 
                severity="MEDIUM"
            )
        }
        
        return stage_fallbacks.get(stage, RejectionCategory(
            category="General Processing Error",
            description=f"Processing failed: {reason}",
            severity="MEDIUM"
        ))
    
    def get_rejection_statistics(self, rejection_reasons: List[Dict]) -> Dict:
        """
        Analyze a list of rejection reasons and return statistics
        
        Args:
            rejection_reasons: List of rejection reason dictionaries
            
        Returns:
            Dictionary with rejection statistics and top categories
        """
        category_counts = {}
        subcategory_counts = {}
        severity_counts = {'HIGH': 0, 'MEDIUM': 0, 'LOW': 0}
        
        for rejection in rejection_reasons:
            reason_text = rejection.get('reason', '')
            stage = rejection.get('stage', '')
            
            category_info = self.categorize_rejection(reason_text, stage)
            
            # Count main categories
            if category_info.category in category_counts:
                category_counts[category_info.category] += 1
            else:
                category_counts[category_info.category] = 1
            
            # Count subcategories
            if category_info.subcategory:
                if category_info.subcategory in subcategory_counts:
                    subcategory_counts[category_info.subcategory] += 1
                else:
                    subcategory_counts[category_info.subcategory] = 1
            
            # Count severity
            severity_counts[category_info.severity] += 1
        
        # Sort categories by count
        top_categories = sorted(category_counts.items(), key=lambda x: x[1], reverse=True)[:10]
        top_subcategories = sorted(subcategory_counts.items(), key=lambda x: x[1], reverse=True)[:10]
        
        return {
            'top_rejection_categories': [
                {
                    'category': category,
                    'count': count,
                    'percentage': round((count / len(rejection_reasons)) * 100, 2)
                }
                for category, count in top_categories
            ],
            'top_subcategories': [
                {
                    'subcategory': subcategory,
                    'count': count,
                    'percentage': round((count / len(rejection_reasons)) * 100, 2)
                }
                for subcategory, count in top_subcategories
            ],
            'severity_distribution': severity_counts,
            'total_rejections': len(rejection_reasons)
        }


# Utility functions for easy integration
def categorize_single_rejection(reason: str, stage: str = None) -> Dict:
    """Utility function to categorize a single rejection reason"""
    categorizer = SmartRejectionCategorizer()
    category_info = categorizer.categorize_rejection(reason, stage)
    
    return {
        'category': category_info.category,
        'subcategory': category_info.subcategory,
        'description': category_info.description,
        'severity': category_info.severity,
        'action_required': category_info.action_required
    }


def analyze_rejection_batch(rejection_list: List[Dict]) -> Dict:
    """Utility function to analyze a batch of rejection reasons"""
    categorizer = SmartRejectionCategorizer()
    return categorizer.get_rejection_statistics(rejection_list)


# Test function
def test_categorizer():
    """Test the categorizer with sample rejection reasons"""
    test_cases = [
        "Stage 4 failed: REJECT: Patient age 36 above maximum 11 for G-DRG",
        "Stage 4 failed: REJECT: Patient gender Male not allowed for G-DRG", 
        "Stage 1 failed: REJECT: Missing Required Fields",
        "Stage 6 failed: Medicine validation failed: Excessive oversupply detected",
        "Stage 5 failed: G-DRG not found for diagnosis code",
        "Stage 3 failed: Facility not accredited for this service type",
        "Stage 6 failed: Inappropriate prescription for patient condition",
        "Medicine validation failed: Prescribed drug contraindicated for diagnosis",
        "REJECT: Inappropriate prescription",
        "REJECT: Medicine dispensed outside admission period",
        "REJECT: Polypharmacy detected",
        "REJECT: Multiple chronic visits",
        "REJECT: Treatment diagnosis mismatch",
        "REJECT: Invalid prescriber level",
        "REJECT: Frequency exceeds maximum allowed",
        "REJECT: Duration exceeds maximum allowed"
    ]
    
    categorizer = SmartRejectionCategorizer()
    
    print("Testing Smart Rejection Categorizer:")
    print("=" * 50)
    
    for reason in test_cases:
        category_info = categorizer.categorize_rejection(reason)
        print(f"\nReason: {reason}")
        print(f"Category: {category_info.category}")
        print(f"Subcategory: {category_info.subcategory}")
        print(f"Severity: {category_info.severity}")
        print(f"Action: {category_info.action_required}")


if __name__ == "__main__":
    test_categorizer()