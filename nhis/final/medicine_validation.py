import asyncio
import json
import logging
import math
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass
from enum import Enum
from datetime import datetime, timedelta

from neon_db_connection import get_nhis_queries, initialize_database, close_database

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class ValidationResult(Enum):
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    FLAGGED = "FLAGGED"
    PENDING = "PENDING"
    PARTIAL = "PARTIAL"
    DENIED = "DENIED"

class DosageResult(Enum):
    WITHIN_LIMITS = "WITHIN_LIMITS"
    MODERATE_OVERSUPPLY = "MODERATE_OVERSUPPLY"
    EXCESSIVE_OVERSUPPLY = "EXCESSIVE_OVERSUPPLY"

class MedicineRejectReason(Enum):
    MEDICINE_DISPENSED_OUTSIDE_ADMISSION = "Medicine dispensed outside admission period"
    DUPLICATE_CLAIMS = "Duplicate claims"
    INAPPROPRIATE_PRESCRIPTION = "Inappropriate prescription"
    POLYPHARMACY = "Polypharmacy"
    OVERSUPPLY_OF_MEDICINE = "Inappropriate prescription"
    MULTIPLE_CHRONIC_VISIT = "Multiple chronic visit"
    GENDER_DIAGNOSIS_MISMATCH = "Gender diagnosis mismatch"
    TREATMENT_DIAGNOSIS_MISMATCH = "Treatment diagnosis mismatch"
    AGE_DIAGNOSIS_MISMATCH = "Age diagnosis mismatch"
    NON_FORMULARY_MEDICINE = "Non-formulary medicine prescribed"
    INVALID_PRESCRIBER_LEVEL = "Invalid prescriber level"
    MEDICINE_NOT_FOUND = "Medicine not found in NHIS formulary"
    FREQUENCY_EXCEEDED = "Frequency exceeds maximum allowed"
    DURATION_EXCEEDED = "Duration exceeds maximum allowed"

@dataclass
class ValidationOutcome:
    result: ValidationResult
    reason: str
    details: Dict[str, Any] = None
    timestamp: datetime = None
    step: str = "Step 6"
    
    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.now()

class MedicineValidationStep6:
    
    def __init__(self):
        self.queries = None
        self.is_initialized = False
        
        self.prescriber_hierarchy = {
            "A": {"level": 5, "name": "Specialist Consultant"},
            "B1": {"level": 4, "name": "Medical Officer"},
            "B2": {"level": 3, "name": "Senior Medical Officer"},
            "C": {"level": 2, "name": "Physician Assistant"},
            "D1": {"level": 1, "name": "Nurse Prescriber Level 1"},
            "D2": {"level": 0, "name": "Nurse Prescriber Level 2"}
        }
        
        self.chronic_conditions = {
            'MEDI02', 'MEDI07', 'MEDI06', 'MEDI08', 'MEDI09', 'MEDI10'
        }
        
        self.male_only_conditions = {
            'SURG15', 'SURG16'
        }
        self.female_only_conditions = {
            'SURG17', 'SURG18', 'OBST01', 'OBST02', 'OBST03'
        }
        
        self.age_restricted_medicines = {
            'ASPIRIN': {'min_age': 16, 'reason': 'Risk of Reye syndrome in children'},
            'TETRACYCLINE': {'min_age': 8, 'reason': 'Tooth discoloration in children'},
            'WARFARIN': {'min_age': 18, 'reason': 'Complex dosing in pediatric patients'}
        }
    
    async def initialize(self):
        if not self.is_initialized:
            await initialize_database()
            self.queries = await get_nhis_queries()
            self.is_initialized = True
            logger.info("Medicine Validation Step 6 initialized")
    
    async def close(self):
        await close_database()
        self.is_initialized = False
        logger.info("Medicine Validation Step 6 closed")
    
    async def process_step6_medicine_validation(self, encounter_id: str) -> ValidationOutcome:
        if not self.is_initialized:
            await self.initialize()
        
        step_results = {
            "encounter_id": encounter_id,
            "steps_completed": [],
            "steps_passed": [],
            "steps_failed": [],
            "overall_result": None,
            "medicine_results": [],
            "specific_rejection_reasons": []
        }
        
        try:
            logger.info(f"STEP 6: Starting medicine validation for encounter {encounter_id}")
            
            claim_data = await self.queries.get_claim_with_calculated_age(encounter_id)
            if not claim_data:
                return ValidationOutcome(
                    result=ValidationResult.REJECTED,
                    reason="REJECT: Claim not found for medicine validation",
                    details={
                        "encounter_id": encounter_id,
                        "category": "Medicine Validation Failed"
                    }
                )
            
            step_results["steps_completed"].append("medicines_present_check")
            medicines_check = await self._check_medicines_present(claim_data)
            
            if medicines_check.result == ValidationResult.APPROVED and not medicines_check.details.get('medicines_found'):
                step_results["steps_passed"].append({
                    "step": "medicines_present_check",
                    "status": "PASSED",
                    "message": medicines_check.reason,
                    "details": medicines_check.details
                })
                step_results["overall_result"] = "APPROVED"
                
                return ValidationOutcome(
                    result=ValidationResult.APPROVED,
                    reason="STEP 6 COMPLETED: No medicines to validate",
                    details={
                        "encounter_id": encounter_id,
                        "medicines_count": 0,
                        "total_medicine_cost": 0.0,
                        "medicine_cost_approved": 0.0,
                        "medicine_cost_denied": 0.0,
                        "next_step": "Step 7: Investigation Validation",
                        "step_by_step_results": step_results,
                        "category": "Medicine Validation Passed"
                    }
                )
            
            if medicines_check.result != ValidationResult.APPROVED:
                step_results["steps_failed"].append({
                    "step": "medicines_present_check",
                    "status": "FAILED",
                    "message": medicines_check.reason,
                    "details": medicines_check.details
                })
                step_results["overall_result"] = medicines_check.result.value
                return self._create_detailed_outcome(medicines_check, step_results)
            
            step_results["steps_passed"].append({
                "step": "medicines_present_check",
                "status": "PASSED",
                "message": medicines_check.reason,
                "details": medicines_check.details
            })
            
            medicines = medicines_check.details['medicines']
            
            # Process each medicine individually
            medicine_individual_results = []
            approved_medicines = []
            partial_medicines = []
            rejected_medicines = []
            total_medicine_cost_approved = 0.0
            
            for medicine in medicines:
                individual_result = await self._process_individual_medicine(medicine, claim_data, encounter_id)
                medicine_individual_results.append(individual_result)
                
                if individual_result['final_status'] == 'APPROVED':
                    approved_medicines.append(individual_result)
                    total_medicine_cost_approved += individual_result['cost']
                elif individual_result['final_status'] == 'PARTIAL':
                    partial_medicines.append(individual_result)
                    total_medicine_cost_approved += individual_result['cost']
                elif individual_result['final_status'] == 'REJECTED':
                    rejected_medicines.append(individual_result)
                    

            total_medicine_cost_rejected = sum(med['cost'] for med in rejected_medicines)
            
            # Store detailed results
            step_results["medicine_results"] = {
                "approved": approved_medicines,
                "partial": partial_medicines,
                "rejected": rejected_medicines
            }
            
            step_results["medicine_costs"] = {
                "approved_cost": total_medicine_cost_approved,
                "rejected_cost": total_medicine_cost_rejected,
                "rejected_count": len(rejected_medicines),
                "total_cost": total_medicine_cost_approved,
                "total_cost": total_medicine_cost_approved + total_medicine_cost_rejected
            }
            
            # Create medicine outcomes for compatibility
            medicine_outcomes = []
            for result in medicine_individual_results:
                medicine_outcomes.append({
                    "medicine_code": result['medicine_code'],
                    "medicine_name": result['medicine_name'],
                    "prescribed_dosage": result['prescribed_dosage'],
                    "frequency": result['frequency'],
                    "duration_days": result['duration_days'],
                    "dosage_result": result['dosage_result'],
                    "validation_details": result['validation_details'],
                    "tariff_calculation": result['tariff_calculation']
                })
            
            # Determine overall result based on individual medicine results
            if rejected_medicines and not approved_medicines and not partial_medicines:
                # All medicines rejected - collect specific reasons
                specific_reasons = []
                primary_reason = None
                
                for med in rejected_medicines:
                    if med.get('rejection_reason'):
                        specific_reasons.append(med['rejection_reason'])
                        if not primary_reason:
                            primary_reason = med['rejection_reason']
                
                # Get the most common reason or use the first one
                if specific_reasons:
                    from collections import Counter
                    reason_counts = Counter(specific_reasons)
                    most_common_reason = reason_counts.most_common(1)[0][0]
                    primary_reason = most_common_reason
                else:
                    primary_reason = "Medicine validation failed"
                
                step_results["steps_failed"].append({
                    "step": "individual_medicine_validation",
                    "status": "FAILED",
                    "message": f"All {len(rejected_medicines)} medicines rejected: {primary_reason}",
                    "details": {
                        "rejected_count": len(rejected_medicines),
                        "specific_reasons": specific_reasons,
                        "primary_reason": primary_reason
                    }
                })
                step_results["overall_result"] = "REJECTED"
                step_results["specific_rejection_reasons"] = specific_reasons
                
                return ValidationOutcome(
                    result=ValidationResult.REJECTED,
                    reason=f"REJECT: {primary_reason}", 
                    details={
                        "encounter_id": encounter_id,
                        "rejected_medicines": len(rejected_medicines),
                        "specific_rejection_reason": primary_reason,
                        "all_rejection_reasons": specific_reasons,
                        "rejected_medicine_details": rejected_medicines,
                        "total_medicine_cost": 0.0,
                        "medicine_cost_approved": 0.0,
                        "medicine_cost_denied": 0.0,
                        "step_by_step_results": step_results,
                        "stage6_details": {
                            "medicine_outcomes": medicine_outcomes
                        },
                        "category": "Medicine Validation Failed"
                    }
                )
            
            elif rejected_medicines and (approved_medicines or partial_medicines):
                # Partial approval - collect rejection reasons for rejected medicines
                specific_reasons = []
                for med in rejected_medicines:
                    if med.get('rejection_reason'):
                        specific_reasons.append(med['rejection_reason'])
                
                primary_reason = specific_reasons[0] if specific_reasons else "Some medicines rejected"
                
                step_results["steps_passed"].append({
                    "step": "individual_medicine_validation",
                    "status": "PARTIAL",
                    "message": f"Partial approval: {len(approved_medicines)} approved, {len(partial_medicines)} partial, {len(rejected_medicines)} rejected",
                    "details": {
                        "approved_count": len(approved_medicines),
                        "partial_count": len(partial_medicines),
                        "rejected_count": len(rejected_medicines),
                        "rejection_reasons": specific_reasons
                    }
                })
                step_results["overall_result"] = "PARTIAL"
                
                return ValidationOutcome(
                result=ValidationResult.PARTIAL,
                reason=f"PARTIAL: Some medicines approved, others rejected due to {primary_reason}",
                details={
                    "encounter_id": encounter_id,
                    "approved_medicines": len(approved_medicines),
                    "partial_medicines": len(partial_medicines),
                    "rejected_medicines": len(rejected_medicines),
                    "specific_rejection_reason": primary_reason,
                    "all_rejection_reasons": specific_reasons,
                    "total_medicine_cost": round(total_medicine_cost_approved, 2),
                    "medicine_cost_approved": round(total_medicine_cost_approved, 2),
                    "medicine_cost_denied": round(total_medicine_cost_rejected, 2),
                    "has_rejections": True,
                    "next_step": "Step 7: Investigation Validation",
                    "step_by_step_results": step_results,
                    "stage6_details": {
                        "medicine_outcomes": medicine_outcomes
                    },
                    "category": "Medicine Validation Partial"
                }
            )
            
            else:
                
                step_results["steps_passed"].append({
                    "step": "individual_medicine_validation",
                    "status": "PASSED",
                    "message": f"All medicines approved: {len(approved_medicines)} full approval, {len(partial_medicines)} partial approval",
                    "details": {
                        "approved_count": len(approved_medicines),
                        "partial_count": len(partial_medicines)
                    }
                })
                step_results["overall_result"] = "APPROVED"
                
                return ValidationOutcome(
                    result=ValidationResult.APPROVED,
                    reason="STEP 6 COMPLETED: Medicine validation passed",
                    details={
                        "encounter_id": encounter_id,
                        "medicines_validated": len(approved_medicines) + len(partial_medicines),
                        "total_medicine_cost": round(total_medicine_cost_approved, 2),
                        "medicine_cost_approved": round(total_medicine_cost_approved, 2),
                        "medicine_cost_denied": round(total_medicine_cost_rejected, 2),
                        "has_rejections": False,
                        "next_step": "Step 7: Investigation Validation",
                        "step_by_step_results": step_results,
                        "stage6_details": {
                            "medicine_outcomes": medicine_outcomes
                        },
                        "category": "Medicine Validation Passed"
                    }
                )
            
        except Exception as e:
            logger.error(f"Error in Step 6 medicine validation: {e}")
            step_results["steps_failed"].append({
                "step": "system_error",
                "status": "ERROR",
                "message": f"System error: {str(e)}",
                "details": {"error_type": type(e).__name__}
            })
            step_results["overall_result"] = "PENDING"
            
            return ValidationOutcome(
                result=ValidationResult.PENDING,
                reason="PEND: System error during medicine validation",
                details={
                    "error": str(e),
                    "encounter_id": encounter_id,
                    "step_by_step_results": step_results,
                    "category": "Medicine Validation Error"
                }
            )

    async def _process_individual_medicine(self, medicine: Dict, claim_data: Dict, encounter_id: str) -> Dict:
        """Process a single medicine individually and return its result"""
        try:
            medicine_code = medicine['medicine_code']
            
            
            individual_issues = []
            
            # Check admission period for this medicine
            admission_check = await self._check_medicine_admission_period(claim_data, [medicine])
            if not admission_check['valid']:
                individual_issues.append({
                    'type': 'admission_period',
                    'reason': MedicineRejectReason.MEDICINE_DISPENSED_OUTSIDE_ADMISSION.value,
                    'details': admission_check
                })
            
            # Check duplicates for this medicine
            duplicate_check = await self._check_duplicate_medicine_claims(claim_data, [medicine])
            if not duplicate_check['valid']:
                individual_issues.append({
                    'type': 'duplicate',
                    'reason': MedicineRejectReason.DUPLICATE_CLAIMS.value,
                    'details': duplicate_check
                })
            
            # Check gender appropriateness
            gender_check = await self._check_gender_diagnosis_mismatch(claim_data)
            if not gender_check['valid']:
                individual_issues.append({
                    'type': 'gender_mismatch',
                    'reason': MedicineRejectReason.GENDER_DIAGNOSIS_MISMATCH.value,
                    'details': gender_check
                })
            
            # Check age appropriateness for this medicine
            age_check = await self._check_age_medicine_appropriateness(claim_data, [medicine])
            if not age_check['valid']:
                individual_issues.append({
                    'type': 'age_inappropriate',
                    'reason': MedicineRejectReason.AGE_DIAGNOSIS_MISMATCH.value,
                    'details': age_check
                })
            
            # Check prescription appropriateness for this medicine
            prescription_check = await self._check_inappropriate_prescription(claim_data, [medicine])
            if not prescription_check['valid']:
                individual_issues.append({
                    'type': 'inappropriate_prescription',
                    'reason': MedicineRejectReason.INAPPROPRIATE_PRESCRIPTION.value,
                    'details': prescription_check
                })
            
            # If there are critical issues, reject this medicine
            if individual_issues:
                primary_issue = individual_issues[0]
                return {
                    'medicine_code': medicine_code,
                    'medicine_name': medicine.get('medicine_name', ''),
                    'prescribed_dosage': medicine.get('prescribed_dosage', ''),
                    'frequency': medicine.get('frequency', ''),
                    'duration_days': medicine.get('duration_days', 0),
                    'final_status': 'REJECTED',
                    'rejection_reason': primary_issue['reason'],
                    'issues': individual_issues,
                    'cost': 0.0,
                    'dosage_result': DosageResult.EXCESSIVE_OVERSUPPLY.value,
                    'validation_details': {
                        'dosage_category': DosageResult.EXCESSIVE_OVERSUPPLY.value,
                        'action_required': 'Reject - validation failed',
                        'rejection_reason': primary_issue['reason']
                    },
                    'tariff_calculation': {
                        'total_cost': 0.0,
                        'cost_calculation': f"Rejected due to: {primary_issue['reason']}",
                        'validation_result': primary_issue['reason']
                    }
                }
            
            # Check formulary for this medicine
            formulary_check = await self._validate_formulary([medicine], encounter_id)
            if formulary_check.result == ValidationResult.REJECTED:
                return {
                    'medicine_code': medicine_code,
                    'medicine_name': medicine.get('medicine_name', ''),
                    'prescribed_dosage': medicine.get('prescribed_dosage', ''),
                    'frequency': medicine.get('frequency', ''),
                    'duration_days': medicine.get('duration_days', 0),
                    'final_status': 'REJECTED',
                    'rejection_reason': MedicineRejectReason.NON_FORMULARY_MEDICINE.value,
                    'cost': 0.0,
                    'dosage_result': DosageResult.EXCESSIVE_OVERSUPPLY.value,
                    'validation_details': {
                        'dosage_category': DosageResult.EXCESSIVE_OVERSUPPLY.value,
                        'action_required': 'Reject - not in formulary',
                        'rejection_reason': MedicineRejectReason.NON_FORMULARY_MEDICINE.value
                    },
                    'tariff_calculation': {
                        'total_cost': 0.0,
                        'cost_calculation': 'Rejected - not in NHIS formulary',
                        'validation_result': MedicineRejectReason.NON_FORMULARY_MEDICINE.value
                    }
                }
            
            # Check prescriber level for this medicine
            prescriber_check = await self._check_prescriber_level([medicine], claim_data['prescriber_level'])
            if prescriber_check.result != ValidationResult.APPROVED:
                return {
                    'medicine_code': medicine_code,
                    'medicine_name': medicine.get('medicine_name', ''),
                    'prescribed_dosage': medicine.get('prescribed_dosage', ''),
                    'frequency': medicine.get('frequency', ''),
                    'duration_days': medicine.get('duration_days', 0),
                    'final_status': 'REJECTED',
                    'rejection_reason': MedicineRejectReason.INVALID_PRESCRIBER_LEVEL.value,
                    'cost': 0.0,
                    'dosage_result': DosageResult.EXCESSIVE_OVERSUPPLY.value,
                    'validation_details': {
                        'dosage_category': DosageResult.EXCESSIVE_OVERSUPPLY.value,
                        'action_required': 'Reject - invalid prescriber level',
                        'rejection_reason': MedicineRejectReason.INVALID_PRESCRIBER_LEVEL.value
                    },
                    'tariff_calculation': {
                        'total_cost': 0.0,
                        'cost_calculation': 'Rejected - invalid prescriber level',
                        'validation_result': MedicineRejectReason.INVALID_PRESCRIBER_LEVEL.value
                    }
                }
            
            # Validate dosage and calculate cost
            tariff_info = await self._get_medicine_tariff(medicine_code)
            standard_dosage_info = await self._get_standard_dosage_info(medicine_code)
            
            dosage_result, calculated_tariff = await self._validate_and_calculate_medicine_cost_corrected(
                medicine, standard_dosage_info, tariff_info, encounter_id
            )
            
            # Determine final status and cost based on dosage result
            if dosage_result == DosageResult.WITHIN_LIMITS:
                final_status = 'APPROVED'
                final_cost = calculated_tariff.get('total_cost', 0.0)
                rejection_reason = None
            elif dosage_result == DosageResult.MODERATE_OVERSUPPLY:
                final_status = 'PARTIAL'
                final_cost = calculated_tariff.get('total_cost', 0.0)
                rejection_reason = None
            elif dosage_result == DosageResult.EXCESSIVE_OVERSUPPLY:
                final_status = 'REJECTED'
                final_cost = 0.0  # Set to 0 for rejected medicines
                # GET THE SPECIFIC REJECTION REASON FROM calculated_tariff
                rejection_reason = calculated_tariff.get('validation_result', 'Medicine validation failed')
            else:
                final_status = 'APPROVED'
                final_cost = calculated_tariff.get('total_cost', 0.0)
                rejection_reason = None
            
            return {
                'medicine_code': medicine_code,
                'medicine_name': medicine.get('medicine_name', ''),
                'prescribed_dosage': medicine.get('prescribed_dosage', ''),
                'frequency': medicine.get('frequency', ''),
                'duration_days': medicine.get('duration_days', 0),
                'final_status': final_status,
                'rejection_reason': rejection_reason,  # Now uses the specific reason
                'cost': final_cost,
                'dosage_result': dosage_result.value,
                'validation_details': self._get_dosage_validation_details(medicine, dosage_result, standard_dosage_info),
                'tariff_calculation': calculated_tariff
            }
            
        except Exception as e:
            logger.error(f"Error processing individual medicine {medicine.get('medicine_code', 'Unknown')}: {e}")
            return {
                'medicine_code': medicine.get('medicine_code', 'Unknown'),
                'medicine_name': medicine.get('medicine_name', ''),
                'prescribed_dosage': medicine.get('prescribed_dosage', ''),
                'frequency': medicine.get('frequency', ''),
                'duration_days': medicine.get('duration_days', 0),
                'final_status': 'REJECTED',
                'rejection_reason': f'Processing error: {str(e)}',
                'cost': 0.0,
                'dosage_result': DosageResult.EXCESSIVE_OVERSUPPLY.value,
                'validation_details': {
                    'dosage_category': DosageResult.EXCESSIVE_OVERSUPPLY.value,
                    'action_required': 'Reject - processing error',
                    'error': str(e)
                },
                'tariff_calculation': {
                    'total_cost': 0.0,
                    'cost_calculation': f'Error: {str(e)}',
                    'validation_result': f'Processing error: {str(e)}'
                }
            }

    async def _check_medicines_present(self, claim_data: Dict) -> ValidationOutcome:
        try:
            medicines = []
            
            if claim_data.get('medicine_code') and claim_data['medicine_code'] not in ['NA', '', None]:
                medicines.append({
                    'medicine_code': claim_data['medicine_code'],
                    'medicine_name': claim_data.get('medicine_name', ''),
                    'prescribed_dosage': claim_data.get('standard_dosage', ''),
                    'frequency': claim_data.get('frequency', ''),
                    'duration_days': claim_data.get('duration_days', 0)
                })
            
            if claim_data.get('medicine_code_procedure') and claim_data['medicine_code_procedure'] not in ['NA', '', None]:
                medicines.append({
                    'medicine_code': claim_data['medicine_code_procedure'],
                    'medicine_name': claim_data.get('medicine_name_procedure', ''),
                    'prescribed_dosage': claim_data.get('standard_dosage_procedure', ''),
                    'frequency': claim_data.get('frequency_procedure', ''),
                    'duration_days': claim_data.get('duration_days_procedure', 0)
                })
            
            if not medicines:
                logger.info(f"No medicines found for {claim_data.get('encounter_id')} - skipping medicine validation")
                return ValidationOutcome(
                    result=ValidationResult.APPROVED,
                    reason="No medicines present - medicine validation not required",
                    details={
                        "medicines_found": False,
                        "medicine_count": 0
                    }
                )
            
            for med in medicines:
                try:
                    if isinstance(med['duration_days'], str):
                        med['duration_days'] = int(med['duration_days'])
                except (ValueError, TypeError):
                    med['duration_days'] = 0
            
            logger.info(f"Found {len(medicines)} medicines for validation")
            
            return ValidationOutcome(
                result=ValidationResult.APPROVED,
                reason=f"Found {len(medicines)} medicines for validation",
                details={
                    "medicines_found": True,
                    "medicine_count": len(medicines),
                    "medicines": medicines
                }
            )
            
        except Exception as e:
            logger.error(f"Error checking medicines present: {e}")
            return ValidationOutcome(
                result=ValidationResult.PENDING,
                reason="PEND: Error checking for medicines",
                details={"error": str(e)}
            )
    
    async def _check_specific_medicine_issues(self, claim_data: Dict, medicines: List[Dict]) -> ValidationOutcome:
        try:
            rejection_reasons = []
            issue_details = []
            
            admission_check = await self._check_medicine_admission_period(claim_data, medicines)
            if not admission_check['valid']:
                rejection_reasons.append(MedicineRejectReason.MEDICINE_DISPENSED_OUTSIDE_ADMISSION.value)
                issue_details.append(admission_check)
            
            duplicate_check = await self._check_duplicate_medicine_claims(claim_data, medicines)
            if not duplicate_check['valid']:
                rejection_reasons.append(MedicineRejectReason.DUPLICATE_CLAIMS.value)
                issue_details.append(duplicate_check)
            
            polypharmacy_check = await self._check_polypharmacy(medicines, claim_data)
            if not polypharmacy_check['valid']:
                rejection_reasons.append(MedicineRejectReason.POLYPHARMACY.value)
                issue_details.append(polypharmacy_check)
            
            chronic_check = await self._check_multiple_chronic_visits(claim_data)
            if not chronic_check['valid']:
                rejection_reasons.append(MedicineRejectReason.MULTIPLE_CHRONIC_VISIT.value)
                issue_details.append(chronic_check)
            
            gender_check = await self._check_gender_diagnosis_mismatch(claim_data)
            if not gender_check['valid']:
                rejection_reasons.append(MedicineRejectReason.GENDER_DIAGNOSIS_MISMATCH.value)
                issue_details.append(gender_check)
            
            age_check = await self._check_age_medicine_appropriateness(claim_data, medicines)
            if not age_check['valid']:
                rejection_reasons.append(MedicineRejectReason.AGE_DIAGNOSIS_MISMATCH.value)
                issue_details.append(age_check)
            
            prescription_check = await self._check_inappropriate_prescription(claim_data, medicines)
            if not prescription_check['valid']:
                rejection_reasons.append(MedicineRejectReason.INAPPROPRIATE_PRESCRIPTION.value)
                issue_details.append(prescription_check)
            
            if rejection_reasons:
                primary_reason = rejection_reasons[0]
                logger.error(f"Medicine validation failed: {primary_reason}")
                
                return ValidationOutcome(
                    result=ValidationResult.REJECTED,
                    reason=f"REJECT: {primary_reason}",
                    details={
                        "rejection_reasons": rejection_reasons,
                        "issue_details": issue_details,
                        "category": "Medicine Validation Failed",
                        "specific_reason": primary_reason
                    }
                )
            
            return ValidationOutcome(
                result=ValidationResult.APPROVED,
                reason="Specific medicine validation checks passed",
                details={"all_checks_passed": True}
            )
            
        except Exception as e:
            logger.error(f"Error in specific medicine validation: {e}")
            return ValidationOutcome(
                result=ValidationResult.PENDING,
                reason="PEND: Error in specific medicine validation",
                details={"error": str(e)}
            )
    
    async def _check_medicine_admission_period(self, claim_data: Dict, medicines: List[Dict]) -> Dict:
        try:
            if claim_data.get('admission_date') and claim_data.get('discharge_date'):
                admission_date = claim_data['admission_date']
                discharge_date = claim_data['discharge_date']
                claim_date = claim_data.get('service_date', claim_data.get('created_at'))
                
                if claim_date:
                    if isinstance(claim_date, str):
                        claim_date = datetime.fromisoformat(claim_date.replace('Z', '+00:00'))
                    if isinstance(admission_date, str):
                        admission_date = datetime.fromisoformat(admission_date.replace('Z', '+00:00'))
                    if isinstance(discharge_date, str):
                        discharge_date = datetime.fromisoformat(discharge_date.replace('Z', '+00:00'))
                    
                    if claim_date < admission_date or claim_date > discharge_date + timedelta(days=1):
                        return {
                            'valid': False,
                            'reason': 'Medicine dispensed outside admission period',
                            'details': {
                                'claim_date': claim_date.isoformat(),
                                'admission_date': admission_date.isoformat(),
                                'discharge_date': discharge_date.isoformat()
                            }
                        }
            
            return {'valid': True, 'reason': 'Medicine within valid dispensing period'}
            
        except Exception as e:
            logger.error(f"Error checking admission period: {e}")
            return {'valid': True, 'reason': 'Could not validate admission period'}
    
    async def _check_duplicate_medicine_claims(self, claim_data: Dict, medicines: List[Dict]) -> Dict:
        try:
            nhis_no = claim_data.get('nhis_no')
            claim_date = claim_data.get('service_date', claim_data.get('created_at'))
            
            if not nhis_no or not claim_date:
                return {'valid': True, 'reason': 'Cannot check duplicates - missing data'}
            
            for medicine in medicines:
                med_code = medicine['medicine_code']
                
                duplicate_query = """
                SELECT encounter_id, service_date, medicine_code
                FROM claims_with_calculated_age 
                WHERE nhis_no = $1 
                    AND (medicine_code = $2 OR medicine_code_procedure = $2)
                    AND encounter_id != $3
                    AND service_date >= $4::date - INTERVAL '30 days'
                ORDER BY service_date DESC
                LIMIT 5
                """
                
                duplicates = await self.queries.db.fetch_all(
                    duplicate_query, 
                    nhis_no, med_code, claim_data['encounter_id'], claim_date
                )
                
                if duplicates:
                    return {
                        'valid': False,
                        'reason': 'Duplicate medicine claims found',
                        'details': {
                            'duplicate_medicine': med_code,
                            'duplicate_count': len(duplicates),
                            'recent_claims': [
                                {
                                    'encounter_id': dup['encounter_id'],
                                    'service_date': dup['service_date'].isoformat() if dup['service_date'] else None
                                }
                                for dup in duplicates
                            ]
                        }
                    }
            return {'valid': True, 'reason': 'No duplicate medicine claims found'}
            
        except Exception as e:
            logger.error(f"Error checking duplicate claims: {e}")
            return {'valid': True, 'reason': 'Could not validate duplicates'}
    
    async def _check_polypharmacy(self, medicines: List[Dict], claim_data: Dict) -> Dict:
        try:
            medicine_count = len(medicines)
            
            if medicine_count > 5:
                return {
                    'valid': False,
                    'reason': 'Polypharmacy detected',
                    'details': {
                        'medicine_count': medicine_count,
                        'threshold': 5,
                        'medicines': [med['medicine_code'] for med in medicines]
                    }
                }
            
            dangerous_combinations = [
                {'drugs': ['WARFARIN', 'ASPIRIN'], 'risk': 'Bleeding risk'},
                {'drugs': ['METFORMIN', 'INSULIN'], 'risk': 'Hypoglycemia risk'}
            ]
            
            medicine_codes = [med['medicine_code'] for med in medicines]
            
            for combo in dangerous_combinations:
                if all(any(drug in med_code for med_code in medicine_codes) for drug in combo['drugs']):
                    return {
                        'valid': False,
                        'reason': 'Dangerous drug combination detected',
                        'details': {
                            'combination': combo['drugs'],
                            'risk': combo['risk']
                        }
                    }
            
            return {'valid': True, 'reason': 'No polypharmacy issues detected'}
            
        except Exception as e:
            logger.error(f"Error checking polypharmacy: {e}")
            return {'valid': True, 'reason': 'Could not validate polypharmacy'}
    
    async def _check_multiple_chronic_visits(self, claim_data: Dict) -> Dict:
        try:
            gdrg_code = claim_data.get('gdrg_code', '')
            nhis_no = claim_data.get('nhis_no')
            claim_date = claim_data.get('service_date', claim_data.get('created_at'))
            
            if not any(chronic in gdrg_code for chronic in self.chronic_conditions):
                return {'valid': True, 'reason': 'Not a chronic condition claim'}
            
            if not nhis_no or not claim_date:
                return {'valid': True, 'reason': 'Cannot check chronic visits - missing data'}
            
            chronic_query = """
            SELECT encounter_id, service_date, gdrg_code
            FROM claims_with_calculated_age 
            WHERE nhis_no = $1 
                AND encounter_id != $2
                AND service_date >= $3::date - INTERVAL '30 days'
                AND service_date <= $3::date + INTERVAL '30 days'
                AND (gdrg_code LIKE 'MEDI02%' OR gdrg_code LIKE 'MEDI07%' OR 
                     gdrg_code LIKE 'MEDI06%' OR gdrg_code LIKE 'MEDI08%' OR
                     gdrg_code LIKE 'MEDI09%' OR gdrg_code LIKE 'MEDI10%')
            ORDER BY service_date DESC
            """
            
            chronic_visits = await self.queries.db.fetch_all(
                chronic_query, nhis_no, claim_data['encounter_id'], claim_date
            )
            
            if len(chronic_visits) >= 2:
                return {
                    'valid': False,
                    'reason': 'Multiple chronic visits detected',
                    'details': {
                        'chronic_visits_count': len(chronic_visits) + 1,
                        'period_days': 30,
                        'recent_visits': [
                            {
                                'encounter_id': visit['encounter_id'],
                                'service_date': visit['service_date'].isoformat() if visit['service_date'] else None,
                                'gdrg_code': visit['gdrg_code']
                            }
                            for visit in chronic_visits
                        ]
                    }
                }
            
            return {'valid': True, 'reason': 'No excessive chronic visits detected'}
            
        except Exception as e:
            logger.error(f"Error checking chronic visits: {e}")
            return {'valid': True, 'reason': 'Could not validate chronic visits'}
    
    async def _check_gender_diagnosis_mismatch(self, claim_data: Dict) -> Dict:
        try:
            gender = claim_data.get('gender', '').upper()
            gdrg_code = claim_data.get('gdrg_code', '')
            
            if not gender or not gdrg_code:
                return {'valid': True, 'reason': 'Cannot validate gender - missing data'}
            
            if gender == 'F' and any(male_condition in gdrg_code for male_condition in self.male_only_conditions):
                return {
                    'valid': False,
                    'reason': 'Gender diagnosis mismatch - male condition for female patient',
                    'details': {
                        'patient_gender': gender,
                        'gdrg_code': gdrg_code,
                        'expected_gender': 'M'
                    }
                }
            
            if gender == 'M' and any(female_condition in gdrg_code for female_condition in self.female_only_conditions):
                return {
                    'valid': False,
                    'reason': 'Gender diagnosis mismatch - female condition for male patient',
                    'details': {
                        'patient_gender': gender,
                        'gdrg_code': gdrg_code,
                        'expected_gender': 'F'
                    }
                }
            
            return {'valid': True, 'reason': 'No gender diagnosis mismatch'}
            
        except Exception as e:
            logger.error(f"Error checking gender diagnosis: {e}")
            return {'valid': True, 'reason': 'Could not validate gender diagnosis'}
    
    async def _check_age_medicine_appropriateness(self, claim_data: Dict, medicines: List[Dict]) -> Dict:
        try:
            age_years = claim_data.get('calculated_age_years', 0)
            
            if age_years is None:
                return {'valid': True, 'reason': 'Cannot validate age - missing age data'}
            
            age_years = int(age_years) if age_years else 0
            
            for medicine in medicines:
                med_code = medicine['medicine_code']
                med_name = medicine.get('medicine_name', '').upper()
                
                for restricted_med, restrictions in self.age_restricted_medicines.items():
                    if restricted_med in med_code or restricted_med in med_name:
                        min_age = restrictions['min_age']
                        if age_years < min_age:
                            return {
                                'valid': False,
                                'reason': 'Age inappropriate medicine prescribed',
                                'details': {
                                    'patient_age': age_years,
                                    'medicine': med_code,
                                    'minimum_age': min_age,
                                    'restriction_reason': restrictions['reason']
                                }
                            }
            
            if age_years < 2:
                infant_restricted = ['CODEINE', 'TRAMADOL', 'MORPHINE']
                for medicine in medicines:
                    med_name = medicine.get('medicine_name', '').upper()
                    if any(restricted in med_name for restricted in infant_restricted):
                        return {
                            'valid': False,
                            'reason': 'Age inappropriate medicine - infant restriction',
                            'details': {
                                'patient_age': age_years,
                                'medicine': medicine['medicine_code'],
                                'restriction': 'Not suitable for infants under 2 years'
                            }
                        }
            
            return {'valid': True, 'reason': 'Medicines appropriate for patient age'}
            
        except Exception as e:
            logger.error(f"Error checking age appropriateness: {e}")
            return {'valid': True, 'reason': 'Could not validate age appropriateness'}
    
    async def _check_inappropriate_prescription(self, claim_data: Dict, medicines: List[Dict]) -> Dict:
        try:
            gdrg_code = claim_data.get('gdrg_code', '')
            
            inappropriate_combinations = {
                'MEDI02': {
                    'inappropriate': ['STEROID', 'DEXAMETHASONE'],
                    'reason': 'Steroids contraindicated in diabetes'
                },
                'MEDI07': {
                    'inappropriate': ['NSAID', 'IBUPROFEN', 'DICLOFENAC'],
                    'reason': 'NSAIDs contraindicated in heart failure'
                },
                'MEDI06': {
                    'inappropriate': ['NSAID', 'GENTAMICIN'],
                    'reason': 'Nephrotoxic drugs contraindicated in kidney disease'
                }
            }
            
            for medicine in medicines:
                med_code = medicine['medicine_code']
                med_name = medicine.get('medicine_name', '').upper()
                
                for condition_prefix, restrictions in inappropriate_combinations.items():
                    if condition_prefix in gdrg_code:
                        inappropriate_meds = restrictions['inappropriate']
                        if any(inappropriate_med in med_code or inappropriate_med in med_name 
                               for inappropriate_med in inappropriate_meds):
                            return {
                                'valid': False,
                                'reason': 'Clinically inappropriate prescription',
                                'details': {
                                    'medicine': med_code,
                                    'diagnosis': gdrg_code,
                                    'clinical_reason': restrictions['reason']
                                }
                            }
            
            return {'valid': True, 'reason': 'No inappropriate prescriptions detected'}
            
        except Exception as e:
            logger.error(f"Error checking inappropriate prescription: {e}")
            return {'valid': True, 'reason': 'Could not validate prescription appropriateness'}
    
    def _extract_specific_reasons_from_formulary(self, formulary_check: ValidationOutcome) -> List[str]:
        reasons = []
        
        if formulary_check.details:
            if formulary_check.details.get('diagnosis_mismatches'):
                reasons.append(MedicineRejectReason.TREATMENT_DIAGNOSIS_MISMATCH.value)
            
            if formulary_check.details.get('non_formulary_medicines'):
                reasons.append(MedicineRejectReason.NON_FORMULARY_MEDICINE.value)
        
        return reasons if reasons else [MedicineRejectReason.INAPPROPRIATE_PRESCRIPTION.value]
    
    def _create_detailed_outcome(self, original_result: ValidationOutcome, step_results: Dict) -> ValidationOutcome:
        if original_result.details is None:
            original_result.details = {}
        
        original_result.details["step_by_step_results"] = step_results
        original_result.details["validation_summary"] = {
            "total_steps": len(step_results["steps_completed"]),
            "steps_passed": len(step_results["steps_passed"]),
            "steps_failed": len(step_results["steps_failed"]),
            "final_result": step_results["overall_result"]
        }
        
        if "category" not in original_result.details:
            original_result.details["category"] = "Medicine Validation Failed"
        
        return original_result
    
    async def _validate_formulary(self, medicines: List[Dict], encounter_id: str) -> ValidationOutcome:
        try:
            claim_data = await self.queries.get_claim_with_calculated_age(encounter_id)
            diagnosis_gdrg = claim_data.get('gdrg_code')
            procedure_gdrg = claim_data.get('gdrg_code_procedure')

            all_formulary_codes = set()
            
            if diagnosis_gdrg:
                diag_medicines = await self.queries.get_gdrg_medicines(diagnosis_gdrg)
                for med in diag_medicines:
                    if med.get('medicine_code'):
                        all_formulary_codes.add(med['medicine_code'])
            
            if procedure_gdrg:
                proc_medicines = await self.queries.get_gdrg_medicines(procedure_gdrg)
                for med in proc_medicines:
                    if med.get('medicine_code'):
                        all_formulary_codes.add(med['medicine_code'])

            non_formulary_medicines = []
            formulary_results = []

            for medicine in medicines:
                med_code = medicine['medicine_code']
                in_formulary = med_code in all_formulary_codes
                
                formulary_results.append({
                    "medicine_code": med_code,
                    "medicine_name": medicine.get('medicine_name', ''),
                    "in_formulary": in_formulary,
                    "checked_against": f"Combined formulary from {diagnosis_gdrg} and {procedure_gdrg}"
                })
                
                if not in_formulary:
                    non_formulary_medicines.append({
                        "medicine_code": med_code,
                        "medicine_name": medicine.get('medicine_name', '')
                    })
            
            if non_formulary_medicines:
                return ValidationOutcome(
                    result=ValidationResult.REJECTED,
                    reason=f"REJECT: {MedicineRejectReason.NON_FORMULARY_MEDICINE.value}",
                    details={
                        "total_medicines": len(medicines),
                        "non_formulary_medicines": non_formulary_medicines,
                        "formulary_results": formulary_results,
                        "category": "Medicine Validation Failed",
                        "specific_reason": MedicineRejectReason.NON_FORMULARY_MEDICINE.value
                    }
                )
            
            return ValidationOutcome(
                result=ValidationResult.APPROVED,
                reason="All medicines found in NHIS formulary",
                details={
                    "total_medicines": len(medicines),
                    "formulary_compliance": "100%",
                    "formulary_results": formulary_results
                }
            )
            
        except Exception as e:
            logger.error(f"Error validating formulary: {e}")
            return ValidationOutcome(
                result=ValidationResult.PENDING,
                reason="PEND: Error validating NHIS formulary",
                details={"error": str(e)}
            )
    
    async def _check_prescriber_level(self, medicines: List[Dict], claim_prescriber_level: str) -> ValidationOutcome:
        try:
            if not claim_prescriber_level:
                return ValidationOutcome(
                    result=ValidationResult.REJECTED,
                    reason=f"REJECT: {MedicineRejectReason.INVALID_PRESCRIBER_LEVEL.value} - missing prescriber level",
                    details={
                        "claim_prescriber_level": claim_prescriber_level,
                        "category": "Medicine Validation Failed",
                        "specific_reason": MedicineRejectReason.INVALID_PRESCRIBER_LEVEL.value
                    }
                )
            
            if claim_prescriber_level not in self.prescriber_hierarchy:
                return ValidationOutcome(
                    result=ValidationResult.REJECTED,
                    reason=f"REJECT: {MedicineRejectReason.INVALID_PRESCRIBER_LEVEL.value} - unknown level",
                    details={
                        "claim_prescriber_level": claim_prescriber_level,
                        "valid_levels": list(self.prescriber_hierarchy.keys()),
                        "category": "Medicine Validation Failed",
                        "specific_reason": MedicineRejectReason.INVALID_PRESCRIBER_LEVEL.value
                    }
                )
            
            prescriber_info = self.prescriber_hierarchy[claim_prescriber_level]
            prescriber_authority_level = prescriber_info["level"]
            
            prescriber_violations = []
            
            for medicine in medicines:
                med_code = medicine['medicine_code']
                required_level = self._determine_required_prescriber_level(medicine)
                
                if prescriber_authority_level < required_level:
                    prescriber_violations.append({
                        "medicine_code": med_code,
                        "medicine_name": medicine['medicine_name'],
                        "required_level": required_level,
                        "prescriber_level": prescriber_authority_level
                    })
            
            if prescriber_violations:
                return ValidationOutcome(
                    result=ValidationResult.REJECTED,
                    reason=f"REJECT: {MedicineRejectReason.INVALID_PRESCRIBER_LEVEL.value}",
                    details={
                        "claim_prescriber_level": claim_prescriber_level,
                        "prescriber_authority": prescriber_authority_level,
                        "violations": prescriber_violations,
                        "category": "Medicine Validation Failed",
                        "specific_reason": MedicineRejectReason.INVALID_PRESCRIBER_LEVEL.value
                    }
                )
            
            logger.info(f"Prescriber level {claim_prescriber_level} valid for all medicines")
            return ValidationOutcome(
                result=ValidationResult.APPROVED,
                reason=f"Prescriber level validation passed - {prescriber_info['name']}",
                details={
                    "claim_prescriber_level": claim_prescriber_level,
                    "prescriber_name": prescriber_info['name'],
                    "authority_level": prescriber_authority_level,
                    "medicines_validated": len(medicines)
                }
            )
            
        except Exception as e:
            logger.error(f"Error checking prescriber level: {e}")
            return ValidationOutcome(
                result=ValidationResult.PENDING,
                reason="PEND: Error validating prescriber level",
                details={"error": str(e)}
            )
    
    def _determine_required_prescriber_level(self, medicine: Dict) -> int:
        med_name = medicine.get('medicine_name', '').lower()
        
        if any(term in med_name for term in ['injection', 'iv', 'intravenous']):
            return 2
        elif any(term in med_name for term in ['controlled', 'narcotic', 'morphine']):
            return 3
        elif any(term in med_name for term in ['chemotherapy', 'oncology']):
            return 4
        else:
            return 0
    
    def _validate_frequency_against_inference(self, prescribed_freq: str, inference_freq: str) -> bool:
        try:
            freq_hierarchy = {
                'OD': 1, 'ONCE': 1,
                'BD': 2, 'BID': 2, 'TWICE': 2,
                'TID': 3, 'TDS': 3,
                'QID': 4, 'QDS': 4
            }
            
            prescribed_level = freq_hierarchy.get(prescribed_freq.upper(), 1)
            max_allowed_level = freq_hierarchy.get(inference_freq.upper(), 1)
            
            return prescribed_level <= max_allowed_level
            
        except Exception as e:
            logger.error(f"Error validating frequency: {e}")
            return True
    
    async def _validate_dosage_duration(self, medicines: List[Dict], encounter_id: str) -> ValidationOutcome:
        try:
            medicine_outcomes = []
            
            for medicine in medicines:
                med_code = medicine['medicine_code']
                
                tariff_info = await self._get_medicine_tariff(med_code)
                
                standard_dosage_info = await self._get_standard_dosage_info(med_code)
                
                dosage_result, calculated_tariff = await self._validate_and_calculate_medicine_cost_corrected(
                    medicine, standard_dosage_info, tariff_info, encounter_id
                )
                
                medicine_outcomes.append({
                    "medicine_code": med_code,
                    "medicine_name": medicine.get('medicine_name', ''),
                    "prescribed_dosage": medicine.get('prescribed_dosage', ''),
                    "frequency": medicine.get('frequency', ''),
                    "duration_days": medicine.get('duration_days', 0),
                    "dosage_result": dosage_result.value,
                    "validation_details": self._get_dosage_validation_details(medicine, dosage_result, standard_dosage_info),
                    "tariff_calculation": calculated_tariff
                })
            
            logger.info(f"Dosage validation and tariff calculation completed for {len(medicine_outcomes)} medicines")
            
            return ValidationOutcome(
                result=ValidationResult.APPROVED,
                reason="Dosage validation and tariff calculation completed",
                details={
                    "medicines_count": len(medicine_outcomes),
                    "medicine_outcomes": medicine_outcomes
                }
            )
            
        except Exception as e:
            logger.error(f"Error validating dosage and calculating tariffs: {e}")
            return ValidationOutcome(
                result=ValidationResult.PENDING,
                reason="PEND: Error validating dosage and calculating tariffs",
                details={"error": str(e)}
            )
    
    async def _get_medicine_tariff(self, medicine_code: str) -> Dict:
        try:
            tariff_query = """
            SELECT 
                code,
                generic_name,
                unit_of_pricing,
                price,
                level_of_prescribing
            FROM medicines 
            WHERE code = $1
            """
            
            result = await self.queries.db.fetch_all(tariff_query, medicine_code)
            if result:
                tariff_data = result[0]
                
                if tariff_data['price'] is not None:
                    logger.info(f"Found tariff for {medicine_code}: {tariff_data['price']} GHS per {tariff_data['unit_of_pricing']}")
                    
                    return {
                        "code": tariff_data['code'],
                        "generic_name": tariff_data.get('generic_name', ''),
                        "unit_of_pricing": tariff_data.get('unit_of_pricing', ''),
                        "price": float(tariff_data['price']),
                        "level_of_prescribing": tariff_data.get('level_of_prescribing')
                    }
                else:
                    logger.error(f"Medicine {medicine_code} found in database but price is NULL")
                    return {
                        "code": medicine_code,
                        "generic_name": tariff_data.get('generic_name', ''),
                        "unit_of_pricing": tariff_data.get('unit_of_pricing', ''),
                        "price": None,
                        "level_of_prescribing": tariff_data.get('level_of_prescribing'),
                        "error": f"Price is NULL in medicines table for {medicine_code}"
                    }
            else:
                logger.error(f"Medicine {medicine_code} not found in medicines table")
                return {
                    "code": medicine_code,
                    "generic_name": "",
                    "unit_of_pricing": "",
                    "price": None,
                    "level_of_prescribing": None,
                    "error": f"Medicine {medicine_code} not found in medicines table"
                }
                
        except Exception as e:
            logger.error(f"Database error getting medicine tariff for {medicine_code}: {e}")
            return {
                "code": medicine_code,
                "generic_name": "",
                "unit_of_pricing": "",
                "price": None,
                "level_of_prescribing": None,
                "error": f"Database error: {str(e)}"
            }
    
    async def _get_standard_dosage_info(self, medicine_code: str) -> Dict:
        try:
            standard_query = """
            SELECT 
                standard_dosage,
                frequency,
                duration_days,
                prescribing_levels
            FROM clinical_diagnosis_inferences 
            WHERE medicine_code = $1 
                AND is_active = true
            LIMIT 1
            """
            
            result = await self.queries.db.fetch_all(standard_query, medicine_code)
            if result:
                return result[0]
            else:
                procedure_query = """
                SELECT 
                    standard_dosage,
                    frequency,
                    duration_days,
                    prescribing_levels
                FROM clinical_procedure_inferences 
                WHERE medicine_code = $1
                LIMIT 1
                """
                
                result = await self.queries.db.fetch_all(procedure_query, medicine_code)
                if result:
                    return result[0]
                
            return {}
            
        except Exception as e:
            logger.error(f"Error getting standard dosage info: {e}")
            return {}
    
    async def _get_encounter_type(self, encounter_id: str) -> str:
        try:
            encounter_query = """
            SELECT encounter_type, admission_date, discharge_date
            FROM claims_v3 
            WHERE encounter_id = $1
            LIMIT 1
            """
            
            result = await self.queries.db.fetch_all(encounter_query, encounter_id)
            
            if result:
                encounter_data = result[0]
                encounter_type = encounter_data.get('encounter_type', '').upper()
                
                if not encounter_type:
                    if encounter_data.get('admission_date') and encounter_data.get('discharge_date'):
                        encounter_type = 'IPD'
                    else:
                        encounter_type = 'OPD'
                
                logger.info(f"Encounter {encounter_id} type: {encounter_type}")
                return encounter_type
            else:
                logger.warning(f"No encounter data found for {encounter_id}, defaulting to OPD")
                return 'OPD'
                
        except Exception as e:
            logger.error(f"Error fetching encounter type: {e}")
            return 'OPD'

    async def _get_duration_days_from_db(self, encounter_id: str, medicine_code: str) -> float:
        try:
            duration_query = """
            SELECT 
                CASE 
                    WHEN medicine_code = $2 THEN duration_days
                    WHEN medicine_code_procedure = $2 THEN duration_days_procedure
                    ELSE duration_days
                END as duration_days
            FROM claims_v3 
            WHERE encounter_id = $1
                AND (medicine_code = $2 OR medicine_code_procedure = $2)
            LIMIT 1
            """
            
            result = await self.queries.db.fetch_all(duration_query, encounter_id, medicine_code)
            
            if result and result[0]['duration_days'] is not None:
                duration_days = float(result[0]['duration_days'])
                logger.info(f"Fetched duration_days from DB for {medicine_code}: {duration_days} days")
                return duration_days
            else:
                logger.warning(f"No duration_days found in DB for encounter {encounter_id}, medicine {medicine_code}")
                return 0.0
                
        except Exception as e:
            logger.error(f"Error fetching duration_days from DB: {e}")
            return 0.0

    async def _validate_and_calculate_medicine_cost_corrected(self, medicine: Dict, standard_info: Dict, tariff_info: Dict, encounter_id: str) -> Tuple[DosageResult, Dict]:
        try:
            prescribed_dosage = medicine.get('prescribed_dosage', '')
            frequency = medicine.get('frequency', 'OD')
            
            encounter_type = await self._get_encounter_type(encounter_id)
            
            duration_days = await self._get_duration_days_from_db(encounter_id, medicine['medicine_code'])
            
            unit_price = tariff_info.get('price')
            if unit_price is None:
                error_message = tariff_info.get('error', 'No tariff price available in medicines table')
                logger.error(f"Cannot calculate cost for {medicine['medicine_code']}: {error_message}")
                
                return DosageResult.WITHIN_LIMITS, {
                    "unit_price": None,
                    "unit_of_pricing": tariff_info.get('unit_of_pricing', ''),
                    "error": error_message,
                    "duration_days_from_db": duration_days,
                    "total_cost": None,
                    "cost_calculation": f"Cannot calculate - {error_message}",
                    "dosage_adjustment": "Cannot calculate - missing tariff data"
                }
            
            unit_price = float(unit_price)
            unit_of_pricing = tariff_info.get('unit_of_pricing', '')
            
            frequency_multiplier = self._get_frequency_multiplier(frequency)
            
            prescribed_amount = self._extract_dosage_amount(prescribed_dosage)
            standard_amount = self._extract_dosage_amount(standard_info.get('standard_dosage', ''))
            
            tariff_unit_amount = self._extract_dosage_amount(unit_of_pricing)
            
            validation_dosage_ratio = prescribed_amount / standard_amount if standard_amount > 0 else 1.0
            
            cost_dosage_ratio = prescribed_amount / tariff_unit_amount if tariff_unit_amount > 0 else 1.0
            
            logger.info(f"Dosage calculation - Prescribed: {prescribed_amount}, Standard: {standard_amount}, Tariff unit: {tariff_unit_amount}")
            logger.info(f"Validation ratio: {validation_dosage_ratio}, Cost ratio: {cost_dosage_ratio}")
            
            dosage_result, rejection_reason = self._determine_dosage_result_enhanced(
                prescribed_amount, standard_amount, duration_days, frequency, standard_info, encounter_type
            )
            
            final_cost = self._calculate_simple_cost(
                dosage_result, frequency_multiplier, duration_days, 
                unit_price, medicine['medicine_code'], prescribed_amount, standard_amount, tariff_unit_amount
            )
            
            frequency_compliant = self._validate_frequency_against_inference(frequency, standard_info.get('frequency', 'OD'))
            max_duration = standard_info.get('duration_days')
            duration_compliant = duration_days <= float(max_duration) if max_duration else True
            
            frequency_rejection_reason = MedicineRejectReason.INAPPROPRIATE_PRESCRIPTION.value if not frequency_compliant else None
            
            duration_rejection_reason = None
            if not duration_compliant:
                if encounter_type.upper() == 'OPD':
                    duration_rejection_reason = MedicineRejectReason.OVERSUPPLY_OF_MEDICINE.value
                else:
                    duration_rejection_reason = MedicineRejectReason.INAPPROPRIATE_PRESCRIPTION.value
            
            tariff_calculation = {
                "unit_price": unit_price,
                "unit_of_pricing": unit_of_pricing,
                "frequency": frequency,
                "frequency_multiplier": frequency_multiplier,
                "duration_days_from_db": duration_days,
                "prescribed_amount": prescribed_amount,
                "standard_amount": standard_amount,
                "tariff_unit_amount": tariff_unit_amount,
                "validation_dosage_ratio": validation_dosage_ratio,
                "cost_dosage_ratio": cost_dosage_ratio,
                "total_cost": final_cost,
                "cost_calculation": f"{frequency_multiplier} × {unit_price} × {duration_days} days × {cost_dosage_ratio} dosage ratio = {final_cost} GHS",
                "dosage_adjustment": self._get_dosage_adjustment_reason(dosage_result),
                "validation_result": rejection_reason,
                "encounter_type": encounter_type,
                "frequency_validation": {
                    "prescribed_frequency": frequency,
                    "max_allowed_frequency": standard_info.get('frequency', 'Unknown'),
                    "frequency_compliant": frequency_compliant,
                    "rejection_reason": frequency_rejection_reason
                },
                "duration_validation": {
                    "prescribed_duration": duration_days,
                    "max_allowed_duration": max_duration,
                    "duration_compliant": duration_compliant,
                    "rejection_reason": duration_rejection_reason,
                    "encounter_type_note": f"Duration violations for {encounter_type}: {duration_rejection_reason if duration_rejection_reason else 'N/A'}"
                }
            }
            
            logger.info(f"Enhanced calculation for {medicine['medicine_code']} ({encounter_type}): {frequency_multiplier} × {unit_price} × {duration_days} × {cost_dosage_ratio} = {final_cost} GHS ({dosage_result.value})")
            
            return dosage_result, tariff_calculation
            
        except Exception as e:
            logger.error(f"Error calculating medicine cost: {e}")
            return DosageResult.WITHIN_LIMITS, {
                "error": str(e),
                "total_cost": None,
                "cost_calculation": "Error in calculation"
            }
    
    def _determine_dosage_result_enhanced(self, prescribed_amount: float, standard_amount: float, 
                                         duration_days: float, prescribed_freq: str, standard_info: Dict, encounter_type: str = 'OPD') -> Tuple[DosageResult, str]:
        try:
            if standard_amount > 0:
                dosage_ratio = prescribed_amount / standard_amount
                logger.info(f"DOSAGE VALIDATION: Prescribed={prescribed_amount}, Standard={standard_amount}, Ratio={dosage_ratio}")
                
                if dosage_ratio > 2.0:
                    logger.warning(f"EXCESSIVE OVERSUPPLY: Dosage ratio {dosage_ratio} exceeds 2.0 threshold")
                    return DosageResult.EXCESSIVE_OVERSUPPLY, MedicineRejectReason.INAPPROPRIATE_PRESCRIPTION.value
                elif dosage_ratio > 1.0:
                    logger.info(f"MODERATE OVERSUPPLY: Dosage ratio {dosage_ratio} exceeds 1.0 but within 2.0")
                    return DosageResult.MODERATE_OVERSUPPLY, "Dosage exceeds standard amount"
            
            inference_freq = standard_info.get('frequency', 'OD')
            if not self._validate_frequency_against_inference(prescribed_freq, inference_freq):
                logger.warning(f"Frequency {prescribed_freq} exceeds maximum {inference_freq} - INAPPROPRIATE PRESCRIPTION")
                return DosageResult.EXCESSIVE_OVERSUPPLY, MedicineRejectReason.INAPPROPRIATE_PRESCRIPTION.value
            
            max_duration = standard_info.get('duration_days')
            if max_duration:
                try:
                    max_duration = float(max_duration)
                    if duration_days > max_duration:
                        if encounter_type.upper() == 'OPD':
                            logger.warning(f"Duration {duration_days} days exceeds maximum {max_duration} days - OVERSUPPLY (OPD)")
                            return DosageResult.EXCESSIVE_OVERSUPPLY, MedicineRejectReason.OVERSUPPLY_OF_MEDICINE.value
                        else:
                            logger.warning(f"Duration {duration_days} days exceeds maximum {max_duration} days - INAPPROPRIATE PRESCRIPTION (IPD)")
                            return DosageResult.EXCESSIVE_OVERSUPPLY, MedicineRejectReason.INAPPROPRIATE_PRESCRIPTION.value
                    elif duration_days > (max_duration * 0.8):
                        return DosageResult.MODERATE_OVERSUPPLY, "Duration near maximum limit"
                except (ValueError, TypeError):
                    logger.error(f"Invalid duration in inference data: {max_duration}")
            
            return DosageResult.WITHIN_LIMITS, "Within acceptable limits"
                
        except Exception as e:
            logger.error(f"Error in enhanced dosage validation: {e}")
            return DosageResult.WITHIN_LIMITS, "Validation error - defaulted to approved"
    
    def _calculate_simple_cost(self, dosage_result: DosageResult, frequency_multiplier: float,
                              duration_days: float, unit_price: float, medicine_code: str, 
                              prescribed_amount: float, standard_amount: float, tariff_unit_amount: float) -> float:
        try:
            if dosage_result == DosageResult.EXCESSIVE_OVERSUPPLY:
                would_be_cost = frequency_multiplier * unit_price * duration_days * (prescribed_amount / tariff_unit_amount if tariff_unit_amount > 0 else 1.0)
                logger.info(f"REJECTED medicine {medicine_code}: Cost would be {would_be_cost:.2f} GHS but rejected, setting to 0.0 GHS")
                return would_be_cost
            elif dosage_result == DosageResult.MODERATE_OVERSUPPLY:
                effective_dosage_ratio = standard_amount / tariff_unit_amount if tariff_unit_amount > 0 else 1.0
                logger.info(f"Moderate oversupply - using standard amount ({standard_amount}) for {medicine_code}")
            else:
                effective_dosage_ratio = prescribed_amount / tariff_unit_amount if tariff_unit_amount > 0 else 1.0
            
            total_cost = frequency_multiplier * unit_price * duration_days * effective_dosage_ratio
            
            return round(total_cost, 2)
            
        except Exception as e:
            logger.error(f"Error in simple cost calculation: {e}")
            return 0.0
    
    def _extract_dosage_amount(self, dosage_str: str) -> float:
        try:
            import re
            if not dosage_str:
                logger.warning(f"Empty dosage string provided")
                return 0.0
            
            logger.info(f"Extracting dosage amount from: '{dosage_str}'")
            
            clean_str = dosage_str.strip().lower()
            
            patterns = [
                r'(\d+(?:\.\d+)?)\s*mg',
                r'(\d+(?:\.\d+)?)\s*g',
                r'(\d+(?:\.\d+)?)\s*ml',
                r'(\d+(?:\.\d+)?)\s*mcg',
                r'(\d+(?:\.\d+)?)\s*(?:tab|tablet)',
                r'(\d+(?:\.\d+)?)\s*(?:cap|capsule)',
                r'(\d+(?:\.\d+)?)\s*unit',
                r'(\d+(?:\.\d+)?)'
            ]
            
            for pattern in patterns:
                match = re.search(pattern, clean_str)
                if match:
                    amount = float(match.group(1))
                    logger.info(f"Extracted dosage amount: {amount} using pattern: {pattern}")
                    return amount
            
            logger.warning(f"Could not extract dosage amount from: '{dosage_str}', defaulting to 0.0")
            return 0.0
            
        except Exception as e:
            logger.error(f"Error extracting dosage amount from '{dosage_str}': {e}")
            return 0.0
    
    def _get_frequency_multiplier(self, frequency: str) -> float:
        frequency_map = {
            'OD': 1.0, 'BD': 2.0, 'TID': 3.0, 'TDS': 3.0, 'QID': 4.0,
            'QDS': 4.0, 'BID': 2.0, 'stat': 1.0, 'SOS': 1.0, 'PRN': 1.0
        }
        return frequency_map.get(frequency.upper(), 1.0)
    
    def _get_dosage_validation_details(self, medicine: Dict, result: DosageResult, standard_info: Dict = None) -> Dict:
        details = {
            "dosage_category": result.value,
            "prescribed_dosage": medicine.get('prescribed_dosage', ''),
            "duration_days": medicine.get('duration_days', 0),
            "frequency": medicine.get('frequency', ''),
            "action_required": self._get_action_for_dosage_result(result)
        }
        
        if standard_info:
            prescribed_freq = medicine.get('frequency', 'OD')
            inference_freq = standard_info.get('frequency', 'OD')
            max_duration = standard_info.get('duration_days')
            
            details.update({
                "frequency_validation": {
                    "prescribed": prescribed_freq,
                    "max_allowed": inference_freq,
                    "compliant": self._validate_frequency_against_inference(prescribed_freq, inference_freq)
                },
                "duration_validation": {
                    "prescribed_days": medicine.get('duration_days', 0),
                    "max_allowed_days": max_duration,
                    "compliant": float(medicine.get('duration_days', 0)) <= float(max_duration) if max_duration else True
                }
            })
        
        return details
    
    def _get_action_for_dosage_result(self, result: DosageResult) -> str:
        if result == DosageResult.WITHIN_LIMITS:
            return "Approve full amount"
        elif result == DosageResult.MODERATE_OVERSUPPLY:
            return "Approve at standard amount"
        elif result == DosageResult.EXCESSIVE_OVERSUPPLY:
            return "Reject - excessive oversupply"
        else:
            return "Review required"
    
    def _get_dosage_adjustment_reason(self, dosage_result: DosageResult) -> str:
        if dosage_result == DosageResult.WITHIN_LIMITS:
            return "Full prescribed amount approved"
        elif dosage_result == DosageResult.MODERATE_OVERSUPPLY:
            return "Approved at standard amount due to moderate oversupply"
        elif dosage_result == DosageResult.EXCESSIVE_OVERSUPPLY:
            return "Rejected due to excessive oversupply"
        else:
            return "Standard approval"