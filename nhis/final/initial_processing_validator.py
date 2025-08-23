"""
NHIS Expert System - Initial Processing Validator (UPDATED)
Implements Initial Processing from the flowchart:
- Input Validation: Check for missing required fields
- Step 1: Intake & Normalization: Validate inputs, use existing G-DRG directly
- Step 2: Eligibility & Coverage: Check exclusions and benefit packages
- Step 3: Setting Router: Route by encounter type (A&E/OPD/IPD flows)

MAJOR UPDATE: Removed ICD-10 to G-DRG mapping since G-DRG is already in claims data
Now uses G-DRG directly for tariff lookup instead of mapping ICD-10 → G-DRG

Decision Points:
- REJECT: Missing Required Fields
- REJECT: Invalid Input Data
- REJECT: Invalid G-DRG Code
- REJECT: Service Excluded from Benefits
- REJECT: Service Not in Benefit Package
- APPROVED: Route to appropriate encounter flow
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
    Initial Processing Validator - Steps 1-3 from the flowchart
    UPDATED: Uses G-DRG directly instead of mapping ICD-10 to G-DRG
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
    
    async def initialize(self):
        """Initialize database connection"""
        if not self.is_initialized:
            await initialize_database()
            self.queries = await get_nhis_queries()
            self.is_initialized = True
            logger.info("✅ Initial Processing Validator initialized")
    
    async def close(self):
        """Close database connections"""
        await close_database()
        self.is_initialized = False
        logger.info("🔌 Initial Processing Validator closed")
    
    async def process_initial_validation(self, encounter_id: str) -> ValidationOutcome:
        """
        Main entry point: Process complete initial validation (Input + Steps 1-3)
        UPDATED: Uses G-DRG directly instead of mapping
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
            logger.info(f"🔄 INITIAL PROCESSING: Starting validation for encounter {encounter_id}")
            
            # INPUT VALIDATION
            step_results["steps_completed"].append("input_validation")
            input_result = await self._validate_input_data(encounter_id)
            
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
            
            claim_data = input_result.details['claim_data']
            
            # STEP 1: INTAKE & NORMALIZATION (UPDATED)
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
                    "routing_decision": step3_result.details['routing_decision'],
                    "validated_gdrg": validated_gdrg,
                    "tariff_info": tariff_info,
                    "next_step": f"{step3_result.details['routing_decision']['flow_type']} Flow Processing",
                    "step_by_step_results": step_results,
                    "validation_summary": {
                        "total_steps": len(step_results["steps_completed"]),
                        "steps_passed": len(step_results["steps_passed"]),
                        "steps_failed": len(step_results["steps_failed"]),
                        "input_validation": "✅ Passed",
                        "intake_normalization": "✅ Passed",
                        "eligibility_coverage": "✅ Passed", 
                        "setting_router": "✅ Passed"
                    }
                }
            )
            
            logger.info(f"✅ INITIAL PROCESSING COMPLETED for {encounter_id}: Routed to {step3_result.details['routing_decision']['flow_type']} flow")
            return final_result
            
        except Exception as e:
            logger.error(f"❌ Error in initial processing: {e}")
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
    
    async def _validate_input_data(self, encounter_id: str) -> ValidationOutcome:
        """
        INPUT VALIDATION: Check for missing required fields
        UPDATED: Made gdrg_code required since we use it directly
        """
        try:
            # Get claim data
            claim = await self.queries.get_claim_with_calculated_age(encounter_id)
            if not claim:
                return ValidationOutcome(
                    result=ValidationResult.REJECTED,
                    reason="REJECT: Claim not found",
                    details={"encounter_id": encounter_id}
                )
            
            # Define required fields (G-DRG is now critical)
            required_fields = [
                'encounter_id', 'provider_name', 'encounter_type',
                'last_name', 'other_names', 'date_of_birth', 'gender',
                'diagnosis_name', 'icd10_code', 'gdrg_code'  # G-DRG is required!
            ]
            
            missing_fields = []
            for field in required_fields:
                if not claim.get(field):
                    missing_fields.append(field)
            
            if missing_fields:
                return ValidationOutcome(
                    result=ValidationResult.REJECTED,
                    reason="REJECT: Missing Required Fields",
                    details={
                        "encounter_id": encounter_id,
                        "missing_fields": missing_fields,
                        "total_missing": len(missing_fields),
                        "critical_note": "G-DRG code is required for direct tariff lookup"
                    }
                )
            
            # Validate data types and formats
            validation_errors = []
            
            # Check encounter type is valid
            if claim['encounter_type'] not in ['IPD', 'OPD', 'A&E']:
                validation_errors.append(f"Invalid encounter_type: {claim['encounter_type']}")
            
            # Check patient age is calculated
            if claim.get('calculated_age', 0) <= 0:
                validation_errors.append("Invalid patient age calculation")
            
            # Check ICD-10 format (basic validation)
            icd10 = claim.get('icd10_code', '')
            if len(icd10) < 3:
                validation_errors.append(f"Invalid ICD-10 format: {icd10}")
            
            # Check G-DRG format (basic validation)
            gdrg = claim.get('gdrg_code', '')
            if len(gdrg) < 5:  # Basic format check
                validation_errors.append(f"Invalid G-DRG format: {gdrg}")
            
            if validation_errors:
                return ValidationOutcome(
                    result=ValidationResult.REJECTED,
                    reason="REJECT: Invalid Input Data",
                    details={
                        "encounter_id": encounter_id,
                        "validation_errors": validation_errors
                    }
                )
            
            logger.info(f"📋 Input validation passed for {encounter_id}")
            return ValidationOutcome(
                result=ValidationResult.APPROVED,
                reason="Input validation completed successfully",
                details={
                    "claim_data": claim,
                    "required_fields_present": len(required_fields),
                    "validation_checks_passed": True,
                    "gdrg_code": claim['gdrg_code']
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
        STEP 1: Intake & Normalization (COMPLETELY UPDATED)
        NEW APPROACH: Use G-DRG directly for tariff lookup instead of mapping ICD-10
        """
        try:
            gdrg_code = claim_data['gdrg_code']
            encounter_type = claim_data['encounter_type']
            icd10_code = claim_data['icd10_code']
            
            logger.info(f"🔍 STEP 1: Using G-DRG {gdrg_code} directly for tariff lookup (encounter: {encounter_type})")
            
            # Validate G-DRG exists and get tariff information
            # Handle case where method might not exist yet
            if hasattr(self.queries, 'get_tariff_by_gdrg'):
                tariff_info = await self.queries.get_tariff_by_gdrg(gdrg_code)
            elif hasattr(self.queries, 'find_gdrg_info_direct'):
                tariff_info = await self.queries.find_gdrg_info_direct(gdrg_code, encounter_type)
            else:
                # Fallback: Check if G-DRG exists in clinical_diagnosis_inferences
                tariff_info = await self._fallback_gdrg_validation(gdrg_code, encounter_type)
            
            if not tariff_info:
                return ValidationOutcome(
                    result=ValidationResult.REJECTED,
                    reason="REJECT: Invalid G-DRG Code - No tariff found",
                    details={
                        "gdrg_code": gdrg_code,
                        "encounter_type": encounter_type,
                        "icd10_code": icd10_code,
                        "diagnosis_name": claim_data.get('diagnosis_name'),
                        "note": "G-DRG not found in tariff database"
                    }
                )
            
            # Validate G-DRG is appropriate for encounter type
            gdrg_encounter_type = tariff_info.get('encounter_type')
            if gdrg_encounter_type and gdrg_encounter_type != encounter_type:
                logger.warning(f"⚠️ G-DRG {gdrg_code} encounter type mismatch: claim={encounter_type}, tariff={gdrg_encounter_type}")
                # Don't reject, just flag for review
            
            # Additional validation: Check if G-DRG matches the diagnosis category
            validation_notes = []
            if 'MEDI' in gdrg_code and claim_data.get('diagnosis_name'):
                validation_notes.append("Medical G-DRG for medical diagnosis")
            elif 'ASUR' in gdrg_code and claim_data.get('diagnosis_name'):
                validation_notes.append("Surgical G-DRG - procedure expected")
            elif 'OBGY' in gdrg_code:
                validation_notes.append("Obstetrics/Gynecology G-DRG")
            elif 'PAED' in gdrg_code:
                validation_notes.append("Pediatric G-DRG")
            elif 'OPHT' in gdrg_code:
                validation_notes.append("Ophthalmology G-DRG")
            
            logger.info(f"✅ G-DRG {gdrg_code} validated successfully - Tariff: {tariff_info.get('tariff_amount', 'N/A')}")
            
            return ValidationOutcome(
                result=ValidationResult.APPROVED,
                reason="Step 1 completed: G-DRG validated and tariff found",
                details={
                    "gdrg_code": gdrg_code,
                    "encounter_type": encounter_type,
                    "icd10_code": icd10_code,
                    "validated_gdrg": gdrg_code,
                    "tariff_info": tariff_info,
                    "validation_notes": validation_notes,
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
        UPDATED: Uses validated G-DRG instead of candidate G-DRGs
        """
        try:
            encounter_type = claim_data['encounter_type']
            diagnosis_name = claim_data.get('diagnosis_name', '').lower()
            
            logger.info(f"🏥 STEP 2: Checking eligibility and coverage for {encounter_type} with G-DRG {validated_gdrg}")
            
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
                        "service_type": service_type,
                        "gdrg_code": validated_gdrg,
                        "covered_services": covered_services,
                        "benefit_package_check": "FAILED"
                    }
                )
            
            logger.info(f"✅ Service covered: {service_type} in {encounter_type} benefit package")
            
            return ValidationOutcome(
                result=ValidationResult.APPROVED,
                reason="Step 2 completed: Service eligible and covered",
                details={
                    "encounter_type": encounter_type,
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
        UPDATED: Uses G-DRG code directly for better classification
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
        Per flowchart: Route by encounter type (A&E/OPD/IPD flows)
        Enhanced with G-DRG specific routing rules
        """
        try:
            encounter_type = claim_data['encounter_type']
            attendance_type = claim_data.get('attendance_type', '')
            gdrg_code = claim_data.get('gdrg_code', '')
            
            logger.info(f"🚏 STEP 3: Routing {encounter_type} encounter (G-DRG: {gdrg_code}, attendance: {attendance_type})")
            
            # Determine routing based on encounter type
            routing_decision = {
                "encounter_type": encounter_type,
                "attendance_type": attendance_type,
                "gdrg_code": gdrg_code,
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
                routing_decision["special_rules"] = [
                    "Emergency imaging justification within 5 days",
                    "A&E classification determines payment rules",
                    "Emergency procedures require immediate validation"
                ]
                
                # Special routing for surgical emergencies
                if gdrg_code.startswith('ASUR'):
                    routing_decision["routing_priority"] = "urgent"
                    routing_decision["special_rules"].append("Emergency surgery - expedited processing")
            
            elif encounter_type == "OPD":
                routing_decision["flow_type"] = "OPD"
                routing_decision["next_validations"] = [
                    "Episode Type Determination",
                    "Visit Limits Validation",
                    "Multi-Specialty Rules",
                    "Procedure Validation",
                    "Chronic Care Rules"
                ]
                routing_decision["special_rules"] = [
                    "Acute: 3 visits in 14 days",
                    "Chronic: 6 visits in 12 months", 
                    "ANC: 6 visits total",
                    "PNC: 3 visits in 6 weeks"
                ]
                
                # Special routing based on G-DRG
                if gdrg_code.startswith('OBGY'):
                    routing_decision["special_rules"].append("Obstetrics/Gynecology specific rules apply")
                elif gdrg_code.startswith('PAED'):
                    routing_decision["special_rules"].append("Pediatric care rules apply")
                elif gdrg_code.startswith('OPHT'):
                    routing_decision["special_rules"].append("Ophthalmology specialist rules apply")
            
            elif encounter_type == "IPD":
                routing_decision["flow_type"] = "IPD"
                routing_decision["next_validations"] = [
                    "Discharge Date Validation",
                    "Bill Timing Check",
                    "Multiple Procedures Rule",
                    "Emergency Readmission Rule",
                    "IPD Tariff Validation"
                ]
                routing_decision["special_rules"] = [
                    "Cannot bill before discharge",
                    "Multiple procedures: 100% + 20% + 20%",
                    "Emergency readmission rules apply"
                ]
                
                # Special routing for surgical IPD
                if gdrg_code.startswith('ASUR'):
                    routing_decision["routing_priority"] = "high"
                    routing_decision["special_rules"].append("Surgical IPD - enhanced validation required")
                    routing_decision["next_validations"].append("Surgical Procedure Validation")
            
            else:
                return ValidationOutcome(
                    result=ValidationResult.REJECTED,
                    reason=f"REJECT: Invalid encounter type for routing: {encounter_type}",
                    details={
                        "encounter_type": encounter_type,
                        "valid_types": ["A&E", "OPD", "IPD"]
                    }
                )
            
            logger.info(f"✅ Routed to {routing_decision['flow_type']} flow with {len(routing_decision['next_validations'])} validation steps")
            
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
    
    async def _fallback_gdrg_validation(self, gdrg_code: str, encounter_type: str) -> Dict[str, Any]:
        """
        Fallback method to validate G-DRG when get_tariff_by_gdrg is not available
        Uses clinical_diagnosis_inferences table directly
        """
        try:
            # Query clinical_diagnosis_inferences table directly
            query = """
            SELECT DISTINCT
                gdrg_code,
                gdrg_description,
                encounter_type,
                specialty_code,
                diagnosis_name,
                effective_from,
                effective_to,
                is_active
            FROM clinical_diagnosis_inferences 
            WHERE gdrg_code = $1 AND encounter_type = $2 AND is_active = true
            LIMIT 1
            """
            
            result = await self.queries.connection.fetchrow(query, gdrg_code, encounter_type)
            
            if result:
                # Estimate tariff based on G-DRG pattern
                estimated_tariff = self._estimate_fallback_tariff(gdrg_code, encounter_type)
                
                return {
                    "gdrg_code": result['gdrg_code'],
                    "gdrg_description": result['gdrg_description'],
                    "encounter_type": result['encounter_type'],
                    "specialty_code": result['specialty_code'],
                    "diagnosis_name": result['diagnosis_name'],
                    "tariff_amount": estimated_tariff,
                    "currency": "GHS",
                    "effective_from": result.get('effective_from'),
                    "effective_to": result.get('effective_to'),
                    "is_active": result.get('is_active'),
                    "source": "clinical_diagnosis_inferences_fallback",
                    "note": "Using fallback validation - estimated tariff"
                }
            
            return None
            
        except Exception as e:
            logger.error(f"Error in fallback G-DRG validation: {e}")
            return None
    
    def _estimate_fallback_tariff(self, gdrg_code: str, encounter_type: str) -> str:
        """
        Estimate tariff for fallback validation
        """
        base_tariffs = {
            "IPD": {"MEDI": 500.00, "ASUR": 1500.00, "OBGY": 800.00, "PAED": 400.00, "OPHT": 600.00},
            "OPD": {"MEDI": 50.00, "ASUR": 200.00, "OBGY": 80.00, "PAED": 40.00, "OPHT": 100.00},
            "A&E": {"MEDI": 150.00, "ASUR": 500.00, "OBGY": 200.00, "PAED": 120.00, "OPHT": 150.00}
        }
        
        # Determine category from G-DRG code
        if gdrg_code.startswith("ASUR"):
            category = "ASUR"
        elif gdrg_code.startswith("OBGY"):
            category = "OBGY"
        elif gdrg_code.startswith("PAED"):
            category = "PAED"
        elif gdrg_code.startswith("OPHT"):
            category = "OPHT"
        else:
            category = "MEDI"
        
        encounter_tariffs = base_tariffs.get(encounter_type, base_tariffs["OPD"])
        base_amount = encounter_tariffs.get(category, encounter_tariffs["MEDI"])
        
        return f"{base_amount:.2f}"
    
    async def validate_multiple_claims(self, encounter_ids: List[str]) -> Dict[str, ValidationOutcome]:
        """
        Batch validate multiple claims for initial processing
        UPDATED: Enhanced logging with G-DRG information
        """
        results = {}
        
        for encounter_id in encounter_ids:
            try:
                result = await self.process_initial_validation(encounter_id)
                results[encounter_id] = result
                
                # Enhanced logging with G-DRG info
                status_emoji = "✅" if result.result == ValidationResult.APPROVED else "❌"
                flow_type = ""
                gdrg_info = ""
                
                if result.details:
                    if result.details.get('routing_decision'):
                        flow_type = f" → {result.details['routing_decision']['flow_type']} Flow"
                    if result.details.get('validated_gdrg'):
                        gdrg_info = f" [G-DRG: {result.details['validated_gdrg']}]"
                
                logger.info(f"{status_emoji} {encounter_id}: {result.reason}{flow_type}{gdrg_info}")
                
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
        UPDATED: Enhanced with G-DRG and tariff information
        """
        results = await self.validate_multiple_claims(encounter_ids)
        
        # Count routing decisions
        routing_stats = {"A&E": 0, "OPD": 0, "IPD": 0, "Unknown": 0}
        gdrg_stats = {}
        tariff_stats = {"total_tariff": 0.0, "average_tariff": 0.0, "tariff_count": 0}
        
        for result in results.values():
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
            "tariff_statistics": tariff_stats,
            "results": results
        }
        
        if summary["total_claims"] > 0:
            summary["success_rate"] = round((summary["approved"] / summary["total_claims"]) * 100, 1)
        
        return summary
    
    async def get_gdrg_tariff_lookup(self, gdrg_code: str) -> Dict[str, Any]:
        """
        Direct G-DRG to tariff lookup utility function
        NEW: Added for easy tariff lookups
        """
        try:
            if not self.is_initialized:
                await self.initialize()
            
            tariff_info = await self.queries.get_tariff_by_gdrg(gdrg_code)
            
            if not tariff_info:
                return {
                    "gdrg_code": gdrg_code,
                    "found": False,
                    "error": "G-DRG not found in tariff database"
                }
            
            return {
                "gdrg_code": gdrg_code,
                "found": True,
                "tariff_info": tariff_info,
                "lookup_timestamp": datetime.now().isoformat()
            }
            
        except Exception as e:
            return {
                "gdrg_code": gdrg_code,
                "found": False,
                "error": str(e)
            }
    
    async def validate_gdrg_batch(self, gdrg_codes: List[str]) -> Dict[str, Dict[str, Any]]:
        """
        Batch validate multiple G-DRG codes
        NEW: Added for bulk G-DRG validation
        """
        results = {}
        
        for gdrg_code in gdrg_codes:
            try:
                result = await self.get_gdrg_tariff_lookup(gdrg_code)
                results[gdrg_code] = result
                
                status = "✅" if result['found'] else "❌"
                tariff = result.get('tariff_info', {}).get('tariff_amount', 'N/A')
                logger.info(f"{status} {gdrg_code}: Tariff = {tariff}")
                
            except Exception as e:
                logger.error(f"Error validating G-DRG {gdrg_code}: {e}")
                results[gdrg_code] = {
                    "gdrg_code": gdrg_code,
                    "found": False,
                    "error": str(e)
                }
        
        return results

# Usage examples and testing
async def main():
    """
    Test the UPDATED initial processing validator with real data
    Focus on direct G-DRG usage instead of ICD-10 mapping
    """
    validator = InitialProcessingValidator()
    
    try:
        await validator.initialize()
        
        # Test with real encounter ID from your data
        test_encounter_id = "LIN-4881-BEEU"  # The failing CVA case
        
        print(f"\n🔄 TESTING UPDATED INITIAL PROCESSING FOR: {test_encounter_id}")
        print("=" * 70)
        print("🎯 NEW APPROACH: Using G-DRG directly instead of ICD-10 mapping")
        print("=" * 70)
        
        # Process initial validation
        result = await validator.process_initial_validation(test_encounter_id)
        
        # Display detailed step results
        print(f"\n📋 INITIAL PROCESSING RESULT:")
        print(f"  Status: {result.result.value}")
        print(f"  Reason: {result.reason}")
        print(f"  Step: {result.step}")
        print(f"  Timestamp: {result.timestamp}")
        
        if result.details and "step_by_step_results" in result.details:
            step_results = result.details["step_by_step_results"]
            
            print(f"\n📝 STEP-BY-STEP RESULTS:")
            print(f"  Encounter ID: {step_results['encounter_id']}")
            print(f"  Steps Completed: {len(step_results['steps_completed'])}")
            print(f"  Steps Passed: {len(step_results['steps_passed'])}")
            print(f"  Steps Failed: {len(step_results['steps_failed'])}")
            print(f"  Overall Result: {step_results['overall_result']}")
            
            if step_results.get('routing_decision'):
                routing = step_results['routing_decision']
                print(f"  Routing Decision: {routing['flow_type']} Flow")
            
            if step_results['steps_passed']:
                print(f"\n  ✅ PASSED STEPS:")
                for step in step_results['steps_passed']:
                    print(f"    {step['step']}: {step['status']} - {step['message']}")
                    if step.get('details'):
                        # Show G-DRG and tariff info
                        details = step['details']
                        if 'validated_gdrg' in details:
                            print(f"      G-DRG: {details['validated_gdrg']}")
                        if 'tariff_info' in details:
                            tariff = details['tariff_info']
                            if tariff.get('tariff_amount'):
                                print(f"      Tariff: {tariff['tariff_amount']}")
            
            if step_results['steps_failed']:
                print(f"\n  ❌ FAILED STEPS:")
                for step in step_results['steps_failed']:
                    print(f"    {step['step']}: {step['status']} - {step['message']}")
                    if step.get('details'):
                        print(f"      Details: {step['details']}")
        
        # Show G-DRG and tariff information
        if result.details:
            if result.details.get('validated_gdrg'):
                print(f"\n🎯 G-DRG INFORMATION:")
                print(f"  Validated G-DRG: {result.details['validated_gdrg']}")
                
                if result.details.get('tariff_info'):
                    tariff_info = result.details['tariff_info']
                    print(f"  Tariff Amount: {tariff_info.get('tariff_amount', 'N/A')}")
                    print(f"  Tariff Currency: {tariff_info.get('currency', 'GHS')}")
                    print(f"  Effective Date: {tariff_info.get('effective_date', 'N/A')}")
            
            # Show routing decision details
            if result.details.get('routing_decision'):
                routing = result.details['routing_decision']
                print(f"\n🚏 ROUTING DECISION:")
                print(f"  Flow Type: {routing['flow_type']}")
                print(f"  Encounter Type: {routing['encounter_type']}")
                print(f"  G-DRG Code: {routing.get('gdrg_code', 'N/A')}")
                print(f"  Priority: {routing.get('routing_priority', 'standard')}")
                print(f"  Next Validations: {len(routing['next_validations'])}")
                for validation in routing['next_validations']:
                    print(f"    • {validation}")
                print(f"  Special Rules: {len(routing['special_rules'])}")
                for rule in routing['special_rules']:
                    print(f"    • {rule}")
        
        # Test direct G-DRG lookup functionality
        print(f"\n🔍 TESTING DIRECT G-DRG LOOKUP:")
        test_gdrgs = ["MEDI14A", "ASUR01A", "OBGY03A", "INVALID_GDRG"]
        
        gdrg_results = await validator.validate_gdrg_batch(test_gdrgs)
        
        for gdrg_code, gdrg_result in gdrg_results.items():
            status = "✅ FOUND" if gdrg_result['found'] else "❌ NOT FOUND"
            print(f"  {gdrg_code}: {status}")
            
            if gdrg_result['found'] and gdrg_result.get('tariff_info'):
                tariff = gdrg_result['tariff_info']
                print(f"    Tariff: {tariff.get('tariff_amount', 'N/A')}")
                print(f"    Description: {tariff.get('description', 'N/A')}")
            elif not gdrg_result['found']:
                print(f"    Error: {gdrg_result.get('error', 'Unknown error')}")
        
        # Test batch validation
        print(f"\n🔄 TESTING BATCH VALIDATION...")
        test_encounters = ["LIN-4881-BEEU", "LIN-3012-BUYW", "LIN-0992-RKLN"]
        
        summary = await validator.get_validation_summary(test_encounters)
        
        print(f"\n📊 BATCH VALIDATION SUMMARY:")
        print(f"  Total Claims: {summary['total_claims']}")
        print(f"  Approved: {summary['approved']} ✅")
        print(f"  Rejected: {summary['rejected']} ❌")
        print(f"  Flagged: {summary['flagged']} ⚠️")
        print(f"  Pending: {summary['pending']} ⏳")
        print(f"  Success Rate: {summary['success_rate']}%")
        
        print(f"\n🚏 ROUTING STATISTICS:")
        for flow_type, count in summary['routing_statistics'].items():
            if count > 0:
                print(f"  {flow_type} Flow: {count} claims")
        
        print(f"\n🎯 G-DRG STATISTICS:")
        for gdrg, count in summary['gdrg_statistics'].items():
            print(f"  {gdrg}: {count} claims")
        
        print(f"\n💰 TARIFF STATISTICS:")
        tariff_stats = summary['tariff_statistics']
        print(f"  Total Tariff Value: {tariff_stats['total_tariff']} GHS")
        print(f"  Average Tariff: {tariff_stats['average_tariff']} GHS")
        print(f"  Claims with Tariff: {tariff_stats['tariff_count']}")
        
        # Show detailed results for each claim
        print(f"\n📋 DETAILED RESULTS PER CLAIM:")
        for encounter_id, claim_result in summary['results'].items():
            print(f"\n   {encounter_id}:")
            print(f"    Status: {claim_result.result.value}")
            print(f"    Reason: {claim_result.reason}")
            
            if claim_result.details:
                if claim_result.details.get('validated_gdrg'):
                    print(f"    G-DRG: {claim_result.details['validated_gdrg']}")
                
                if claim_result.details.get('tariff_info'):
                    tariff = claim_result.details['tariff_info'].get('tariff_amount', 'N/A')
                    print(f"    Tariff: {tariff}")
                
                if claim_result.details.get('step_by_step_results'):
                    step_data = claim_result.details["step_by_step_results"]
                    print(f"    Steps Passed: {len(step_data['steps_passed'])}")
                    print(f"    Steps Failed: {len(step_data['steps_failed'])}")
                    
                    # Show routing decision
                    if step_data.get('routing_decision'):
                        routing = step_data['routing_decision']
                        print(f"    Routed To: {routing['flow_type']} Flow")
                    
                    # Show failed steps with details
                    for step in step_data['steps_failed']:
                        print(f"       ❌ {step['step']}: {step['message']}")
        
        print(f"\n🎉 TESTING COMPLETED!")
        print("=" * 70)
        print("✨ KEY IMPROVEMENTS:")
        print("   • No more ICD-10 to G-DRG mapping failures")
        print("   • Direct G-DRG to tariff lookup")
        print("   • Enhanced validation with tariff information")
        print("   • Better routing decisions based on G-DRG")
        print("   • Batch G-DRG validation capabilities")
        
    except Exception as e:
        logger.error(f"Test failed: {e}")
        print(f"\n❌ TEST FAILED: {e}")
    
    finally:
        await validator.close()

if __name__ == "__main__":
    asyncio.run(main())