import asyncio
import json
import logging
from typing import Dict, List, Optional, Any
from dataclasses import dataclass
from enum import Enum
from datetime import datetime
from decimal import Decimal

from neon_db_connection import get_nhis_queries, initialize_database, close_database

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class ValidationResult(Enum):
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    FLAGGED = "FLAGGED"
    PENDING = "PENDING"
    PARTIAL = "PARTIAL"

@dataclass
class ValidationOutcome:
    result: ValidationResult
    reason: str
    details: Dict[str, Any] = None
    timestamp: datetime = None
    step: str = "Step 4"
    
    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.now()

class FacilityCredentialingValidator:
    
    def __init__(self):
        self.queries = None
        self.is_initialized = False
    
    async def initialize(self):
        if not self.is_initialized:
            await initialize_database()
            self.queries = await get_nhis_queries()
            self.is_initialized = True
            logger.info("Facility Credentialing Validator initialized")
    
    async def close(self):
        await close_database()
        self.is_initialized = False
        logger.info("Facility Credentialing Validator closed")
    
    async def process_step4_credentialing_check(self, encounter_id: str) -> ValidationOutcome:
        if not self.is_initialized:
            await self.initialize()
        
        try:
            logger.info(f"STEP 4: Starting credentialing check for encounter {encounter_id}")
            
            claim = await self.queries.get_claim_with_calculated_age(encounter_id)
            if not claim:
                return ValidationOutcome(
                    result=ValidationResult.REJECTED,
                    reason="REJECT: Claim not found",
                    details={"encounter_id": encounter_id}
                )
            
            has_procedure = bool(
                claim.get('icd10_code_procedure') and 
                claim['icd10_code_procedure'] not in ['NA', '', None, 'nan', 'NaN', 'NAN'] and 
                len(str(claim['icd10_code_procedure']).strip()) >= 3
            )
            
            logger.info(f"Encounter {encounter_id}: Diagnosis={claim.get('icd10_code')}, Procedure={claim.get('icd10_code_procedure')}, Has_Procedure={has_procedure}")
            
            if not has_procedure:
                logger.info(f"Single path validation for {encounter_id}")
                return await self._validate_single_path(encounter_id, claim)
            
            logger.info(f"Dual path validation for {encounter_id}")
            return await self._validate_dual_paths(encounter_id, claim)
            
        except Exception as e:
            logger.error(f"Error in Step 4 credentialing check: {e}")
            return ValidationOutcome(
                result=ValidationResult.PENDING,
                reason="PEND: System error during credentialing check",
                details={"error": str(e), "encounter_id": encounter_id}
            )
    
    async def _validate_single_path(self, encounter_id: str, claim: Dict) -> ValidationOutcome:
        
        step_results = {
            "encounter_id": encounter_id,
            "steps_completed": [],
            "steps_passed": [],
            "steps_failed": [],
            "overall_result": None
        }
        
        try:
            step_results["steps_completed"].append("1_facility_information")
            facility_info_result = await self._get_facility_information_from_claims(encounter_id)
            
            if facility_info_result.result == ValidationResult.APPROVED:
                step_results["steps_passed"].append({
                    "step": "1_facility_information",
                    "status": "PASSED",
                    "message": facility_info_result.reason,
                    "details": {
                        "provider_name": facility_info_result.details['claim_data']['provider_name'],
                        "facility_level": facility_info_result.details['claim_data']['healthcare_level']
                    }
                })
            else:
                step_results["steps_failed"].append({
                    "step": "1_facility_information", 
                    "status": "FAILED",
                    "message": facility_info_result.reason,
                    "details": facility_info_result.details
                })
                step_results["overall_result"] = facility_info_result.result.value
                return self._create_detailed_outcome(facility_info_result, step_results)
            
            claim_data = facility_info_result.details['claim_data']
            gdrg_code = claim_data['gdrg_code']
            
            logger.info(f"Single path G-DRG for {encounter_id}: {gdrg_code}")
            
            step_results["steps_completed"].append("2_gdrg_level_eligibility")
            level_eligibility_result = await self._check_facility_level_gdrg_eligibility(claim_data, gdrg_code)
            
            if level_eligibility_result.result == ValidationResult.APPROVED:
                step_results["steps_passed"].append({
                    "step": "2_gdrg_level_eligibility",
                    "status": "PASSED", 
                    "message": level_eligibility_result.reason,
                    "details": level_eligibility_result.details
                })
            else:
                step_results["steps_failed"].append({
                    "step": "2_gdrg_level_eligibility",
                    "status": "FAILED",
                    "message": level_eligibility_result.reason,
                    "details": level_eligibility_result.details
                })
                step_results["overall_result"] = level_eligibility_result.result.value
                return self._create_detailed_outcome(level_eligibility_result, step_results)
            
            step_results["steps_completed"].append("3_age_requirements")
            age_check_result = await self._validate_patient_age_requirements(claim_data, gdrg_code)
            
            if age_check_result.result == ValidationResult.APPROVED:
                step_results["steps_passed"].append({
                    "step": "3_age_requirements",
                    "status": "PASSED",
                    "message": age_check_result.reason,
                    "details": age_check_result.details
                })
            else:
                step_results["steps_failed"].append({
                    "step": "3_age_requirements",
                    "status": "FAILED",
                    "message": age_check_result.reason,
                    "details": age_check_result.details
                })
                step_results["overall_result"] = age_check_result.result.value
                return self._create_detailed_outcome(age_check_result, step_results)
            
            step_results["steps_completed"].append("4_gender_requirements")
            gender_check_result = await self._validate_gender_requirements(claim_data, gdrg_code)
            
            if gender_check_result.result == ValidationResult.APPROVED:
                step_results["steps_passed"].append({
                    "step": "4_gender_requirements",
                    "status": "PASSED",
                    "message": gender_check_result.reason,
                    "details": gender_check_result.details
                })
            else:
                step_results["steps_failed"].append({
                    "step": "4_gender_requirements",
                    "status": "FAILED",
                    "message": gender_check_result.reason,
                    "details": gender_check_result.details
                })
                step_results["overall_result"] = gender_check_result.result.value
                return self._create_detailed_outcome(gender_check_result, step_results)
            
            step_results["overall_result"] = "APPROVED"
            
            final_result = ValidationOutcome(
                result=ValidationResult.APPROVED,
                reason="STEP 4 PASSED: Facility credentialing and level checks completed",
                details={
                    "encounter_id": encounter_id,
                    "provider_name": claim_data['provider_name'],
                    "facility_level": claim_data['healthcare_level'],
                    "gdrg_code": gdrg_code,
                    "gdrg_description": claim_data.get('gdrg_description'),
                    "validation_approach": "single_path_validation",
                    "next_step": "Step 5: G-DRG Determination",
                    "step_by_step_results": step_results
                }
            )
            
            logger.info(f"STEP 4 PASSED for {encounter_id}: {claim_data['provider_name']} Level {claim_data['healthcare_level']}, G-DRG {gdrg_code}")
            return final_result
            
        except Exception as e:
            logger.error(f"Error in single path validation: {e}")
            return ValidationOutcome(
                result=ValidationResult.PENDING,
                reason="PEND: System error during validation",
                details={"error": str(e), "encounter_id": encounter_id}
            )
    
    async def _validate_dual_paths(self, encounter_id: str, claim: Dict) -> ValidationOutcome:
        
        logger.info(f"=== DUAL PATH CREDENTIALING START for {encounter_id} ===")
        
        facility_check = await self._get_facility_information_from_claims(encounter_id)
        if facility_check.result != ValidationResult.APPROVED:
            logger.error(f"Facility check failed for {encounter_id}")
            return facility_check
        
        claim_data = facility_check.details['claim_data']
        
        diagnosis_gdrg = claim_data.get('gdrg_code')
        logger.info(f"Diagnosis G-DRG from claim: {diagnosis_gdrg}")
        
        procedure_gdrg = claim_data.get('gdrg_code_procedure')
        logger.info(f"Procedure G-DRG from claim: {procedure_gdrg}")
        
        diagnosis_result = None
        procedure_result = None
        
        if diagnosis_gdrg:
            logger.info(f"--- Validating DIAGNOSIS path: {diagnosis_gdrg} ---")
            diagnosis_result = await self._validate_gdrg_path(claim_data, diagnosis_gdrg, "diagnosis")
            if diagnosis_result['valid']:
                logger.info(f"✓ Diagnosis G-DRG {diagnosis_gdrg}: PASSED all checks")
            else:
                logger.warning(f"✗ Diagnosis G-DRG {diagnosis_gdrg}: FAILED - {diagnosis_result['reason']}")
        
        if procedure_gdrg:
            logger.info(f"--- Validating PROCEDURE path: {procedure_gdrg} ---")
            procedure_result = await self._validate_gdrg_path(claim_data, procedure_gdrg, "procedure")
            if procedure_result['valid']:
                logger.info(f"✓ Procedure G-DRG {procedure_gdrg}: PASSED all checks")
            else:
                logger.warning(f"✗ Procedure G-DRG {procedure_gdrg}: FAILED - {procedure_result['reason']}")
        
        approved_paths = []
        rejected_paths = []
        
        if diagnosis_result and diagnosis_result['valid']:
            approved_paths.append({"type": "diagnosis", "gdrg": diagnosis_gdrg})
        elif diagnosis_result:
            rejected_paths.append({"type": "diagnosis", "gdrg": diagnosis_gdrg, "reason": diagnosis_result['reason']})
        
        if procedure_result and procedure_result['valid']:
            approved_paths.append({"type": "procedure", "gdrg": procedure_gdrg})
        elif procedure_result:
            rejected_paths.append({"type": "procedure", "gdrg": procedure_gdrg, "reason": procedure_result['reason']})
        
        total_paths = len(approved_paths) + len(rejected_paths)
        
        logger.info(f"=== DUAL PATH RESULTS for {encounter_id} ===")
        logger.info(f"Approved paths: {len(approved_paths)}/{total_paths}")
        logger.info(f"Rejected paths: {len(rejected_paths)}/{total_paths}")
        
        if len(approved_paths) == total_paths and total_paths > 0:
            logger.info(f"BOTH PATHS APPROVED for {encounter_id}")
            return ValidationOutcome(
                result=ValidationResult.APPROVED,
                reason=f"STEP 4 PASSED: Both G-DRG paths validated",
                details={
                    "encounter_id": encounter_id,
                    "validation_approach": "dual_path_independent_validation",
                    "approved_paths": approved_paths,
                    "total_paths": total_paths,
                    "next_step": "Step 5: G-DRG Determination (will select highest tariff)"
                }
            )
        
        elif len(approved_paths) > 0 and len(rejected_paths) > 0:
            logger.warning(f"PARTIAL APPROVAL for {encounter_id}: {len(approved_paths)} approved, {len(rejected_paths)} rejected")
            for path in approved_paths:
                logger.info(f"  ✓ Approved: {path['type']} G-DRG {path['gdrg']}")
            for path in rejected_paths:
                logger.warning(f"  ✗ Rejected: {path['type']} G-DRG {path['gdrg']} - {path['reason']}")
            
            return ValidationOutcome(
                result=ValidationResult.PARTIAL,
                reason=f"PARTIAL: {len(approved_paths)}/{total_paths} G-DRG paths approved",
                details={
                    "encounter_id": encounter_id,
                    "validation_approach": "dual_path_independent_validation",
                    "approved_paths": approved_paths,
                    "rejected_paths": rejected_paths,
                    "total_paths": total_paths,
                    "next_step": "Step 5: Approved path(s) proceed, rejected excluded"
                }
            )
        
        else:
            logger.error(f"ALL PATHS REJECTED for {encounter_id}")
            for path in rejected_paths:
                logger.error(f"  ✗ {path['type']} G-DRG {path['gdrg']}: {path['reason']}")
            
            return ValidationOutcome(
                result=ValidationResult.REJECTED,
                reason=f"REJECT: All {total_paths} G-DRG path(s) failed credentialing",
                details={
                    "encounter_id": encounter_id,
                    "validation_approach": "dual_path_independent_validation",
                    "rejected_paths": rejected_paths,
                    "total_paths": total_paths
                }
            )
    
    async def _validate_gdrg_path(self, claim_data: Dict, gdrg_code: str, path_type: str) -> Dict:
        
        try:
            logger.info(f"  Checking facility level eligibility for {path_type} G-DRG {gdrg_code}")
            level_check = await self._check_facility_level_gdrg_eligibility(claim_data, gdrg_code)
            if level_check.result != ValidationResult.APPROVED:
                logger.warning(f"  Level check failed: {level_check.reason}")
                return {"valid": False, "reason": level_check.reason}
            logger.info(f"  Level check passed for {gdrg_code}")
            
            logger.info(f"  Checking age requirements for {path_type} G-DRG {gdrg_code}")
            age_check = await self._validate_patient_age_requirements(claim_data, gdrg_code)
            if age_check.result != ValidationResult.APPROVED:
                logger.warning(f"  Age check failed: {age_check.reason}")
                return {"valid": False, "reason": age_check.reason}
            logger.info(f"  Age check passed for {gdrg_code}")
            
            logger.info(f"  Checking gender requirements for {path_type} G-DRG {gdrg_code}")
            gender_check = await self._validate_gender_requirements(claim_data, gdrg_code)
            if gender_check.result != ValidationResult.APPROVED:
                logger.warning(f"  Gender check failed: {gender_check.reason}")
                return {"valid": False, "reason": gender_check.reason}
            logger.info(f"  Gender check passed for {gdrg_code}")
            
            logger.info(f"  All credentialing checks PASSED for {path_type} G-DRG {gdrg_code}")
            return {"valid": True, "reason": "All credentialing checks passed"}
            
        except Exception as e:
            logger.error(f"Error validating {path_type} path for {gdrg_code}: {e}")
            return {"valid": False, "reason": f"Validation error: {str(e)}"}
    
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
        
        return original_result
    
    async def _get_facility_information_from_claims(self, encounter_id: str) -> ValidationOutcome:
        try:
            claim = await self.queries.get_claim_with_calculated_age(encounter_id)
            if not claim:
                return ValidationOutcome(
                    result=ValidationResult.REJECTED,
                    reason="REJECT: Claim not found",
                    details={"encounter_id": encounter_id}
                )
            
            required_facility_fields = ['provider_name', 'healthcare_level']
            missing_fields = []
            
            for field in required_facility_fields:
                if not claim.get(field):
                    missing_fields.append(field)
            
            if missing_fields:
                return ValidationOutcome(
                    result=ValidationResult.REJECTED,
                    reason="REJECT: Missing facility information in claim",
                    details={
                        "encounter_id": encounter_id,
                        "missing_fields": missing_fields
                    }
                )
            
            logger.info(f"Facility info: {claim['provider_name']} (Level {claim['healthcare_level']})")
            
            return ValidationOutcome(
                result=ValidationResult.APPROVED,
                reason="Facility information retrieved from claims data",
                details={
                    "claim_data": claim,
                    "data_source": "claims_v3_table"
                }
            )
            
        except Exception as e:
            logger.error(f"Error getting facility information from claims: {e}")
            return ValidationOutcome(
                result=ValidationResult.PENDING,
                reason="PEND: Error retrieving facility information",
                details={"error": str(e)}
            )
    
    async def _check_facility_level_gdrg_eligibility(self, claim_data: Dict, gdrg_code: str) -> ValidationOutcome:
        try:
            facility_level = str(claim_data['healthcare_level'])
            provider_name = claim_data['provider_name']
            encounter_type = claim_data['encounter_type']
            
            logger.info(f"Checking Level {facility_level} eligibility for G-DRG {gdrg_code}")
            
            diagnosis_query = """
            SELECT 
                gdrg_code,
                gdrg_description,
                encounter_type_eligible_facility,
                encounter_type
            FROM clinical_diagnosis_inferences 
            WHERE gdrg_code = $1 
            AND encounter_type = $2
            AND (is_active = true OR is_active = 't')
            ORDER BY encounter_type
            """
            
            diagnosis_results = await self.queries.db.fetch_all(diagnosis_query, gdrg_code, encounter_type)
            
            procedure_query = """
            SELECT 
                gdrg_code,
                gdrg_description,
                level_procedure as encounter_type_eligible_facility,
                encounter_type
            FROM clinical_procedure_inferences 
            WHERE gdrg_code = $1
            AND encounter_type = $2
            ORDER BY encounter_type
            """
            
            procedure_results = await self.queries.db.fetch_all(procedure_query, gdrg_code, encounter_type)
            
            all_results = list(diagnosis_results) + list(procedure_results)
            
            logger.info(f"Found {len(all_results)} inference records for G-DRG {gdrg_code} with encounter type {encounter_type}")
            
            if not all_results:
                logger.warning(f"No strict match found, searching without encounter type constraint")
                
                loose_diagnosis_query = """
                SELECT 
                    gdrg_code,
                    gdrg_description,
                    encounter_type_eligible_facility,
                    encounter_type
                FROM clinical_diagnosis_inferences 
                WHERE gdrg_code = $1 
                AND (is_active = true OR is_active = 't')
                ORDER BY encounter_type
                """
                
                loose_diagnosis_results = await self.queries.db.fetch_all(loose_diagnosis_query, gdrg_code)
                
                loose_procedure_query = """
                SELECT 
                    gdrg_code,
                    gdrg_description,
                    level_procedure as encounter_type_eligible_facility,
                    encounter_type
                FROM clinical_procedure_inferences 
                WHERE gdrg_code = $1
                ORDER BY encounter_type
                """
                
                loose_procedure_results = await self.queries.db.fetch_all(loose_procedure_query, gdrg_code)
                
                all_results = list(loose_diagnosis_results) + list(loose_procedure_results)
                
                logger.info(f"Found {len(all_results)} inference records without encounter type constraint")
                
                if not all_results:
                    logger.warning(f"No inference records found, checking tariff table")
                    icd10_fallback = await self.queries.get_tariff_by_gdrg(gdrg_code)
                    if icd10_fallback:
                        logger.info(f"G-DRG {gdrg_code} found in icd10_codes table - using permissive validation")
                        return ValidationOutcome(
                            result=ValidationResult.APPROVED,
                            reason="G-DRG found in tariff database - permissive validation applied",
                            details={
                                "facility_level": facility_level,
                                "gdrg_code": gdrg_code,
                                "validation_mode": "permissive_tariff_based",
                                "data_source": "icd10_codes_table_fallback"
                            }
                        )
                    
                    logger.error(f"G-DRG {gdrg_code} not found in any table")
                    return ValidationOutcome(
                        result=ValidationResult.REJECTED,
                        reason="REJECT: G-DRG not found in clinical inference data",
                        details={
                            "gdrg_code": gdrg_code,
                            "encounter_type": encounter_type,
                            "provider_name": provider_name,
                            "facility_level": facility_level,
                            "searched_tables": ["clinical_diagnosis_inferences", "clinical_procedure_inferences"]
                        }
                    )
            
            best_match = None
            for result in all_results:
                if result['encounter_type'] == encounter_type:
                    best_match = result
                    break
            
            if not best_match:
                best_match = all_results[0]
                logger.warning(f"Using first available record as fallback")
            
            gdrg_info = best_match
            eligible_facilities = gdrg_info['encounter_type_eligible_facility']
            
            logger.info(f"Raw eligible facilities data: {eligible_facilities}")
            
            if isinstance(eligible_facilities, str):
                try:
                    eligible_facilities = json.loads(eligible_facilities)
                    logger.info(f"Parsed eligible facilities from JSON: {eligible_facilities}")
                except json.JSONDecodeError:
                    eligible_facilities = eligible_facilities.strip()
                    
                    if eligible_facilities.startswith('[') and eligible_facilities.endswith(']'):
                        inner = eligible_facilities[1:-1]
                        eligible_facilities = [x.strip().strip('"').strip("'") for x in inner.split(',')]
                    elif ',' in eligible_facilities:
                        eligible_facilities = [x.strip().strip('"').strip("'") for x in eligible_facilities.split(',')]
                    else:
                        eligible_facilities = [eligible_facilities.strip('"').strip("'")]
                    
                    logger.info(f"Parsed eligible facilities from string: {eligible_facilities}")
            elif isinstance(eligible_facilities, list):
                eligible_facilities = [str(x).strip().strip('"').strip("'") for x in eligible_facilities]
                logger.info(f"Cleaned eligible facilities list: {eligible_facilities}")
            else:
                eligible_facilities = [str(eligible_facilities).strip('"').strip("'")]
                logger.info(f"Converted eligible facilities to list: {eligible_facilities}")
            
            logger.info(f"Checking if facility level '{facility_level}' is in eligible levels {eligible_facilities}")
            
            if facility_level not in eligible_facilities:
                logger.error(f"LEVEL MISMATCH: Facility level {facility_level} not in eligible levels {eligible_facilities}")
                return ValidationOutcome(
                    result=ValidationResult.REJECTED,
                    reason="REJECT: Facility Level Not Authorized for G-DRG",
                    details={
                        "provider_name": provider_name,
                        "facility_level": facility_level,
                        "gdrg_code": gdrg_code,
                        "gdrg_description": gdrg_info.get('gdrg_description'),
                        "eligible_levels": eligible_facilities,
                        "encounter_type_requested": encounter_type,
                        "encounter_type_used": gdrg_info['encounter_type']
                    }
                )
            
            logger.info(f"✓ Level {facility_level} is authorized for G-DRG {gdrg_code}")
            
            return ValidationOutcome(
                result=ValidationResult.APPROVED,
                reason="Facility level is authorized for G-DRG",
                details={
                    "facility_level": facility_level,
                    "eligible_levels": eligible_facilities,
                    "gdrg_code": gdrg_code,
                    "gdrg_description": gdrg_info.get('gdrg_description'),
                    "encounter_type_requested": encounter_type,
                    "encounter_type_used": gdrg_info['encounter_type']
                }
            )
            
        except Exception as e:
            logger.error(f"Error checking facility level G-DRG eligibility: {e}")
            return ValidationOutcome(
                result=ValidationResult.PENDING,
                reason="PEND: Error validating facility level eligibility",
                details={"error": str(e)}
            )
    
    async def _validate_patient_age_requirements(self, claim_data: Dict, gdrg_code: str) -> ValidationOutcome:
        try:
            gdrg_info_list = await self.queries.get_gdrg_info_by_code(gdrg_code)
            if not gdrg_info_list:
                logger.info(f"No G-DRG info found for {gdrg_code} - no age restrictions")
                return ValidationOutcome(
                    result=ValidationResult.APPROVED, 
                    reason="No age restrictions found",
                    details={"age_restriction_source": "none_found"}
                )
            
            gdrg_info = gdrg_info_list[0]
            age_restrictions = gdrg_info.get('age_restrictions')
            
            if not age_restrictions:
                logger.info(f"No age restrictions specified for G-DRG {gdrg_code}")
                return ValidationOutcome(
                    result=ValidationResult.APPROVED, 
                    reason="No age restrictions specified",
                    details={"age_restriction_source": "not_specified"}
                )
            
            if isinstance(age_restrictions, str):
                try:
                    age_restrictions = json.loads(age_restrictions)
                except json.JSONDecodeError:
                    logger.warning(f"Invalid age restrictions format for G-DRG {gdrg_code}")
                    return ValidationOutcome(
                        result=ValidationResult.APPROVED, 
                        reason="Invalid age restrictions format",
                        details={"age_restriction_source": "invalid_format"}
                    )
            
            patient_age = claim_data.get('calculated_age', 0)
            min_age = age_restrictions.get('min_age')
            max_age = age_restrictions.get('max_age')
            
            logger.info(f"Age check for G-DRG {gdrg_code}: Patient age={patient_age}, Min={min_age}, Max={max_age}")
            
            if min_age and patient_age < min_age:
                logger.error(f"Patient age {patient_age} below minimum {min_age}")
                return ValidationOutcome(
                    result=ValidationResult.REJECTED,
                    reason=f"REJECT: Patient age {patient_age} below minimum {min_age} for G-DRG",
                    details={
                        "patient_name": f"{claim_data.get('last_name')} {claim_data.get('other_names', '')}",
                        "patient_age": patient_age,
                        "min_age_required": min_age,
                        "gdrg_code": gdrg_code,
                        "age_restriction_source": "clinical_inference_data"
                    }
                )
            
            if max_age and patient_age > max_age:
                logger.error(f"Patient age {patient_age} above maximum {max_age}")
                return ValidationOutcome(
                    result=ValidationResult.REJECTED,
                    reason=f"REJECT: Patient age {patient_age} above maximum {max_age} for G-DRG",
                    details={
                        "patient_name": f"{claim_data.get('last_name')} {claim_data.get('other_names', '')}",
                        "patient_age": patient_age,
                        "max_age_allowed": max_age,
                        "gdrg_code": gdrg_code,
                        "age_restriction_source": "clinical_inference_data"
                    }
                )
            
            logger.info(f"✓ Patient age {patient_age} meets G-DRG requirements")
            return ValidationOutcome(
                result=ValidationResult.APPROVED,
                reason="Patient age meets G-DRG requirements",
                details={
                    "patient_age": patient_age,
                    "min_age": min_age,
                    "max_age": max_age,
                    "age_restriction_source": "clinical_inference_data"
                }
            )
            
        except Exception as e:
            logger.error(f"Error validating patient age: {e}")
            return ValidationOutcome(
                result=ValidationResult.PENDING,
                reason="PEND: Error validating patient age",
                details={"error": str(e)}
            )
    
    async def _validate_gender_requirements(self, claim_data: Dict, gdrg_code: str) -> ValidationOutcome:
        try:
            icd10_procedure = claim_data.get('icd10_code_procedure')
            icd10_code = claim_data.get('icd10_code', '')
            
            has_both_diagnosis_and_procedure = bool(
                icd10_code and icd10_code not in ['NA', '', None, 'nan', 'NaN', 'NAN'] and
                icd10_procedure and icd10_procedure not in ['NA', '', None, 'nan', 'NaN', 'NAN']
            )
            
            if has_both_diagnosis_and_procedure:
                logger.info(f"Skipping gender validation for {claim_data.get('encounter_id')} - dual path claim")
                return ValidationOutcome(
                    result=ValidationResult.APPROVED,
                    reason="Gender validation deferred to Stage 5 dual evaluation",
                    details={
                        "validation_status": "DEFERRED_TO_STAGE5",
                        "reason": "Claims with both diagnosis and procedure paths are validated separately in Stage 5"
                    }
                )
            
            gdrg_info_list = await self.queries.get_gdrg_info_by_code(gdrg_code)
            if not gdrg_info_list:
                logger.info(f"No G-DRG info found for {gdrg_code} - no gender restrictions")
                return ValidationOutcome(
                    result=ValidationResult.APPROVED, 
                    reason="No gender restrictions found",
                    details={"gender_restriction_source": "none_found"}
                )
            
            gdrg_info = gdrg_info_list[0]
            gender_restrictions = gdrg_info.get('gender_restriction')
            
            if not gender_restrictions:
                logger.info(f"No gender restrictions specified for G-DRG {gdrg_code}")
                return ValidationOutcome(
                    result=ValidationResult.APPROVED, 
                    reason="No gender restrictions specified",
                    details={"gender_restriction_source": "not_specified"}
                )
            
            if isinstance(gender_restrictions, str):
                try:
                    gender_restrictions = json.loads(gender_restrictions)
                except json.JSONDecodeError:
                    if gender_restrictions.startswith('[') and gender_restrictions.endswith(']'):
                        gender_restrictions = gender_restrictions.strip('[]').replace('"', '').split()
                    else:
                        gender_restrictions = [gender_restrictions]
            elif isinstance(gender_restrictions, list):
                pass
            else:
                gender_restrictions = [str(gender_restrictions)]
            
            patient_gender = claim_data.get('gender', '').strip()
            normalized_patient_gender = patient_gender.lower()
            normalized_restrictions = [str(g).lower().strip() for g in gender_restrictions]
            
            logger.info(f"Gender check for G-DRG {gdrg_code}: Patient={patient_gender}, Allowed={gender_restrictions}")
            
            if normalized_patient_gender not in normalized_restrictions:
                logger.error(f"GENDER MISMATCH: Patient gender '{patient_gender}' not in allowed {gender_restrictions}")
                return ValidationOutcome(
                    result=ValidationResult.REJECTED,
                    reason=f"REJECT: Patient gender '{patient_gender}' not allowed for G-DRG",
                    details={
                        "patient_name": f"{claim_data.get('last_name')} {claim_data.get('other_names', '')}",
                        "patient_gender": patient_gender,
                        "allowed_genders": gender_restrictions,
                        "gdrg_code": gdrg_code,
                        "gender_restriction_source": "clinical_inference_data"
                    }
                )
            
            logger.info(f"✓ Patient gender {patient_gender} meets G-DRG requirements")
            return ValidationOutcome(
                result=ValidationResult.APPROVED,
                reason="Patient gender meets G-DRG requirements",
                details={
                    "patient_gender": patient_gender,
                    "allowed_genders": gender_restrictions,
                    "gender_restriction_source": "clinical_inference_data"
                }
            )
            
        except Exception as e:
            logger.error(f"Error validating patient gender: {e}")
            return ValidationOutcome(
                result=ValidationResult.PENDING,
                reason="PEND: Error validating patient gender",
                details={"error": str(e)}
            )
    
    async def validate_multiple_claims(self, encounter_ids: List[str]) -> Dict[str, ValidationOutcome]:
        results = {}
        
        for encounter_id in encounter_ids:
            try:
                result = await self.process_step4_credentialing_check(encounter_id)
                results[encounter_id] = result
                
                logger.info(f"{encounter_id}: {result.reason}")
                
            except Exception as e:
                logger.error(f"Error validating {encounter_id}: {e}")
                results[encounter_id] = ValidationOutcome(
                    result=ValidationResult.PENDING,
                    reason=f"PEND: Validation error - {str(e)}",
                    details={"encounter_id": encounter_id}
                )
        
        return results


if __name__ == "__main__":
    
    async def main():
        validator = FacilityCredentialingValidator()
        
        try:
            await validator.initialize()
            
            test_encounter_id = "LIN-4881-BEEU"
            
            print(f"\nTesting Step 4 validation for: {test_encounter_id}")
            print("=" * 70)
            
            result = await validator.process_step4_credentialing_check(test_encounter_id)
            
            print(f"\nResult: {result.result.value}")
            print(f"Reason: {result.reason}")
            
        except Exception as e:
            logger.error(f"Test failed: {e}")
        
        finally:
            await validator.close()
    
    asyncio.run(main())