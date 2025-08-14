"""
NHIS Expert System - Claim Adapter

Converts ClaimV2 database records to StandardClaim format for processing.
Handles all field mapping, data transformation, and validation.
"""

from typing import Dict, List, Any, Optional
from datetime import datetime, date
from decimal import Decimal
import json
import re

from .interfaces import BaseClaimAdapter
from .models import StandardClaim, ClaimDecision, ValidationIssue
from .enums import EncounterType, EpisodeType, ValidationSeverity
from .exceptions import ValidationError, ClaimProcessingError


class ClaimV2Adapter(BaseClaimAdapter):
    """
    Adapter to convert ClaimV2 database records to StandardClaim format.
    
    This bridges the gap between your database structure and the 
    expert system's processing format.
    """
    
    def __init__(self):
        self.name = "ClaimV2Adapter"
        self._service_type_mapping = self._build_service_type_mapping()
        self._encounter_type_mapping = self._build_encounter_type_mapping()
    
    def adapt_from_database(self, claim_v2_record: Any) -> StandardClaim:
        """
        Convert ClaimV2 database record to StandardClaim.
        
        Args:
            claim_v2_record: ClaimV2 SQLAlchemy model instance
            
        Returns:
            StandardClaim ready for processing
            
        Raises:
            ValidationError: If required fields are missing or invalid
        """
        try:
            # Extract core identifiers
            claim_id = str(claim_v2_record.id)
            encounter_id = claim_v2_record.encounter_id
            batch_id = str(claim_v2_record.batch_id) if claim_v2_record.batch_id else None
            
            # Extract and validate provider information
            provider_info = self._extract_provider_info(claim_v2_record)
            
            # Extract and validate patient information
            patient_info = self._extract_patient_info(claim_v2_record)
            
            # Extract encounter details
            encounter_info = self._extract_encounter_info(claim_v2_record)
            
            # Extract clinical information
            clinical_info = self._extract_clinical_info(claim_v2_record)
            
            # Extract medicines, procedures, investigations
            clinical_components = self._extract_clinical_components(claim_v2_record)
            
            # Build StandardClaim
            standard_claim = StandardClaim(
                # Core identifiers
                claim_id=claim_id,
                encounter_id=encounter_id,
                batch_id=batch_id,
                
                # Provider information
                facility_id=provider_info['facility_id'],
                facility_name=provider_info['facility_name'],
                facility_level=provider_info['facility_level'],
                prescriber_level=provider_info['prescriber_level'],
                district=provider_info['district'],
                provider_type=provider_info['provider_type'],
                
                # Patient information
                patient_id=patient_info['patient_id'],
                patient_age=patient_info['patient_age'],
                gender=patient_info['gender'],
                date_of_birth=patient_info['date_of_birth'],
                
                # Encounter details
                visit_date=encounter_info['visit_date'],
                encounter_type=encounter_info['encounter_type'],
                admission_date=encounter_info['admission_date'],
                discharge_date=encounter_info['discharge_date'],
                service_outcome=encounter_info['service_outcome'],
                attendance_type=encounter_info['attendance_type'],
                specialties_attended=encounter_info['specialties_attended'],
                
                # Clinical information
                icd10_diagnosis=clinical_info['icd10_diagnosis'],
                diagnosis_name=clinical_info['diagnosis_name'],
                claimed_gdrgs=clinical_info['claimed_gdrgs'],
                
                # Clinical components
                procedures=clinical_components['procedures'],
                medicines=clinical_components['medicines'],
                investigations=clinical_components['investigations'],
                
                # Episode information
                episode_id=encounter_id,  # Use encounter_id as episode_id
                episode_type=self._determine_episode_type(clinical_info['icd10_diagnosis']),
                
                # Metadata
                created_at=claim_v2_record.created_at,
                updated_at=claim_v2_record.updated_at
            )
            
            # Validate the converted claim
            self._validate_converted_claim(standard_claim)
            
            return standard_claim
            
        except Exception as e:
            raise ClaimProcessingError(
                f"Failed to convert ClaimV2 record to StandardClaim: {str(e)}",
                claim_id=str(claim_v2_record.id) if hasattr(claim_v2_record, 'id') else None,
                processing_step="claim_adaptation"
            )
    
    def adapt_to_output(self, claim: StandardClaim, decision: ClaimDecision) -> Dict[str, Any]:
        """
        Convert processing results to output format for database storage.
        
        Args:
            claim: Original standardized claim
            decision: Processing decision
            
        Returns:
            Dictionary ready for database storage or API response
        """
        return {
            # Core information
            "claim_id": claim.claim_id,
            "encounter_id": claim.encounter_id,
            "batch_id": claim.batch_id,
            
            # Decision information
            "status": decision.status.value,
            "decision_reason": decision.decision_reason.value,
            "decision_rationale": decision.decision_rationale,
            "decision_timestamp": decision.decision_timestamp.isoformat(),
            
            # Financial results
            "total_claimed": str(decision.calculation_result.total_claimed),
            "total_approved": str(decision.calculation_result.total_approved),
            "total_denied": str(decision.calculation_result.total_denied),
            "total_pending": str(decision.calculation_result.total_pending),
            
            # G-DRG information
            "final_gdrg": decision.final_gdrg,
            "gdrg_determination_method": decision.gdrg_determination_method.value if decision.gdrg_determination_method else None,
            "age_suffix_applied": decision.age_suffix_applied,
            
            # Validation issues
            "validation_issues": [issue.to_dict() for issue in decision.validation_issues],
            "critical_issues_count": len(decision.get_critical_issues()),
            
            # Required actions
            "required_documents": decision.required_documents,
            "recommended_actions": decision.recommended_actions,
            
            # Processing metadata
            "total_processing_time_ms": decision.total_processing_time_ms,
            "rules_applied_count": len(decision.rules_applied),
            
            # Detailed breakdown (for audit purposes)
            "calculation_breakdown": decision.calculation_result.to_dict(),
            "processing_steps": [step.to_dict() for step in decision.processing_steps],
            "episode_information": decision.episode_information
        }
    
    def _extract_provider_info(self, claim_v2: Any) -> Dict[str, Any]:
        """Extract provider information from ClaimV2 record"""
        return {
            'facility_id': str(claim_v2.provider_id),
            'facility_name': claim_v2.provider_name,
            'facility_level': claim_v2.healthcare_level,
            'prescriber_level': claim_v2.prescriber_level,
            'district': claim_v2.district,
            'provider_type': claim_v2.provider_type
        }
    
    def _extract_patient_info(self, claim_v2: Any) -> Dict[str, Any]:
        """Extract patient information from ClaimV2 record"""
        # Calculate age from date of birth
        patient_age = 0
        date_of_birth = None
        
        if claim_v2.date_of_birth:
            if isinstance(claim_v2.date_of_birth, datetime):
                date_of_birth = claim_v2.date_of_birth.date()
            else:
                date_of_birth = claim_v2.date_of_birth
            
            # Calculate age
            today = date.today()
            patient_age = today.year - date_of_birth.year
            if today.month < date_of_birth.month or (today.month == date_of_birth.month and today.day < date_of_birth.day):
                patient_age -= 1
        
        return {
            'patient_id': claim_v2.nhis_number,
            'patient_age': max(0, patient_age),  # Ensure non-negative age
            'gender': claim_v2.gender,
            'date_of_birth': date_of_birth
        }
    
    def _extract_encounter_info(self, claim_v2: Any) -> Dict[str, Any]:
        """Extract encounter information from ClaimV2 record"""
        # Determine encounter type from service types
        encounter_type = self._map_encounter_type(claim_v2.service_type_1, claim_v2.service_type_2)
        
        # Extract visit date (use admission_date if available, otherwise current date)
        visit_date = date.today()
        if claim_v2.admission_date:
            if isinstance(claim_v2.admission_date, datetime):
                visit_date = claim_v2.admission_date.date()
            else:
                visit_date = claim_v2.admission_date
        
        # Parse specialties attended
        specialties = []
        if claim_v2.specialties_attended:
            # Handle comma-separated specialties
            specialties = [s.strip() for s in claim_v2.specialties_attended.split(',') if s.strip()]
        
        return {
            'visit_date': visit_date,
            'encounter_type': encounter_type,
            'admission_date': claim_v2.admission_date,
            'discharge_date': claim_v2.discharge_date,
            'service_outcome': claim_v2.service_outcome,
            'attendance_type': claim_v2.attendance_type,
            'specialties_attended': specialties
        }
    
    def _extract_clinical_info(self, claim_v2: Any) -> Dict[str, Any]:
        """Extract clinical information from ClaimV2 record"""
        # Extract ICD-10 diagnosis
        icd10_diagnosis = claim_v2.icd10_diagnosis or ""
        
        # Clean and validate ICD-10 code
        icd10_diagnosis = self._clean_icd10_code(icd10_diagnosis)
        
        # Extract claimed G-DRGs
        claimed_gdrgs = []
        if claim_v2.g_drg_diagnosis:
            claimed_gdrgs.append(claim_v2.g_drg_diagnosis)
        if claim_v2.g_drg_procedure and claim_v2.g_drg_procedure != claim_v2.g_drg_diagnosis:
            claimed_gdrgs.append(claim_v2.g_drg_procedure)
        
        return {
            'icd10_diagnosis': icd10_diagnosis,
            'diagnosis_name': claim_v2.diagnosis_name,
            'claimed_gdrgs': claimed_gdrgs
        }
    
    def _extract_clinical_components(self, claim_v2: Any) -> Dict[str, Any]:
        """Extract medicines, procedures, and investigations"""
        components = {
            'medicines': [],
            'procedures': [],
            'investigations': []
        }
        
        # Extract medicine information
        if claim_v2.medicine_code:
            medicine = {
                'code': claim_v2.medicine_code,
                'name': claim_v2.medicine_name,
                'dosage': claim_v2.dosage,
                'frequency': claim_v2.frequency,
                'duration': self._parse_duration(claim_v2.duration)
            }
            components['medicines'].append(medicine)
        
        # Extract procedure information
        if claim_v2.procedure_name or claim_v2.icd10_procedure:
            procedure = {
                'name': claim_v2.procedure_name,
                'icd10_code': claim_v2.icd10_procedure,
                'description': claim_v2.icd10_description_procedure,
                'level': claim_v2.level_procedure,
                'g_drg': claim_v2.g_drg_procedure
            }
            components['procedures'].append(procedure)
        
        # Extract investigation information
        if claim_v2.g_drg_inve:
            investigation = {
                'g_drg_code': claim_v2.g_drg_inve,
                'description': claim_v2.description_inve
            }
            components['investigations'].append(investigation)
        
        return components
    
    def _map_encounter_type(self, service_type_1: str, service_type_2: str) -> EncounterType:
        """Map service types to encounter type"""
        # Priority: service_type_1 first, then service_type_2
        service_type = service_type_1 or service_type_2 or ""
        service_type_clean = service_type.strip().upper()
        
        # Use mapping dictionary
        return self._encounter_type_mapping.get(service_type_clean, EncounterType.OPD)
    
    def _determine_episode_type(self, icd10_code: str) -> Optional[EpisodeType]:
        """Determine episode type based on ICD-10 code"""
        if not icd10_code:
            return None
        
        # Check for chronic conditions (simplified logic)
        chronic_prefixes = ['I10', 'E11', 'I20', 'I25', 'I50', 'N18', 'J44']
        if any(icd10_code.startswith(prefix) for prefix in chronic_prefixes):
            return EpisodeType.CHRONIC
        
        # Check for pregnancy-related codes
        pregnancy_prefixes = ['O', 'Z34', 'Z35', 'Z36', 'Z37', 'Z38', 'Z39']
        if any(icd10_code.startswith(prefix) for prefix in pregnancy_prefixes):
            return EpisodeType.ANTENATAL
        
        # Default to acute
        return EpisodeType.ACUTE
    
    def _clean_icd10_code(self, icd10_code: str) -> str:
        """Clean and validate ICD-10 code format"""
        if not icd10_code:
            return ""
        
        # Remove whitespace and convert to uppercase
        cleaned = icd10_code.strip().upper()
        
        # Basic ICD-10 format validation (letter followed by numbers)
        if re.match(r'^[A-Z]\d{2}', cleaned):
            return cleaned
        
        return cleaned  # Return as-is if doesn't match expected format
    
    def _parse_duration(self, duration_str: str) -> Optional[int]:
        """Parse duration string to number of days"""
        if not duration_str:
            return None
        
        duration_clean = str(duration_str).strip().lower()
        
        # Extract number from duration string
        numbers = re.findall(r'\d+', duration_clean)
        if not numbers:
            return None
        
        days = int(numbers[0])
        
        # Convert based on unit
        if 'week' in duration_clean:
            days *= 7
        elif 'month' in duration_clean:
            days *= 30
        elif 'year' in duration_clean:
            days *= 365
        
        return days
    
    def _validate_converted_claim(self, claim: StandardClaim) -> None:
        """Validate the converted StandardClaim"""
        issues = []
        
        # Check required fields
        if not claim.claim_id:
            issues.append("Missing claim_id")
        
        if not claim.facility_id:
            issues.append("Missing facility_id")
        
        if not claim.icd10_diagnosis:
            issues.append("Missing ICD-10 diagnosis")
        
        if claim.patient_age < 0 or claim.patient_age > 150:
            issues.append(f"Invalid patient age: {claim.patient_age}")
        
        if not claim.visit_date:
            issues.append("Missing visit_date")
        
        # Check date consistency for inpatients
        if claim.encounter_type == EncounterType.IPD:
            if claim.admission_date and claim.discharge_date:
                if claim.discharge_date < claim.admission_date:
                    issues.append("Discharge date before admission date")
        
        if issues:
            raise ValidationError(
                f"Claim validation failed: {'; '.join(issues)}",
                field_name="claim_conversion",
                validation_rule="claim_adapter_validation"
            )
    
    def _build_service_type_mapping(self) -> Dict[str, str]:
        """Build mapping from service types to standardized values"""
        return {
            'OUTPATIENT': 'OPD',
            'OPD': 'OPD',
            'OUT-PATIENT': 'OPD',
            'INPATIENT': 'IPD',
            'IPD': 'IPD',
            'IN-PATIENT': 'IPD',
            'EMERGENCY': 'A&E',
            'A&E': 'A&E',
            'ACCIDENT': 'A&E',
            'CASUALTY': 'A&E'
        }
    
    def _build_encounter_type_mapping(self) -> Dict[str, EncounterType]:
        """Build mapping from service types to EncounterType enums"""
        return {
            'OUTPATIENT': EncounterType.OPD,
            'OPD': EncounterType.OPD,
            'OUT-PATIENT': EncounterType.OPD,
            'INPATIENT': EncounterType.IPD,
            'IPD': EncounterType.IPD,
            'IN-PATIENT': EncounterType.IPD,
            'EMERGENCY': EncounterType.AE,
            'A&E': EncounterType.AE,
            'ACCIDENT': EncounterType.AE,
            'CASUALTY': EncounterType.AE
        }
    
    def get_adapter_info(self) -> Dict[str, Any]:
        """Get adapter metadata"""
        return {
            "name": self.name,
            "supported_input_type": "ClaimV2",
            "output_type": "StandardClaim",
            "service_type_mappings": len(self._service_type_mapping),
            "encounter_type_mappings": len(self._encounter_type_mapping)
        }


# Utility functions for claim adaptation

def batch_adapt_claims(claims_v2_records: List[Any]) -> List[StandardClaim]:
    """
    Convert multiple ClaimV2 records to StandardClaim format.
    
    Args:
        claims_v2_records: List of ClaimV2 database records
        
    Returns:
        List of StandardClaim objects
    """
    adapter = ClaimV2Adapter()
    adapted_claims = []
    
    for record in claims_v2_records:
        try:
            adapted_claim = adapter.adapt_from_database(record)
            adapted_claims.append(adapted_claim)
        except Exception as e:
            # Log error and continue with other claims
            print(f"Failed to adapt claim {record.id}: {e}")
            continue
    
    return adapted_claims


def validate_claim_v2_completeness(claim_v2_record: Any) -> List[str]:
    """
    Check ClaimV2 record completeness before adaptation.
    
    Args:
        claim_v2_record: ClaimV2 database record
        
    Returns:
        List of missing or invalid fields
    """
    issues = []
    
    # Check essential fields
    essential_fields = [
        'id', 'provider_id', 'icd10_diagnosis'
    ]
    
    for field in essential_fields:
        if not hasattr(claim_v2_record, field) or not getattr(claim_v2_record, field):
            issues.append(f"Missing essential field: {field}")
    
    # Check date fields
    if hasattr(claim_v2_record, 'date_of_birth') and not claim_v2_record.date_of_birth:
        issues.append("Missing date_of_birth (needed for age calculation)")
    
    # Check service type
    if not claim_v2_record.service_type_1 and not claim_v2_record.service_type_2:
        issues.append("Missing service type information")
    
    return issues