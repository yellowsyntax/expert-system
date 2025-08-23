import asyncio
import json
import logging
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass
from enum import Enum
from datetime import datetime, timedelta
from collections import defaultdict

from neon_db_connection import get_nhis_queries, initialize_database, close_database

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class ValidationResult(Enum):
    """Validation outcomes per flowchart"""
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    FLAGGED = "FLAGGED"
    PENDING = "PENDING"

@dataclass
class ValidationOutcome:
    """Result of a validation check"""
    result: ValidationResult
    reason: str
    details: Dict[str, Any] = None
    timestamp: datetime = None
    step: str = "Enhanced Validation"
    
    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.now()

@dataclass
class DuplicateGroup:
    """Group of duplicate claims for reporting"""
    patient_id: str
    admission_date: str
    claim_count: int
    encounter_ids: List[str]
    providers_involved: List[str]
    total_amount: float
    violation_type: str
    severity: str
    is_cross_provider: bool
    claims_details: List[Dict]

class EnhancedValidations:
    """
    Enhanced validation methods to complement existing NHIS Expert System
    Covers: Medicine dispensing period, duplicate claims, polypharmacy, 
    gender-diagnosis mismatch, supporting documents
    """
    
    def __init__(self):
        self.queries = None
        self.is_initialized = False
        
        # Drug interaction database (expandable)
        self.drug_interactions = {
            'WARFARIN': {
                'contraindicated': ['ASPIRIN', 'HEPARIN', 'NSAID'],
                'severity': 'HIGH',
                'effect': 'Increased bleeding risk'
            },
            'DIGOXIN': {
                'contraindicated': ['QUINIDINE', 'VERAPAMIL', 'AMIODARONE'],
                'severity': 'HIGH', 
                'effect': 'Digoxin toxicity'
            },
            'INSULIN': {
                'contraindicated': ['GLIBENCLAMIDE'],
                'severity': 'MEDIUM',
                'effect': 'Hypoglycemia risk'
            },
            'METFORMIN': {
                'contraindicated': ['CONTRAST_AGENTS'],
                'severity': 'HIGH',
                'effect': 'Lactic acidosis risk'
            }
        }
        
        # Gender-specific condition mappings
        self.gender_conditions = {
            'male_only': {
                'icd10_prefixes': ['N40', 'N41', 'N42', 'C61', 'Z87.430'],
                'keywords': ['prostate', 'testicular', 'penile']
            },
            'female_only': {
                'icd10_prefixes': ['O', 'Z3', 'N70', 'N71', 'N72', 'N73', 'C50', 'C51', 'C52', 'C53', 'C54', 'C55', 'C56', 'C57', 'C58', 'N80', 'N81', 'N82'],
                'keywords': ['pregnancy', 'pregnant', 'cervical', 'ovarian', 'uterine', 'vaginal', 'breast', 'endometriosis']
            }
        }
        
        self.document_requirements = {
            'surgical_procedures': ['Surgical consent form', 'Pre-operative assessment', 'Post-operative notes'],
            'cancer_diagnosis': ['Histopathology report', 'Staging documentation', 'Treatment protocol'],
            'emergency_surgery': ['Emergency justification', 'Clinical urgency assessment'],
            'chronic_conditions': ['Treatment plan', 'Follow-up schedule', 'Monitoring results'],
            'high_cost_procedures': ['Clinical justification', 'Alternative treatment consideration', 'Cost-benefit analysis'],
            'experimental_treatments': ['Ethics approval', 'Informed consent', 'Research protocol']
        }
    
    async def initialize(self):
        """Initialize database connection"""
        if not self.is_initialized:
            await initialize_database()
            self.queries = await get_nhis_queries()
            self.is_initialized = True
            logger.info("✅ Enhanced Validations initialized")
    
    async def close(self):
        """Close database connections"""
        await close_database()
        self.is_initialized = False
        logger.info("🔌 Enhanced Validations closed")
    
    async def validate_medicine_dispensing_period(self, claim_data: Dict) -> ValidationOutcome:
        """
        ENHANCED: Medicine Dispensed Outside Admission Period
        Validates medicines are dispensed within appropriate timeframes
        """
        try:
            encounter_type = claim_data.get('encounter_type')
            encounter_id = claim_data.get('encounter_id')
            
            # Only applicable for IPD encounters
            if encounter_type != 'IPD':
                return ValidationOutcome(
                    result=ValidationResult.APPROVED,
                    reason="Medicine dispensing period check not applicable for non-IPD encounters",
                    details={"encounter_type": encounter_type}
                )
            
            admission_date = claim_data.get('admission_date')
            discharge_date = claim_data.get('discharge_date')
            medicine_date = claim_data.get('medicine_date')
            
            # Check if required dates are present
            if not admission_date:
                return ValidationOutcome(
                    result=ValidationResult.FLAGGED,
                    reason="FLAG: Missing admission date for medicine dispensing validation",
                    details={"missing_data": "admission_date"}
                )
            
            if not medicine_date:
                return ValidationOutcome(
                    result=ValidationResult.FLAGGED,
                    reason="FLAG: Missing medicine date for dispensing validation",
                    details={"missing_data": "medicine_date"}
                )
            
            # Convert dates to datetime objects
            if isinstance(admission_date, str):
                admission_date = datetime.fromisoformat(admission_date.replace('Z', '+00:00'))
            if isinstance(discharge_date, str) and discharge_date:
                discharge_date = datetime.fromisoformat(discharge_date.replace('Z', '+00:00'))
            if isinstance(medicine_date, str):
                medicine_date = datetime.fromisoformat(medicine_date.replace('Z', '+00:00'))
            
            # Validation 1: Medicine dispensed before admission
            if medicine_date < admission_date:
                days_before = (admission_date - medicine_date).days
                return ValidationOutcome(
                    result=ValidationResult.REJECTED,
                    reason="REJECT: Medicine dispensed before admission",
                    details={
                        "encounter_id": encounter_id,
                        "medicine_date": medicine_date.isoformat(),
                        "admission_date": admission_date.isoformat(),
                        "days_before_admission": days_before,
                        "violation_type": "PRE_ADMISSION_DISPENSING"
                    }
                )
            
            # Validation 2: Medicine dispensed after discharge (with grace period)
            if discharge_date:
                # Allow 24-hour grace period after discharge for discharge medications
                discharge_grace_period = discharge_date + timedelta(hours=24)
                
                if medicine_date > discharge_grace_period:
                    days_after = (medicine_date - discharge_date).days
                    return ValidationOutcome(
                        result=ValidationResult.REJECTED,
                        reason="REJECT: Medicine dispensed outside admission period",
                        details={
                            "encounter_id": encounter_id,
                            "medicine_date": medicine_date.isoformat(),
                            "discharge_date": discharge_date.isoformat(),
                            "days_after_discharge": days_after,
                            "grace_period_hours": 24,
                            "violation_type": "POST_DISCHARGE_DISPENSING"
                        }
                    )
            
            # Calculate length of stay for validation
            if discharge_date:
                los_days = (discharge_date - admission_date).days
            else:
                los_days = (datetime.now() - admission_date).days
            
            logger.info(f"✅ Medicine dispensing period validation passed for {encounter_id}")
            
            return ValidationOutcome(
                result=ValidationResult.APPROVED,
                reason="Medicine dispensed within appropriate admission period",
                details={
                    "encounter_id": encounter_id,
                    "admission_date": admission_date.isoformat(),
                    "medicine_date": medicine_date.isoformat(),
                    "discharge_date": discharge_date.isoformat() if discharge_date else None,
                    "length_of_stay_days": los_days,
                    "validation_status": "WITHIN_PERIOD"
                }
            )
            
        except Exception as e:
            logger.error(f"Error validating medicine dispensing period: {e}")
            return ValidationOutcome(
                result=ValidationResult.PENDING,
                reason=f"PEND: Error validating medicine dispensing period - {str(e)}",
                details={"error": str(e)}
            )
    
    async def validate_duplicate_claims(self, claim_data: Dict) -> ValidationOutcome:
        """
        ENHANCED: Same-Day Patient Claims Detection
        Primary focus: Only ONE claim per patient per admission date allowed
        Secondary: Next claim for same patient must be at least 7 days apart
        """
        try:
            nhis_number = claim_data.get('nhis_number')
            admission_date = claim_data.get('admission_date')
            encounter_id = claim_data.get('encounter_id')
            provider_name = claim_data.get('provider_name')
            icd10_code = claim_data.get('icd10_code')
            diagnosis_name = claim_data.get('diagnosis_name', '')
            
            if not nhis_number or not admission_date:
                return ValidationOutcome(
                    result=ValidationResult.FLAGGED,
                    reason="FLAG: Missing patient ID or admission date for duplicate checking",
                    details={"missing_data": ["nhis_number", "admission_date"]}
                )
            
            # Convert admission date
            if isinstance(admission_date, str):
                admission_date = datetime.fromisoformat(admission_date.replace('Z', '+00:00'))
            
            admission_date_only = admission_date.date()
            
            logger.info(f"🔍 Checking duplicates for patient {nhis_number} on {admission_date_only}")
            
            # PRIMARY CHECK: Same patient, same admission date (ANY other claim same day = DUPLICATE)
            same_day_query = """
            SELECT 
                encounter_id, 
                icd10_code, 
                diagnosis_name, 
                provider_name,
                claim_status,
                submitted_at,
                admission_date,
                total_claimed_amount,
                encounter_type
            FROM claims_v3 
            WHERE nhis_number = $1 
                AND DATE(admission_date) = $2
                AND encounter_id != $3
            ORDER BY submitted_at ASC
            """
            
            same_day_duplicates = await self.queries.db.fetch_all(
                same_day_query, nhis_number, admission_date_only, encounter_id
            )
            
            # If ANY claim exists for same patient on same admission date = IMMEDIATE REJECTION
            if same_day_duplicates:
                duplicate_details = []
                for dup in same_day_duplicates:
                    duplicate_details.append({
                        'encounter_id': dup['encounter_id'],
                        'diagnosis': dup['diagnosis_name'],
                        'provider': dup['provider_name'],
                        'claim_status': dup['claim_status'],
                        'submitted_at': dup['submitted_at'].isoformat() if dup['submitted_at'] else None,
                        'amount_claimed': dup.get('total_claimed_amount', 0)
                    })
                
                return ValidationOutcome(
                    result=ValidationResult.REJECTED,
                    reason="REJECT: Same-day duplicate claim - Only ONE claim allowed per patient per day",
                    details={
                        "violation_type": "SAME_DAY_DUPLICATE",
                        "admission_date": admission_date_only.isoformat(),
                        "patient_id": nhis_number,
                        "current_encounter": encounter_id,
                        "duplicate_count": len(same_day_duplicates),
                        "existing_claims": duplicate_details,
                        "policy": "STRICT: Maximum 1 claim per patient per admission date",
                        "action_required": "Cancel duplicate submission or consolidate claims",
                        "severity": "HIGH"
                    }
                )
            
            # SECONDARY CHECK: 7-day minimum gap between claims for same patient
            week_window_query = """
            SELECT 
                encounter_id,
                admission_date,
                icd10_code,
                diagnosis_name,
                provider_name,
                claim_status,
                ABS(EXTRACT(EPOCH FROM ($2::date - DATE(admission_date)))/86400) as days_apart
            FROM claims_v3 
            WHERE nhis_number = $1 
                AND encounter_id != $3
                AND ABS(EXTRACT(EPOCH FROM ($2::date - DATE(admission_date)))/86400) < 7
                AND ABS(EXTRACT(EPOCH FROM ($2::date - DATE(admission_date)))/86400) > 0
            ORDER BY admission_date DESC
            """
            
            recent_claims = await self.queries.db.fetch_all(
                week_window_query, nhis_number, admission_date_only, encounter_id
            )
            
            if recent_claims:
                violation_claims = []
                for claim in recent_claims:
                    days_gap = float(claim['days_apart'])
                    violation_claims.append({
                        'encounter_id': claim['encounter_id'],
                        'admission_date': claim['admission_date'].date().isoformat() if claim['admission_date'] else None,
                        'diagnosis': claim['diagnosis_name'],
                        'provider': claim['provider_name'],
                        'days_apart': round(days_gap, 1),
                        'claim_status': claim['claim_status']
                    })
                
                return ValidationOutcome(
                    result=ValidationResult.FLAGGED,
                    reason="FLAG: Claims submitted within 7-day minimum gap period",
                    details={
                        "violation_type": "INSUFFICIENT_GAP",
                        "minimum_gap_days": 7,
                        "patient_id": nhis_number,
                        "current_admission_date": admission_date_only.isoformat(),
                        "recent_claims_count": len(recent_claims),
                        "recent_claims": violation_claims,
                        "policy": "Claims for same patient should be minimum 7 days apart",
                        "requires_clinical_review": True,
                        "severity": "MEDIUM"
                    }
                )
            
            # ADDITIONAL CHECK: Cross-provider same-day shopping
            cross_provider_same_day_query = """
            SELECT 
                encounter_id,
                provider_name,
                icd10_code,
                diagnosis_name,
                total_claimed_amount
            FROM claims_v3 
            WHERE nhis_number = $1 
                AND DATE(admission_date) = $2
                AND provider_name != $3
                AND encounter_id != $4
            """
            
            cross_provider_claims = await self.queries.db.fetch_all(
                cross_provider_same_day_query, nhis_number, admission_date_only, provider_name, encounter_id
            )
            
            if cross_provider_claims:
                return ValidationOutcome(
                    result=ValidationResult.REJECTED,
                    reason="REJECT: Cross-provider same-day claims detected",
                    details={
                        "violation_type": "CROSS_PROVIDER_SAME_DAY",
                        "patient_id": nhis_number,
                        "admission_date": admission_date_only.isoformat(),
                        "current_provider": provider_name,
                        "other_providers": [c['provider_name'] for c in cross_provider_claims],
                        "other_encounters": [c['encounter_id'] for c in cross_provider_claims],
                        "concern": "Patient seeking treatment from multiple providers same day",
                        "severity": "HIGH"
                    }
                )
            
            # PATTERN CHECK: Frequent claims pattern (more than 4 claims in 30 days)
            frequent_claims_query = """
            SELECT COUNT(*) as claim_count,
                   MIN(admission_date) as earliest_date,
                   MAX(admission_date) as latest_date
            FROM claims_v3 
            WHERE nhis_number = $1 
                AND admission_date BETWEEN $2 AND $3
                AND encounter_id != $4
            """
            
            thirty_days_ago = admission_date_only - timedelta(days=30)
            thirty_days_forward = admission_date_only + timedelta(days=30)
            
            pattern_result = await self.queries.db.fetch_one(
                frequent_claims_query, nhis_number, thirty_days_ago, thirty_days_forward, encounter_id
            )
            
            if pattern_result and pattern_result['claim_count'] > 4:
                return ValidationOutcome(
                    result=ValidationResult.FLAGGED,
                    reason="FLAG: Frequent claims pattern detected",
                    details={
                        "violation_type": "FREQUENT_CLAIMS_PATTERN",
                        "patient_id": nhis_number,
                        "claims_in_30_days": pattern_result['claim_count'],
                        "threshold_exceeded": 4,
                        "date_range": f"{pattern_result['earliest_date']} to {pattern_result['latest_date']}",
                        "requires_investigation": True,
                        "concern": "Unusually high frequency of medical encounters"
                    }
                )
            
            logger.info(f"✅ No duplicate claims found for patient {nhis_number} on {admission_date_only}")
            
            return ValidationOutcome(
                result=ValidationResult.APPROVED,
                reason="No duplicate claims detected - Patient compliance with claim submission policy",
                details={
                    "patient_id": nhis_number,
                    "admission_date": admission_date_only.isoformat(),
                    "checks_performed": [
                        "same_day_duplicate",
                        "minimum_gap_validation", 
                        "cross_provider_check",
                        "frequent_pattern_analysis"
                    ],
                    "validation_status": "COMPLIANT",
                    "policy_adherence": "Patient follows one-claim-per-day rule"
                }
            )
            
        except Exception as e:
            logger.error(f"Error validating duplicate claims: {e}")
            return ValidationOutcome(
                result=ValidationResult.PENDING,
                reason=f"PEND: Error checking duplicate claims - {str(e)}",
                details={"error": str(e), "patient_id": claim_data.get('nhis_number')}
            )
    
    async def bulk_duplicate_analysis(self, days_back: int = 30) -> Dict[str, Any]:
        """
        BULK ANALYSIS: Scan entire claims_v3 table for duplicate patterns
        Focus on same-day patient duplicates across all claims
        """
        try:
            if not self.is_initialized:
                await self.initialize()
            
            logger.info(f"🔍 Starting bulk duplicate analysis for last {days_back} days")
            
            # Get all claims in the specified period
            bulk_query = """
            SELECT 
                encounter_id,
                nhis_number,
                admission_date,
                provider_name,
                icd10_code,
                diagnosis_name,
                encounter_type,
                claim_status,
                submitted_at,
                total_claimed_amount
            FROM claims_v3 
            WHERE admission_date >= $1
            ORDER BY nhis_number, admission_date, submitted_at
            """
            
            cutoff_date = datetime.now() - timedelta(days=days_back)
            all_claims = await self.queries.db.fetch_all(bulk_query, cutoff_date)
            
            logger.info(f"📊 Analyzing {len(all_claims)} claims for duplicates")
            
            # Group claims by patient and admission date
            patient_date_groups = {}
            total_violations = 0
            violation_details = []
            
            for claim in all_claims:
                patient_id = claim['nhis_number']
                admission_date = claim['admission_date'].date() if claim['admission_date'] else None
                
                if not admission_date:
                    continue
                
                key = (patient_id, admission_date)
                
                if key not in patient_date_groups:
                    patient_date_groups[key] = []
                
                patient_date_groups[key].append({
                    'encounter_id': claim['encounter_id'],
                    'provider': claim['provider_name'],
                    'diagnosis': claim['diagnosis_name'],
                    'icd10': claim['icd10_code'],
                    'encounter_type': claim['encounter_type'],
                    'claim_status': claim['claim_status'],
                    'submitted_at': claim['submitted_at'],
                    'amount': claim.get('total_claimed_amount', 0)
                })
            
            # Find duplicate violations
            for (patient_id, admission_date), claims_group in patient_date_groups.items():
                if len(claims_group) > 1:  # Multiple claims same patient same day = VIOLATION
                    total_violations += 1
                    
                    # Sort by submission time
                    claims_group.sort(key=lambda x: x['submitted_at'] or datetime.min)
                    
                    # Calculate total amount involved
                    total_amount = sum(c['amount'] for c in claims_group if c['amount'])
                    
                    # Check if cross-provider
                    providers = set(c['provider'] for c in claims_group)
                    is_cross_provider = len(providers) > 1
                    
                    # Check if same diagnosis
                    diagnoses = set(c['icd10'] for c in claims_group)
                    is_same_diagnosis = len(diagnoses) == 1
                    
                    violation_details.append({
                        'patient_id': patient_id,
                        'admission_date': admission_date.isoformat(),
                        'violation_type': 'SAME_DAY_MULTIPLE_CLAIMS',
                        'claim_count': len(claims_group),
                        'encounter_ids': [c['encounter_id'] for c in claims_group],
                        'providers_involved': list(providers),
                        'is_cross_provider': is_cross_provider,
                        'is_same_diagnosis': is_same_diagnosis,
                        'total_amount_involved': total_amount,
                        'claims_details': claims_group,
                        'severity': 'HIGH' if is_cross_provider or total_amount > 5000 else 'MEDIUM'
                    })
            
            # Additional analysis: 7-day gap violations
            gap_violations = []
            for patient_id in set(claim['nhis_number'] for claim in all_claims):
                patient_claims = [c for c in all_claims if c['nhis_number'] == patient_id]
                patient_claims.sort(key=lambda x: x['admission_date'] or datetime.min)
                
                for i in range(len(patient_claims) - 1):
                    current_date = patient_claims[i]['admission_date']
                    next_date = patient_claims[i + 1]['admission_date']
                    
                    if current_date and next_date:
                        days_gap = (next_date - current_date).days
                        
                        if 0 < days_gap < 7:  # Claims within 7 days
                            gap_violations.append({
                                'patient_id': patient_id,
                                'first_claim': patient_claims[i]['encounter_id'],
                                'second_claim': patient_claims[i + 1]['encounter_id'],
                                'first_date': current_date.date().isoformat(),
                                'second_date': next_date.date().isoformat(),
                                'days_gap': days_gap,
                                'violation_type': 'INSUFFICIENT_GAP'
                            })
            
            # Summary statistics
            unique_patients_with_violations = len(set(v['patient_id'] for v in violation_details))
            high_severity_violations = len([v for v in violation_details if v['severity'] == 'HIGH'])
            cross_provider_violations = len([v for v in violation_details if v['is_cross_provider']])
            
            summary = {
                'analysis_period_days': days_back,
                'total_claims_analyzed': len(all_claims),
                'total_patients_analyzed': len(set(claim['nhis_number'] for claim in all_claims)),
                'same_day_violations': {
                    'total_violations': total_violations,
                    'unique_patients_affected': unique_patients_with_violations,
                    'high_severity_count': high_severity_violations,
                    'cross_provider_count': cross_provider_violations,
                    'total_amount_involved': sum(v['total_amount_involved'] for v in violation_details)
                },
                'gap_violations': {
                    'total_gap_violations': len(gap_violations),
                    'patients_affected': len(set(v['patient_id'] for v in gap_violations))
                },
                'compliance_rate': f"{((len(all_claims) - total_violations) / len(all_claims) * 100):.2f}%" if all_claims else "0%"
            }
            
            logger.info(f"📋 Bulk analysis complete: {total_violations} same-day violations found")
            
            return {
                'summary': summary,
                'same_day_violations': violation_details,
                'gap_violations': gap_violations,
                'analysis_timestamp': datetime.now().isoformat()
            }
            
        except Exception as e:
            logger.error(f"Error in bulk duplicate analysis: {e}")
            return {
                'error': str(e),
                'analysis_timestamp': datetime.now().isoformat()
            }
    
    async def list_all_duplicates(self, days_back: int = 30, format_type: str = "detailed") -> List[DuplicateGroup]:
        """
        LIST ALL DUPLICATES: Get structured list of all duplicate violations
        """
        try:
            analysis_results = await self.bulk_duplicate_analysis(days_back)
            
            if 'error' in analysis_results:
                logger.error(f"Error getting duplicates list: {analysis_results['error']}")
                return []
            
            duplicates_list = []
            
            for violation in analysis_results['same_day_violations']:
                duplicate_group = DuplicateGroup(
                    patient_id=violation['patient_id'],
                    admission_date=violation['admission_date'],
                    claim_count=violation['claim_count'],
                    encounter_ids=violation['encounter_ids'],
                    providers_involved=violation['providers_involved'],
                    total_amount=violation['total_amount_involved'],
                    violation_type=violation['violation_type'],
                    severity=violation['severity'],
                    is_cross_provider=violation['is_cross_provider'],
                    claims_details=violation['claims_details']
                )
                duplicates_list.append(duplicate_group)
            
            # Sort by severity and amount
            duplicates_list.sort(key=lambda x: (x.severity == 'HIGH', x.total_amount), reverse=True)
            
            return duplicates_list
            
        except Exception as e:
            logger.error(f"Error listing duplicates: {e}")
            return []
    
    async def generate_duplicate_violations_report(self, days_back: int = 30) -> str:
        """
        Generate a comprehensive report of duplicate violations
        """
        analysis_results = await self.bulk_duplicate_analysis(days_back)
        
        if 'error' in analysis_results:
            return f"❌ Error generating report: {analysis_results['error']}"
        
        summary = analysis_results['summary']
        violations = analysis_results['same_day_violations']
        gap_violations = analysis_results['gap_violations']
        
        report = f"""
╔══════════════════════════════════════════════════════════════╗
║                    NHIS DUPLICATE CLAIMS REPORT             ║
║                  Analysis Period: {days_back} days                   ║
╚══════════════════════════════════════════════════════════════╝

📊 SUMMARY STATISTICS:
═══════════════════════════════════════════════════════════════
• Total Claims Analyzed: {summary['total_claims_analyzed']:,}
• Total Patients: {summary['total_patients_analyzed']:,}
• Overall Compliance Rate: {summary['compliance_rate']}

🚨 SAME-DAY VIOLATIONS (CRITICAL):
═══════════════════════════════════════════════════════════════
• Total Violations: {summary['same_day_violations']['total_violations']}
• Patients Affected: {summary['same_day_violations']['unique_patients_affected']}
• High Severity Cases: {summary['same_day_violations']['high_severity_count']}
• Cross-Provider Cases: {summary['same_day_violations']['cross_provider_count']}
• Total Amount Involved: GH₵{summary['same_day_violations']['total_amount_involved']:,.2f}

⚠️  7-DAY GAP VIOLATIONS:
═══════════════════════════════════════════════════════════════
• Total Gap Violations: {summary['gap_violations']['total_gap_violations']}
• Patients Affected: {summary['gap_violations']['patients_affected']}

📋 TOP VIOLATIONS DETAIL:
═══════════════════════════════════════════════════════════════
"""
        
        # Add top 10 violations
        sorted_violations = sorted(violations, key=lambda x: x['claim_count'], reverse=True)[:10]
        
        for i, violation in enumerate(sorted_violations, 1):
            report += f"""
{i}. Patient: {violation['patient_id']} | Date: {violation['admission_date']}
   Claims: {violation['claim_count']} | Severity: {violation['severity']}
   Providers: {', '.join(violation['providers_involved'])}
   Amount: GH₵{violation['total_amount_involved']:,.2f}
   Encounters: {', '.join(violation['encounter_ids'])}
"""
        
        report += f"""
═══════════════════════════════════════════════════════════════
Report Generated: {analysis_results['analysis_timestamp']}
System: NHIS Enhanced Duplicate Validator
═══════════════════════════════════════════════════════════════
"""
        
        return report
    
    async def validate_polypharmacy(self, medicines: List[Dict], claim_data: Dict = None) -> ValidationOutcome:
        """
        NEW: Comprehensive Polypharmacy and Drug Interaction Validation
        """
        try:
            if not medicines or len(medicines) == 0:
                return ValidationOutcome(
                    result=ValidationResult.APPROVED,
                    reason="No medicines to validate for polypharmacy",
                    details={"medicine_count": 0}
                )
            
            if len(medicines) == 1:
                return ValidationOutcome(
                    result=ValidationResult.APPROVED,
                    reason="Single medicine - no polypharmacy concerns",
                    details={"medicine_count": 1}
                )
            
            medicine_codes = [med.get('medicine_code', '').upper() for med in medicines]
            medicine_names = [med.get('medicine_name', '').upper() for med in medicines]
            
            # Check 1: Drug-drug interactions
            interactions_found = []
            
            for i, med_code in enumerate(medicine_codes):
                med_name = medicine_names[i] if i < len(medicine_names) else ""
                
                # Check against interaction database
                for drug, interaction_info in self.drug_interactions.items():
                    if drug in med_code or drug in med_name:
                        contraindicated = interaction_info['contraindicated']
                        
                        for j, other_med_code in enumerate(medicine_codes):
                            if i != j:  # Don't compare medicine with itself
                                other_med_name = medicine_names[j] if j < len(medicine_names) else ""
                                
                                for contraindicated_drug in contraindicated:
                                    if (contraindicated_drug in other_med_code or 
                                        contraindicated_drug in other_med_name):
                                        interactions_found.append({
                                            'medicine1': med_code,
                                            'medicine2': other_med_code,
                                            'interaction_drug1': drug,
                                            'interaction_drug2': contraindicated_drug,
                                            'severity': interaction_info['severity'],
                                            'effect': interaction_info['effect']
                                        })
            
            if interactions_found:
                # Determine result based on severity
                high_severity = any(int['severity'] == 'HIGH' for int in interactions_found)
                
                result_type = ValidationResult.REJECTED if high_severity else ValidationResult.FLAGGED
                reason = "REJECT: High-severity drug interactions detected" if high_severity else "FLAG: Drug interactions detected"
                
                return ValidationOutcome(
                    result=result_type,
                    reason=reason,
                    details={
                        "interactions": interactions_found,
                        "interaction_count": len(interactions_found),
                        "total_medicines": len(medicines),
                        "high_severity_count": len([i for i in interactions_found if i['severity'] == 'HIGH']),
                        "action_required": "Clinical review for drug interactions"
                    }
                )
            
            # Check 2: Excessive polypharmacy
            if len(medicines) > 10:
                return ValidationOutcome(
                    result=ValidationResult.REJECTED,
                    reason="REJECT: Excessive polypharmacy detected",
                    details={
                        "medicine_count": len(medicines),
                        "threshold_exceeded": 10,
                        "concern": "High risk of adverse drug events",
                        "action_required": "Clinical justification required"
                    }
                )
            elif len(medicines) > 5:
                return ValidationOutcome(
                    result=ValidationResult.FLAGGED,
                    reason="FLAG: Polypharmacy detected - clinical review recommended",
                    details={
                        "medicine_count": len(medicines),
                        "threshold": 5,
                        "recommendation": "Review for drug interactions and necessity",
                        "requires_clinical_review": True
                    }
                )
            
            # Check 3: Duplicate therapeutic classes
            therapeutic_classes = []
            duplicate_classes = []
            
            # Simple therapeutic classification (expandable)
            class_mapping = {
                'INSULIN': 'DIABETES',
                'METFORMIN': 'DIABETES',
                'GLIBENCLAMIDE': 'DIABETES',
                'ASPIRIN': 'ANTIPLATELET',
                'WARFARIN': 'ANTICOAGULANT',
                'HEPARIN': 'ANTICOAGULANT',
                'PARACETAMOL': 'ANALGESIC',
                'IBUPROFEN': 'NSAID',
                'DICLOFENAC': 'NSAID'
            }
            
            for med_code in medicine_codes:
                for drug, class_name in class_mapping.items():
                    if drug in med_code:
                        if class_name in therapeutic_classes:
                            duplicate_classes.append(class_name)
                        else:
                            therapeutic_classes.append(class_name)
            
            if duplicate_classes:
                return ValidationOutcome(
                    result=ValidationResult.FLAGGED,
                    reason="FLAG: Duplicate therapeutic classes detected",
                    details={
                        "duplicate_classes": list(set(duplicate_classes)),
                        "all_classes": therapeutic_classes,
                        "concern": "Multiple drugs from same therapeutic class",
                        "review_required": True
                    }
                )
            
            logger.info(f"✅ Polypharmacy validation passed for {len(medicines)} medicines")
            
            return ValidationOutcome(
                result=ValidationResult.APPROVED,
                reason="Polypharmacy validation passed",
                details={
                    "medicine_count": len(medicines),
                    "interactions_checked": True,
                    "therapeutic_class_analysis": "No duplicates found",
                    "validation_status": "SAFE_COMBINATION"
                }
            )
            
        except Exception as e:
            logger.error(f"Error validating polypharmacy: {e}")
            return ValidationOutcome(
                result=ValidationResult.PENDING,
                reason=f"PEND: Error validating polypharmacy - {str(e)}",
                details={"error": str(e)}
            )
    
    async def validate_gender_diagnosis_mismatch(self, claim_data: Dict) -> ValidationOutcome:
        """
        ENHANCED: Comprehensive Gender-Diagnosis Mismatch Validation
        """
        try:
            gender = claim_data.get('gender', '').upper()
            icd10_code = claim_data.get('icd10_code', '')
            diagnosis_name = claim_data.get('diagnosis_name', '').lower()
            encounter_id = claim_data.get('encounter_id')
            
            if not gender or not icd10_code:
                return ValidationOutcome(
                    result=ValidationResult.FLAGGED,
                    reason="FLAG: Missing gender or diagnosis for validation",
                    details={"missing_data": ["gender", "icd10_code"]}
                )
            
            # Check male-only conditions for female patients
            if gender == 'F':
                for condition_prefix in self.gender_conditions['male_only']['icd10_prefixes']:
                    if icd10_code.startswith(condition_prefix):
                        return ValidationOutcome(
                            result=ValidationResult.REJECTED,
                            reason="REJECT: Gender-diagnosis mismatch - male-only condition in female patient",
                            details={
                                "encounter_id": encounter_id,
                                "patient_gender": gender,
                                "icd10_code": icd10_code,
                                "diagnosis_name": claim_data.get('diagnosis_name'),
                                "condition_type": "MALE_ONLY",
                                "mismatch_severity": "HIGH"
                            }
                        )
                
                # Check male-only keywords in diagnosis text
                for keyword in self.gender_conditions['male_only']['keywords']:
                    if keyword in diagnosis_name:
                        return ValidationOutcome(
                            result=ValidationResult.FLAGGED,
                            reason="FLAG: Potential gender-diagnosis mismatch in diagnosis text",
                            details={
                                "encounter_id": encounter_id,
                                "patient_gender": gender,
                                "diagnosis_text": diagnosis_name,
                                "suspicious_keyword": keyword,
                                "requires_manual_review": True
                            }
                        )
            
            # Check female-only conditions for male patients
            if gender == 'M':
                for condition_prefix in self.gender_conditions['female_only']['icd10_prefixes']:
                    if icd10_code.startswith(condition_prefix):
                        return ValidationOutcome(
                            result=ValidationResult.REJECTED,
                            reason="REJECT: Gender-diagnosis mismatch - female-only condition in male patient",
                            details={
                                "encounter_id": encounter_id,
                                "patient_gender": gender,
                                "icd10_code": icd10_code,
                                "diagnosis_name": claim_data.get('diagnosis_name'),
                                "condition_type": "FEMALE_ONLY",
                                "mismatch_severity": "HIGH"
                            }
                        )
                
                # Check female-only keywords in diagnosis text
                for keyword in self.gender_conditions['female_only']['keywords']:
                    if keyword in diagnosis_name:
                        return ValidationOutcome(
                            result=ValidationResult.FLAGGED,
                            reason="FLAG: Potential gender-diagnosis mismatch in diagnosis text",
                            details={
                                "encounter_id": encounter_id,
                                "patient_gender": gender,
                                "diagnosis_text": diagnosis_name,
                                "suspicious_keyword": keyword,
                                "requires_manual_review": True
                            }
                        )
            
            # Additional age-gender checks for pediatric conditions
            patient_age = claim_data.get('calculated_age', 0)
            
            # Check for pregnancy-related conditions in male or very young female patients
            if icd10_code.startswith('O') or icd10_code.startswith('Z3'):
                if gender == 'M':
                    return ValidationOutcome(
                        result=ValidationResult.REJECTED,
                        reason="REJECT: Pregnancy-related diagnosis in male patient",
                        details={
                            "patient_gender": gender,
                            "diagnosis_category": "PREGNANCY_RELATED",
                            "mismatch_severity": "CRITICAL"
                        }
                    )
                elif gender == 'F' and patient_age < 10:
                    return ValidationOutcome(
                        result=ValidationResult.FLAGGED,
                        reason="FLAG: Pregnancy-related diagnosis in very young female patient",
                        details={
                            "patient_age": patient_age,
                            "patient_gender": gender,
                            "requires_age_verification": True
                        }
                    )
            
            logger.info(f"✅ Gender-diagnosis validation passed for {encounter_id}")
            
            return ValidationOutcome(
                result=ValidationResult.APPROVED,
                reason="Gender-diagnosis validation passed",
                details={
                    "encounter_id": encounter_id,
                    "patient_gender": gender,
                    "patient_age": patient_age,
                    "icd10_code": icd10_code,
                    "validation_status": "GENDER_APPROPRIATE"
                }
            )
            
        except Exception as e:
            logger.error(f"Error validating gender-diagnosis match: {e}")
            return ValidationOutcome(
                result=ValidationResult.PENDING,
                reason=f"PEND: Error validating gender-diagnosis match - {str(e)}",
                details={"error": str(e)}
            )
    
    async def validate_supporting_documents(self, claim_data: Dict) -> ValidationOutcome:
        """
        ENHANCED: Comprehensive Supporting Document Requirements Validation
        """
        try:
            encounter_type = claim_data.get('encounter_type')
            icd10_code = claim_data.get('icd10_code', '')
            gdrg_code = claim_data.get('gdrg_code', '')
            diagnosis_name = claim_data.get('diagnosis_name', '').lower()
            encounter_id = claim_data.get('encounter_id')
            patient_age = claim_data.get('calculated_age', 0)
            
            required_documents = []
            document_categories = []
            urgency_level = "ROUTINE"
            
            # Surgical procedures
            if gdrg_code.startswith('ASUR') or 'surgery' in diagnosis_name or 'operation' in diagnosis_name:
                required_documents.extend(self.document_requirements['surgical_procedures'])
                document_categories.append('SURGICAL')
                urgency_level = "HIGH"
            
            # ZOOM procedures (high-cost outpatient procedures)
            if gdrg_code.startswith('ZOOM'):
                required_documents.extend(self.document_requirements['high_cost_procedures'])
                document_categories.append('HIGH_COST')
                urgency_level = "HIGH"
            
            # Cancer diagnoses
            if icd10_code.startswith('C'):
                required_documents.extend(self.document_requirements['cancer_diagnosis'])
                document_categories.append('ONCOLOGY')
                urgency_level = "CRITICAL"
            
            # Emergency procedures
            if encounter_type == 'A&E' and any(term in diagnosis_name for term in ['surgery', 'operation', 'procedure']):
                required_documents.extend(self.document_requirements['emergency_surgery'])
                document_categories.append('EMERGENCY')
                urgency_level = "CRITICAL"
            
            # Chronic conditions requiring ongoing management
            chronic_icd10_prefixes = ['E1', 'I1', 'J44', 'N18', 'F2', 'F3']  # Diabetes, HTN, COPD, CKD, Mental health
            if any(icd10_code.startswith(prefix) for prefix in chronic_icd10_prefixes):
                required_documents.extend(self.document_requirements['chronic_conditions'])
                document_categories.append('CHRONIC')
            
            # Pediatric cases (special documentation requirements)
            if patient_age < 18:
                required_documents.extend(['Parental consent', 'Pediatric assessment'])
                document_categories.append('PEDIATRIC')
            
            # Geriatric cases (age > 80)
            if patient_age > 80:
                required_documents.extend(['Geriatric assessment', 'Functional status evaluation'])
                document_categories.append('GERIATRIC')
            
            # Mental health conditions
            if icd10_code.startswith('F'):
                required_documents.extend(['Mental health assessment', 'Risk evaluation'])
                document_categories.append('MENTAL_HEALTH')
                urgency_level = "HIGH"
            
            # Experimental or rare treatments
            experimental_keywords = ['experimental', 'trial', 'research', 'investigational']
            if any(keyword in diagnosis_name for keyword in experimental_keywords):
                required_documents.extend(self.document_requirements['experimental_treatments'])
                document_categories.append('EXPERIMENTAL')
                urgency_level = "CRITICAL"
            
            # Remove duplicates and sort
            required_documents = list(set(required_documents))
            required_documents.sort()
            
            # Determine submission deadline based on urgency
            deadline_mapping = {
                "ROUTINE": "14 days",
                "HIGH": "7 days", 
                "CRITICAL": "3 days"
            }
            
            deadline = deadline_mapping.get(urgency_level, "14 days")
            
            # For this implementation, simulate document checking
            # In a real system, you'd check against uploaded documents in a documents table
            documents_submitted = []  # This would come from document management system
            missing_documents = required_documents  # Simulate all documents missing
            
            # Determine result based on requirements
            if not required_documents:
                return ValidationOutcome(
                    result=ValidationResult.APPROVED,
                    reason="No supporting documents required",
                    details={
                        "encounter_id": encounter_id,
                        "document_requirements": "NONE",
                        "categories": document_categories
                    }
                )
            
            if missing_documents:
                # Determine severity based on document category and urgency
                if urgency_level == "CRITICAL":
                    result_type = ValidationResult.REJECTED
                    reason = "REJECT: Critical supporting documents missing"
                elif urgency_level == "HIGH":
                    result_type = ValidationResult.FLAGGED
                    reason = "FLAG: Important supporting documents required"
                else:
                    result_type = ValidationResult.FLAGGED
                    reason = "FLAG: Supporting documents required"
                
                return ValidationOutcome(
                    result=result_type,
                    reason=reason,
                    details={
                        "encounter_id": encounter_id,
                        "required_documents": required_documents,
                        "missing_documents": missing_documents,
                        "document_categories": document_categories,
                        "urgency_level": urgency_level,
                        "submission_deadline": deadline,
                        "total_required": len(required_documents),
                        "total_missing": len(missing_documents),
                        "compliance_rate": f"{((len(required_documents) - len(missing_documents)) / len(required_documents) * 100):.1f}%",
                        "next_action": f"Submit missing documents within {deadline}"
                    }
                )
            
            logger.info(f"✅ Supporting documents validation passed for {encounter_id}")
            
            return ValidationOutcome(
                result=ValidationResult.APPROVED,
                reason="All supporting document requirements met",
                details={
                    "encounter_id": encounter_id,
                    "required_documents": required_documents,
                    "document_categories": document_categories,
                    "compliance_status": "COMPLETE",
                    "total_documents": len(required_documents)
                }
            )
            
        except Exception as e:
            logger.error(f"Error validating supporting documents: {e}")
            return ValidationOutcome(
                result=ValidationResult.PENDING,
                reason=f"PEND: Error validating supporting documents - {str(e)}",
                details={"error": str(e)}
            )
    
    async def run_all_enhanced_validations(self, encounter_id: str) -> Dict[str, ValidationOutcome]:
        """
        MASTER METHOD: Run all enhanced validations for a claim
        """
        try:
            if not self.is_initialized:
                await self.initialize()
            
            # Get claim data
            claim_data = await self.queries.get_claim_with_calculated_age(encounter_id)
            if not claim_data:
                return {
                    "error": ValidationOutcome(
                        result=ValidationResult.REJECTED,
                        reason="REJECT: Claim not found",
                        details={"encounter_id": encounter_id}
                    )
                }
            
            logger.info(f"🔍 Running enhanced validations for {encounter_id}")
            
            results = {}
            
            # 1. Medicine dispensing period validation
            results["medicine_dispensing_period"] = await self.validate_medicine_dispensing_period(claim_data)
            
            # 2. Duplicate claims validation (ENHANCED)
            results["duplicate_claims"] = await self.validate_duplicate_claims(claim_data)
            
            # 3. Gender-diagnosis mismatch validation
            results["gender_diagnosis_mismatch"] = await self.validate_gender_diagnosis_mismatch(claim_data)
            
            # 4. Supporting documents validation
            results["supporting_documents"] = await self.validate_supporting_documents(claim_data)
            
            # 5. Polypharmacy validation
            medicines = []
            if claim_data.get('medicine_code') and claim_data['medicine_code'] not in ['NA', '', None]:
                medicines.append({
                    'medicine_code': claim_data['medicine_code'],
                    'medicine_name': claim_data.get('medicine_name', '')
                })
            if claim_data.get('medicine_code_procedure') and claim_data['medicine_code_procedure'] not in ['NA', '', None]:
                medicines.append({
                    'medicine_code': claim_data['medicine_code_procedure'],
                    'medicine_name': claim_data.get('medicine_name_procedure', '')
                })
            
            results["polypharmacy"] = await self.validate_polypharmacy(medicines, claim_data)
            
            # Summary statistics
            total_checks = len(results)
            approved = len([r for r in results.values() if r.result == ValidationResult.APPROVED])
            rejected = len([r for r in results.values() if r.result == ValidationResult.REJECTED])
            flagged = len([r for r in results.values() if r.result == ValidationResult.FLAGGED])
            pending = len([r for r in results.values() if r.result == ValidationResult.PENDING])
            
            results["summary"] = ValidationOutcome(
                result=ValidationResult.APPROVED if rejected == 0 else ValidationResult.REJECTED if rejected > 0 else ValidationResult.FLAGGED,
                reason=f"Enhanced validations completed: {approved} approved, {rejected} rejected, {flagged} flagged",
                details={
                    "encounter_id": encounter_id,
                    "total_checks": total_checks,
                    "approved": approved,
                    "rejected": rejected,
                    "flagged": flagged,
                    "pending": pending,
                    "success_rate": f"{(approved / total_checks * 100):.1f}%",
                    "validation_timestamp": datetime.now().isoformat()
                }
            )
            
            logger.info(f"✅ Enhanced validations completed for {encounter_id}: {approved}/{total_checks} passed")
            return results
            
        except Exception as e:
            logger.error(f"Error running enhanced validations: {e}")
            return {
                "error": ValidationOutcome(
                    result=ValidationResult.PENDING,
                    reason=f"PEND: Error running enhanced validations - {str(e)}",
                    details={"error": str(e)}
                )
            }
    
    async def validate_multiple_claims(self, encounter_ids: List[str]) -> Dict[str, Dict[str, ValidationOutcome]]:
        """
        BATCH PROCESSING: Run enhanced validations for multiple claims
        """
        results = {}
        
        for encounter_id in encounter_ids:
            try:
                claim_results = await self.run_all_enhanced_validations(encounter_id)
                results[encounter_id] = claim_results
                
                # Log summary for each claim
                if "summary" in claim_results:
                    summary = claim_results["summary"]
                    status_emoji = "✅" if summary.result == ValidationResult.APPROVED else "⚠️" if summary.result == ValidationResult.FLAGGED else "❌"
                    logger.info(f"{status_emoji} {encounter_id}: {summary.reason}")
                
            except Exception as e:
                logger.error(f"Error processing {encounter_id}: {e}")
                results[encounter_id] = {
                    "error": ValidationOutcome(
                        result=ValidationResult.PENDING,
                        reason=f"PEND: Processing error - {str(e)}",
                        details={"encounter_id": encounter_id}
                    )
                }
        
        return results

# Additional standalone functions for duplicate checking
async def check_patient_same_day_duplicates(nhis_number: str, admission_date: str) -> Dict[str, Any]:
    """
    STANDALONE: Quick check for same-day duplicates for a specific patient
    """
    validator = EnhancedValidations()
    try:
        await validator.initialize()
        
        # Convert date string to date object
        if isinstance(admission_date, str):
            if 'T' in admission_date:
                check_date = datetime.fromisoformat(admission_date.replace('Z', '+00:00')).date()
            else:
                check_date = datetime.strptime(admission_date, '%Y-%m-%d').date()
        else:
            check_date = admission_date
        
        # Query for same-day claims
        query = """
        SELECT 
            encounter_id,
            provider_name,
            icd10_code,
            diagnosis_name,
            encounter_type,
            claim_status,
            submitted_at,
            total_claimed_amount
        FROM claims_v3 
        WHERE nhis_number = $1 
            AND DATE(admission_date) = $2
        ORDER BY submitted_at
        """
        
        same_day_claims = await validator.queries.db.fetch_all(query, nhis_number, check_date)
        
        result = {
            'patient_id': nhis_number,
            'admission_date': check_date.isoformat(),
            'total_claims': len(same_day_claims),
            'has_duplicates': len(same_day_claims) > 1,
            'violation_severity': 'NONE'
        }
        
        if len(same_day_claims) > 1:
            result['violation_severity'] = 'HIGH'
            result['duplicate_details'] = []
            
            providers = set()
            total_amount = 0
            
            for claim in same_day_claims:
                providers.add(claim['provider_name'])
                total_amount += claim.get('total_claimed_amount', 0)
                
                result['duplicate_details'].append({
                    'encounter_id': claim['encounter_id'],
                    'provider': claim['provider_name'],
                    'diagnosis': claim['diagnosis_name'],
                    'icd10': claim['icd10_code'],
                    'encounter_type': claim['encounter_type'],
                    'status': claim['claim_status'],
                    'amount': claim.get('total_claimed_amount', 0)
                })
            
            result['cross_provider'] = len(providers) > 1
            result['total_amount_involved'] = total_amount
            result['providers_involved'] = list(providers)
        
        return result
        
    finally:
        await validator.close()

async def run_daily_duplicate_scan() -> Dict[str, Any]:
    """
    SCHEDULED: Daily scan for duplicate violations across all recent claims
    """
    validator = EnhancedValidations()
    try:
        await validator.initialize()
        
        # Scan last 3 days for new duplicates
        return await validator.bulk_duplicate_analysis(days_back=3)
        
    finally:
        await validator.close()

async def generate_weekly_duplicate_report() -> str:
    """
    REPORTING: Generate weekly duplicate violations report
    """
    validator = EnhancedValidations()
    try:
        await validator.initialize()
        return await validator.generate_duplicate_violations_report(days_back=7)
    finally:
        await validator.close()

async def get_all_duplicates_list(days_back: int = 30) -> List[DuplicateGroup]:
    """
    PUBLIC API: Get structured list of all duplicate violations
    """
    validator = EnhancedValidations()
    try:
        await validator.initialize()
        return await validator.list_all_duplicates(days_back)
    finally:
        await validator.close()

# Integration functions for existing system
async def integrate_enhanced_validations_into_orchestrator(encounter_id: str) -> Dict[str, ValidationOutcome]:
    """
    INTEGRATION FUNCTION: Use this to integrate enhanced validations into master_orchestrator.py
    
    Add this call in your master orchestrator after Stage 6 (Medicine Validation)
    and before Stage 7 (Final Processing)
    """
    enhanced_validator = EnhancedValidations()
    
    try:
        await enhanced_validator.initialize()
        results = await enhanced_validator.run_all_enhanced_validations(encounter_id)
        return results
    finally:
        await enhanced_validator.close()

async def integrate_duplicate_validation_only(encounter_id: str) -> ValidationOutcome:
    """
    INTEGRATION: Just run duplicate validation for a single claim
    """
    validator = EnhancedValidations()
    
    try:
        await validator.initialize()
        
        # Get claim data
        claim_data = await validator.queries.get_claim_with_calculated_age(encounter_id)
        if not claim_data:
            return ValidationOutcome(
                result=ValidationResult.REJECTED,
                reason="REJECT: Claim not found for duplicate validation",
                details={"encounter_id": encounter_id}
            )
        
        # Run only duplicate validation
        return await validator.validate_duplicate_claims(claim_data)
        
    except Exception as e:
        logger.error(f"Error in duplicate validation integration: {e}")
        return ValidationOutcome(
            result=ValidationResult.PENDING,
            reason=f"PEND: Error in duplicate validation - {str(e)}",
            details={"encounter_id": encounter_id, "error": str(e)}
        )
    finally:
        await validator.close()

# Testing and demonstration functions
async def test_enhanced_validations():
    """
    Test function to demonstrate enhanced validations including duplicates
    """
    enhanced = EnhancedValidations()
    
    try:
        await enhanced.initialize()
        
        print(f"\n🔍 TESTING ENHANCED VALIDATIONS WITH DUPLICATE DETECTION")
        print("=" * 70)
        
        # Test individual claim
        test_encounter_id = "LIN-3012-BUYW"
        
        print(f"\n1️⃣ Testing individual claim: {test_encounter_id}")
        results = await enhanced.run_all_enhanced_validations(test_encounter_id)
        
        for validation_type, result in results.items():
            print(f"\n📋 {validation_type.upper().replace('_', ' ')}:")
            print(f"  Status: {result.result.value}")
            print(f"  Reason: {result.reason}")
            
            if result.details:
                print(f"  Details:")
                for key, value in result.details.items():
                    if isinstance(value, list) and len(value) > 3:
                        print(f"    {key}: {len(value)} items")
                    else:
                        print(f"    {key}: {value}")
        
        # Test bulk duplicate analysis
        print(f"\n2️⃣ Running bulk duplicate analysis...")
        bulk_results = await enhanced.bulk_duplicate_analysis(days_back=7)
        
        if 'summary' in bulk_results:
            summary = bulk_results['summary']
            print(f"   Claims analyzed: {summary['total_claims_analyzed']}")
            print(f"   Same-day violations: {summary['same_day_violations']['total_violations']}")
            print(f"   Compliance rate: {summary['compliance_rate']}")
        
        # Test duplicate listing
        print(f"\n3️⃣ Getting structured duplicates list...")
        duplicates_list = await enhanced.list_all_duplicates(days_back=7)
        print(f"   Total duplicate groups found: {len(duplicates_list)}")
        
        for i, dup in enumerate(duplicates_list[:3], 1):  # Show first 3
            print(f"   {i}. Patient {dup.patient_id}: {dup.claim_count} claims on {dup.admission_date}")
            print(f"      Severity: {dup.severity}, Amount: GH₵{dup.total_amount:.2f}")
        
        # Test patient-specific check
        print(f"\n4️⃣ Testing patient-specific duplicate check...")
        patient_check = await check_patient_same_day_duplicates('TEST123456', '2024-12-01')
        print(f"   Patient: {patient_check['patient_id']}")
        print(f"   Has duplicates: {patient_check['has_duplicates']}")
        print(f"   Total claims: {patient_check['total_claims']}")
        
        # Generate sample report
        print(f"\n5️⃣ Generating sample duplicate report...")
        report = await enhanced.generate_duplicate_violations_report(days_back=7)
        print("   Report generated successfully ✅")
        print(f"   Report length: {len(report)} characters")
        
        print(f"\n✅ ENHANCED VALIDATIONS WITH DUPLICATES TEST COMPLETED")
        
    except Exception as e:
        print(f"❌ Test failed: {e}")
    finally:
        await enhanced.close()

async def test_duplicate_detection_only():
    """
    Test ONLY the duplicate detection functionality
    """
    enhanced = EnhancedValidations()
    
    try:
        await enhanced.initialize()
        
        print(f"\n🔍 TESTING DUPLICATE DETECTION SYSTEM")
        print("=" * 50)
        
        # Test bulk analysis
        print(f"\n📊 Running bulk duplicate analysis (last 30 days)...")
        bulk_results = await enhanced.bulk_duplicate_analysis(days_back=30)
        
        if 'error' in bulk_results:
            print(f"   ❌ Error: {bulk_results['error']}")
            return
        
        summary = bulk_results['summary']
        violations = bulk_results['same_day_violations']
        gap_violations = bulk_results['gap_violations']
        
        print(f"\n📈 SUMMARY STATISTICS:")
        print(f"   • Total Claims Analyzed: {summary['total_claims_analyzed']:,}")
        print(f"   • Total Patients: {summary['total_patients_analyzed']:,}")
        print(f"   • Compliance Rate: {summary['compliance_rate']}")
        print(f"   • Same-day Violations: {summary['same_day_violations']['total_violations']}")
        print(f"   • Patients Affected: {summary['same_day_violations']['unique_patients_affected']}")
        print(f"   • High Severity Cases: {summary['same_day_violations']['high_severity_count']}")
        print(f"   • Cross-provider Cases: {summary['same_day_violations']['cross_provider_count']}")
        print(f"   • Total Amount Involved: GH₵{summary['same_day_violations']['total_amount_involved']:,.2f}")
        
        if violations:
            print(f"\n🚨 TOP 5 VIOLATIONS:")
            top_violations = sorted(violations, key=lambda x: x['total_amount_involved'], reverse=True)[:5]
            
            for i, violation in enumerate(top_violations, 1):
                print(f"\n   {i}. Patient: {violation['patient_id']}")
                print(f"      Date: {violation['admission_date']}")
                print(f"      Claims: {violation['claim_count']} | Severity: {violation['severity']}")
                print(f"      Providers: {', '.join(violation['providers_involved'])}")
                print(f"      Amount: GH₵{violation['total_amount_involved']:,.2f}")
                print(f"      Cross-provider: {'Yes' if violation['is_cross_provider'] else 'No'}")
                print(f"      Encounters: {', '.join(violation['encounter_ids'])}")
        
        # Test structured duplicates list
        print(f"\n📋 STRUCTURED DUPLICATES LIST:")
        duplicates_list = await enhanced.list_all_duplicates(days_back=30)
        print(f"   Total duplicate groups: {len(duplicates_list)}")
        
        high_severity = [d for d in duplicates_list if d.severity == 'HIGH']
        cross_provider = [d for d in duplicates_list if d.is_cross_provider]
        
        print(f"   High severity groups: {len(high_severity)}")
        print(f"   Cross-provider groups: {len(cross_provider)}")
        
        if duplicates_list:
            print(f"\n   Sample duplicate group:")
            sample = duplicates_list[0]
            print(f"   • Patient: {sample.patient_id}")
            print(f"   • Date: {sample.admission_date}")
            print(f"   • Claims: {sample.claim_count}")
            print(f"   • Providers: {', '.join(sample.providers_involved)}")
            print(f"   • Amount: GH₵{sample.total_amount:.2f}")
            print(f"   • Type: {sample.violation_type}")
        
        # Generate and display report excerpt
        print(f"\n📄 GENERATING COMPREHENSIVE REPORT...")
        report = await enhanced.generate_duplicate_violations_report(days_back=30)
        
        # Show first 1000 characters of report
        print(f"\n📝 REPORT EXCERPT:")
        print(report[:1000] + "..." if len(report) > 1000 else report)
        
        print(f"\n✅ DUPLICATE DETECTION TEST COMPLETED")
        print(f"   Full report length: {len(report):,} characters")
        
    except Exception as e:
        print(f"❌ Duplicate detection test failed: {e}")
        import traceback
        traceback.print_exc()
    finally:
        await enhanced.close()

# Command line utilities
async def cli_duplicate_scan(days: int = 7):
    """
    Command line utility for duplicate scanning
    """
    print(f"🔍 Scanning for duplicates in last {days} days...")
    
    validator = EnhancedValidations()
    try:
        await validator.initialize()
        results = await validator.bulk_duplicate_analysis(days_back=days)
        
        if 'error' in results:
            print(f"❌ Error: {results['error']}")
            return
        
        summary = results['summary']
        print(f"\n📊 SCAN RESULTS:")
        print(f"   Claims analyzed: {summary['total_claims_analyzed']:,}")
        print(f"   Violations found: {summary['same_day_violations']['total_violations']}")
        print(f"   Compliance rate: {summary['compliance_rate']}")
        
        if summary['same_day_violations']['total_violations'] > 0:
            print(f"\n⚠️  ACTION REQUIRED:")
            print(f"   {summary['same_day_violations']['unique_patients_affected']} patients have duplicate claims")
            print(f"   {summary['same_day_violations']['high_severity_count']} high severity cases need immediate attention")
            print(f"   Total amount involved: GH₵{summary['same_day_violations']['total_amount_involved']:,.2f}")
        else:
            print(f"\n✅ No duplicate violations found!")
            
    finally:
        await validator.close()

async def cli_patient_duplicates(nhis_number: str, date: str = None):
    """
    Command line utility to check specific patient for duplicates
    """
    if not date:
        date = datetime.now().strftime('%Y-%m-%d')
    
    print(f"🔍 Checking patient {nhis_number} for duplicates on {date}...")
    
    result = await check_patient_same_day_duplicates(nhis_number, date)
    
    print(f"\n📋 RESULTS:")
    print(f"   Patient ID: {result['patient_id']}")
    print(f"   Date: {result['admission_date']}")
    print(f"   Total claims: {result['total_claims']}")
    print(f"   Has duplicates: {'YES' if result['has_duplicates'] else 'NO'}")
    print(f"   Severity: {result['violation_severity']}")
    
    if result['has_duplicates']:
        print(f"\n🚨 DUPLICATE DETAILS:")
        print(f"   Cross-provider: {'YES' if result['cross_provider'] else 'NO'}")
        print(f"   Total amount: GH₵{result['total_amount_involved']:,.2f}")
        print(f"   Providers involved: {', '.join(result['providers_involved'])}")
        
        print(f"\n📄 CLAIMS BREAKDOWN:")
        for i, claim in enumerate(result['duplicate_details'], 1):
            print(f"   {i}. {claim['encounter_id']} - {claim['provider']}")
            print(f"      Diagnosis: {claim['diagnosis']}")
            print(f"      Status: {claim['status']}")
            print(f"      Amount: GH₵{claim['amount']:,.2f}")

# Main execution with command line interface
if __name__ == "__main__":
    import sys
    
    if len(sys.argv) > 1:
        command = sys.argv[1].lower()
        
        if command == "test":
            asyncio.run(test_enhanced_validations())
        elif command == "test-duplicates":
            asyncio.run(test_duplicate_detection_only())
        elif command == "scan":
            days = int(sys.argv[2]) if len(sys.argv) > 2 else 7
            asyncio.run(cli_duplicate_scan(days))
        elif command == "patient":
            if len(sys.argv) < 3:
                print("Usage: python script.py patient <nhis_number> [date]")
                sys.exit(1)
            nhis_number = sys.argv[2]
            date = sys.argv[3] if len(sys.argv) > 3 else None
            asyncio.run(cli_patient_duplicates(nhis_number, date))
        elif command == "report":
            days = int(sys.argv[2]) if len(sys.argv) > 2 else 7
            report = asyncio.run(generate_weekly_duplicate_report())
            print(report)
        elif command == "bulk":
            days = int(sys.argv[2]) if len(sys.argv) > 2 else 3
            results = asyncio.run(run_daily_duplicate_scan())
            print(json.dumps(results, indent=2, default=str))
        else:
            print("Available commands:")
            print("  test                    - Run full enhanced validations test")
            print("  test-duplicates         - Run only duplicate detection test")
            print("  scan [days]            - Scan for duplicates (default: 7 days)")
            print("  patient <nhis> [date]  - Check specific patient for duplicates")
            print("  report [days]          - Generate duplicate violations report")
            print("  bulk [days]            - Run bulk analysis and output JSON")
    else:
        # Default: run comprehensive test
        asyncio.run(test_enhanced_validations())