"""
NHIS Expert System - Initial Processing Validator (FIXED)
Fixed the execute_query method call issue by using proper database methods
"""

import asyncio
import json
import logging
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass
from enum import Enum
from datetime import datetime

# Import our database connection
from neon_db_connection import get_nhis_queries, initialize_database, close_database

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class ValidationResult(Enum):
    """Validation outcomes per flowchart"""
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    FLAGGED = "FLAGGED"
    PENDING = "PENDING"

class EncounterType(Enum):
    """Encounter types for routing"""
    IPD = "IPD"  # Inpatient
    OPD = "OPD"  # Outpatient  
    AE = "A&E"   # Accident & Emergency

@dataclass
class ValidationOutcome:
    """Result of a validation check"""
    result: ValidationResult
    reason: str
    details: Dict[str, Any] = None
    timestamp: datetime = None
    step: str = "Initial Processing"
    
    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.now()

class InitialProcessingValidator:
    """
    Initial Processing Validator - FIXED VERSION
    Fixed the execute_query method call issue
    """
    
    def __init__(self):
        self.queries = None
        self.is_initialized = False
        
        # NHIS Exclusions List (services not covered)
        self.exclusions_list = [
            "cosmetic_surgery",
            "fertility_treatment", 
            "experimental_procedures",
            "non_emergency_dental_cosmetics",
            "weight_loss_surgery_elective",
            "plastic_surgery_cosmetic",
            "alternative_medicine",
            "medical_tourism"
        ]
        
        # NHIS Benefit Package (covered services by encounter type)
        self.benefit_package = {
            "IPD": [
                "emergency_care", "surgical_procedures", "medical_treatment",
                "diagnostic_services", "laboratory_tests", "imaging",
                "medicines", "blood_transfusion", "dialysis", "intensive_care",
                "specialist_care", "rehabilitation"
            ],
            "OPD": [
                "consultation", "minor_procedures", "diagnostic_services", 
                "laboratory_tests", "basic_imaging", "medicines",
                "physiotherapy", "antenatal_care", "postnatal_care",
                "specialist_consultation", "follow_up_care", "chronic_care",
                "medical_treatment"
            ],
            "A&E": [
                "emergency_care", "trauma_care", "stabilization",
                "emergency_procedures", "emergency_imaging",
                "emergency_medicines", "observation", "resuscitation",
                "emergency_surgery", "critical_care"
            ]
        }
        
        # Tariff Misapplication Rules
        self.tariff_misapplication_rules = {
            "OPD": {
                "rejected_specialty_codes": ["ASUR", "MEDI"],
                "reason": "OPD encounters cannot use ASUR (Surgical) or MEDI (Medical Inpatient) specialty codes"
            },
            "IPD": {
                "rejected_specialty_codes": ["OPDC"],
                "reason": "IPD encounters cannot use OPDC (Outpatient) specialty codes"
            }
        }
    
    async def initialize(self):
        """Initialize database connection"""
        if not self.is_initialized:
            await initialize_database()
            self.queries = await get_nhis_queries()
            self.is_initialized = True
            logger.info("Initial Processing Validator initialized")
    
    async def close(self):
        """Close database connections"""
        await close_database()
        self.is_initialized = False
        logger.info("Initial Processing Validator closed")
    
    async def process_initial_validation(self, encounter_id: str) -> ValidationOutcome:
        """
        Main entry point: Process complete initial validation
        FIXED: Uses proper database method calls
        """
        if not self.is_initialized:
            await self.initialize()
        
        # Track all step results
        step_results = {
            "encounter_id": encounter_id,
            "steps_completed": [],
            "steps_passed": [],
            "steps_failed": [],
            "overall_result": None,
            "routing_decision": None
        }
        
        try:
            logger.info(f"INITIAL PROCESSING: Starting validation for encounter {encounter_id}")
            
            # PRE-VALIDATION: TARIFF MISAPPLICATION CHECK (FIXED)
            step_results["steps_completed"].append("tariff_misapplication_check")
            tariff_check_result = await self._validate_tariff_application(encounter_id)
            
            if tariff_check_result.result != ValidationResult.APPROVED:
                step_results["steps_failed"].append({
                    "step": "tariff_misapplication_check",
                    "status": "FAILED",
                    "message": tariff_check_result.reason,
                    "details": tariff_check_result.details
                })
                step_results["overall_result"] = tariff_check_result.result.value
                return self._create_detailed_outcome(tariff_check_result, step_results)
            
            step_results["steps_passed"].append({
                "step": "tariff_misapplication_check",
                "status": "PASSED",
                "message": tariff_check_result.reason,
                "details": tariff_check_result.details
            })
            
            claim_data = tariff_check_result.details['claim_data']
            
            # INPUT VALIDATION
            step_results["steps_completed"].append("input_validation")
            input_result = await self._validate_input_data_with_claim(claim_data)
            
            if input_result.result != ValidationResult.APPROVED:
                step_results["steps_failed"].append({
                    "step": "input_validation",
                    "status": "FAILED",
                    "message": input_result.reason,
                    "details": input_result.details
                })
                step_results["overall_result"] = input_result.result.value
                return self._create_detailed_outcome(input_result, step_results)
            
            step_results["steps_passed"].append({
                "step": "input_validation",
                "status": "PASSED",
                "message": input_result.reason,
                "details": input_result.details
            })
            
            # STEP 1: INTAKE & NORMALIZATION
            step_results["steps_completed"].append("step1_intake_normalization")
            step1_result = await self._step1_intake_normalization(claim_data)
            
            if step1_result.result != ValidationResult.APPROVED:
                step_results["steps_failed"].append({
                    "step": "step1_intake_normalization",
                    "status": "FAILED", 
                    "message": step1_result.reason,
                    "details": step1_result.details
                })
                step_results["overall_result"] = step1_result.result.value
                return self._create_detailed_outcome(step1_result, step_results)
            
            step_results["steps_passed"].append({
                "step": "step1_intake_normalization",
                "status": "PASSED",
                "message": step1_result.reason,
                "details": step1_result.details
            })
            
            validated_gdrg = step1_result.details['validated_gdrg']
            tariff_info = step1_result.details['tariff_info']
            
            # STEP 2: ELIGIBILITY & COVERAGE
            step_results["steps_completed"].append("step2_eligibility_coverage")
            step2_result = await self._step2_eligibility_coverage(claim_data, validated_gdrg)
            
            if step2_result.result != ValidationResult.APPROVED:
                step_results["steps_failed"].append({
                    "step": "step2_eligibility_coverage",
                    "status": "FAILED",
                    "message": step2_result.reason,
                    "details": step2_result.details
                })
                step_results["overall_result"] = step2_result.result.value
                return self._create_detailed_outcome(step2_result, step_results)
            
            step_results["steps_passed"].append({
                "step": "step2_eligibility_coverage",
                "status": "PASSED",
                "message": step2_result.reason,
                "details": step2_result.details
            })
            
            # STEP 3: SETTING ROUTER
            step_results["steps_completed"].append("step3_setting_router")
            step3_result = await self._step3_setting_router(claim_data)
            
            if step3_result.result != ValidationResult.APPROVED:
                step_results["steps_failed"].append({
                    "step": "step3_setting_router",
                    "status": "FAILED",
                    "message": step3_result.reason,
                    "details": step3_result.details
                })
                step_results["overall_result"] = step3_result.result.value
                return self._create_detailed_outcome(step3_result, step_results)
            
            step_results["steps_passed"].append({
                "step": "step3_setting_router",
                "status": "PASSED",
                "message": step3_result.reason,
                "details": step3_result.details
            })
            
            step_results["routing_decision"] = step3_result.details['routing_decision']
            step_results["overall_result"] = "APPROVED"
            
            # All initial processing steps passed
            final_result = ValidationOutcome(
                result=ValidationResult.APPROVED,
                reason="INITIAL PROCESSING COMPLETED: Ready for encounter-specific flow",
                details={
                    "encounter_id": encounter_id,
                    "encounter_type": claim_data['encounter_type'],
                    "specialty_code": claim_data.get('specialty_code'),
                    "routing_decision": step3_result.details['routing_decision'],
                    "validated_gdrg": validated_gdrg,
                    "tariff_info": tariff_info,
                    "next_step": f"{step3_result.details['routing_decision']['flow_type']} Flow Processing",
                    "step_by_step_results": step_results,
                    "validation_summary": {
                        "total_steps": len(step_results["steps_completed"]),
                        "steps_passed": len(step_results["steps_passed"]),
                        "steps_failed": len(step_results["steps_failed"]),
                        "tariff_misapplication_check": "Passed",
                        "input_validation": "Passed",
                        "intake_normalization": "Passed",
                        "eligibility_coverage": "Passed", 
                        "setting_router": "Passed"
                    }
                }
            )
            
            logger.info(f"INITIAL PROCESSING COMPLETED for {encounter_id}: Routed to {step3_result.details['routing_decision']['flow_type']} flow")
            return final_result
            
        except Exception as e:
            logger.error(f"Error in initial processing: {e}")
            step_results["steps_failed"].append({
                "step": "system_error",
                "status": "ERROR",
                "message": f"System error: {str(e)}",
                "details": {"error_type": type(e).__name__}
            })
            step_results["overall_result"] = "PENDING"
            
            return ValidationOutcome(
                result=ValidationResult.PENDING,
                reason="PEND: System error during initial processing",
                details={
                    "error": str(e),
                    "encounter_id": encounter_id,
                    "step_by_step_results": step_results
                }
            )
    
    async def _validate_tariff_application(self, encounter_id: str) -> ValidationOutcome:
        """
        FIXED: Tariff Misapplication Check
        Now uses proper database method calls
        """
        try:
            logger.info(f"TARIFF MISAPPLICATION CHECK: Validating {encounter_id}")
            
            # Query claims_v3 table directly for encounter_type and specialty_code
            query = """
            SELECT 
                encounter_id,
                encounter_type,
                specialty_code,
                provider_name,
                diagnosis_name,
                gdrg_code,
                last_name,
                other_names,
                date_of_birth,
                gender,
                icd10_code,
                attendance_type,
                EXTRACT(YEARS FROM AGE(CURRENT_DATE, date_of_birth::date)) as calculated_age
            FROM claims_v3 
            WHERE encounter_id = $1
            """
            
            # FIXED: Use the proper database method
            claim = await self.queries.db.fetch_one(query, encounter_id)
            
            if not claim:
                return ValidationOutcome(
                    result=ValidationResult.REJECTED,
                    reason="REJECT: Claim not found for tariff validation",
                    details={"encounter_id": encounter_id}
                )
            
            encounter_type = claim.get('encounter_type')
            specialty_code = claim.get('specialty_code')
            
            logger.info(f"Encounter Type: {encounter_type}, Specialty Code: {specialty_code}")
            
            # Check for tariff misapplication
            if encounter_type in self.tariff_misapplication_rules:
                rule = self.tariff_misapplication_rules[encounter_type]
                rejected_codes = rule["rejected_specialty_codes"]
                
                if specialty_code in rejected_codes:
                    return ValidationOutcome(
                        result=ValidationResult.REJECTED,
                        reason="REJECT: Misapplication of tariff",
                        details={
                            "encounter_id": encounter_id,
                            "encounter_type": encounter_type,
                            "specialty_code": specialty_code,
                            "rule_violation": rule["reason"],
                            "rejected_specialty_codes": rejected_codes,
                            "provider_name": claim.get('provider_name'),
                            "diagnosis_name": claim.get('diagnosis_name'),
                            "gdrg_code": claim.get('gdrg_code'),
                            "validation_rule": f"{encounter_type} encounters cannot use {specialty_code} specialty codes"
                        }
                    )
            
            # Tariff application is valid
            logger.info(f"Tariff application valid for {encounter_id}: {encounter_type} + {specialty_code}")
            
            return ValidationOutcome(
                result=ValidationResult.APPROVED,
                reason="Tariff application validation passed",
                details={
                    "encounter_id": encounter_id,
                    "encounter_type": encounter_type,
                    "specialty_code": specialty_code,
                    "validation_rule": "Encounter type and specialty code combination is valid",
                    "claim_data": dict(claim)  # Pass claim data to next steps
                }
            )
            
        except Exception as e:
            logger.error(f"Error in tariff misapplication check: {e}")
            return ValidationOutcome(
                result=ValidationResult.PENDING,
                reason="PEND: Error during tariff misapplication validation",
                details={"error": str(e), "encounter_id": encounter_id}
            )
    
    def _create_detailed_outcome(self, original_result: ValidationOutcome, step_results: Dict) -> ValidationOutcome:
        """Create detailed outcome with step-by-step results"""
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
    
    async def _validate_input_data_with_claim(self, claim_data: Dict) -> ValidationOutcome:
        """
        INPUT VALIDATION: Check for missing required fields (using existing claim data)
        """
        try:
            encounter_id = claim_data['encounter_id']
            
            # Define required fields (G-DRG is now critical)
            required_fields = [
                'encounter_id', 'provider_name', 'encounter_type',
                'last_name', 'other_names', 'date_of_birth', 'gender',
                'diagnosis_name', 'icd10_code', 'gdrg_code', 'specialty_code'
            ]
            
            missing_fields = []
            for field in required_fields:
                if not claim_data.get(field):
                    missing_fields.append(field)
            
            if missing_fields:
                return ValidationOutcome(
                    result=ValidationResult.REJECTED,
                    reason="REJECT: Missing Required Fields",
                    details={
                        "encounter_id": encounter_id,
                        "missing_fields": missing_fields,
                        "total_missing": len(missing_fields),
                        "critical_note": "G-DRG code and specialty code are required"
                    }
                )
            
            # Validate data types and formats
            validation_errors = []
            
            # Check encounter type is valid
            if claim_data['encounter_type'] not in ['IPD', 'OPD', 'A&E']:
                validation_errors.append(f"Invalid encounter_type: {claim_data['encounter_type']}")
            
            # Check patient age is calculated
            if claim_data.get('calculated_age', 0) <= 0:
                validation_errors.append("Invalid patient age calculation")
            
            # Check ICD-10 format (basic validation)
            icd10 = claim_data.get('icd10_code', '')
            if len(icd10) < 3:
                validation_errors.append(f"Invalid ICD-10 format: {icd10}")
            
            # Check G-DRG format (basic validation)
            gdrg = claim_data.get('gdrg_code', '')
            if len(gdrg) < 5:  # Basic format check
                validation_errors.append(f"Invalid G-DRG format: {gdrg}")
            
            # Check specialty code format
            specialty = claim_data.get('specialty_code', '')
            if len(specialty) < 3:
                validation_errors.append(f"Invalid specialty code format: {specialty}")
            
            if validation_errors:
                return ValidationOutcome(
                    result=ValidationResult.REJECTED,
                    reason="REJECT: Invalid Input Data",
                    details={
                        "encounter_id": encounter_id,
                        "validation_errors": validation_errors
                    }
                )
            
            logger.info(f"Input validation passed for {encounter_id}")
            return ValidationOutcome(
                result=ValidationResult.APPROVED,
                reason="Input validation completed successfully",
                details={
                    "claim_data": claim_data,
                    "required_fields_present": len(required_fields),
                    "validation_checks_passed": True,
                    "gdrg_code": claim_data['gdrg_code'],
                    "specialty_code": claim_data['specialty_code']
                }
            )
            
        except Exception as e:
            logger.error(f"Error in input validation: {e}")
            return ValidationOutcome(
                result=ValidationResult.PENDING,
                reason="PEND: Error during input validation",
                details={"error": str(e)}
            )
    
    async def _step1_intake_normalization(self, claim_data: Dict) -> ValidationOutcome:
        """
        STEP 1: Intake & Normalization
        Use G-DRG directly for tariff lookup
        """
        try:
            gdrg_code = claim_data['gdrg_code']
            encounter_type = claim_data['encounter_type']
            specialty_code = claim_data['specialty_code']
            icd10_code = claim_data['icd10_code']
            
            logger.info(f"STEP 1: Using G-DRG {gdrg_code} directly for tariff lookup")
            
            # Validate G-DRG exists and get tariff information
            tariff_info = await self.queries.get_tariff_by_gdrg(gdrg_code)
            
            if not tariff_info:
                return ValidationOutcome(
                    result=ValidationResult.REJECTED,
                    reason="REJECT: Invalid G-DRG Code - No tariff found",
                    details={
                        "gdrg_code": gdrg_code,
                        "encounter_type": encounter_type,
                        "specialty_code": specialty_code,
                        "icd10_code": icd10_code,
                        "diagnosis_name": claim_data.get('diagnosis_name'),
                        "note": "G-DRG not found in tariff database"
                    }
                )
            
            logger.info(f"G-DRG {gdrg_code} validated successfully - Tariff: {tariff_info.get('tariff_amount', 'N/A')}")
            
            return ValidationOutcome(
                result=ValidationResult.APPROVED,
                reason="Step 1 completed: G-DRG validated and tariff found",
                details={
                    "gdrg_code": gdrg_code,
                    "encounter_type": encounter_type,
                    "specialty_code": specialty_code,
                    "icd10_code": icd10_code,
                    "validated_gdrg": gdrg_code,
                    "tariff_info": tariff_info,
                    "approach": "Direct G-DRG lookup (no ICD-10 mapping required)"
                }
            )
            
        except Exception as e:
            logger.error(f"Error in Step 1 intake & normalization: {e}")
            return ValidationOutcome(
                result=ValidationResult.PENDING,
                reason="PEND: Error during intake & normalization",
                details={"error": str(e)}
            )
    
    async def _step2_eligibility_coverage(self, claim_data: Dict, validated_gdrg: str) -> ValidationOutcome:
        """
        STEP 2: Eligibility & Coverage
        """
        try:
            encounter_type = claim_data['encounter_type']
            specialty_code = claim_data['specialty_code']
            diagnosis_name = claim_data.get('diagnosis_name', '').lower()
            
            logger.info(f"STEP 2: Checking eligibility and coverage for {encounter_type} with G-DRG {validated_gdrg}")
            
            # Check 1: Service in Exclusions List?
            exclusion_flags = []
            for exclusion in self.exclusions_list:
                if exclusion.replace('_', ' ') in diagnosis_name:
                    exclusion_flags.append(exclusion)
            
            # Also check G-DRG for exclusions
            if 'cosmetic' in validated_gdrg.lower():
                exclusion_flags.append("cosmetic_procedure")
            
            if exclusion_flags:
                return ValidationOutcome(
                    result=ValidationResult.REJECTED,
                    reason="REJECT: Service Excluded from Benefits",
                    details={
                        "encounter_type": encounter_type,
                        "specialty_code": specialty_code,
                        "diagnosis_name": claim_data.get('diagnosis_name'),
                        "gdrg_code": validated_gdrg,
                        "excluded_services": exclusion_flags,
                        "exclusions_policy": "NHIS exclusions list"
                    }
                )
            
            # Check 2: Service in Benefit Package?
            covered_services = self.benefit_package.get(encounter_type, [])
            
            # Determine service type from G-DRG and diagnosis
            service_type = self._determine_service_type(claim_data, validated_gdrg)
            
            if service_type not in covered_services:
                return ValidationOutcome(
                    result=ValidationResult.REJECTED,
                    reason="REJECT: Service Not in Benefit Package",
                    details={
                        "encounter_type": encounter_type,
                        "specialty_code": specialty_code,
                        "service_type": service_type,
                        "gdrg_code": validated_gdrg,
                        "covered_services": covered_services,
                        "benefit_package_check": "FAILED"
                    }
                )
            
            logger.info(f"Service covered: {service_type} in {encounter_type} benefit package")
            
            return ValidationOutcome(
                result=ValidationResult.APPROVED,
                reason="Step 2 completed: Service eligible and covered",
                details={
                    "encounter_type": encounter_type,
                    "specialty_code": specialty_code,
                    "service_type": service_type,
                    "gdrg_code": validated_gdrg,
                    "exclusions_check": "PASSED",
                    "benefit_package_check": "PASSED",
                    "covered_under": f"{encounter_type} benefit package"
                }
            )
            
        except Exception as e:
            logger.error(f"Error in Step 2 eligibility & coverage: {e}")
            return ValidationOutcome(
                result=ValidationResult.PENDING,
                reason="PEND: Error during eligibility & coverage check",
                details={"error": str(e)}
            )
    
    def _determine_service_type(self, claim_data: Dict, gdrg_code: str) -> str:
        """
        Determine service type from claim data and G-DRG
        """
        # Primary classification from G-DRG code
        if gdrg_code.startswith('ASUR'):
            return "surgical_procedures"
        elif gdrg_code.startswith('MEDI'):
            return "medical_treatment"
        elif gdrg_code.startswith('OBGY'):
            if 'antenatal' in claim_data.get('diagnosis_name', '').lower():
                return "antenatal_care"
            elif 'postnatal' in claim_data.get('diagnosis_name', '').lower():
                return "postnatal_care"
            else:
                return "specialist_care"
        elif gdrg_code.startswith('PAED'):
            return "medical_treatment"  # Pediatric care
        elif gdrg_code.startswith('OPHT'):
            return "specialist_care"  # Ophthalmology
        
        # Secondary classification from diagnosis name
        diagnosis = claim_data.get('diagnosis_name', '').lower()
        
        if any(term in diagnosis for term in ['emergency', 'acute', 'trauma']):
            return "emergency_care"
        elif any(term in diagnosis for term in ['surgery', 'operation', 'procedure']):
            return "surgical_procedures"
        elif any(term in diagnosis for term in ['pregnancy', 'antenatal', 'prenatal']):
            return "antenatal_care"
        elif any(term in diagnosis for term in ['postnatal', 'postpartum']):
            return "postnatal_care"
        elif any(term in diagnosis for term in ['consultation', 'follow', 'chronic']):
            return "consultation"
        else:
            return "medical_treatment"
    
    async def _step3_setting_router(self, claim_data: Dict) -> ValidationOutcome:
        """
        STEP 3: Setting Router
        Route by encounter type (A&E/OPD/IPD flows)
        """
        try:
            encounter_type = claim_data['encounter_type']
            attendance_type = claim_data.get('attendance_type', '')
            gdrg_code = claim_data.get('gdrg_code', '')
            specialty_code = claim_data.get('specialty_code', '')
            
            logger.info(f"STEP 3: Routing {encounter_type} encounter")
            
            # Determine routing based on encounter type
            routing_decision = {
                "encounter_type": encounter_type,
                "attendance_type": attendance_type,
                "gdrg_code": gdrg_code,
                "specialty_code": specialty_code,
                "flow_type": None,
                "next_validations": [],
                "special_rules": [],
                "routing_priority": "standard"
            }
            
            if encounter_type == "A&E":
                routing_decision["flow_type"] = "A&E"
                routing_decision["next_validations"] = [
                    "A&E Classification",
                    "Emergency CT/MRI Check", 
                    "Detention Rules",
                    "Emergency Tariff Validation"
                ]
            elif encounter_type == "OPD":
                routing_decision["flow_type"] = "OPD"
                routing_decision["next_validations"] = [
                    "Episode Type Determination",
                    "Visit Limits Validation",
                    "Multi-Specialty Rules",
                    "Procedure Validation",
                    "Chronic Care Rules"
                ]
            elif encounter_type == "IPD":
                routing_decision["flow_type"] = "IPD"
                routing_decision["next_validations"] = [
                    "Discharge Date Validation",
                    "Bill Timing Check",
                    "Multiple Procedures Rule",
                    "Emergency Readmission Rule",
                    "IPD Tariff Validation"
                ]
            else:
                return ValidationOutcome(
                    result=ValidationResult.REJECTED,
                    reason=f"REJECT: Invalid encounter type for routing: {encounter_type}",
                    details={
                        "encounter_type": encounter_type,
                        "specialty_code": specialty_code,
                        "valid_types": ["A&E", "OPD", "IPD"]
                    }
                )
            
            logger.info(f"Routed to {routing_decision['flow_type']} flow")
            
            return ValidationOutcome(
                result=ValidationResult.APPROVED,
                reason=f"Step 3 completed: Routed to {routing_decision['flow_type']} flow",
                details={
                    "routing_decision": routing_decision,
                    "ready_for_encounter_flow": True
                }
            )
            
        except Exception as e:
            logger.error(f"Error in Step 3 setting router: {e}")
            return ValidationOutcome(
                result=ValidationResult.PENDING,
                reason="PEND: Error during setting router",
                details={"error": str(e)}
            )
    
    async def validate_multiple_claims(self, encounter_ids: List[str]) -> Dict[str, ValidationOutcome]:
        """
        Batch validate multiple claims for initial processing
        """
        results = {}
        
        for encounter_id in encounter_ids:
            try:
                result = await self.process_initial_validation(encounter_id)
                results[encounter_id] = result
                
                # Enhanced logging
                status_emoji = "" if result.result == ValidationResult.APPROVED else "❌"
                flow_type = ""
                gdrg_info = ""
                specialty_info = ""
                
                if result.details:
                    if result.details.get('routing_decision'):
                        flow_type = f" → {result.details['routing_decision']['flow_type']} Flow"
                    if result.details.get('validated_gdrg'):
                        gdrg_info = f" [G-DRG: {result.details['validated_gdrg']}]"
                    if result.details.get('specialty_code'):
                        specialty_info = f" [Specialty: {result.details['specialty_code']}]"
                
                logger.info(f"{status_emoji} {encounter_id}: {result.reason}{flow_type}{gdrg_info}{specialty_info}")
                
            except Exception as e:
                logger.error(f"Error validating {encounter_id}: {e}")
                results[encounter_id] = ValidationOutcome(
                    result=ValidationResult.PENDING,
                    reason=f"PEND: Validation error - {str(e)}",
                    details={"encounter_id": encounter_id}
                )
        
        return results
    
    async def get_validation_summary(self, encounter_ids: List[str]) -> Dict[str, Any]:
        """
        Get summary statistics for batch initial processing
        """
        results = await self.validate_multiple_claims(encounter_ids)
        
        # Count routing decisions
        routing_stats = {"A&E": 0, "OPD": 0, "IPD": 0, "Unknown": 0}
        gdrg_stats = {}
        specialty_stats = {}
        tariff_stats = {"total_tariff": 0.0, "average_tariff": 0.0, "tariff_count": 0}
        
        # Track tariff misapplication rejections
        tariff_misapplication_count = 0
        misapplication_details = []
        
        for encounter_id, result in results.items():
            # Check for tariff misapplication rejections
            if (result.result == ValidationResult.REJECTED and 
                "Misapplication of tariff" in result.reason):
                tariff_misapplication_count += 1
                if result.details:
                    misapplication_details.append({
                        "encounter_id": encounter_id,
                        "encounter_type": result.details.get('encounter_type'),
                        "specialty_code": result.details.get('specialty_code'),
                        "rule_violation": result.details.get('rule_violation')
                    })
            
            # Routing statistics
            if result.details and result.details.get('routing_decision'):
                flow_type = result.details['routing_decision']['flow_type']
                routing_stats[flow_type] = routing_stats.get(flow_type, 0) + 1
            else:
                routing_stats["Unknown"] += 1
            
            # G-DRG statistics
            if result.details and result.details.get('validated_gdrg'):
                gdrg = result.details['validated_gdrg']
                gdrg_stats[gdrg] = gdrg_stats.get(gdrg, 0) + 1
            
            # Specialty code statistics
            if result.details and result.details.get('specialty_code'):
                specialty = result.details['specialty_code']
                specialty_stats[specialty] = specialty_stats.get(specialty, 0) + 1
            
            # Tariff statistics
            if result.details and result.details.get('tariff_info'):
                tariff_info = result.details['tariff_info']
                if tariff_info.get('tariff_amount'):
                    try:
                        amount = float(tariff_info['tariff_amount'])
                        tariff_stats["total_tariff"] += amount
                        tariff_stats["tariff_count"] += 1
                    except (ValueError, TypeError):
                        pass
        
        # Calculate average tariff
        if tariff_stats["tariff_count"] > 0:
            tariff_stats["average_tariff"] = round(tariff_stats["total_tariff"] / tariff_stats["tariff_count"], 2)
        
        summary = {
            "total_claims": len(encounter_ids),
            "approved": len([r for r in results.values() if r.result == ValidationResult.APPROVED]),
            "rejected": len([r for r in results.values() if r.result == ValidationResult.REJECTED]),
            "flagged": len([r for r in results.values() if r.result == ValidationResult.FLAGGED]),
            "pending": len([r for r in results.values() if r.result == ValidationResult.PENDING]),
            "success_rate": 0,
            "routing_statistics": routing_stats,
            "gdrg_statistics": gdrg_stats,
            "specialty_statistics": specialty_stats,
            "tariff_statistics": tariff_stats,
            "tariff_misapplication": {
                "count": tariff_misapplication_count,
                "percentage": 0,
                "details": misapplication_details
            },
            "results": results
        }
        
        if summary["total_claims"] > 0:
            summary["success_rate"] = round((summary["approved"] / summary["total_claims"]) * 100, 1)
            summary["tariff_misapplication"]["percentage"] = round((tariff_misapplication_count / summary["total_claims"]) * 100, 1)
        
        return summary
    
    async def get_tariff_misapplication_report(self, encounter_ids: List[str]) -> Dict[str, Any]:
        """
        Generate specific report on tariff misapplication issues
        """
        try:
            if not self.is_initialized:
                await self.initialize()
            
            # Query claims_v3 table for potential misapplication cases
            query = """
            SELECT 
                encounter_id,
                encounter_type,
                specialty_code,
                provider_name,
                diagnosis_name,
                gdrg_code,
                CASE 
                    WHEN encounter_type = 'OPD' AND specialty_code IN ('ASUR', 'MEDI') THEN 'OPD_INVALID_SPECIALTY'
                    WHEN encounter_type = 'IPD' AND specialty_code = 'OPDC' THEN 'IPD_INVALID_SPECIALTY'
                    ELSE 'VALID'
                END as misapplication_type
            FROM claims_v3 
            WHERE encounter_id = ANY($1)
            ORDER BY misapplication_type DESC, encounter_type, specialty_code
            """
            
            results = await self.queries.db.fetch_all(query, encounter_ids)
            
            report = {
                "total_claims_checked": len(encounter_ids),
                "misapplication_cases": [],
                "valid_cases": [],
                "summary": {
                    "OPD_INVALID_SPECIALTY": 0,
                    "IPD_INVALID_SPECIALTY": 0,
                    "VALID": 0
                },
                "provider_analysis": {},
                "recommendations": []
            }
            
            for row in results:
                case_data = {
                    "encounter_id": row['encounter_id'],
                    "encounter_type": row['encounter_type'],
                    "specialty_code": row['specialty_code'],
                    "provider_name": row['provider_name'],
                    "diagnosis_name": row['diagnosis_name'],
                    "gdrg_code": row['gdrg_code'],
                    "misapplication_type": row['misapplication_type']
                }
                
                if row['misapplication_type'] != 'VALID':
                    report["misapplication_cases"].append(case_data)
                else:
                    report["valid_cases"].append(case_data)
                
                report["summary"][row['misapplication_type']] += 1
                
                # Provider analysis
                provider = row['provider_name']
                if provider not in report["provider_analysis"]:
                    report["provider_analysis"][provider] = {
                        "total_claims": 0,
                        "misapplication_count": 0,
                        "misapplication_types": []
                    }
                
                report["provider_analysis"][provider]["total_claims"] += 1
                if row['misapplication_type'] != 'VALID':
                    report["provider_analysis"][provider]["misapplication_count"] += 1
                    if row['misapplication_type'] not in report["provider_analysis"][provider]["misapplication_types"]:
                        report["provider_analysis"][provider]["misapplication_types"].append(row['misapplication_type'])
            
            # Generate recommendations
            total_misapplications = report["summary"]["OPD_INVALID_SPECIALTY"] + report["summary"]["IPD_INVALID_SPECIALTY"]
            
            if total_misapplications > 0:
                report["recommendations"].append(
                    f"Found {total_misapplications} tariff misapplication cases that should be rejected"
                )
                
                if report["summary"]["OPD_INVALID_SPECIALTY"] > 0:
                    report["recommendations"].append(
                        f"{report['summary']['OPD_INVALID_SPECIALTY']} OPD claims using invalid ASUR/MEDI specialty codes"
                    )
                
                if report["summary"]["IPD_INVALID_SPECIALTY"] > 0:
                    report["recommendations"].append(
                        f"{report['summary']['IPD_INVALID_SPECIALTY']} IPD claims using invalid OPDC specialty codes"
                    )
                
                # Provider-specific recommendations
                for provider, stats in report["provider_analysis"].items():
                    if stats["misapplication_count"] > 0:
                        rate = round((stats["misapplication_count"] / stats["total_claims"]) * 100, 1)
                        report["recommendations"].append(
                            f"Provider '{provider}': {stats['misapplication_count']}/{stats['total_claims']} claims ({rate}%) have tariff misapplication issues"
                        )
            else:
                report["recommendations"].append("No tariff misapplication cases found in the analyzed claims")
            
            return report
            
        except Exception as e:
            logger.error(f"Error generating tariff misapplication report: {e}")
            return {
                "error": str(e),
                "total_claims_checked": len(encounter_ids),
                "status": "ERROR"
            }

# Usage example
async def main():
    """
    Test the FIXED initial processing validator
    """
    validator = InitialProcessingValidator()
    
    try:
        await validator.initialize()
        
        # Test with the failing encounter ID
        test_encounter_id = "LIN-0992-RKLN"
        
        print(f"\n🔄 TESTING FIXED INITIAL PROCESSING")
        print("=" * 60)
        print("🔧 FIXED ISSUES:")
        print("   • Changed execute_query() to db.fetch_one()")
        print("   • Proper database method calls")
        print("   • Fixed tariff misapplication validation")
        print("=" * 60)
        
        # Process initial validation
        result = await validator.process_initial_validation(test_encounter_id)
        
        # Display results
        print(f"\n📋 INITIAL PROCESSING RESULT:")
        print(f"  Status: {result.result.value}")
        print(f"  Reason: {result.reason}")
        print(f"  Timestamp: {result.timestamp}")
        
        if result.details:
            if "step_by_step_results" in result.details:
                step_results = result.details["step_by_step_results"]
                print(f"\n📝 STEP-BY-STEP RESULTS:")
                print(f"  Steps Completed: {len(step_results['steps_completed'])}")
                print(f"  Steps Passed: {len(step_results['steps_passed'])}")
                print(f"  Steps Failed: {len(step_results['steps_failed'])}")
                
                if step_results['steps_passed']:
                    print(f"\n   PASSED STEPS:")
                    for step in step_results['steps_passed']:
                        print(f"    {step['step']}: {step['message']}")
                
                if step_results['steps_failed']:
                    print(f"\n   FAILED STEPS:")
                    for step in step_results['steps_failed']:
                        print(f"    {step['step']}: {step['message']}")
            
            if result.details.get('routing_decision'):
                routing = result.details['routing_decision']
                print(f"\n🎯 ROUTING DECISION:")
                print(f"  Flow Type: {routing['flow_type']}")
                print(f"  Next Validations: {len(routing['next_validations'])}")
        
        print(f"\n🎉 TESTING COMPLETED!")
        
    except Exception as e:
        print(f"\n❌ TEST FAILED: {e}")
    
    finally:
        await validator.close()

if __name__ == "__main__":
    asyncio.run(main())