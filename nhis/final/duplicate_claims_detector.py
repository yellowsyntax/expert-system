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
    SAME_DAY_VISITS = "SAME_DAY_VISITS"  # Same patient, same day, different encounters
    EXACT_DUPLICATE = "EXACT_DUPLICATE"  # Completely identical claims
    PARTIAL_DUPLICATE = "PARTIAL_DUPLICATE"  # Similar but not identical

class DuplicateFlag(Enum):
    """Duplicate flag status"""
    CLEAN = "CLEAN"
    flagged = "flagged"
    SUSPICIOUS = "SUSPICIOUS"
    BLOCKED = "BLOCKED"

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
        
        # Fields to compare for duplicates
        self.critical_fields = [
            'last_name', 'other_names', 'date_of_birth', 'gender', 'nhis_number',
            'diagnosis_name', 'icd10_code', 'gdrg_code', 'medicine_name',
            'admission_date', 'discharge_date', 'encounter_type'
        ]
        
        self.identifying_fields = [
            'last_name', 'other_names', 'date_of_birth', 'gender'
        ]
        
        self.clinical_fields = [
            'diagnosis_name', 'icd10_code', 'gdrg_code', 'medicine_name',
            'standard_dosage', 'frequency', 'duration_days'
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
            if result.flag_status in [DuplicateFlag.flagged, DuplicateFlag.BLOCKED]:
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
        Type 1: Different encounter_id but same information
        """
        try:
            encounter_id = claim['encounter_id']
            
            # Create signature of critical claim information
            claim_signature = self._create_claim_signature(claim, self.critical_fields)
            
            # Find other claims with same signature but different encounter_id
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
            AND diagnosis_name = $6
            AND icd10_code = $7
            AND gdrg_code = $8
            ORDER BY submitted_at DESC
            """
            
            potential_duplicates = await self.queries.db.fetch_all(
                query,
                encounter_id,
                claim['last_name'],
                claim['other_names'], 
                claim['date_of_birth'],
                claim['gender'],
                claim['diagnosis_name'],
                claim['icd10_code'],
                claim['gdrg_code']
            )
            
            matches = []
            for duplicate in potential_duplicates:
                # Calculate detailed similarity
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
                            )
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
        Type 2: Same encounter_id but different information
        """
        try:
            encounter_id = claim['encounter_id']
            
            # Find all claims with same encounter_id
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
            WHERE encounter_id = $1
            ORDER BY submitted_at ASC
            """
            
            same_encounter_claims = await self.queries.db.fetch_all(query, encounter_id)
            
            matches = []
            if len(same_encounter_claims) > 1:
                # Compare each claim with others
                for i, claim1 in enumerate(same_encounter_claims):
                    for j, claim2 in enumerate(same_encounter_claims[i+1:], i+1):
                        
                        # Calculate differences
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
                                    "critical_differences": differing_fields
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
        """Calculate similarity score between two claims"""
        matching_fields = []
        differing_fields = []
        
        for field in fields:
            val1 = str(claim1.get(field, '')).strip().lower()
            val2 = str(claim2.get(field, '')).strip().lower()
            
            if val1 == val2:
                matching_fields.append(field)
            else:
                differing_fields.append(field)
        
        similarity_score = len(matching_fields) / len(fields) if fields else 0.0
        return similarity_score, matching_fields, differing_fields
    
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
    
    def _calculate_time_diff(self, time1, time2) -> Optional[str]:
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
        Creates structured JSON flag_reason
        """
        try:
            # Create structured flag reason based on duplicate types found
            duplicate_types = [match.duplicate_type.value for match in result.duplicate_matches]
            highest_confidence = result.highest_confidence_match.confidence_score if result.highest_confidence_match else 0.0
            
            # Determine primary duplicate issue and severity
            primary_issue, severity, category = self._categorize_duplicate_issue(duplicate_types, highest_confidence)
            
            # Create structured flag reason
            flag_reason_structure = {
                "stage": "DUPLICATE_DETECTION",
                "reason": f"Stage 0 failed: {result.recommendation}",
                "details": {
                    "category": category,
                    "recommendation": self._get_duplicate_recommendation(duplicate_types),
                    "specific_issue": primary_issue,
                    "action_required": self._get_required_action(duplicate_types),
                    "duplicate_types_found": duplicate_types,
                    "total_duplicates": result.total_duplicates_found,
                    "highest_confidence_score": highest_confidence,
                    "duplicate_encounters": [match.duplicate_encounter_id for match in result.duplicate_matches]
                },
                "category": "DUPLICATE_VALIDATION",
                "severity": severity,
                "timestamp": datetime.now().isoformat()
            }
            
            # Convert to JSON string for storage
            flag_reason_json = json.dumps(flag_reason_structure, default=str)
            
            # Update the claims_v3 table with structured flag reason
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
                highest_confidence
            )
            
            # Log the duplicate detection for audit trail
            await self._log_duplicate_detection(encounter_id, result, flag_reason_structure)
            
            logger.info(f"DATABASE UPDATED: {encounter_id} marked as flagged/processed due to {category} ({severity} severity)")
            
        except Exception as e:
            logger.error(f"Error updating claim duplicate status for {encounter_id}: {e}")
    
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
            flag_status = DuplicateFlag.BLOCKED
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
            flag_status = DuplicateFlag.BLOCKED
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
                    DuplicateFlag.BLOCKED: "🚫"
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
        blocked_count = len([r for r in results.values() if r.flag_status == DuplicateFlag.BLOCKED])
        
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
        if blocked_count > 0:
            recommendations.append(f"IMMEDIATE ACTION: {blocked_count} claims should be blocked for manual review")
        if flagged_count > 0:
            recommendations.append(f"REVIEW REQUIRED: {flagged_count} claims flagged for duplicate review")
        if suspicious_count > 0:
            recommendations.append(f"MONITORING: {suspicious_count} claims marked suspicious")
        
        # Calculate rates
        duplicate_rate = round(((total_claims - clean_count) / total_claims * 100), 2) if total_claims > 0 else 0
        block_rate = round((blocked_count / total_claims * 100), 2) if total_claims > 0 else 0
        
        return {
            "summary_statistics": {
                "total_claims_analyzed": total_claims,
                "clean_claims": clean_count,
                "suspicious_claims": suspicious_count,
                "flagged_claims": flagged_count,
                "blocked_claims": blocked_count,
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

# Updated flagged claims report with structured flag reason parsing
async def get_flagged_claims_report() -> Dict[str, Any]:
    """
    Get report of all claims currently flagged for duplicates with parsed structured reasons
    """
    try:
        await initialize_database()
        queries = await get_nhis_queries()
        
        # Get all flagged claims with structured flag reasons
        flagged_query = """
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
            highest_duplicate_confidence,
            submitted_at
        FROM claims_v3 
        WHERE processed_status = 'flagged' 
        ORDER BY flagged_at DESC, highest_duplicate_confidence DESC
        """
        
        flagged_claims = await queries.db.fetch_all(flagged_query)
        
        # Parse structured flag reasons
        parsed_flagged_claims = []
        for claim in flagged_claims:
            claim_dict = dict(claim)
            if claim_dict.get('flag_reason'):
                claim_dict['parsed_flag_reason'] = parse_flag_reason(claim_dict['flag_reason'])
            parsed_flagged_claims.append(claim_dict)
        
        # Get duplicate detection log summary with structured data
        log_query = """
        SELECT 
            flag_status,
            COUNT(*) as count,
            AVG(highest_confidence) as avg_confidence,
            MAX(detection_timestamp) as latest_detection,
            structured_flag_reason->>'severity' as severity,
            structured_flag_reason->'details'->>'category' as category
        FROM duplicate_detection_log 
        WHERE structured_flag_reason IS NOT NULL
        GROUP BY flag_status, structured_flag_reason->>'severity', structured_flag_reason->'details'->>'category'
        ORDER BY count DESC
        """
        
        try:
            log_summary = await queries.db.fetch_all(log_query)
        except Exception:
            log_summary = []  # Table might not exist yet
        
        # Analyze by severity and category
        severity_breakdown = {}
        category_breakdown = {}
        
        for claim in parsed_flagged_claims:
            parsed_flag = claim.get('parsed_flag_reason', {})
            severity = parsed_flag.get('severity', 'UNKNOWN')
            category = parsed_flag.get('details', {}).get('category', 'Unknown Category')
            
            severity_breakdown[severity] = severity_breakdown.get(severity, 0) + 1
            category_breakdown[category] = category_breakdown.get(category, 0) + 1
        
        report = {
            "flagged_claims_summary": {
                "total_flagged_claims": len(flagged_claims),
                "claims_needing_review": len([c for c in flagged_claims if c.get('processed_status') == 'flagged']),
                "latest_flagged_date": flagged_claims[0].get('flagged_at') if flagged_claims else None,
                "severity_breakdown": severity_breakdown,
                "category_breakdown": category_breakdown
            },
            "flagged_claims_details": parsed_flagged_claims,
            "duplicate_detection_log_summary": [dict(log) for log in log_summary],
            "generated_at": datetime.now().isoformat()
        }
        
        return report
        
    except Exception as e:
        logger.error(f"Error generating flagged claims report: {e}")
        return {
            "error": str(e),
            "flagged_claims_summary": {"total_flagged_claims": 0, "error_occurred": True}
        }

# Function to query claims by specific duplicate categories
async def get_claims_by_duplicate_category(category: str = None, severity: str = None) -> Dict[str, Any]:
    """
    Get flagged claims filtered by specific duplicate category or severity
    
    Args:
        category: Filter by category (e.g., "Potential Fraud", "Data Integrity Violation")
        severity: Filter by severity (e.g., "CRITICAL", "HIGH", "MEDIUM", "LOW")
    """
    try:
        await initialize_database()
        queries = await get_nhis_queries()
        
        base_query = """
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
        """
        
        conditions = []
        params = []
        
        if category:
            conditions.append("flag_reason->'details'->>'category' = $" + str(len(params) + 1))
            params.append(category)
        
        if severity:
            conditions.append("flag_reason->>'severity' = $" + str(len(params) + 1))
            params.append(severity)
        
        if conditions:
            base_query += " AND " + " AND ".join(conditions)
        
        base_query += " ORDER BY flagged_at DESC, highest_duplicate_confidence DESC"
        
        claims = await queries.db.fetch_all(base_query, *params)
        
        # Parse flag reasons
        parsed_claims = []
        for claim in claims:
            claim_dict = dict(claim)
            if claim_dict.get('flag_reason'):
                claim_dict['parsed_flag_reason'] = parse_flag_reason(claim_dict['flag_reason'])
            parsed_claims.append(claim_dict)
        
        return {
            "filter_criteria": {
                "category": category,
                "severity": severity
            },
            "total_matching_claims": len(parsed_claims),
            "matching_claims": parsed_claims,
            "generated_at": datetime.now().isoformat()
        }
        
    except Exception as e:
        logger.error(f"Error querying claims by duplicate category: {e}")
        return {
            "error": str(e),
            "filter_criteria": {"category": category, "severity": severity},
            "total_matching_claims": 0
        }

async def run_duplicate_detection_stage(encounter_ids: List[str]) -> Dict[str, Any]:
    """
    Main function to run duplicate detection and update database statuses
    Updates processed_status and claim_status for flagged claims in database
    """
    detector = DuplicateClaimsDetector()
    
    try:
        await detector.initialize()
        
        logger.info(f"DUPLICATE DETECTION STAGE: Processing {len(encounter_ids)} claims")
        
        # Process each claim and update database
        results = {}
        database_updates = {
            "flagged_claims": [],
            "blocked_claims": [],
            "clean_claims": [],
            "update_errors": []
        }
        
        for encounter_id in encounter_ids:
            try:
                # Detect duplicates for this claim
                result = await detector.detect_all_duplicates(encounter_id)
                results[encounter_id] = result
                
                # Track database updates
                if result.flag_status == DuplicateFlag.flagged:
                    database_updates["flagged_claims"].append({
                        "encounter_id": encounter_id,
                        "reason": result.recommendation,
                        "duplicate_count": result.total_duplicates_found,
                        "confidence": result.highest_confidence_match.confidence_score if result.highest_confidence_match else 0.0
                    })
                elif result.flag_status == DuplicateFlag.BLOCKED:
                    database_updates["blocked_claims"].append({
                        "encounter_id": encounter_id,
                        "reason": result.recommendation,
                        "duplicate_count": result.total_duplicates_found,
                        "confidence": result.highest_confidence_match.confidence_score if result.highest_confidence_match else 0.0
                    })
                else:
                    database_updates["clean_claims"].append(encounter_id)
                
                # Log result
                status_indicator = {
                    DuplicateFlag.CLEAN: "CLEAN",
                    DuplicateFlag.SUSPICIOUS: "SUSPICIOUS", 
                    DuplicateFlag.flagged: "flagged (DB UPDATED)",
                    DuplicateFlag.BLOCKED: "BLOCKED (DB UPDATED)"
                }
                
                status = status_indicator.get(result.flag_status, "UNKNOWN")
                logger.info(f"{encounter_id}: {status} ({result.total_duplicates_found} duplicates)")
                
            except Exception as e:
                logger.error(f"Error processing {encounter_id}: {e}")
                database_updates["update_errors"].append({
                    "encounter_id": encounter_id,
                    "error": str(e)
                })
                
                # Create error result
                results[encounter_id] = DuplicateDetectionResult(
                    encounter_id=encounter_id,
                    flag_status=DuplicateFlag.SUSPICIOUS,
                    duplicate_matches=[],
                    total_duplicates_found=0,
                    highest_confidence_match=None,
                    recommendation=f"MANUAL REVIEW: Error during processing - {str(e)}",
                    details={"error": str(e)}
                )
        
        # Generate comprehensive summary
        total_flagged = len(database_updates["flagged_claims"])
        total_blocked = len(database_updates["blocked_claims"])
        total_clean = len(database_updates["clean_claims"])
        total_errors = len(database_updates["update_errors"])
        
        # Count duplicate types across all results
        duplicate_type_stats = {}
        high_confidence_duplicates = []
        
        for result in results.values():
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
        if total_blocked > 0:
            recommendations.append(f"DATABASE UPDATED: {total_blocked} claims marked as BLOCKED/processed")
        if total_flagged > 0:
            recommendations.append(f"DATABASE UPDATED: {total_flagged} claims marked as flagged/processed")
        if total_clean > 0:
            recommendations.append(f"READY FOR VALIDATION: {total_clean} clean claims can proceed")
        if total_errors > 0:
            recommendations.append(f"MANUAL REVIEW: {total_errors} claims had processing errors")
        
        # Calculate rates
        total_processed = len(encounter_ids)
        duplicate_rate = round(((total_flagged + total_blocked) / total_processed * 100), 2) if total_processed > 0 else 0
        
        report = {
            "summary_statistics": {
                "total_claims_processed": total_processed,
                "clean_claims": total_clean,
                "flagged_claims": total_flagged,
                "blocked_claims": total_blocked,
                "error_claims": total_errors,
                "duplicate_detection_rate": duplicate_rate,
                "database_updates_completed": total_flagged + total_blocked
            },
            "database_updates": database_updates,
            "duplicate_type_breakdown": duplicate_type_stats,
            "high_confidence_duplicates": high_confidence_duplicates,
            "recommendations": recommendations,
            "detailed_results": results,
            "processing_metadata": {
                "detection_timestamp": datetime.now().isoformat(),
                "schema_updates_applied": True,
                "audit_logging_enabled": True,
                "confidence_thresholds": detector.confidence_thresholds
            }
        }
        
        logger.info(f"DUPLICATE DETECTION STAGE COMPLETED: {total_flagged} flagged, {total_blocked} blocked, {total_clean} clean, {total_errors} errors")
        
        return report
        
    except Exception as e:
        logger.error(f"Error in duplicate detection stage: {e}")
        return {
            "error": str(e),
            "summary_statistics": {
                "total_claims_processed": len(encounter_ids),
                "error_occurred": True
            },
            "recommendations": [f"SYSTEM ERROR: Duplicate detection failed - {str(e)}"]
        }
    
    finally:
        await detector.close()

# Example usage and testing
async def main():
    """
    Test the duplicate detection system
    """
    try:
        # Test encounter IDs (replace with actual IDs from your database)
        test_encounter_ids = [
            "LIN-0992-RKLN",
            "LIN-4881-BEEU", 
            "LIN-1234-TEST",
            "LIN-5678-DEMO"
        ]
        
        print("DUPLICATE DETECTION SYSTEM - TESTING")
        print("=" * 60)
        print("DETECTION CAPABILITIES:")
        print("  1. Different encounter IDs, same information")
        print("  2. Same encounter ID, different information") 
        print("  3. Same patient, same day visits")
        print("  4. Exact duplicates")
        print("=" * 60)
        
        # Run complete duplicate detection stage
        report = await run_duplicate_detection_stage(test_encounter_ids)
        
        if "error" in report:
            print(f"ERROR: {report['error']}")
            return
        
        # Display summary results
        stats = report["summary_statistics"]
        print(f"\nSUMMARY RESULTS:")
        print(f"  Total Claims Analyzed: {stats['total_claims_processed']}")
        print(f"  Clean Claims: {stats['clean_claims']}")
        print(f"  flagged Claims: {stats['flagged_claims']}")
        print(f"  Blocked Claims: {stats['blocked_claims']}")
        print(f"  Error Claims: {stats['error_claims']}")
        print(f"  Duplicate Detection Rate: {stats['duplicate_detection_rate']}%")
        
        # Display duplicate type breakdown
        if report["duplicate_type_breakdown"]:
            print(f"\nDUPLICATE TYPES DETECTED:")
            for dup_type, count in report["duplicate_type_breakdown"].items():
                print(f"  {dup_type}: {count} cases")
        
        # Display high confidence duplicates
        if report["high_confidence_duplicates"]:
            print(f"\nHIGH CONFIDENCE DUPLICATES:")
            for dup in report["high_confidence_duplicates"][:5]:  # Show first 5
                print(f"  {dup['primary_encounter']} <-> {dup['duplicate_encounter']}")
                print(f"    Type: {dup['type']}, Confidence: {dup['confidence']:.2f}")
        
        # Display recommendations
        if report["recommendations"]:
            print(f"\nRECOMMENDATIONS:")
            for rec in report["recommendations"]:
                print(f"  - {rec}")
        
        # Show detailed results for first few claims
        print(f"\nDETAILED RESULTS (First 3 claims):")
        detailed = report["detailed_results"]
        for i, (encounter_id, result) in enumerate(list(detailed.items())[:3]):
            print(f"\n  [{i+1}] {encounter_id}:")
            print(f"      Status: {result.flag_status.value}")
            print(f"      Duplicates Found: {result.total_duplicates_found}")
            print(f"      Recommendation: {result.recommendation}")
            
            if result.highest_confidence_match:
                hcm = result.highest_confidence_match
                print(f"      Highest Confidence Match:")
                print(f"        Duplicate: {hcm.duplicate_encounter_id}")
                print(f"        Type: {hcm.duplicate_type.value}")
                print(f"        Confidence: {hcm.confidence_score:.3f}")
        
        print(f"\nTESTING COMPLETED!")
        print("=" * 60)
        print("INTEGRATION READY:")
        print("  - Run this stage before InitialProcessingValidator")
        print("  - Use database updates to filter claims")
        print("  - Handle flagged/blocked claims separately")
        print("  - Log all duplicate matches for audit trail")
        
    except Exception as e:
        print(f"TEST FAILED: {e}")

if __name__ == "__main__":
    asyncio.run(main())