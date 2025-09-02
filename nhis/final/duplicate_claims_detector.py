import asyncio
import json
import logging
from typing import Dict, List, Optional, Any, Tuple, Set
from dataclasses import dataclass
from enum import Enum
from datetime import datetime, date, timedelta
import hashlib

# Import our database connection
from neon_db_connection import get_nhis_queries, initialize_database, close_database

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class DuplicateType(Enum):
    """Types of duplicate claims"""
    DIFFERENT_ENCOUNTER_SAME_INFO = "DIFFERENT_ENCOUNTER_SAME_INFO"  # Different encounter_id, same info
    SAME_ENCOUNTER_DIFFERENT_INFO = "SAME_ENCOUNTER_DIFFERENT_INFO"  # Same encounter_id, different info
    SAME_DAY_VISITS = "SAME_DAY_VISITS"  
    EXACT_DUPLICATE = "EXACT_DUPLICATE"  # Completely identical claims
    PARTIAL_DUPLICATE = "PARTIAL_DUPLICATE"  # Similar but not identical

class DuplicateFlag(Enum):
    """Duplicate flag status"""
    CLEAN = "CLEAN"
    flagged = "flagged"
    SUSPICIOUS = "SUSPICIOUS"
    

@dataclass
class DuplicateMatch:
    """Represents a duplicate match between claims"""
    primary_encounter_id: str
    duplicate_encounter_id: str
    duplicate_type: DuplicateType
    confidence_score: float
    matching_fields: List[str]
    differing_fields: List[str]
    detection_timestamp: datetime
    details: Dict[str, Any]
    
    def __post_init__(self):
        if self.detection_timestamp is None:
            self.detection_timestamp = datetime.now()

@dataclass
class DuplicateDetectionResult:
    """Result of duplicate detection process"""
    encounter_id: str
    flag_status: DuplicateFlag
    duplicate_matches: List[DuplicateMatch]
    total_duplicates_found: int
    highest_confidence_match: Optional[DuplicateMatch]
    recommendation: str
    details: Dict[str, Any]
    timestamp: datetime = None
    
    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.now()

class DuplicateClaimsDetector:
    """
    Pre-processing duplicate claims detector
    Identifies and flags all types of duplicate claims before validation
    """
    
    def __init__(self):
        self.queries = None
        self.is_initialized = False
        
        # Fields to compare for duplicates - ALL fields from schema
        self.critical_fields = [
            # Patient identifying fields
            'last_name', 'other_names', 'date_of_birth', 'gender', 'nhis_number',
            
            # Provider fields
            'provider_id', 'provider_name', 'district', 'provider_type', 
            'healthcare_level', 'prescriber_level',
            
            # Encounter fields
            'encounter_id', 'encounter_type', 'admission_date', 'discharge_date',
            'service_type_1', 'service_type_2', 'service_outcome', 'attendance_type',
            'specialties_attended', 'specialty_code',
            
            # Diagnosis fields
            'diagnosis_name', 'icd10_diagnosis', 'icd10_code', 'g_drg_diagnosis',
            'gdrg_code', 'gdrg_description',
            
            # Procedure fields
            'procedure_name', 'icd10_procedure', 'icd10_code_procedure',
            'icd10_description_procedure', 'specialty_code_procedure',
            'g_drg_procedure', 'gdrg_code_procedure', 'gdrg_description_procedure',
            'level_procedure', 'procedure_date',
            
            # Medicine fields
            'medicine_code', 'medicine_name', 'medicine_code_procedure',
            'medicine_name_procedure', 'dosage', 'standard_dosage',
            'standard_dosage_procedure', 'frequency', 'frequency_procedure',
            'duration', 'duration_days', 'duration_days_procedure', 'medicine_date',
            
            # Investigation fields
            'g_drg_inve', 'description_inve'
        ]
        
        # Patient identifying fields (high priority for duplicate detection)
        self.identifying_fields = [
            'last_name', 'other_names', 'date_of_birth', 'gender', 'nhis_number'
        ]
        
        # Clinical core fields (medium priority)
        self.clinical_fields = [
            'diagnosis_name', 'icd10_diagnosis', 'icd10_code', 'gdrg_code',
            'procedure_name', 'icd10_procedure', 'medicine_name', 'medicine_code',
            'standard_dosage', 'frequency', 'duration_days'
        ]
        
        # Administrative fields (lower priority but important for context)
        self.administrative_fields = [
            'provider_id', 'provider_name', 'encounter_type', 'admission_date',
            'discharge_date', 'service_type_1', 'service_type_2'
        ]
        
        # Confidence thresholds
        self.confidence_thresholds = {
            "high": 0.9,      # Block/Reject
            "medium": 0.7,    # Flag for review
            "low": 0.5        # Suspicious
        }
    
    async def initialize(self):
        """Initialize database connection and ensure schema is ready"""
        if not self.is_initialized:
            await initialize_database()
            self.queries = await get_nhis_queries()
            
            # Ensure database schema supports duplicate detection
            await self._update_claims_schema_if_needed()
            await self._ensure_duplicate_log_table_exists()
            
            self.is_initialized = True
            logger.info("Duplicate Claims Detector initialized with database schema ready")
    
    async def close(self):
        """Close database connections"""
        await close_database()
        self.is_initialized = False
        logger.info("Duplicate Claims Detector closed")
    
    async def detect_all_duplicates(self, encounter_id: str) -> DuplicateDetectionResult:
        """
        Main entry point: Detect all types of duplicates for a single claim
        Updates database status for flagged claims
        """
        if not self.is_initialized:
            await self.initialize()
        
        try:
            logger.info(f"DUPLICATE DETECTION: Starting for encounter {encounter_id}")
            
            # Get the claim data
            claim = await self.queries.get_claim_by_encounter_id(encounter_id)
            if not claim:
                return DuplicateDetectionResult(
                    encounter_id=encounter_id,
                    flag_status=DuplicateFlag.CLEAN,
                    duplicate_matches=[],
                    total_duplicates_found=0,
                    highest_confidence_match=None,
                    recommendation="PROCEED: Claim not found in database",
                    details={"error": "Claim not found"}
                )
            
            all_matches = []
            
            # 1. Check for different encounter IDs with same information
            same_info_matches = await self._detect_different_encounter_same_info(claim)
            all_matches.extend(same_info_matches)
            
            # 2. Check for same encounter ID with different information
            different_info_matches = await self._detect_same_encounter_different_info(claim)
            all_matches.extend(different_info_matches)
            
            # 3. Check for same-day visits by same patient
            same_day_matches = await self._detect_same_day_visits(claim)
            all_matches.extend(same_day_matches)
            
            # 4. Check for exact duplicates
            exact_matches = await self._detect_exact_duplicates(claim)
            all_matches.extend(exact_matches)
            
            # Analyze results and determine flag status
            result = await self._analyze_duplicate_matches(encounter_id, all_matches, claim)
            
            # Update database status if duplicates are found
            if result.flag_status in [DuplicateFlag.flagged, DuplicateFlag.flagged]:
                await self._update_claim_duplicate_status(encounter_id, result)
            
            logger.info(f"DUPLICATE DETECTION COMPLETED for {encounter_id}: {result.flag_status.value} ({result.total_duplicates_found} duplicates)")
            
            return result
            
        except Exception as e:
            logger.error(f"Error in duplicate detection: {e}")
            return DuplicateDetectionResult(
                encounter_id=encounter_id,
                flag_status=DuplicateFlag.SUSPICIOUS,
                duplicate_matches=[],
                total_duplicates_found=0,
                highest_confidence_match=None,
                recommendation="MANUAL REVIEW: System error during duplicate detection",
                details={"error": str(e)}
            )
    
    async def _detect_different_encounter_same_info(self, claim: Dict) -> List[DuplicateMatch]:
        """
        Type 1: Different encounter_id but same information - using ALL fields
        """
        try:
            encounter_id = claim['encounter_id']
            
            # Find other claims with same core patient and clinical info but different encounter_id
            query = """
            SELECT 
                provider_id, provider_name, district, provider_type, healthcare_level, prescriber_level,
                last_name, other_names, date_of_birth, gender, nhis_number,
                encounter_id, encounter_type, admission_date, discharge_date,
                service_type_1, service_type_2, service_outcome, attendance_type,
                specialties_attended, specialty_code,
                diagnosis_name, icd10_diagnosis, icd10_code, g_drg_diagnosis, gdrg_code, gdrg_description,
                procedure_name, icd10_procedure, icd10_code_procedure, icd10_description_procedure,
                specialty_code_procedure, g_drg_procedure, gdrg_code_procedure, gdrg_description_procedure,
                level_procedure, procedure_date,
                medicine_code, medicine_name, medicine_code_procedure, medicine_name_procedure,
                dosage, standard_dosage, standard_dosage_procedure, frequency, frequency_procedure,
                duration, duration_days, duration_days_procedure, medicine_date,
                g_drg_inve, description_inve, submitted_at
            FROM claims_v3 
            WHERE encounter_id != $1
            AND last_name = $2
            AND other_names = $3
            AND date_of_birth = $4
            AND gender = $5
            AND COALESCE(diagnosis_name, '') = COALESCE($6, '')
            AND COALESCE(icd10_code, '') = COALESCE($7, '')
            AND COALESCE(gdrg_code, '') = COALESCE($8, '')
            ORDER BY submitted_at DESC
            LIMIT 50
            """
            
            potential_duplicates = await self.queries.db.fetch_all(
                query,
                encounter_id,
                claim.get('last_name', ''),
                claim.get('other_names', ''), 
                claim.get('date_of_birth'),
                claim.get('gender', ''),
                claim.get('diagnosis_name'),
                claim.get('icd10_code'),
                claim.get('gdrg_code')
            )
            
            matches = []
            for duplicate in potential_duplicates:
                # Calculate detailed similarity across ALL fields
                similarity_score, matching_fields, differing_fields = self._calculate_similarity(
                    claim, dict(duplicate), self.critical_fields
                )
                
                if similarity_score >= self.confidence_thresholds["low"]:
                    match = DuplicateMatch(
                        primary_encounter_id=encounter_id,
                        duplicate_encounter_id=duplicate['encounter_id'],
                        duplicate_type=DuplicateType.DIFFERENT_ENCOUNTER_SAME_INFO,
                        confidence_score=similarity_score,
                        matching_fields=matching_fields,
                        differing_fields=differing_fields,
                        detection_timestamp=datetime.now(),
                        details={
                            "original_claim": claim,
                            "duplicate_claim": dict(duplicate),
                            "signature_match": True,
                            "provider_original": claim.get('provider_name'),
                            "provider_duplicate": duplicate.get('provider_name'),
                            "submission_time_diff": self._calculate_time_diff(
                                claim.get('submitted_at'), duplicate.get('submitted_at')
                            ),
                            "matching_field_count": len(matching_fields),
                            "differing_field_count": len(differing_fields),
                            "key_differences": self._identify_key_differences(differing_fields)
                        }
                    )
                    matches.append(match)
            
            logger.info(f"Found {len(matches)} different encounter / same info duplicates")
            return matches
            
        except Exception as e:
            logger.error(f"Error detecting different encounter same info: {e}")
            return []
    
    async def _detect_same_encounter_different_info(self, claim: Dict) -> List[DuplicateMatch]:
        """
        Type 2: Same encounter_id but different information - using ALL fields
        """
        try:
            encounter_id = claim['encounter_id']
            
            # Find all claims with same encounter_id
            query = """
            SELECT 
                provider_id, provider_name, district, provider_type, healthcare_level, prescriber_level,
                last_name, other_names, date_of_birth, gender, nhis_number,
                encounter_id, encounter_type, admission_date, discharge_date,
                service_type_1, service_type_2, service_outcome, attendance_type,
                specialties_attended, specialty_code,
                diagnosis_name, icd10_diagnosis, icd10_code, g_drg_diagnosis, gdrg_code, gdrg_description,
                procedure_name, icd10_procedure, icd10_code_procedure, icd10_description_procedure,
                specialty_code_procedure, g_drg_procedure, gdrg_code_procedure, gdrg_description_procedure,
                level_procedure, procedure_date,
                medicine_code, medicine_name, medicine_code_procedure, medicine_name_procedure,
                dosage, standard_dosage, standard_dosage_procedure, frequency, frequency_procedure,
                duration, duration_days, duration_days_procedure, medicine_date,
                g_drg_inve, description_inve, submitted_at
            FROM claims_v3 
            WHERE encounter_id = $1
            ORDER BY submitted_at ASC
            """
            
            same_encounter_claims = await self.queries.db.fetch_all(query, encounter_id)
            
            matches = []
            if len(same_encounter_claims) > 1:
                # Compare each claim with others
                for i, claim1 in enumerate(same_encounter_claims):
                    for j, claim2 in enumerate(same_encounter_claims[i+1:], i+1):
                        
                        # Calculate differences across ALL fields
                        similarity_score, matching_fields, differing_fields = self._calculate_similarity(
                            dict(claim1), dict(claim2), self.critical_fields
                        )
                        
                        # If they're the same encounter but have differences, it's suspicious
                        if len(differing_fields) > 0:
                            confidence = 1.0 - (similarity_score * 0.5)  # Higher confidence for same encounter differences
                            
                            match = DuplicateMatch(
                                primary_encounter_id=encounter_id,
                                duplicate_encounter_id=encounter_id,  # Same encounter
                                duplicate_type=DuplicateType.SAME_ENCOUNTER_DIFFERENT_INFO,
                                confidence_score=confidence,
                                matching_fields=matching_fields,
                                differing_fields=differing_fields,
                                detection_timestamp=datetime.now(),
                                details={
                                    "claim_version_1": dict(claim1),
                                    "claim_version_2": dict(claim2),
                                    "submission_1": claim1.get('submitted_at'),
                                    "submission_2": claim2.get('submitted_at'),
                                    "total_versions": len(same_encounter_claims),
                                    "version_index_1": i,
                                    "version_index_2": j,
                                    "critical_differences": differing_fields,
                                    "data_integrity_issues": self._analyze_data_integrity_issues(differing_fields)
                                }
                            )
                            matches.append(match)
            
            logger.info(f"Found {len(matches)} same encounter / different info duplicates")
            return matches
            
        except Exception as e:
            logger.error(f"Error detecting same encounter different info: {e}")
            return []
    
    async def _detect_same_day_visits(self, claim: Dict) -> List[DuplicateMatch]:
        """
        Type 3: Same patient, same day visits (different encounters)
        """
        try:
            encounter_id = claim['encounter_id']
            
            # Get admission date (use current date if not available)
            visit_date = claim.get('admission_date') or claim.get('submitted_at') or datetime.now().date()
            if isinstance(visit_date, datetime):
                visit_date = visit_date.date()
            
            # Find other encounters for same patient on same day
            query = """
            SELECT 
                encounter_id,
                last_name,
                other_names,
                date_of_birth,
                gender,
                nhis_number,
                diagnosis_name,
                icd10_code,
                gdrg_code,
                encounter_type,
                admission_date,
                discharge_date,
                provider_name,
                submitted_at
            FROM claims_v3 
            WHERE encounter_id != $1
            AND last_name = $2
            AND other_names = $3
            AND date_of_birth = $4
            AND (
                DATE(admission_date) = $5 OR 
                DATE(submitted_at) = $5
            )
            ORDER BY submitted_at DESC
            """
            
            same_day_claims = await self.queries.db.fetch_all(
                query,
                encounter_id,
                claim['last_name'],
                claim['other_names'],
                claim['date_of_birth'],
                visit_date
            )
            
            matches = []
            for same_day_claim in same_day_claims:
                # Calculate patient identity confidence
                patient_similarity = self._calculate_patient_similarity(claim, dict(same_day_claim))
                
                if patient_similarity >= 0.8:  # High confidence same patient
                    # Check if it's legitimate multiple visits or suspicious
                    legitimacy_score = self._assess_same_day_visit_legitimacy(claim, dict(same_day_claim))
                    
                    confidence = patient_similarity * (1.0 - legitimacy_score)  # Higher confidence if less legitimate
                    
                    match = DuplicateMatch(
                        primary_encounter_id=encounter_id,
                        duplicate_encounter_id=same_day_claim['encounter_id'],
                        duplicate_type=DuplicateType.SAME_DAY_VISITS,
                        confidence_score=confidence,
                        matching_fields=['patient_identity', 'visit_date'],
                        differing_fields=['encounter_id', 'diagnosis', 'provider'],
                        detection_timestamp=datetime.now(),
                        details={
                            "original_claim": claim,
                            "same_day_claim": dict(same_day_claim),
                            "visit_date": str(visit_date),
                            "patient_similarity": patient_similarity,
                            "legitimacy_assessment": legitimacy_score,
                            "same_provider": claim.get('provider_name') == same_day_claim.get('provider_name'),
                            "same_diagnosis": claim.get('diagnosis_name') == same_day_claim.get('diagnosis_name'),
                            "encounter_types": [claim.get('encounter_type'), same_day_claim.get('encounter_type')]
                        }
                    )
                    matches.append(match)
            
            logger.info(f"Found {len(matches)} same day visit duplicates")
            return matches
            
        except Exception as e:
            logger.error(f"Error detecting same day visits: {e}")
            return []
    
    async def _detect_exact_duplicates(self, claim: Dict) -> List[DuplicateMatch]:
        """
        Type 4: Exact duplicates - completely identical claims
        """
        try:
            encounter_id = claim['encounter_id']
            
            # Create full claim hash for exact matching
            claim_hash = self._create_claim_hash(claim)
            
            # Find claims with identical information
            query = """
            SELECT 
                encounter_id,
                last_name,
                other_names,
                date_of_birth,
                gender,
                nhis_number,
                diagnosis_name,
                icd10_code,
                gdrg_code,
                medicine_name,
                standard_dosage,
                frequency,
                duration_days,
                admission_date,
                discharge_date,
                encounter_type,
                provider_name,
                submitted_at
            FROM claims_v3 
            WHERE encounter_id != $1
            AND last_name = $2
            AND other_names = $3
            AND date_of_birth = $4
            AND gender = $5
            AND nhis_number = $6
            AND diagnosis_name = $7
            AND icd10_code = $8
            AND gdrg_code = $9
            AND COALESCE(medicine_name, '') = $10
            AND encounter_type = $11
            """
            
            exact_duplicates = await self.queries.db.fetch_all(
                query,
                encounter_id,
                claim['last_name'],
                claim['other_names'],
                claim['date_of_birth'],
                claim['gender'],
                claim.get('nhis_number', ''),
                claim['diagnosis_name'],
                claim['icd10_code'],
                claim['gdrg_code'],
                claim.get('medicine_name', ''),
                claim['encounter_type']
            )
            
            matches = []
            for duplicate in exact_duplicates:
                # Verify exact match with hash comparison
                duplicate_hash = self._create_claim_hash(dict(duplicate))
                
                if claim_hash == duplicate_hash:
                    match = DuplicateMatch(
                        primary_encounter_id=encounter_id,
                        duplicate_encounter_id=duplicate['encounter_id'],
                        duplicate_type=DuplicateType.EXACT_DUPLICATE,
                        confidence_score=1.0,  # Perfect match
                        matching_fields=list(self.critical_fields),
                        differing_fields=['encounter_id'],  # Only encounter ID differs
                        detection_timestamp=datetime.now(),
                        details={
                            "original_claim": claim,
                            "exact_duplicate": dict(duplicate),
                            "hash_match": True,
                            "submission_time_diff": self._calculate_time_diff(
                                claim.get('submitted_at'), duplicate.get('submitted_at')
                            )
                        }
                    )
                    matches.append(match)
            
            logger.info(f"Found {len(matches)} exact duplicates")
            return matches
            
        except Exception as e:
            logger.error(f"Error detecting exact duplicates: {e}")
            return []
    
    def _create_claim_signature(self, claim: Dict, fields: List[str]) -> str:
        """Create a signature hash from specific claim fields"""
        signature_parts = []
        for field in fields:
            value = str(claim.get(field, '')).strip().lower()
            signature_parts.append(value)
        
        signature_string = '|'.join(signature_parts)
        return hashlib.md5(signature_string.encode()).hexdigest()
    
    def _create_claim_hash(self, claim: Dict) -> str:
        """Create a full hash of all claim fields"""
        # Sort keys to ensure consistent hashing
        sorted_items = sorted(claim.items())
        hash_string = json.dumps(sorted_items, default=str, sort_keys=True)
        return hashlib.sha256(hash_string.encode()).hexdigest()
    
    def _calculate_similarity(self, claim1: Dict, claim2: Dict, fields: List[str]) -> Tuple[float, List[str], List[str]]:
        """
        Calculate similarity score between two claims with intelligent null handling
        """
        matching_fields = []
        differing_fields = []
        valid_comparisons = 0  # Only count fields where at least one claim has a value
        
        for field in fields:
            val1 = claim1.get(field)
            val2 = claim2.get(field)
            
            # Smart null handling
            val1_is_null = self._is_null_or_empty(val1)
            val2_is_null = self._is_null_or_empty(val2)
            
            # If both values are null/empty, don't count this field in comparison
            if val1_is_null and val2_is_null:
                continue
            
            # Count this as a valid comparison since at least one has a value
            valid_comparisons += 1
            
            # If one is null and other isn't, they differ
            if val1_is_null != val2_is_null:
                differing_fields.append(field)
                continue
            
            # Both have values - normalize and compare
            val1_norm = self._normalize_value(val1)
            val2_norm = self._normalize_value(val2)
            
            if val1_norm == val2_norm:
                matching_fields.append(field)
            else:
                differing_fields.append(field)
        
        # Calculate similarity based only on valid comparisons
        similarity_score = len(matching_fields) / valid_comparisons if valid_comparisons > 0 else 1.0
        return similarity_score, matching_fields, differing_fields
    
    def _is_null_or_empty(self, value) -> bool:
        """
        Check if a value should be considered null/empty for comparison purposes
        """
        if value is None:
            return True
        
        if isinstance(value, str):
            # Consider empty string, whitespace, or common null indicators as null
            cleaned = value.strip().lower()
            return cleaned == '' or cleaned in ['null', 'none', 'n/a', 'na', '-', '--', 'unknown']
        
        return False
    
    def _normalize_value(self, value) -> str:
        """
        Normalize a value for comparison (case-insensitive, trimmed)
        """
        if value is None:
            return ""
        
        if isinstance(value, str):
            return value.strip().lower()
        
        # Handle dates
        if hasattr(value, 'isoformat'):
            return value.isoformat()
        
        return str(value).strip().lower()
    
    def _calculate_patient_similarity(self, claim1: Dict, claim2: Dict) -> float:
        """Calculate how likely two claims are for the same patient"""
        patient_fields = ['last_name', 'other_names', 'date_of_birth', 'gender', 'nhis_number']
        similarity, _, _ = self._calculate_similarity(claim1, claim2, patient_fields)
        return similarity
    
    def _assess_same_day_visit_legitimacy(self, claim1: Dict, claim2: Dict) -> float:
        """Assess if same-day visits are legitimate (0.0 = suspicious, 1.0 = legitimate)"""
        legitimacy_score = 0.0
        
        # Different encounter types might be legitimate (e.g., A&E then IPD)
        if claim1.get('encounter_type') != claim2.get('encounter_type'):
            legitimacy_score += 0.3
        
        # Different providers might be legitimate (referral)
        if claim1.get('provider_name') != claim2.get('provider_name'):
            legitimacy_score += 0.2
        
        # Different diagnoses might be legitimate (multiple conditions)
        if claim1.get('diagnosis_name') != claim2.get('diagnosis_name'):
            legitimacy_score += 0.3
        
        # Different G-DRG codes suggest different procedures
        if claim1.get('gdrg_code') != claim2.get('gdrg_code'):
            legitimacy_score += 0.2
        
        return min(legitimacy_score, 1.0)
    
    def _identify_key_differences(self, differing_fields: List[str]) -> Dict[str, str]:
        """
        Identify the most important differences between claims
        """
        key_differences = {}
        
        # Categorize differences by importance
        critical_differences = []
        important_differences = []
        minor_differences = []
        
        for field in differing_fields:
            if field in self.identifying_fields:
                critical_differences.append(field)
            elif field in self.clinical_fields:
                important_differences.append(field)
            elif field in self.administrative_fields:
                minor_differences.append(field)
            else:
                important_differences.append(field)
        
        key_differences = {
            "critical_patient_data": critical_differences,
            "important_clinical_data": important_differences, 
            "administrative_data": minor_differences,
            "total_differences": len(differing_fields),
            "severity": self._assess_difference_severity(critical_differences, important_differences, minor_differences)
        }
        
        return key_differences
    
    def _analyze_data_integrity_issues(self, differing_fields: List[str]) -> Dict[str, Any]:
        """
        Analyze what type of data integrity issues exist
        """
        issues = {
            "patient_identity_conflict": any(field in self.identifying_fields for field in differing_fields),
            "clinical_data_conflict": any(field in self.clinical_fields for field in differing_fields),
            "provider_data_conflict": any(field in ['provider_id', 'provider_name'] for field in differing_fields),
            "temporal_data_conflict": any(field in ['admission_date', 'discharge_date', 'procedure_date', 'medicine_date'] for field in differing_fields),
            "medication_conflict": any(field in ['medicine_name', 'dosage', 'frequency', 'duration_days'] for field in differing_fields),
            "diagnosis_conflict": any(field in ['diagnosis_name', 'icd10_code', 'gdrg_code'] for field in differing_fields),
            "procedure_conflict": any(field in ['procedure_name', 'icd10_procedure', 'icd10_code_procedure'] for field in differing_fields)
        }
        
        # Determine overall severity
        if issues["patient_identity_conflict"]:
            issues["overall_severity"] = "CRITICAL"
        elif issues["clinical_data_conflict"] or issues["diagnosis_conflict"]:
            issues["overall_severity"] = "HIGH"
        elif issues["medication_conflict"] or issues["procedure_conflict"]:
            issues["overall_severity"] = "MEDIUM"
        else:
            issues["overall_severity"] = "LOW"
        
        return issues
    
    def _assess_difference_severity(self, critical: List[str], important: List[str], minor: List[str]) -> str:
        """
        Assess the severity of differences between claims
        """
        if len(critical) > 0:
            return "CRITICAL"
        elif len(important) > 3:
            return "HIGH"
        elif len(important) > 0:
            return "MEDIUM"
        else:
            return "LOW"
    
    def _create_comprehensive_claim_signature(self, claim: Dict) -> str:
        """
        Create a comprehensive signature using ALL non-null fields for exact duplicate detection
        """
        signature_parts = []
        
        # Process all fields in a consistent order
        for field in sorted(self.critical_fields):
            value = claim.get(field)
            if not self._is_null_or_empty(value):
                normalized_value = self._normalize_value(value)
                signature_parts.append(f"{field}:{normalized_value}")
        
        signature_string = '|'.join(signature_parts)
        return hashlib.sha256(signature_string.encode()).hexdigest()
    
    def _calculate_time_diff(self, time1, time2) -> str:
        """Calculate time difference between submissions"""
        try:
            if time1 and time2:
                if isinstance(time1, str):
                    time1 = datetime.fromisoformat(time1.replace('Z', '+00:00'))
                if isinstance(time2, str):
                    time2 = datetime.fromisoformat(time2.replace('Z', '+00:00'))
                
                diff = abs((time1 - time2).total_seconds())
                
                if diff < 3600:  # Less than 1 hour
                    return f"{int(diff/60)} minutes"
                elif diff < 86400:  # Less than 1 day
                    return f"{int(diff/3600)} hours"
                else:
                    return f"{int(diff/86400)} days"
            return None
        except Exception as e:
            logger.error(f"Error calculating time diff: {e}")
            return None

    async def _update_claim_duplicate_status(self, encounter_id: str, result: DuplicateDetectionResult):
        """
        Update claim status in database when duplicates are detected
        Sets processed_status to 'flagged' and claim_status to 'processed'
        Creates detailed JSON flag_reason with specific duplicate information
        """
        try:
            # Get the highest confidence match for primary duplicate info
            highest_match = result.highest_confidence_match
            
            # Create detailed duplicate information
            duplicate_details = []
            for match in result.duplicate_matches:
                duplicate_info = {
                    "duplicate_encounter_id": match.duplicate_encounter_id,
                    "duplicate_type": match.duplicate_type.value,
                    "confidence_score": round(match.confidence_score, 3),
                    "matching_fields": match.matching_fields,
                    "differing_fields": match.differing_fields,
                    "detection_timestamp": match.detection_timestamp.isoformat(),
                    "summary": self._create_duplicate_summary(match)
                }
                
                # Add type-specific details
                if match.duplicate_type == DuplicateType.DIFFERENT_ENCOUNTER_SAME_INFO:
                    duplicate_info.update({
                        "issue_description": "Different encounter ID but identical patient and clinical information",
                        "risk_level": "HIGH" if match.confidence_score >= 0.8 else "MEDIUM",
                        "provider_comparison": {
                            "same_provider": match.details.get("provider_original") == match.details.get("provider_duplicate"),
                            "original_provider": match.details.get("provider_original"),
                            "duplicate_provider": match.details.get("provider_duplicate")
                        }
                    })
                
                elif match.duplicate_type == DuplicateType.SAME_ENCOUNTER_DIFFERENT_INFO:
                    duplicate_info.update({
                        "issue_description": "Same encounter ID contains conflicting information",
                        "risk_level": "CRITICAL",
                        "data_integrity_issue": True,
                        "version_count": match.details.get("total_versions", 2)
                    })
                
                elif match.duplicate_type == DuplicateType.SAME_DAY_VISITS:
                    duplicate_info.update({
                        "issue_description": "Multiple encounters for same patient on same date",
                        "risk_level": "MEDIUM" if match.confidence_score < 0.7 else "HIGH",
                        "visit_details": {
                            "same_provider": match.details.get("same_provider", False),
                            "same_diagnosis": match.details.get("same_diagnosis", False),
                            "encounter_types": match.details.get("encounter_types", [])
                        }
                    })
                
                elif match.duplicate_type == DuplicateType.EXACT_DUPLICATE:
                    duplicate_info.update({
                        "issue_description": "Exact duplicate claim submission detected",
                        "risk_level": "CRITICAL",
                        "fraud_indicator": True,
                        "submission_time_difference": match.details.get("submission_time_diff")
                    })
                
                duplicate_details.append(duplicate_info)
            
            # Determine primary duplicate issue and severity
            primary_issue, severity, category = self._categorize_duplicate_issue(
                [match.duplicate_type.value for match in result.duplicate_matches], 
                highest_match.confidence_score if highest_match else 0.0
            )
            
            # Create enhanced structured flag reason with specific duplicate info
            flag_reason_structure = {
                "stage": "DUPLICATE_DETECTION",
                "reason": f"Stage 0 failed: {result.recommendation}",
                "details": {
                    "category": category,
                    "primary_issue": primary_issue,
                    "severity": severity,
                    "total_duplicates_found": result.total_duplicates_found,
                    "highest_confidence_score": round(highest_match.confidence_score, 3) if highest_match else 0.0,
                    
                    # PRIMARY DUPLICATE INFO (the key info you wanted)
                    "primary_duplicate_encounter_id": highest_match.duplicate_encounter_id if highest_match else None,
                    "primary_duplicate_type": highest_match.duplicate_type.value if highest_match else None,
                    "primary_duplicate_confidence": round(highest_match.confidence_score, 3) if highest_match else 0.0,
                    "primary_duplicate_summary": self._create_duplicate_summary(highest_match) if highest_match else None,
                    
                    # ALL DUPLICATE ENCOUNTER IDs and TYPES
                    "duplicate_encounter_ids": [match.duplicate_encounter_id for match in result.duplicate_matches],
                    "duplicate_types": [match.duplicate_type.value for match in result.duplicate_matches],
                    "duplicate_confidences": [round(match.confidence_score, 3) for match in result.duplicate_matches],
                    
                    # DETAILED INFO for each duplicate
                    "all_duplicates": duplicate_details,
                    
                    # SPECIFIC RECOMMENDATION based on duplicate type
                    "specific_recommendation": self._get_duplicate_recommendation([match.duplicate_type.value for match in result.duplicate_matches]),
                    "action_required": self._get_required_action([match.duplicate_type.value for match in result.duplicate_matches]),
                    
                    # SUMMARY BY TYPE
                    "duplicate_types_summary": self._create_type_summary(result.duplicate_matches)
                },
                "category": "DUPLICATE_VALIDATION",
                "severity": severity,
                "timestamp": datetime.now().isoformat()
            }
            
            # Convert to JSON string for storage
            flag_reason_json = json.dumps(flag_reason_structure, default=str)
            
            # Update the claims_v3 table with enhanced JSON flag reason
            update_query = """
            UPDATE claims_v3 
            SET 
                processed_status = 'flagged',
                claim_status = 'processed',
                flag_reason = $2,
                flagged_at = CURRENT_TIMESTAMP,
                duplicate_count = $3,
                highest_duplicate_confidence = $4
            WHERE encounter_id = $1
            """
            
            await self.queries.db.execute(
                update_query,
                encounter_id,
                flag_reason_json,
                result.total_duplicates_found,
                round(highest_match.confidence_score, 3) if highest_match else 0.0
            )
            
            # Log the duplicate detection for audit trail
            await self._log_duplicate_detection(encounter_id, result, flag_reason_structure)
            
            logger.info(f"DATABASE UPDATED: {encounter_id} flagged for {category} - Primary duplicate: {highest_match.duplicate_encounter_id if highest_match else 'N/A'} ({highest_match.duplicate_type.value if highest_match else 'N/A'})")
            
        except Exception as e:
            logger.error(f"Error updating claim duplicate status for {encounter_id}: {e}")

    def _create_duplicate_summary(self, match: DuplicateMatch) -> str:
        """Create a human-readable summary of the duplicate match"""
        type_descriptions = {
            DuplicateType.DIFFERENT_ENCOUNTER_SAME_INFO: f"Same patient/clinical info as {match.duplicate_encounter_id}",
            DuplicateType.SAME_ENCOUNTER_DIFFERENT_INFO: f"Conflicting data in encounter {match.duplicate_encounter_id}",
            DuplicateType.SAME_DAY_VISITS: f"Same-day visit with {match.duplicate_encounter_id}",
            DuplicateType.EXACT_DUPLICATE: f"Exact copy of {match.duplicate_encounter_id}",
            DuplicateType.PARTIAL_DUPLICATE: f"Partial match with {match.duplicate_encounter_id}"
        }
        
        base_summary = type_descriptions.get(match.duplicate_type, f"Duplicate of {match.duplicate_encounter_id}")
        confidence_text = f" (Confidence: {match.confidence_score:.1%})"
        
        return base_summary + confidence_text

    def _create_type_summary(self, matches: List[DuplicateMatch]) -> Dict[str, Any]:
        """Create summary by duplicate type"""
        type_summary = {}
        
        for match in matches:
            type_name = match.duplicate_type.value
            if type_name not in type_summary:
                type_summary[type_name] = {
                    "count": 0,
                    "highest_confidence": 0.0,
                    "encounter_ids": [],
                    "avg_confidence": 0.0
                }
            
            type_summary[type_name]["count"] += 1
            type_summary[type_name]["encounter_ids"].append(match.duplicate_encounter_id)
            type_summary[type_name]["highest_confidence"] = max(
                type_summary[type_name]["highest_confidence"], 
                match.confidence_score
            )
        
        # Calculate average confidence
        for type_name, summary in type_summary.items():
            matching_scores = [m.confidence_score for m in matches if m.duplicate_type.value == type_name]
            summary["avg_confidence"] = round(sum(matching_scores) / len(matching_scores), 3)
        
        return type_summary

    def _get_duplicate_recommendation(self, duplicate_types: List[str]) -> str:
        """
        Get specific recommendation based on duplicate types found
        """
        recommendations = []
        
        if DuplicateType.EXACT_DUPLICATE.value in duplicate_types:
            recommendations.append("Investigate for potential fraudulent submission")
        
        if DuplicateType.DIFFERENT_ENCOUNTER_SAME_INFO.value in duplicate_types:
            recommendations.append("Verify encounter ID assignment and billing processes")
        
        if DuplicateType.SAME_ENCOUNTER_DIFFERENT_INFO.value in duplicate_types:
            recommendations.append("Review data entry procedures and system integrity")
        
        if DuplicateType.SAME_DAY_VISITS.value in duplicate_types:
            recommendations.append("Validate medical necessity for multiple same-day encounters")
        
        if not recommendations:
            recommendations.append("Manual review required to determine appropriate action")
        
        return "; ".join(recommendations)

    def _get_required_action(self, duplicate_types: List[str]) -> str:
        """
        Get required action based on duplicate types
        """
        actions = set()  # Use set to avoid duplicate actions
        
        if DuplicateType.EXACT_DUPLICATE.value in duplicate_types:
            actions.add("Flag for fraud investigation")
            actions.add("Hold payment pending review")
        
        if DuplicateType.DIFFERENT_ENCOUNTER_SAME_INFO.value in duplicate_types:
            actions.add("Verify provider billing systems")
            actions.add("Consolidate duplicate entries")
        
        if DuplicateType.SAME_ENCOUNTER_DIFFERENT_INFO.value in duplicate_types:
            actions.add("Audit data entry processes")
            actions.add("Resolve conflicting information")
        
        if DuplicateType.SAME_DAY_VISITS.value in duplicate_types:
            actions.add("Validate clinical necessity")
            actions.add("Review provider billing patterns")
        
        if not actions:
            actions.add("Manual case review required")
        
        return "; ".join(sorted(actions))
    
    def _categorize_duplicate_issue(self, duplicate_types: List[str], confidence: float) -> Tuple[str, str, str]:
        """
        Categorize the duplicate issue to determine primary issue, severity, and category
        Returns: (primary_issue, severity, category)
        """
        # Determine severity based on confidence and duplicate type
        if confidence >= 0.9:
            severity = "CRITICAL"
        elif confidence >= 0.7:
            severity = "HIGH"
        elif confidence >= 0.5:
            severity = "MEDIUM"
        else:
            severity = "LOW"
        
        # Determine primary issue and category
        if DuplicateType.EXACT_DUPLICATE.value in duplicate_types:
            return (
                "Exact duplicate claim submission detected",
                "CRITICAL",  # Always critical for exact duplicates
                "Potential Fraud"
            )
        elif DuplicateType.DIFFERENT_ENCOUNTER_SAME_INFO.value in duplicate_types:
            return (
                "Same patient information submitted with different encounter IDs",
                severity,
                "Data Integrity Violation"
            )
        elif DuplicateType.SAME_ENCOUNTER_DIFFERENT_INFO.value in duplicate_types:
            return (
                "Same encounter ID contains conflicting information",
                "HIGH",  # Always high for data integrity issues
                "Data Consistency Error"
            )
        elif DuplicateType.SAME_DAY_VISITS.value in duplicate_types:
            return (
                "Multiple encounters for same patient on same date",
                severity,
                "Suspicious Billing Pattern"
            )
        else:
            return (
                "Multiple duplicate patterns detected",
                severity,
                "Complex Duplicate Case"
            )
            
    async def _log_duplicate_detection(self, encounter_id: str, result: DuplicateDetectionResult, flag_reason_structure: Dict = None):
        """
        Log duplicate detection details for audit trail with structured flag reason
        """
        try:
            # First check if the duplicate_detection_log table exists, if not create it
            await self._ensure_duplicate_log_table_exists()
            
            # Insert main duplicate detection record with structured flag reason
            log_query = """
            INSERT INTO duplicate_detection_log (
                encounter_id,
                detection_timestamp,
                flag_status,
                total_duplicates_found,
                highest_confidence,
                recommendation,
                detection_details,
                structured_flag_reason
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
            """
            
            await self.queries.db.execute(
                log_query,
                encounter_id,
                result.timestamp,
                result.flag_status.value,
                result.total_duplicates_found,
                result.highest_confidence_match.confidence_score if result.highest_confidence_match else 0.0,
                result.recommendation,
                json.dumps(result.details, default=str),
                json.dumps(flag_reason_structure, default=str) if flag_reason_structure else None
            )
            
            # Insert individual duplicate match records
            for match in result.duplicate_matches:
                match_query = """
                INSERT INTO duplicate_matches_log (
                    primary_encounter_id,
                    duplicate_encounter_id,
                    duplicate_type,
                    confidence_score,
                    matching_fields,
                    differing_fields,
                    detection_timestamp,
                    match_details
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                """
                
                await self.queries.db.execute(
                    match_query,
                    match.primary_encounter_id,
                    match.duplicate_encounter_id,
                    match.duplicate_type.value,
                    match.confidence_score,
                    json.dumps(match.matching_fields),
                    json.dumps(match.differing_fields),
                    match.detection_timestamp,
                    json.dumps(match.details, default=str)
                )
            
            logger.debug(f"Structured duplicate detection logged for {encounter_id}")
            
        except Exception as e:
            logger.error(f"Error logging duplicate detection for {encounter_id}: {e}")
    
    async def _ensure_duplicate_log_table_exists(self):
        """
        Create duplicate detection log tables with structured flag reason support
        """
        try:
            # Create main duplicate detection log table with structured flag reason
            create_main_table = """
            CREATE TABLE IF NOT EXISTS duplicate_detection_log (
                id SERIAL PRIMARY KEY,
                encounter_id VARCHAR(50) NOT NULL,
                detection_timestamp TIMESTAMP NOT NULL,
                flag_status VARCHAR(20) NOT NULL,
                total_duplicates_found INTEGER DEFAULT 0,
                highest_confidence DECIMAL(5,3) DEFAULT 0.000,
                recommendation TEXT,
                detection_details JSONB,
                structured_flag_reason JSONB,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            
            CREATE INDEX IF NOT EXISTS idx_duplicate_log_encounter ON duplicate_detection_log(encounter_id);
            CREATE INDEX IF NOT EXISTS idx_duplicate_log_timestamp ON duplicate_detection_log(detection_timestamp);
            CREATE INDEX IF NOT EXISTS idx_duplicate_log_flag_status ON duplicate_detection_log(flag_status);
            CREATE INDEX IF NOT EXISTS idx_duplicate_log_structured_flag ON duplicate_detection_log USING GIN(structured_flag_reason);
            """
            
            # Create duplicate matches log table  
            create_matches_table = """
            CREATE TABLE IF NOT EXISTS duplicate_matches_log (
                id SERIAL PRIMARY KEY,
                primary_encounter_id VARCHAR(50) NOT NULL,
                duplicate_encounter_id VARCHAR(50) NOT NULL,
                duplicate_type VARCHAR(50) NOT NULL,
                confidence_score DECIMAL(5,3) NOT NULL,
                matching_fields JSONB,
                differing_fields JSONB,
                detection_timestamp TIMESTAMP NOT NULL,
                match_details JSONB,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            
            CREATE INDEX IF NOT EXISTS idx_duplicate_matches_primary ON duplicate_matches_log(primary_encounter_id);
            CREATE INDEX IF NOT EXISTS idx_duplicate_matches_duplicate ON duplicate_matches_log(duplicate_encounter_id);
            CREATE INDEX IF NOT EXISTS idx_duplicate_matches_type ON duplicate_matches_log(duplicate_type);
            CREATE INDEX IF NOT EXISTS idx_duplicate_matches_confidence ON duplicate_matches_log(confidence_score);
            """
            
            await self.queries.db.execute(create_main_table)
            await self.queries.db.execute(create_matches_table)
            
        except Exception as e:
            # If table creation fails, we'll just log to file instead
            logger.warning(f"Could not create duplicate log tables, will use file logging: {e}")
    
    async def _update_claims_schema_if_needed(self):
        """
        Add duplicate-related columns to claims_v3 table with JSON support for flag_reason
        """
        try:
            # Check if duplicate columns exist and add them if not
            alter_queries = [
                "ALTER TABLE claims_v3 ADD COLUMN IF NOT EXISTS processed_status VARCHAR(20) DEFAULT 'PENDING'",
                "ALTER TABLE claims_v3 ADD COLUMN IF NOT EXISTS flag_reason JSONB",  # Changed to JSONB for structured data
                "ALTER TABLE claims_v3 ADD COLUMN IF NOT EXISTS flagged_at TIMESTAMP",
                "ALTER TABLE claims_v3 ADD COLUMN IF NOT EXISTS duplicate_count INTEGER DEFAULT 0",
                "ALTER TABLE claims_v3 ADD COLUMN IF NOT EXISTS highest_duplicate_confidence DECIMAL(5,3) DEFAULT 0.000"
            ]
            
            for query in alter_queries:
                try:
                    await self.queries.db.execute(query)
                except Exception as col_error:
                    logger.debug(f"Column may already exist: {col_error}")
            
            # Create indexes for performance including JSON index
            index_queries = [
                "CREATE INDEX IF NOT EXISTS idx_claims_processed_status ON claims_v3(processed_status)",
                "CREATE INDEX IF NOT EXISTS idx_claims_flagged_at ON claims_v3(flagged_at)",
                "CREATE INDEX IF NOT EXISTS idx_claims_duplicate_count ON claims_v3(duplicate_count)",
                "CREATE INDEX IF NOT EXISTS idx_claims_flag_reason ON claims_v3 USING GIN(flag_reason)"  # JSON index
            ]
            
            for query in index_queries:
                try:
                    await self.queries.db.execute(query)
                except Exception as idx_error:
                    logger.debug(f"Index may already exist: {idx_error}")
                    
            logger.info("Claims table schema updated for structured duplicate detection")
            
        except Exception as e:
            logger.error(f"Error updating claims schema: {e}")

    async def _analyze_duplicate_matches(self, encounter_id: str, matches: List[DuplicateMatch], claim: Dict) -> DuplicateDetectionResult:
        """Analyze all duplicate matches and determine final status"""
        
        if not matches:
            return DuplicateDetectionResult(
                encounter_id=encounter_id,
                flag_status=DuplicateFlag.CLEAN,
                duplicate_matches=[],
                total_duplicates_found=0,
                highest_confidence_match=None,
                recommendation="PROCEED: No duplicates detected",
                details={"analysis": "Clean claim, no duplicates found"}
            )
        
        # Find highest confidence match
        highest_confidence_match = max(matches, key=lambda m: m.confidence_score)
        highest_confidence = highest_confidence_match.confidence_score
        
        # Count by type
        type_counts = {}
        for match in matches:
            type_name = match.duplicate_type.value
            type_counts[type_name] = type_counts.get(type_name, 0) + 1
        
        # Determine flag status based on confidence and type
        if highest_confidence >= self.confidence_thresholds["high"]:
            flag_status = DuplicateFlag.flagged
            recommendation = "BLOCK: High confidence duplicate detected - manual review required"
        elif highest_confidence >= self.confidence_thresholds["medium"]:
            flag_status = DuplicateFlag.flagged
            recommendation = "FLAG: Medium confidence duplicate - requires review before processing"
        else:
            flag_status = DuplicateFlag.SUSPICIOUS
            recommendation = "SUSPICIOUS: Low confidence duplicate patterns - monitor closely"
        
        # Special handling for same encounter different info (always flag)
        if DuplicateType.SAME_ENCOUNTER_DIFFERENT_INFO.value in type_counts:
            flag_status = DuplicateFlag.flagged
            recommendation = "FLAG: Same encounter ID with different information - data integrity issue"
        
        # Special handling for exact duplicates (always block)
        if DuplicateType.EXACT_DUPLICATE.value in type_counts:
            flag_status = DuplicateFlag.flagged
            recommendation = "BLOCK: Exact duplicate claim detected - likely fraudulent submission"
        
        return DuplicateDetectionResult(
            encounter_id=encounter_id,
            flag_status=flag_status,
            duplicate_matches=matches,
            total_duplicates_found=len(matches),
            highest_confidence_match=highest_confidence_match,
            recommendation=recommendation,
            details={
                "analysis_summary": {
                    "highest_confidence": highest_confidence,
                    "duplicate_type_counts": type_counts,
                    "total_matches": len(matches)
                },
                "original_claim_info": {
                    "encounter_id": claim.get('encounter_id'),
                    "provider_name": claim.get('provider_name'),
                    "patient_name": f"{claim.get('last_name', '')} {claim.get('other_names', '')}".strip(),
                    "diagnosis": claim.get('diagnosis_name'),
                    "gdrg_code": claim.get('gdrg_code'),
                    "encounter_type": claim.get('encounter_type'),
                    "submission_date": str(claim.get('submitted_at'))
                },
                "duplicate_summary": [
                    {
                        "duplicate_encounter": match.duplicate_encounter_id,
                        "type": match.duplicate_type.value,
                        "confidence": match.confidence_score,
                        "matching_fields_count": len(match.matching_fields),
                        "differing_fields_count": len(match.differing_fields)
                    }
                    for match in matches
                ]
            }
        )
    
    async def batch_detect_duplicates(self, encounter_ids: List[str]) -> Dict[str, DuplicateDetectionResult]:
        """
        Detect duplicates for multiple claims in batch
        """
        results = {}
        
        for encounter_id in encounter_ids:
            try:
                result = await self.detect_all_duplicates(encounter_id)
                results[encounter_id] = result
                
                # Log summary
                status_indicator = {
                    DuplicateFlag.CLEAN: "✅",
                    DuplicateFlag.SUSPICIOUS: "🟡", 
                    DuplicateFlag.flagged: "🚩",
                    DuplicateFlag.flagged: "🚫"
                }
                
                indicator = status_indicator.get(result.flag_status, "❓")
                logger.info(f"{indicator} {encounter_id}: {result.flag_status.value} ({result.total_duplicates_found} duplicates)")
                
            except Exception as e:
                logger.error(f"Error processing {encounter_id}: {e}")
                results[encounter_id] = DuplicateDetectionResult(
                    encounter_id=encounter_id,
                    flag_status=DuplicateFlag.SUSPICIOUS,
                    duplicate_matches=[],
                    total_duplicates_found=0,
                    highest_confidence_match=None,
                    recommendation=f"MANUAL REVIEW: Error during processing - {str(e)}",
                    details={"error": str(e)}
                )
        
        return results

# Main batch processing function for integration with AutomatedBatchProcessor
async def run_duplicate_detection_stage(encounter_ids: List[str]) -> Dict[str, Any]:
    """
    Core batch duplicate detection stage - flags duplicates with detailed reasons
    
    Args:
        encounter_ids: List of encounter IDs to process
    
    Returns:
        Dict containing batch processing results and database update status
    """
    logger.info(f"DUPLICATE DETECTION: Starting for batch with {len(encounter_ids)} claims")
    
    # Initialize detector
    detector = DuplicateClaimsDetector()
    
    try:
        await detector.initialize()
        
        # Track results
        clean_claims = 0
        flagged_claims = 0
        flagged_claims = 0
        error_claims = 0
        
        database_updates = {
            "flagged_claims": [],
            "flagged_claims": [],
            "clean_claims": [],
            "error_claims": []
        }
        
        high_confidence_duplicates = []
        
        # Process each claim
        for encounter_id in encounter_ids:
            try:
                # Run duplicate detection
                result = await detector.detect_all_duplicates(encounter_id)
                
                # Process result and update database
                if result.flag_status == DuplicateFlag.CLEAN:
                    clean_claims += 1
                    database_updates["clean_claims"].append(encounter_id)
                    
                elif result.flag_status == DuplicateFlag.flagged:
                    flagged_claims += 1
                    
                    database_updates["flagged_claims"].append({
                        "encounter_id": encounter_id,
                        "reason": result.recommendation,
                        "confidence": result.highest_confidence_match.confidence_score if result.highest_confidence_match else 0.0
                    })
                    
                    # Track high confidence duplicates for reporting
                    if result.highest_confidence_match and result.highest_confidence_match.confidence_score >= 0.8:
                        high_confidence_duplicates.append({
                            "primary_encounter": encounter_id,
                            "duplicate_encounter": result.highest_confidence_match.duplicate_encounter_id,
                            "type": result.highest_confidence_match.duplicate_type.value,
                            "confidence": result.highest_confidence_match.confidence_score
                        })
                    
                elif result.flag_status == DuplicateFlag.flagged:
                    flagged_claims += 1
                    
                    database_updates["flagged_claims"].append({
                        "encounter_id": encounter_id,
                        "reason": result.recommendation,
                        "confidence": result.highest_confidence_match.confidence_score if result.highest_confidence_match else 0.0
                    })
                    
                    # Track high confidence duplicates for reporting
                    if result.highest_confidence_match and result.highest_confidence_match.confidence_score >= 0.8:
                        high_confidence_duplicates.append({
                            "primary_encounter": encounter_id,
                            "duplicate_encounter": result.highest_confidence_match.duplicate_encounter_id,
                            "type": result.highest_confidence_match.duplicate_type.value,
                            "confidence": result.highest_confidence_match.confidence_score
                        })
                        
                else:  # SUSPICIOUS or error cases
                    error_claims += 1
                    database_updates["error_claims"].append({
                        "encounter_id": encounter_id,
                        "reason": result.recommendation,
                        "error": result.details.get("error") if result.details else "Unknown error"
                    })
                
            except Exception as e:
                logger.error(f"Error processing duplicate detection for {encounter_id}: {e}")
                error_claims += 1
                database_updates["error_claims"].append({
                    "encounter_id": encounter_id,
                    "reason": f"Processing error: {str(e)}",
                    "error": str(e)
                })
        
        # Calculate summary statistics
        total_claims = len(encounter_ids)
        duplicate_detection_rate = round(((total_claims - clean_claims) / total_claims * 100), 2) if total_claims > 0 else 0
        
        summary_statistics = {
            "total_claims": total_claims,
            "clean_claims": clean_claims,
            "flagged_claims": flagged_claims,
            "flagged_claims": flagged_claims,
            "error_claims": error_claims,
            "duplicate_detection_rate": duplicate_detection_rate
        }
        
        # Generate simple recommendations
        recommendations = []
        if flagged_claims > 0:
            recommendations.append(f"IMMEDIATE ACTION: {flagged_claims} claims flagged for manual review")
        if flagged_claims > 0:
            recommendations.append(f"REVIEW REQUIRED: {flagged_claims} claims flagged for duplicate review")
        if error_claims > 0:
            recommendations.append(f"ERRORS: {error_claims} claims had processing errors")
        if clean_claims == total_claims:
            recommendations.append("CLEAN BATCH: No duplicates detected - proceed with normal processing")
        
        logger.info(f"DUPLICATE DETECTION COMPLETED:")
        logger.info(f"  Total Claims: {total_claims}")
        logger.info(f"  Clean: {clean_claims}")
        logger.info(f"  Flagged: {flagged_claims}")
        logger.info(f"  flagged: {flagged_claims}")
        logger.info(f"  Errors: {error_claims}")
        logger.info(f"  Duplicate Rate: {duplicate_detection_rate}%")
        
        return {
            "summary_statistics": summary_statistics,
            "database_updates": database_updates,
            "high_confidence_duplicates": high_confidence_duplicates,
            "recommendations": recommendations
        }
        
    except Exception as e:
        logger.error(f"Critical error in batch duplicate detection: {e}")
        return {
            "error": str(e),
            "summary_statistics": {
                "total_claims": len(encounter_ids),
                "clean_claims": 0,
                "flagged_claims": 0,
                "flagged_claims": 0,
                "error_claims": len(encounter_ids),
                "duplicate_detection_rate": 0.0
            },
            "database_updates": {
                "error_claims": [{"encounter_id": eid, "error": str(e)} for eid in encounter_ids]
            },
            "recommendations": ["CRITICAL: Batch processing failed - Manual review required for all claims"]
        }
        
    finally:
        await detector.close()

    
    async def get_duplicate_summary_report(self, encounter_ids: List[str]) -> Dict[str, Any]:
        """
        Generate comprehensive duplicate detection report
        """
        results = await self.batch_detect_duplicates(encounter_ids)
        
        # Summary statistics
        total_claims = len(encounter_ids)
        clean_count = len([r for r in results.values() if r.flag_status == DuplicateFlag.CLEAN])
        suspicious_count = len([r for r in results.values() if r.flag_status == DuplicateFlag.SUSPICIOUS])
        flagged_count = len([r for r in results.values() if r.flag_status == DuplicateFlag.flagged])
        flagged_count = len([r for r in results.values() if r.flag_status == DuplicateFlag.flagged])
        
        # Duplicate type analysis
        duplicate_type_stats = {}
        high_confidence_duplicates = []
        
        for encounter_id, result in results.items():
            for match in result.duplicate_matches:
                type_name = match.duplicate_type.value
                duplicate_type_stats[type_name] = duplicate_type_stats.get(type_name, 0) + 1
                
                if match.confidence_score >= 0.8:
                    high_confidence_duplicates.append({
                        "primary_encounter": match.primary_encounter_id,
                        "duplicate_encounter": match.duplicate_encounter_id,
                        "type": type_name,
                        "confidence": match.confidence_score
                    })
        
        # Generate recommendations
        recommendations = []
        if flagged_count > 0:
            recommendations.append(f"IMMEDIATE ACTION: {flagged_count} claims should be flagged for manual review")
        if flagged_count > 0:
            recommendations.append(f"REVIEW REQUIRED: {flagged_count} claims flagged for duplicate review")
        if suspicious_count > 0:
            recommendations.append(f"MONITORING: {suspicious_count} claims marked suspicious")
        
        # Calculate rates
        duplicate_rate = round(((total_claims - clean_count) / total_claims * 100), 2) if total_claims > 0 else 0
        block_rate = round((flagged_count / total_claims * 100), 2) if total_claims > 0 else 0
        
        return {
            "summary_statistics": {
                "total_claims_analyzed": total_claims,
                "clean_claims": clean_count,
                "suspicious_claims": suspicious_count,
                "flagged_claims": flagged_count,
                "flagged_claims": flagged_count,
                "duplicate_detection_rate": duplicate_rate,
                "block_rate": block_rate
            },
            "duplicate_type_breakdown": duplicate_type_stats,
            "high_confidence_duplicates": high_confidence_duplicates,
            "recommendations": recommendations,
            "detailed_results": results,
            "processing_metadata": {
                "detection_timestamp": datetime.now().isoformat(),
                "confidence_thresholds": self.confidence_thresholds,
                "fields_analyzed": {
                    "critical_fields": self.critical_fields,
                    "identifying_fields": self.identifying_fields,
                    "clinical_fields": self.clinical_fields
                }
            }
        }

# Helper function to parse structured flag reasons
def parse_flag_reason(flag_reason_json: str) -> Dict[str, Any]:
    """
    Parse structured flag reason JSON and return formatted data
    """
    try:
        if isinstance(flag_reason_json, str):
            return json.loads(flag_reason_json)
        elif isinstance(flag_reason_json, dict):
            return flag_reason_json
        else:
            return {"error": "Invalid flag reason format", "raw_data": str(flag_reason_json)}
    except Exception as e:
        return {"error": f"Failed to parse flag reason: {e}", "raw_data": str(flag_reason_json)}

# UTILITY FUNCTION to parse and display duplicate info from JSON
def display_duplicate_info(encounter_id: str, flag_reason_json: str) -> str:
    """
    Parse flag reason JSON and display duplicate information like your example
    """
    try:
        flag_data = json.loads(flag_reason_json)
        details = flag_data.get('details', {})
        
        # Extract key info
        status = details.get('severity', 'UNKNOWN')
        duplicates_found = details.get('total_duplicates_found', 0)
        recommendation = flag_data.get('reason', 'No recommendation')
        
        # Primary duplicate info
        primary_duplicate_id = details.get('primary_duplicate_encounter_id', 'Unknown')
        primary_duplicate_type = details.get('primary_duplicate_type', 'Unknown')
        primary_confidence = details.get('primary_duplicate_confidence', 0.0)
        
        # Format output like your example
        output = []
        output.append(f"{encounter_id}: Status: {status}")
        output.append(f"Duplicates Found: {duplicates_found}")
        output.append(f"Recommendation: {recommendation}")
        
        if primary_duplicate_id and primary_duplicate_id != 'Unknown':
            output.append("Highest Confidence Match:")
            output.append(f"  Duplicate: {primary_duplicate_id}")
            output.append(f"  Type: {primary_duplicate_type}")
            output.append(f"  Confidence: {primary_confidence:.3f}")
        
        return "\n".join(output)
        
    except Exception as e:
        return f"{encounter_id}: Error parsing duplicate info - {str(e)}"

# QUERY FUNCTION to get flagged duplicates with specific info
async def get_flagged_duplicates_with_details() -> List[Dict[str, Any]]:
    """
    Query flagged claims and extract duplicate information from JSON
    """
    try:
        await initialize_database()
        queries = await get_nhis_queries()
        
        query = """
        SELECT 
            encounter_id,
            provider_name,
            last_name,
            other_names,
            diagnosis_name,
            gdrg_code,
            encounter_type,
            processed_status,
            claim_status,
            flag_reason,
            flagged_at,
            duplicate_count,
            highest_duplicate_confidence
        FROM claims_v3 
        WHERE processed_status = 'flagged' 
        AND flag_reason IS NOT NULL
        AND flag_reason::text LIKE '%DUPLICATE_DETECTION%'
        ORDER BY flagged_at DESC, highest_duplicate_confidence DESC
        LIMIT 50
        """
        
        flagged_claims = await queries.db.fetch_all(query)
        
        # Parse and enhance each claim
        enhanced_claims = []
        for claim in flagged_claims:
            claim_dict = dict(claim)
            
            # Parse flag reason JSON
            try:
                flag_data = json.loads(claim_dict['flag_reason'])
                details = flag_data.get('details', {})
                
                # Add parsed duplicate info to claim
                claim_dict.update({
                    'primary_duplicate_encounter_id': details.get('primary_duplicate_encounter_id'),
                    'primary_duplicate_type': details.get('primary_duplicate_type'),
                    'primary_duplicate_confidence': details.get('primary_duplicate_confidence'),
                    'duplicate_category': details.get('category'),
                    'severity': details.get('severity'),
                    'duplicate_encounter_ids': details.get('duplicate_encounter_ids', []),
                    'specific_recommendation': details.get('specific_recommendation'),
                    'action_required': details.get('action_required')
                })
                
            except Exception as e:
                logger.error(f"Error parsing flag reason for {claim_dict['encounter_id']}: {e}")
                claim_dict['parse_error'] = str(e)
            
            enhanced_claims.append(claim_dict)
        
        return enhanced_claims
        
    except Exception as e:
        logger.error(f"Error querying flagged duplicates: {e}")
        return []

# Main execution functions
async def main_duplicate_detection():
    """
    Main function to run duplicate detection on claims
    """
    detector = DuplicateClaimsDetector()
    
    try:
        await detector.initialize()
        
        # Example usage - replace with actual encounter IDs
        test_encounter_ids = [
            "ENC_001",
            "ENC_002", 
            "ENC_003"
        ]
        
        # Run batch duplicate detection
        results = await detector.batch_detect_duplicates(test_encounter_ids)
        
        # Generate summary report
        report = await detector.get_duplicate_summary_report(test_encounter_ids)
        
        print("=== DUPLICATE DETECTION SUMMARY ===")
        print(f"Total Claims Analyzed: {report['summary_statistics']['total_claims_analyzed']}")
        print(f"Clean Claims: {report['summary_statistics']['clean_claims']}")
        print(f"Flagged Claims: {report['summary_statistics']['flagged_claims']}")
        print(f"flagged Claims: {report['summary_statistics']['flagged_claims']}")
        print(f"Duplicate Detection Rate: {report['summary_statistics']['duplicate_detection_rate']}%")
        
        print("\n=== INDIVIDUAL RESULTS ===")
        for encounter_id, result in results.items():
            print(f"\n{encounter_id}: {result.flag_status.value}")
            if result.duplicate_matches:
                print(f"  Duplicates Found: {result.total_duplicates_found}")
                print(f"  Highest Confidence: {result.highest_confidence_match.confidence_score:.3f}")
                print(f"  Recommendation: {result.recommendation}")
        
        return results, report
        
    except Exception as e:
        logger.error(f"Error in main duplicate detection: {e}")
        return None, None
    
    finally:
        await detector.close()

# Usage example
if __name__ == "__main__":
    # Run the duplicate detection
    results, report = asyncio.run(main_duplicate_detection())
    
    if results:
        print("\n=== DUPLICATE DETECTION COMPLETED SUCCESSFULLY ===")
    else:
        print("\n=== DUPLICATE DETECTION FAILED ===")

# Additional utility functions for specific use cases

async def check_single_claim_duplicates(encounter_id: str) -> DuplicateDetectionResult:
    """
    Check duplicates for a single claim
    """
    detector = DuplicateClaimsDetector()
    
    try:
        await detector.initialize()
        result = await detector.detect_all_duplicates(encounter_id)
        return result
    
    finally:
        await detector.close()

async def get_all_flagged_duplicates():
    """
    Get all flagged duplicate claims with parsed details
    """
    enhanced_claims = await get_flagged_duplicates_with_details()
    
    print(f"\n=== FLAGGED DUPLICATE CLAIMS ({len(enhanced_claims)}) ===")
    
    for claim in enhanced_claims:
        print(f"\nEncounter: {claim['encounter_id']}")
        print(f"Provider: {claim['provider_name']}")
        print(f"Patient: {claim['last_name']}, {claim['other_names']}")
        print(f"Diagnosis: {claim['diagnosis_name']}")
        print(f"Severity: {claim.get('severity', 'Unknown')}")
        print(f"Primary Duplicate: {claim.get('primary_duplicate_encounter_id', 'None')}")
        print(f"Duplicate Type: {claim.get('primary_duplicate_type', 'None')}")
        print(f"Confidence: {claim.get('primary_duplicate_confidence', 0.0):.3f}")
        print(f"Action Required: {claim.get('action_required', 'Manual Review')}")
        print("-" * 50)
    
    return enhanced_claims

# Quick test function for development
async def quick_test():
    """
    Quick test of duplicate detection functionality
    """
    print("Starting Quick Duplicate Detection Test...")
    
    # Test single claim
    test_encounter = "TEST_ENC_001"
    result = await check_single_claim_duplicates(test_encounter)
    
    print(f"\nTest Result for {test_encounter}:")
    print(f"Status: {result.flag_status.value}")
    print(f"Duplicates Found: {result.total_duplicates_found}")
    print(f"Recommendation: {result.recommendation}")
    
    return result