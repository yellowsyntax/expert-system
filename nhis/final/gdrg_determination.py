import asyncio
import json
import logging
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass
from enum import Enum
from datetime import datetime
from sqlalchemy import cast, Text

from neon_db_connection import get_nhis_queries, initialize_database, close_database

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class ValidationResult(Enum):
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    FLAGGED = "FLAGGED"
    PENDING = "PENDING"
    PARTIAL = "PARTIAL"

class GDRGPathType(Enum):
    PROCEDURE_PATH = "PROCEDURE_PATH"
    DIAGNOSIS_PATH = "DIAGNOSIS_PATH"
    DUAL_EVALUATION = "DUAL_EVALUATION"

class SpecialCaseType(Enum):
    OPDC13A_SUPPORTING_DOCS = "OPDC13A_SUPPORTING_DOCS"

@dataclass
class ValidationOutcome:
    result: ValidationResult
    reason: str
    detailed_reason: str = ""
    financial_impact: Dict[str, Any] = None
    selection_logic: Dict[str, Any] = None
    details: Dict[str, Any] = None
    timestamp: datetime = None
    step: str = "Step 5"
    special_case_triggered: bool = False
    special_case_type: Optional[SpecialCaseType] = None
    
    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.now()
        if self.financial_impact is None:
            self.financial_impact = {}
        if self.selection_logic is None:
            self.selection_logic = {}

class EnhancedGDRGDeterminationStep5:
    
    def __init__(self):
        self.queries = None
        self.is_initialized = False
        
        self.special_case_codes = {
            "OPDC13A": {
                "case_type": SpecialCaseType.OPDC13A_SUPPORTING_DOCS,
                "flag_reason": "OPDC13A requires supporting documents",
                "detailed_reason": "Supporting documents required for verification",
                "stop_processing": True,
                "required_documents": [
                    "Medical practitioner's detailed report",
                    "Laboratory investigation results",
                    "Diagnostic imaging reports (if applicable)",
                    "Specialist consultation notes",
                    "Treatment protocol documentation"
                ],
                "manual_review_required": True,
                "processing_instructions": "Claim flagged for manual review - verify supporting documents before approval"
            }
        }
        
        self.cancer_icd10_codes = [
            'C00', 'C01', 'C02', 'C03', 'C04', 'C05', 'C06', 'C07', 'C08', 'C09',
            'C10', 'C11', 'C12', 'C13', 'C14', 'C15', 'C16', 'C17', 'C18', 'C19',
            'C20', 'C21', 'C22', 'C23', 'C24', 'C25', 'C26', 'C30', 'C31', 'C32',
            'C33', 'C34', 'C37', 'C38', 'C39', 'C40', 'C41', 'C43', 'C44', 'C45',
            'C46', 'C47', 'C48', 'C49', 'C50', 'C51', 'C52', 'C53', 'C54', 'C55',
            'C56', 'C57', 'C58', 'C60', 'C61', 'C62', 'C63', 'C64', 'C65', 'C66',
            'C67', 'C68', 'C69', 'C70', 'C71', 'C72', 'C73', 'C74', 'C75', 'C76',
            'C77', 'C78', 'C79', 'C80', 'C81', 'C82', 'C83', 'C84', 'C85', 'C88',
            'C90', 'C91', 'C92', 'C93', 'C94', 'C95', 'C96', 'C97'
        ]
        
        self.surgical_procedure_ranges = [
            ('0', '1'),
            ('F', 'F')
        ]
    
    async def initialize(self):
        if not self.is_initialized:
            await initialize_database()
            self.queries = await get_nhis_queries()
            self.is_initialized = True
            logger.info("Enhanced G-DRG Determination Step 5 initialized with individual validation")
    
    async def close(self):
        await close_database()
        self.is_initialized = False
        logger.info("Enhanced G-DRG Determination Step 5 closed")
    
    async def process_step5_gdrg_determination(self, encounter_id: str) -> ValidationOutcome:
        if not self.is_initialized:
            await self.initialize()
        
        step_results = {
            "encounter_id": encounter_id,
            "steps_completed": [],
            "steps_passed": [],
            "steps_failed": [],
            "overall_result": None,
            "gdrg_determination": {},
            "special_case_triggered": False,
            "special_case_details": None,
            "dual_evaluation_performed": False,
            "tariff_comparison": {}
        }
        
        try:
            logger.info(f"ENHANCED STEP 5: Starting dual G-DRG determination with validation for {encounter_id}")
            
            claim_data = await self.queries.get_claim_with_calculated_age(encounter_id)
            if not claim_data:
                return ValidationOutcome(
                    result=ValidationResult.REJECTED,
                    reason="REJECT: Claim not found for G-DRG determination",
                    detailed_reason=f"Claim {encounter_id} not found in database for G-DRG determination process",
                    details={"encounter_id": encounter_id}
                )
            
            step_results["steps_completed"].append("A0_opdc13a_check")
            a0_result = await self._a0_check_opdc13a_special_case(claim_data)
            
            if a0_result.special_case_triggered:
                step_results["special_case_triggered"] = True
                step_results["special_case_details"] = a0_result.details
                step_results["steps_failed"].append({
                    "step": "A0_opdc13a_check",
                    "status": "FLAGGED",
                    "message": a0_result.reason,
                    "details": a0_result.details,
                    "special_case": True,
                    "stop_processing": True
                })
                step_results["overall_result"] = a0_result.result.value
                
                logger.warning(f"OPDC13A SPECIAL CASE TRIGGERED for {encounter_id}: {a0_result.reason}")
                logger.warning(f"PROCESSING STOPPED - Manual review required")
                
                return self._create_detailed_outcome(a0_result, step_results)
            
            step_results["steps_passed"].append({
                "step": "A0_opdc13a_check",
                "status": "PASSED",
                "message": "No OPDC13A detected - continuing normal processing",
                "details": a0_result.details
            })
            
            step_results["steps_completed"].append("A1_icd10_present")
            a1_result = await self._a1_check_icd10_present(claim_data)
            
            if a1_result.result != ValidationResult.APPROVED:
                step_results["steps_failed"].append({
                    "step": "A1_icd10_present",
                    "status": "FAILED",
                    "message": a1_result.reason,
                    "details": a1_result.details
                })
                step_results["overall_result"] = a1_result.result.value
                return self._create_detailed_outcome(a1_result, step_results)
            
            step_results["steps_passed"].append({
                "step": "A1_icd10_present",
                "status": "PASSED",
                "message": a1_result.reason,
                "details": a1_result.details
            })
            
            step_results["steps_completed"].append("A2_dual_gdrg_evaluation_with_validation")
            a2_result = await self._a2_dual_gdrg_evaluation_with_validation(claim_data)
            
            if a2_result.result == ValidationResult.REJECTED:
                step_results["steps_failed"].append({
                    "step": "A2_dual_gdrg_evaluation_with_validation",
                    "status": "FAILED",
                    "message": a2_result.reason,
                    "details": a2_result.details
                })
                step_results["overall_result"] = a2_result.result.value
                return self._create_detailed_outcome(a2_result, step_results)
            elif a2_result.result == ValidationResult.PARTIAL:
                step_results["steps_passed"].append({
                    "step": "A2_dual_gdrg_evaluation_with_validation",
                    "status": "PARTIAL",
                    "message": a2_result.reason,
                    "details": a2_result.details
                })
                step_results["overall_result"] = a2_result.result.value
            else:
                step_results["steps_passed"].append({
                    "step": "A2_dual_gdrg_evaluation_with_validation", 
                    "status": "PASSED",
                    "message": a2_result.reason,
                    "details": a2_result.details
                })
                step_results["overall_result"] = a2_result.result.value
            
            step_results["dual_evaluation_performed"] = True
            step_results["tariff_comparison"] = a2_result.details.get("tariff_comparison", {})
            step_results["gdrg_determination"]["path_type"] = a2_result.details["path_type"]
            step_results["gdrg_determination"]["selected_gdrg"] = a2_result.details["selected_gdrg"]
            step_results["gdrg_determination"]["selection_reason"] = a2_result.details["evaluation_summary"]["selection_reason"]
            
            final_gdrg = a2_result.details["selected_gdrg"]
            selected_tariff_info = a2_result.details["selected_tariff_info"]
            
            step_results["steps_completed"].append("A3_age_validation")
            step_results["steps_passed"].append({
                "step": "A3_age_validation",
                "status": "PASSED",
                "message": "Age split already applied during dual evaluation",
                "details": {"final_gdrg": final_gdrg}
            })
            
            step_results["steps_completed"].append("A4_tariff_validation")
            step_results["steps_passed"].append({
                "step": "A4_tariff_validation",
                "status": "PASSED",
                "message": f"Tariff validated: {selected_tariff_info['amount']} {selected_tariff_info['currency']}",
                "details": {"tariff_info": selected_tariff_info}
            })
            
            step_results["gdrg_determination"]["final_gdrg"] = final_gdrg
            step_results["gdrg_determination"]["tariff_info"] = selected_tariff_info
            
            detailed_reason = self._create_comprehensive_detailed_reason(
                claim_data, a2_result.details, step_results
            )
            
            if a2_result.result == ValidationResult.PARTIAL:
                result_message = "STEP 5 PARTIAL: Higher-paying G-DRG rejected, lower-paying approved"
            else:
                result_message = "STEP 5 COMPLETED: Dual G-DRG evaluation successful"
            
            final_result = ValidationOutcome(
                result=a2_result.result,
                reason=result_message,
                detailed_reason=detailed_reason,
                financial_impact=a2_result.financial_impact,
                selection_logic=a2_result.selection_logic,
                details={
                    "encounter_id": encounter_id,
                    "gdrg_determination": step_results["gdrg_determination"],
                    "patient_age": claim_data.get('calculated_age'),
                    "encounter_type": claim_data.get('encounter_type'),
                    "next_step": "Step 6: Medicine Validation",
                    "step_by_step_results": step_results,
                    "special_case_checked": True,
                    "special_case_triggered": step_results["special_case_triggered"],
                    "opdc13a_check_passed": True,
                    "dual_evaluation_summary": a2_result.details.get("evaluation_summary", {}),
                    "tariff_comparison": step_results["tariff_comparison"],
                    "gdrg_summary": {
                        "selected_gdrg": final_gdrg,
                        "path_used": step_results["gdrg_determination"]["path_type"],
                        "selection_reason": step_results["gdrg_determination"]["selection_reason"],
                        "tariff_amount": selected_tariff_info["amount"],
                        "tariff_currency": selected_tariff_info["currency"],
                        "dual_evaluation": True,
                        "validation_applied": True
                    },
                    "validation_summary": {
                        "total_steps": len(step_results["steps_completed"]),
                        "steps_passed": len(step_results["steps_passed"]),
                        "steps_failed": len(step_results["steps_failed"])
                    }
                }
            )
            
            logger.info(f"ENHANCED STEP 5 COMPLETED for {encounter_id}: G-DRG {final_gdrg} selected, tariff {selected_tariff_info['amount']}")
            return final_result
            
        except Exception as e:
            logger.error(f"Error in Enhanced Step 5 G-DRG determination: {e}")
            step_results["steps_failed"].append({
                "step": "system_error",
                "status": "ERROR",
                "message": f"System error: {str(e)}",
                "details": {"error_type": type(e).__name__}
            })
            step_results["overall_result"] = "PENDING"
            
            return ValidationOutcome(
                result=ValidationResult.PENDING,
                reason="PEND: System error during G-DRG determination",
                detailed_reason=f"System error occurred during G-DRG determination for {encounter_id}: {str(e)}",
                details={
                    "error": str(e),
                    "encounter_id": encounter_id,
                    "step_by_step_results": step_results
                }
            )
    
    async def _a0_check_opdc13a_special_case(self, claim_data: Dict) -> ValidationOutcome:
        try:
            encounter_id = claim_data.get('encounter_id')
            icd10_code = claim_data.get('icd10_code', '').strip().upper()
            gdrg_code = claim_data.get('gdrg_code', '').strip().upper()
            
            logger.info(f"A0: OPDC13A SPECIAL CASE CHECK for {encounter_id}")
            logger.info(f"   ICD-10 Code: {icd10_code}")
            logger.info(f"   G-DRG Code: {gdrg_code}")
            
            opdc13a_found = False
            detection_source = None
            
            if icd10_code == 'OPDC13A':
                opdc13a_found = True
                detection_source = "ICD-10"
                logger.warning(f"OPDC13A DETECTED in ICD-10 code for {encounter_id}")
            
            if gdrg_code == 'OPDC13A':
                opdc13a_found = True
                detection_source = "G-DRG" if not detection_source else "Both ICD-10 and G-DRG"
                logger.warning(f"OPDC13A DETECTED in G-DRG code for {encounter_id}")
            
            if opdc13a_found:
                logger.warning(f"PROCESSING STOPPED for {encounter_id}: OPDC13A detected in {detection_source}")
                
                special_case_config = self.special_case_codes["OPDC13A"]
                
                special_case_details = {
                    "encounter_id": encounter_id,
                    "icd10_code": icd10_code,
                    "gdrg_code": gdrg_code,
                    "opdc13a_detected_in": detection_source,
                    "special_case_type": special_case_config["case_type"].value,
                    "flag_reason": special_case_config["flag_reason"],
                    "detailed_reason": special_case_config["detailed_reason"],
                    "stop_processing": special_case_config["stop_processing"],
                    "manual_review_required": special_case_config["manual_review_required"],
                    "required_documents": special_case_config["required_documents"],
                    "processing_instructions": special_case_config["processing_instructions"],
                    "triggered_at": datetime.now().isoformat(),
                    "next_action": "MANUAL_REVIEW_REQUIRED"
                }
                
                detailed_reason = f"OPDC13A special case detected in {detection_source}. Supporting documents required: {', '.join(special_case_config['required_documents'])}. Manual review required before processing can continue."
                
                return ValidationOutcome(
                    result=ValidationResult.FLAGGED,
                    reason=f"FLAG: {special_case_config['detailed_reason']} (OPDC13A detected in {detection_source})",
                    detailed_reason=detailed_reason,
                    details=special_case_details,
                    special_case_triggered=True,
                    special_case_type=special_case_config["case_type"]
                )
            
            logger.info(f"A0: OPDC13A CHECK PASSED for {encounter_id} - No OPDC13A detected")
            
            return ValidationOutcome(
                result=ValidationResult.APPROVED,
                reason="A0 passed: No OPDC13A detected",
                detailed_reason=f"OPDC13A check completed for {encounter_id}. No OPDC13A found in ICD-10 ({icd10_code}) or G-DRG ({gdrg_code}) codes.",
                details={
                    "encounter_id": encounter_id,
                    "icd10_code": icd10_code,
                    "gdrg_code": gdrg_code,
                    "opdc13a_detected": False,
                    "opdc13a_checked_in": ["ICD-10", "G-DRG"],
                    "special_case_triggered": False,
                    "continue_processing": True
                },
                special_case_triggered=False
            )
            
        except Exception as e:
            logger.error(f"Error in A0 OPDC13A check: {e}")
            return ValidationOutcome(
                result=ValidationResult.PENDING,
                reason="PEND: Error checking OPDC13A special case",
                detailed_reason=f"Error occurred while checking OPDC13A special case for {claim_data.get('encounter_id')}: {str(e)}",
                details={"error": str(e)},
                special_case_triggered=False
            )
    
    async def _a1_check_icd10_present(self, claim_data: Dict) -> ValidationOutcome:
        try:
            encounter_id = claim_data.get('encounter_id')
            icd10_code = claim_data.get('icd10_code')
            diagnosis_name = claim_data.get('diagnosis_name')
            
            if not icd10_code or icd10_code.strip() == '':
                detailed_reason = f"ICD-10 code is missing for encounter {encounter_id}. ICD-10 code is required for G-DRG determination. Diagnosis name: {diagnosis_name or 'Not provided'}"
                
                return ValidationOutcome(
                    result=ValidationResult.PENDING,
                    reason="PEND: Missing ICD-10",
                    detailed_reason=detailed_reason,
                    details={
                        "encounter_id": encounter_id,
                        "diagnosis_name": diagnosis_name,
                        "icd10_code": icd10_code,
                        "requirement": "ICD-10 code is required for G-DRG determination"
                    }
                )
            
            if len(icd10_code) < 3:
                detailed_reason = f"Invalid ICD-10 format for encounter {encounter_id}. Code '{icd10_code}' is too short (minimum 3 characters required). Diagnosis: {diagnosis_name or 'Not provided'}"
                
                return ValidationOutcome(
                    result=ValidationResult.PENDING,
                    reason="PEND: Invalid ICD-10 format",
                    detailed_reason=detailed_reason,
                    details={
                        "encounter_id": encounter_id,
                        "icd10_code": icd10_code,
                        "error": "ICD-10 code too short"
                    }
                )
            
            logger.info(f"A1: ICD-10 present: {icd10_code} ({diagnosis_name})")
            detailed_reason = f"ICD-10 validation passed for encounter {encounter_id}. Code: {icd10_code}, Diagnosis: {diagnosis_name or 'Not provided'}"
            
            return ValidationOutcome(
                result=ValidationResult.APPROVED,
                reason="A1 passed: ICD-10 code present and valid",
                detailed_reason=detailed_reason,
                details={
                    "icd10_code": icd10_code,
                    "diagnosis_name": diagnosis_name,
                    "validation_status": "PASSED"
                }
            )
            
        except Exception as e:
            logger.error(f"Error in A1 ICD-10 check: {e}")
            return ValidationOutcome(
                result=ValidationResult.PENDING,
                reason="PEND: Error validating ICD-10",
                detailed_reason=f"Error occurred while validating ICD-10 for encounter {claim_data.get('encounter_id')}: {str(e)}",
                details={"error": str(e)}
            )
    
    async def _a2_dual_gdrg_evaluation_with_validation(self, claim_data: Dict) -> ValidationOutcome:
        try:
            encounter_id = claim_data.get('encounter_id')
            icd10_procedure = claim_data.get('icd10_code_procedure')
            procedure_description = claim_data.get('icd10_description_procedure')
            
            primary_icd10 = claim_data.get('icd10_code')
            diagnosis_name = claim_data.get('diagnosis_name')
            encounter_type = claim_data.get('encounter_type')
            patient_age = claim_data.get('calculated_age', 0)
            provider_name = claim_data.get('provider_name')
            
            facility_info = await self.queries.get_facility_info_by_name(provider_name)
            facility_level = facility_info.get('facility_level', '2') if facility_info else '2'
            
            logger.info(f"A2: DUAL G-DRG EVALUATION WITH VALIDATION for encounter {encounter_id}")
            
            evaluation_results = {
                "procedure_evaluation": {
                    "evaluated": False,
                    "gdrg_found": False,
                    "base_gdrg": None,
                    "final_gdrg": None,
                    "validation_passed": False,
                    "validation_details": {},
                    "rejection_reasons": [],
                    "tariff": 0.0,
                    "tariff_info": None,
                    "source": None,
                    "error": None
                },
                "diagnosis_evaluation": {
                    "evaluated": False,
                    "gdrg_found": False,
                    "base_gdrg": None,
                    "final_gdrg": None,
                    "validation_passed": False,
                    "validation_details": {},
                    "rejection_reasons": [],
                    "tariff": 0.0,
                    "tariff_info": None,
                    "source": None,
                    "error": None
                }
            }
            
            has_procedures = bool(
                icd10_procedure and 
                icd10_procedure not in ['NA', '', None] and
                len(icd10_procedure.strip()) >= 3
            )
            
            if has_procedures:
                logger.info(f"Evaluating procedure G-DRG for: {icd10_procedure}")
                evaluation_results["procedure_evaluation"]["evaluated"] = True
                
                try:
                    procedure_gdrg = await self._get_gdrg_from_procedure_inferences(
                        icd10_procedure, encounter_type, patient_age
                    )
                    
                    if procedure_gdrg:
                        evaluation_results["procedure_evaluation"]["gdrg_found"] = True
                        evaluation_results["procedure_evaluation"]["base_gdrg"] = procedure_gdrg
                        evaluation_results["procedure_evaluation"]["source"] = "clinical_procedure_inferences"
                        
                        age_split_result = await self._a3_apply_age_split(claim_data, procedure_gdrg)
                        final_procedure_gdrg = age_split_result.details['final_gdrg']
                        evaluation_results["procedure_evaluation"]["final_gdrg"] = final_procedure_gdrg
                        
                        validation_result = await self._validate_individual_gdrg(claim_data, final_procedure_gdrg, "procedure")
                        evaluation_results["procedure_evaluation"]["validation_passed"] = validation_result["valid"]
                        evaluation_results["procedure_evaluation"]["validation_details"] = validation_result["details"]
                        evaluation_results["procedure_evaluation"]["rejection_reasons"] = validation_result["rejection_reasons"]
                        
                        if validation_result["valid"]:
                            procedure_tariff_info = await self._lookup_facility_tariff(
                                provider_name, facility_level, final_procedure_gdrg, encounter_type
                            )
                            
                            if procedure_tariff_info:
                                evaluation_results["procedure_evaluation"]["tariff"] = procedure_tariff_info['amount']
                                evaluation_results["procedure_evaluation"]["tariff_info"] = procedure_tariff_info
                                logger.info(f"Procedure G-DRG {final_procedure_gdrg}: VALID - {procedure_tariff_info['amount']} GHS")
                            else:
                                evaluation_results["procedure_evaluation"]["error"] = "No tariff found"
                        else:
                            logger.warning(f"Procedure G-DRG {final_procedure_gdrg}: REJECTED - {', '.join(validation_result['rejection_reasons'])}")
                            evaluation_results["procedure_evaluation"]["tariff"] = 0.0
                    else:
                        evaluation_results["procedure_evaluation"]["error"] = "No G-DRG found in procedure inferences"
                        
                except Exception as e:
                    evaluation_results["procedure_evaluation"]["error"] = str(e)
                    logger.error(f"Error evaluating procedure G-DRG: {e}")
            
            logger.info(f"Evaluating diagnosis G-DRG for: {primary_icd10}")
            evaluation_results["diagnosis_evaluation"]["evaluated"] = True
            
            try:
                diagnosis_gdrg = await self._get_gdrg_from_diagnosis_inferences(
                    primary_icd10, encounter_type, patient_age
                )
                
                if not diagnosis_gdrg:
                    diagnosis_gdrg = claim_data.get('gdrg_code')
                    evaluation_results["diagnosis_evaluation"]["source"] = "claim_fallback"
                    logger.warning(f"Using claim G-DRG as fallback: {diagnosis_gdrg}")
                else:
                    evaluation_results["diagnosis_evaluation"]["source"] = "clinical_diagnosis_inferences"
                
                if diagnosis_gdrg:
                    evaluation_results["diagnosis_evaluation"]["gdrg_found"] = True
                    evaluation_results["diagnosis_evaluation"]["base_gdrg"] = diagnosis_gdrg
                    
                    age_split_result = await self._a3_apply_age_split(claim_data, diagnosis_gdrg)
                    final_diagnosis_gdrg = age_split_result.details['final_gdrg']
                    evaluation_results["diagnosis_evaluation"]["final_gdrg"] = final_diagnosis_gdrg
                    
                    validation_result = await self._validate_individual_gdrg(claim_data, final_diagnosis_gdrg, "diagnosis")
                    evaluation_results["diagnosis_evaluation"]["validation_passed"] = validation_result["valid"]
                    evaluation_results["diagnosis_evaluation"]["validation_details"] = validation_result["details"]
                    evaluation_results["diagnosis_evaluation"]["rejection_reasons"] = validation_result["rejection_reasons"]
                    
                    if validation_result["valid"]:
                        diagnosis_tariff_info = await self._lookup_facility_tariff(
                            provider_name, facility_level, final_diagnosis_gdrg, encounter_type
                        )
                        
                        if diagnosis_tariff_info:
                            evaluation_results["diagnosis_evaluation"]["tariff"] = diagnosis_tariff_info['amount']
                            evaluation_results["diagnosis_evaluation"]["tariff_info"] = diagnosis_tariff_info
                            logger.info(f"Diagnosis G-DRG {final_diagnosis_gdrg}: VALID - {diagnosis_tariff_info['amount']} GHS")
                        else:
                            evaluation_results["diagnosis_evaluation"]["error"] = "No tariff found"
                    else:
                        logger.warning(f"Diagnosis G-DRG {final_diagnosis_gdrg}: REJECTED - {', '.join(validation_result['rejection_reasons'])}")
                        evaluation_results["diagnosis_evaluation"]["tariff"] = 0.0
                else:
                    evaluation_results["diagnosis_evaluation"]["error"] = "No diagnosis G-DRG found"
                    
            except Exception as e:
                evaluation_results["diagnosis_evaluation"]["error"] = str(e)
                logger.error(f"Error evaluating diagnosis G-DRG: {e}")
            
            valid_options = []
            
            if (evaluation_results["procedure_evaluation"]["validation_passed"] and 
                evaluation_results["procedure_evaluation"]["tariff"] > 0):
                valid_options.append({
                    "type": "procedure",
                    "evaluation": evaluation_results["procedure_evaluation"],
                    "tariff": evaluation_results["procedure_evaluation"]["tariff"]
                })
            
            if (evaluation_results["diagnosis_evaluation"]["validation_passed"] and 
                evaluation_results["diagnosis_evaluation"]["tariff"] > 0):
                valid_options.append({
                    "type": "diagnosis", 
                    "evaluation": evaluation_results["diagnosis_evaluation"],
                    "tariff": evaluation_results["diagnosis_evaluation"]["tariff"]
                })
            
            if not valid_options:
                all_rejection_reasons = []
                if evaluation_results["procedure_evaluation"]["evaluated"]:
                    all_rejection_reasons.extend(evaluation_results["procedure_evaluation"]["rejection_reasons"])
                all_rejection_reasons.extend(evaluation_results["diagnosis_evaluation"]["rejection_reasons"])
                
                return ValidationOutcome(
                    result=ValidationResult.REJECTED,
                    reason=f"REJECT: No valid G-DRGs found - all failed validation",
                    detailed_reason=f"All G-DRG options failed validation. Rejection reasons: {', '.join(set(all_rejection_reasons))}",
                    details={
                        "encounter_id": encounter_id,
                        "evaluation_results": evaluation_results,
                        "rejection_reasons": list(set(all_rejection_reasons)),
                        "path_type": GDRGPathType.DUAL_EVALUATION.value,
                        "selected_gdrg": None,
                        "selected_tariff": 0,
                        "selected_tariff_info": None,
                        "evaluation_summary": {
                            "procedure_evaluated": evaluation_results["procedure_evaluation"]["evaluated"],
                            "procedure_gdrg": evaluation_results["procedure_evaluation"]["final_gdrg"],
                            "procedure_tariff": 0,
                            "diagnosis_gdrg": evaluation_results["diagnosis_evaluation"]["final_gdrg"],
                            "diagnosis_tariff": 0,
                            "winner": None,
                            "winning_tariff": 0,
                            "selection_reason": "All G-DRGs failed validation"
                        }
                    }
                )
            
            elif len(valid_options) == 1:
                selected_option = valid_options[0]
                selected_evaluation = selected_option["evaluation"]
                
                if evaluation_results["procedure_evaluation"]["evaluated"] and evaluation_results["diagnosis_evaluation"]["evaluated"]:
                    rejected_type = "diagnosis" if selected_option["type"] == "procedure" else "procedure"
                    rejected_eval = evaluation_results[f"{rejected_type}_evaluation"]
                    
                    financial_impact = {
                        "procedure_tariff": evaluation_results["procedure_evaluation"]["tariff"],
                        "diagnosis_tariff": evaluation_results["diagnosis_evaluation"]["tariff"],
                        "selected_tariff": selected_evaluation["tariff"],
                        "rejected_tariff": rejected_eval["tariff"],
                        "tariff_loss": rejected_eval["tariff"] if rejected_eval["tariff"] > selected_evaluation["tariff"] else 0,
                        "currency": "GHS"
                    }
                    
                    return ValidationOutcome(
                        result=ValidationResult.PARTIAL,
                        reason=f"PARTIAL: {selected_option['type'].title()} G-DRG used - {rejected_type} G-DRG rejected",
                        detailed_reason=f"{selected_option['type'].title()} G-DRG {selected_evaluation['final_gdrg']} selected with tariff {selected_evaluation['tariff']} GHS. {rejected_type.title()} G-DRG rejected due to: {', '.join(rejected_eval['rejection_reasons'])}",
                        financial_impact=financial_impact,
                        details={
                            "path_type": GDRGPathType.DUAL_EVALUATION.value,
                            "selected_gdrg": selected_evaluation['final_gdrg'],
                            "selected_tariff": selected_evaluation['tariff'],
                            "selected_tariff_info": selected_evaluation['tariff_info'],
                            "evaluation_results": evaluation_results,
                            "partial_reason": f"{rejected_type.title()} G-DRG validation failed",
                            "evaluation_summary": {
                                "procedure_evaluated": evaluation_results["procedure_evaluation"]["evaluated"],
                                "procedure_gdrg": evaluation_results["procedure_evaluation"]["final_gdrg"],
                                "procedure_tariff": evaluation_results["procedure_evaluation"]["tariff"],
                                "diagnosis_gdrg": evaluation_results["diagnosis_evaluation"]["final_gdrg"],
                                "diagnosis_tariff": evaluation_results["diagnosis_evaluation"]["tariff"],
                                "winner": selected_evaluation['final_gdrg'],
                                "winning_tariff": selected_evaluation['tariff'],
                                "selection_reason": f"{selected_option['type'].title()} G-DRG used - {rejected_type} rejected due to validation failure"
                            },
                            "tariff_comparison": {
                                "procedure": {
                                    "gdrg": evaluation_results["procedure_evaluation"]["final_gdrg"],
                                    "tariff": evaluation_results["procedure_evaluation"]["tariff"],
                                    "available": evaluation_results["procedure_evaluation"]["validation_passed"],
                                    "source": evaluation_results["procedure_evaluation"]["source"],
                                    "rejection_reasons": evaluation_results["procedure_evaluation"]["rejection_reasons"]
                                },
                                "diagnosis": {
                                    "gdrg": evaluation_results["diagnosis_evaluation"]["final_gdrg"],
                                    "tariff": evaluation_results["diagnosis_evaluation"]["tariff"],
                                    "available": evaluation_results["diagnosis_evaluation"]["validation_passed"],
                                    "source": evaluation_results["diagnosis_evaluation"]["source"],
                                    "rejection_reasons": evaluation_results["diagnosis_evaluation"]["rejection_reasons"]
                                }
                            }
                        }
                    )
                else:
                    financial_impact = {
                        "procedure_tariff": evaluation_results["procedure_evaluation"]["tariff"],
                        "diagnosis_tariff": evaluation_results["diagnosis_evaluation"]["tariff"],
                        "selected_tariff": selected_evaluation["tariff"],
                        "currency": "GHS"
                    }
                    
                    return ValidationOutcome(
                        result=ValidationResult.APPROVED,
                        reason=f"APPROVED: {selected_option['type'].title()} G-DRG validated - {selected_evaluation['tariff']} GHS",
                        detailed_reason=f"{selected_option['type'].title()} G-DRG {selected_evaluation['final_gdrg']} validated and approved with tariff {selected_evaluation['tariff']} GHS",
                        financial_impact=financial_impact,
                        details={
                            "path_type": f"{selected_option['type']}_path".upper(),
                            "selected_gdrg": selected_evaluation['final_gdrg'],
                            "selected_tariff": selected_evaluation['tariff'],
                            "selected_tariff_info": selected_evaluation['tariff_info'],
                            "evaluation_results": evaluation_results,
                            "evaluation_summary": {
                                "procedure_evaluated": evaluation_results["procedure_evaluation"]["evaluated"],
                                "procedure_gdrg": evaluation_results["procedure_evaluation"]["final_gdrg"],
                                "procedure_tariff": evaluation_results["procedure_evaluation"]["tariff"],
                                "diagnosis_gdrg": evaluation_results["diagnosis_evaluation"]["final_gdrg"],
                                "diagnosis_tariff": evaluation_results["diagnosis_evaluation"]["tariff"],
                                "winner": selected_evaluation['final_gdrg'],
                                "winning_tariff": selected_evaluation['tariff'],
                                "selection_reason": f"{selected_option['type'].title()} G-DRG selected - only valid option"
                            }
                        }
                    )
            
            else:
                selected_option = max(valid_options, key=lambda x: x["tariff"])
                selected_evaluation = selected_option["evaluation"]
                
                other_option = [opt for opt in valid_options if opt != selected_option][0]
                
                financial_impact = {
                    "procedure_tariff": evaluation_results["procedure_evaluation"]["tariff"],
                    "diagnosis_tariff": evaluation_results["diagnosis_evaluation"]["tariff"],
                    "selected_tariff": selected_evaluation["tariff"],
                    "tariff_difference": abs(selected_option["tariff"] - other_option["tariff"]),
                    "selection_advantage": selected_option["tariff"] - other_option["tariff"],
                    "currency": "GHS"
                }
                
                selection_logic = {
                    "evaluation_method": "dual_gdrg_validation_comparison",
                    "both_validated": True,
                    "selection_criteria": "highest_valid_tariff",
                    "winner": selected_option["type"],
                    "winning_tariff": selected_evaluation["tariff"],
                    "runner_up_tariff": other_option["tariff"]
                }
                
                return ValidationOutcome(
                    result=ValidationResult.APPROVED,
                    reason=f"APPROVED: {selected_option['type'].title()} G-DRG selected - higher valid tariff: {selected_option['tariff']} vs {other_option['tariff']} GHS",
                    detailed_reason=f"Both G-DRGs valid. {selected_option['type'].title()} G-DRG {selected_evaluation['final_gdrg']} selected with higher tariff {selected_evaluation['tariff']} GHS vs {other_option['type']} G-DRG {other_option['evaluation']['final_gdrg']} with {other_option['tariff']} GHS",
                    financial_impact=financial_impact,
                    selection_logic=selection_logic,
                    details={
                        "path_type": GDRGPathType.DUAL_EVALUATION.value,
                        "selected_gdrg": selected_evaluation['final_gdrg'],
                        "selected_tariff": selected_evaluation['tariff'],
                        "selected_tariff_info": selected_evaluation['tariff_info'],
                        "evaluation_results": evaluation_results,
                        "selection_reason": "highest_valid_tariff",
                        "evaluation_summary": {
                            "procedure_evaluated": evaluation_results["procedure_evaluation"]["evaluated"],
                            "procedure_gdrg": evaluation_results["procedure_evaluation"]["final_gdrg"],
                            "procedure_tariff": evaluation_results["procedure_evaluation"]["tariff"],
                            "diagnosis_gdrg": evaluation_results["diagnosis_evaluation"]["final_gdrg"],
                            "diagnosis_tariff": evaluation_results["diagnosis_evaluation"]["tariff"],
                            "winner": selected_evaluation['final_gdrg'],
                            "winning_tariff": selected_evaluation['tariff'],
                            "selection_reason": f"Both valid - {selected_option['type']} G-DRG has higher tariff"
                        },
                        "tariff_comparison": {
                            "procedure": {
                                "gdrg": evaluation_results["procedure_evaluation"]["final_gdrg"],
                                "tariff": evaluation_results["procedure_evaluation"]["tariff"],
                                "available": evaluation_results["procedure_evaluation"]["validation_passed"],
                                "source": evaluation_results["procedure_evaluation"]["source"]
                            },
                            "diagnosis": {
                                "gdrg": evaluation_results["diagnosis_evaluation"]["final_gdrg"],
                                "tariff": evaluation_results["diagnosis_evaluation"]["tariff"],
                                "available": evaluation_results["diagnosis_evaluation"]["validation_passed"],
                                "source": evaluation_results["diagnosis_evaluation"]["source"]
                            }
                        }
                    }
                )
                
        except Exception as e:
            logger.error(f"Error in A2 dual G-DRG evaluation with validation: {e}")
            fallback_gdrg = claim_data.get('gdrg_code')
            detailed_reason = f"Error during dual G-DRG evaluation for encounter {claim_data.get('encounter_id')}: {str(e)}. Fallback to claim G-DRG: {fallback_gdrg}"
            
            return ValidationOutcome(
                result=ValidationResult.APPROVED,
                reason="A2: Fallback to claim G-DRG due to evaluation error",
                detailed_reason=detailed_reason,
                details={
                    "path_type": GDRGPathType.DIAGNOSIS_PATH.value,
                    "error": str(e),
                    "selected_gdrg": fallback_gdrg,
                    "source": "claim_fallback_error",
                    "evaluation_summary": {
                        "selection_reason": "Error fallback to claim G-DRG"
                    }
                }
            )
    
    async def _validate_individual_gdrg(self, claim_data: Dict, gdrg_code: str, gdrg_type: str) -> Dict:
        try:
            patient_age = claim_data.get('calculated_age', 0)
            patient_gender = claim_data.get('gender', '').upper()
            primary_icd10 = claim_data.get('icd10_code', '')
            encounter_id = claim_data.get('encounter_id')
            
            rejection_reasons = []
            validation_details = {
                "gdrg_code": gdrg_code,
                "gdrg_type": gdrg_type,
                "patient_age": patient_age,
                "patient_gender": patient_gender,
                "primary_icd10": primary_icd10,
                "checks_performed": []
            }
            
            age_check = await self._validate_gdrg_age_appropriateness(gdrg_code, patient_age, primary_icd10)
            validation_details["checks_performed"].append("age_validation")
            validation_details["age_validation"] = age_check
            
            if not age_check["valid"]:
                rejection_reasons.append(f"Age inappropriate: {age_check['reason']}")
            
            gender_check = await self._validate_gdrg_gender_appropriateness(gdrg_code, patient_gender, primary_icd10)
            validation_details["checks_performed"].append("gender_validation")
            validation_details["gender_validation"] = gender_check
            
            if not gender_check["valid"]:
                rejection_reasons.append(f"Gender inappropriate: {gender_check['reason']}")
            
            clinical_check = await self._validate_gdrg_clinical_appropriateness(gdrg_code, primary_icd10, claim_data)
            validation_details["checks_performed"].append("clinical_validation")
            validation_details["clinical_validation"] = clinical_check
            
            if not clinical_check["valid"]:
                rejection_reasons.append(f"Clinically inappropriate: {clinical_check['reason']}")
            
            is_valid = len(rejection_reasons) == 0
            
            if is_valid:
                logger.info(f"G-DRG {gdrg_code} ({gdrg_type}): VALIDATION PASSED for {encounter_id}")
            else:
                logger.warning(f"G-DRG {gdrg_code} ({gdrg_type}): VALIDATION FAILED for {encounter_id} - {', '.join(rejection_reasons)}")
            
            return {
                "valid": is_valid,
                "details": validation_details,
                "rejection_reasons": rejection_reasons
            }
            
        except Exception as e:
            logger.error(f"Error validating G-DRG {gdrg_code}: {e}")
            return {
                "valid": False,
                "details": {"error": str(e)},
                "rejection_reasons": [f"Validation error: {str(e)}"]
            }

    async def _validate_gdrg_age_appropriateness(self, gdrg_code: str, patient_age: int, icd10_code: str) -> Dict:
        try:
            if gdrg_code.endswith('C'):
                if patient_age >= 12:
                    is_cancer = any(icd10_code.startswith(cancer_code) for cancer_code in self.cancer_icd10_codes)
                    if is_cancer and patient_age < 19:
                        return {"valid": True, "reason": "Childhood cancer exception allows pediatric G-DRG"}
                    else:
                        return {"valid": False, "reason": f"Pediatric G-DRG inappropriate for age {patient_age}"}
            
            elif gdrg_code.endswith('A'):
                if patient_age < 12:
                    return {"valid": False, "reason": f"Adult G-DRG inappropriate for age {patient_age}"}
            
            return {"valid": True, "reason": "Age appropriate"}
            
        except Exception as e:
            return {"valid": True, "reason": f"Age validation error: {str(e)}"}

    async def _validate_gdrg_gender_appropriateness(self, gdrg_code: str, patient_gender: str, icd10_code: str) -> Dict:
        try:
            male_only_gdrgs = ['SURG15', 'SURG16']
            female_only_gdrgs = ['SURG17', 'SURG18', 'OBST01', 'OBST02', 'OBST03']
            
            base_gdrg = gdrg_code.rstrip('AC')
            
            if any(male_gdrg in base_gdrg for male_gdrg in male_only_gdrgs):
                if patient_gender != 'M':
                    return {"valid": False, "reason": f"Male-specific G-DRG {gdrg_code} inappropriate for {patient_gender} patient"}
            
            if any(female_gdrg in base_gdrg for female_gdrg in female_only_gdrgs):
                if patient_gender != 'F':
                    return {"valid": False, "reason": f"Female-specific G-DRG {gdrg_code} inappropriate for {patient_gender} patient"}
            
            return {"valid": True, "reason": "Gender appropriate"}
            
        except Exception as e:
            return {"valid": True, "reason": f"Gender validation error: {str(e)}"}

    async def _validate_gdrg_clinical_appropriateness(self, gdrg_code: str, primary_icd10: str, claim_data: Dict) -> Dict:
        try:
            contraindicated_combinations = {
                'CARDI': {
                    'inappropriate_with': ['Z51'],
                    'reason': 'Cardiac G-DRG inappropriate for aftercare encounters'
                },
                'SURG': {
                    'inappropriate_with': ['Z00', 'Z01'],
                    'reason': 'Surgical G-DRG inappropriate for health examination'
                }
            }
            
            base_gdrg = gdrg_code.rstrip('AC')
            
            for gdrg_pattern, rules in contraindicated_combinations.items():
                if gdrg_pattern in base_gdrg:
                    for inappropriate_icd10 in rules['inappropriate_with']:
                        if primary_icd10.startswith(inappropriate_icd10):
                            return {
                                "valid": False, 
                                "reason": f"{rules['reason']} (ICD-10: {primary_icd10})"
                            }
            
            return {"valid": True, "reason": "Clinically appropriate"}
            
        except Exception as e:
            return {"valid": True, "reason": f"Clinical validation error: {str(e)}"}
    
    def _create_dual_evaluation_detailed_reason(self, encounter_id: str, claim_data: Dict, 
                                               evaluation_results: Dict, selected_evaluation: Dict, 
                                               selection_reason: str) -> str:
        
        primary_icd10 = claim_data.get('icd10_code')
        procedure_icd10 = claim_data.get('icd10_code_procedure')
        diagnosis_name = claim_data.get('diagnosis_name')
        procedure_description = claim_data.get('icd10_description_procedure')
        
        reason_parts = []
        
        reason_parts.append(f"Dual G-DRG evaluation completed for encounter {encounter_id}.")
        
        diag_eval = evaluation_results["diagnosis_evaluation"]
        reason_parts.append(f"Diagnosis: {primary_icd10} ({diagnosis_name or 'Not provided'})")
        if diag_eval["gdrg_found"]:
            reason_parts.append(f"Diagnosis G-DRG: {diag_eval['base_gdrg']} → {diag_eval['final_gdrg']} = {diag_eval['tariff']} GHS (Source: {diag_eval['source']})")
        else:
            reason_parts.append(f"Diagnosis G-DRG: Not found or no tariff available. Error: {diag_eval['error']}")
        
        proc_eval = evaluation_results["procedure_evaluation"]
        if proc_eval["evaluated"]:
            reason_parts.append(f"Procedure: {procedure_icd10} ({procedure_description or 'Not provided'})")
            if proc_eval["gdrg_found"]:
                reason_parts.append(f"Procedure G-DRG: {proc_eval['base_gdrg']} → {proc_eval['final_gdrg']} = {proc_eval['tariff']} GHS (Source: {proc_eval['source']})")
            else:
                reason_parts.append(f"Procedure G-DRG: Not found or no tariff available. Error: {proc_eval['error']}")
        else:
            reason_parts.append("Procedure evaluation: Skipped (no valid procedure codes)")
        
        reason_parts.append(f"Selection decision: {selection_reason}")
        reason_parts.append(f"Final G-DRG selected: {selected_evaluation['final_gdrg']} with tariff {selected_evaluation['tariff']} GHS")
        
        return " ".join(reason_parts)
    
    def _create_comprehensive_detailed_reason(self, claim_data: Dict, a2_details: Dict, step_results: Dict) -> str:
        
        encounter_id = claim_data.get('encounter_id')
        reason_parts = []
        
        reason_parts.append(f"Step 5 G-DRG determination completed for encounter {encounter_id}.")
        
        reason_parts.append("OPDC13A special case check: Passed - no OPDC13A detected in ICD-10 or G-DRG codes.")
        
        icd10_code = claim_data.get('icd10_code')
        reason_parts.append(f"ICD-10 validation: Passed - {icd10_code} is valid.")
        
        eval_summary = a2_details.get("evaluation_summary", {})
        reason_parts.append(f"Dual G-DRG evaluation: {eval_summary.get('selection_reason', 'Selection completed')}")
        
        final_gdrg = step_results["gdrg_determination"]["final_gdrg"]
        tariff_info = step_results["gdrg_determination"]["tariff_info"]
        reason_parts.append(f"Final result: G-DRG {final_gdrg} selected with tariff {tariff_info['amount']} {tariff_info['currency']}")
        
        path_type = step_results["gdrg_determination"]["path_type"]
        reason_parts.append(f"Processing path: {path_type}")
        
        return " ".join(reason_parts)
    
    async def _get_gdrg_from_procedure_inferences(self, icd10_code: str, encounter_type: str, patient_age: int) -> Optional[str]:
        try:
            query = """
            SELECT 
                gdrg_code,
                gdrg_description,
                age_restrictions,
                gender_restriction,
                level_procedure
            FROM clinical_procedure_inferences 
            WHERE icd10_code = $1 
                AND encounter_type = $2
            ORDER BY gdrg_code
            LIMIT 1
            """
            
            result = await self.queries.db.fetch_one(query, icd10_code, encounter_type)
            
            if result:
                age_restrictions = result.get('age_restrictions')
                if age_restrictions and isinstance(age_restrictions, str):
                    try:
                        age_restrictions = json.loads(age_restrictions)
                        min_age = age_restrictions.get('min_age')
                        max_age = age_restrictions.get('max_age')
                        
                        if min_age and patient_age < min_age:
                            logger.warning(f"Patient age {patient_age} below minimum {min_age} for procedure G-DRG")
                            return None
                        if max_age and patient_age > max_age:
                            logger.warning(f"Patient age {patient_age} above maximum {max_age} for procedure G-DRG")
                            return None
                    except:
                        pass
                
                logger.info(f"Found procedure G-DRG: {result['gdrg_code']} for {icd10_code}")
                return result['gdrg_code']
            
            return None
            
        except Exception as e:
            logger.error(f"Error querying clinical_procedure_inferences: {e}")
            return None
    
    async def _get_gdrg_from_diagnosis_inferences(self, icd10_code: str, encounter_type: str, patient_age: int) -> Optional[str]:
        try:
            query = """
            SELECT 
                gdrg_code,
                gdrg_description,
                age_restrictions,
                gender_restriction
            FROM clinical_diagnosis_inferences 
            WHERE icd10_code = $1 
                AND encounter_type = $2
            ORDER BY gdrg_code
            LIMIT 1
            """
            
            result = await self.queries.db.fetch_one(query, icd10_code, encounter_type)
            
            if result:
                age_restrictions = result.get('age_restrictions')
                if age_restrictions and isinstance(age_restrictions, str):
                    try:
                        age_restrictions = json.loads(age_restrictions)
                        min_age = age_restrictions.get('min_age')
                        max_age = age_restrictions.get('max_age')
                        
                        if min_age and patient_age < min_age:
                            logger.warning(f"Patient age {patient_age} below minimum {min_age} for diagnosis G-DRG")
                            return None
                        if max_age and patient_age > max_age:
                            logger.warning(f"Patient age {patient_age} above maximum {max_age} for diagnosis G-DRG")
                            return None
                    except:
                        pass
                
                logger.info(f"Found diagnosis G-DRG: {result['gdrg_code']} for {icd10_code}")
                return result['gdrg_code']
            
            return None
            
        except Exception as e:
            logger.error(f"Error querying clinical_diagnosis_inferences: {e}")
            return None
    
    async def _a3_apply_age_split(self, claim_data: Dict, base_gdrg: str) -> ValidationOutcome:
        try:
            patient_age = claim_data.get('calculated_age', 0)
            icd10_code = claim_data.get('icd10_code', '')
            encounter_id = claim_data.get('encounter_id')
            
            is_cancer = any(icd10_code.startswith(cancer_code) for cancer_code in self.cancer_icd10_codes)
            
            if is_cancer and patient_age < 19:
                age_suffix = 'C'
                age_rule_applied = f"Childhood cancer rule: Age {patient_age} < 19 years → 'C' suffix"
                logger.info(f"A3: Childhood cancer rule applied - {age_rule_applied}")
                
            elif patient_age < 12:
                age_suffix = 'C'
                age_rule_applied = f"Pediatric rule: Age {patient_age} < 12 years → 'C' suffix"
                logger.info(f"A3: Pediatric rule applied - {age_rule_applied}")
                
            else:
                age_suffix = 'A'
                age_rule_applied = f"Adult rule: Age {patient_age} ≥ 12 years → 'A' suffix"
                logger.info(f"A3: Adult rule applied - {age_rule_applied}")
            
            base_gdrg_clean = base_gdrg.rstrip('AC')
            final_gdrg = f"{base_gdrg_clean}{age_suffix}"
            
            detailed_reason = f"Age split applied for encounter {encounter_id}. Patient age: {patient_age} years. Base G-DRG: {base_gdrg} → Final G-DRG: {final_gdrg}. Rule applied: {age_rule_applied}"
            if is_cancer:
                detailed_reason += f" Cancer diagnosis detected in ICD-10: {icd10_code}."
            
            return ValidationOutcome(
                result=ValidationResult.APPROVED,
                reason=f"A3: Age split applied - {age_rule_applied}",
                detailed_reason=detailed_reason,
                details={
                    "patient_age": patient_age,
                    "is_cancer_diagnosis": is_cancer,
                    "icd10_code": icd10_code,
                    "base_gdrg": base_gdrg,
                    "age_suffix": age_suffix,
                    "final_gdrg": final_gdrg,
                    "age_rule_applied": age_rule_applied
                }
            )
            
        except Exception as e:
            logger.error(f"Error in A3 age split: {e}")
            fallback_gdrg = f"{base_gdrg.rstrip('AC')}A"
            detailed_reason = f"Age split error for encounter {claim_data.get('encounter_id')}: {str(e)}. Applied default adult suffix 'A'. Final G-DRG: {fallback_gdrg}"
            
            return ValidationOutcome(
                result=ValidationResult.APPROVED,
                reason="A3: Default age split applied due to error",
                detailed_reason=detailed_reason,
                details={
                    "error": str(e),
                    "fallback_gdrg": fallback_gdrg,
                    "final_gdrg": fallback_gdrg,
                    "age_suffix": "A",
                    "age_rule_applied": "Default adult rule (error fallback)"
                }
            )
    
    async def _lookup_facility_tariff(self, provider_name: str, facility_level: str, 
                                    gdrg_code: str, encounter_type: str) -> Optional[Dict]:
        try:
            base_gdrg = gdrg_code.rstrip('AC')
            
            logger.info(f"TARIFF LOOKUP: {gdrg_code} → {base_gdrg} for {provider_name}")
            
            tariff_result = None
            lookup_strategy = None
            
            tariff_query_exact = """
            SELECT 
                icd_code,
                diagnosis_description,
                gdrg_code,
                gdrg_name,
                tariff
            FROM icd10_codes 
            WHERE gdrg_code = $1 
                AND tariff IS NOT NULL
            LIMIT 1
            """
            
            tariff_result = await self.queries.db.fetch_one(tariff_query_exact, gdrg_code)
            if tariff_result:
                lookup_strategy = "exact_gdrg_match"
                logger.info(f"Found exact G-DRG match: {gdrg_code}")
            
            if not tariff_result:
                tariff_result = await self.queries.db.fetch_one(tariff_query_exact, base_gdrg)
                if tariff_result:
                    lookup_strategy = "base_gdrg_match"
                    logger.info(f"Found base G-DRG match: {base_gdrg}")
            
            if not tariff_result:
                tariff_query_pattern = """
                SELECT 
                    icd_code,
                    diagnosis_description,
                    gdrg_code,
                    gdrg_name,
                    tariff
                FROM icd10_codes 
                WHERE gdrg_code LIKE $1 
                    AND tariff IS NOT NULL
                ORDER BY 
                    CASE 
                        WHEN gdrg_code = $2 THEN 1
                        WHEN gdrg_code = $3 THEN 2
                        ELSE 3 
                    END
                LIMIT 1
                """
                
                pattern = f"{base_gdrg}%"
                tariff_result = await self.queries.db.fetch_one(tariff_query_pattern, pattern, gdrg_code, base_gdrg)
                if tariff_result:
                    lookup_strategy = "pattern_match"
                    logger.info(f"Found pattern match: {tariff_result['gdrg_code']} for {gdrg_code}")
            
            if not tariff_result or not tariff_result.get('tariff'):
                logger.error(f"No tariff found for {gdrg_code} or {base_gdrg} in any strategy")
                return None
            
            try:
                base_amount = float(tariff_result['tariff'])
            except (ValueError, TypeError) as e:
                logger.error(f"Invalid tariff amount: {tariff_result.get('tariff')} - {e}")
                return None
            
            facility_multipliers = {
                '1': 0,
                '2': 1,
                '3': 1
            }
            
            encounter_multipliers = {
                'OPD': 1,
                'IPD': 1,
                'A&E': 1
            }
            
            facility_multiplier = facility_multipliers.get(str(facility_level), 1.00)
            adjusted_amount = base_amount * facility_multiplier
            
            encounter_multiplier = encounter_multipliers.get(encounter_type, 1.00)
            final_amount = adjusted_amount * encounter_multiplier
            
            age_multiplier = 1.00
            if gdrg_code.endswith('C'):
                age_multiplier = 0.95
            elif gdrg_code.endswith('A'):
                age_multiplier = 1.00
            
            final_amount = final_amount * age_multiplier
            
            logger.info(f"TARIFF CALCULATED: {gdrg_code} = {base_amount} × {facility_multiplier} × {encounter_multiplier} × {age_multiplier} = {final_amount:.2f} GHS")
            
            tariff_info = {
                'gdrg_code': gdrg_code,
                'base_gdrg_used': tariff_result['gdrg_code'],
                'lookup_strategy': lookup_strategy,
                'amount': round(final_amount, 2),
                'currency': 'GHS',
                'base_amount': base_amount,
                'facility_multiplier': facility_multiplier,
                'encounter_multiplier': encounter_multiplier,
                'age_multiplier': age_multiplier,
                'description': tariff_result.get('gdrg_name') or tariff_result.get('diagnosis_description'),
                'provider_name': provider_name,
                'facility_level': facility_level
            }
            
            return tariff_info
            
        except Exception as e:
            logger.error(f"Error in tariff lookup: {e}")
            return None
    
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
        
        if step_results.get("special_case_triggered"):
            original_result.details["special_case_triggered"] = True
            original_result.details["special_case_details"] = step_results["special_case_details"]
            original_result.details["processing_stopped"] = True
            original_result.details["manual_review_required"] = True
        
        return original_result
    
    async def validate_multiple_claims(self, encounter_ids: List[str]) -> Dict[str, ValidationOutcome]:
        results = {}
        special_cases_found = []
        dual_evaluations_performed = 0
        partial_approvals = 0
        
        for encounter_id in encounter_ids:
            try:
                result = await self.process_step5_gdrg_determination(encounter_id)
                results[encounter_id] = result
                
                if result.details and result.details.get("dual_evaluation_summary"):
                    dual_evaluations_performed += 1
                
                if result.result == ValidationResult.PARTIAL:
                    partial_approvals += 1
                
                if result.special_case_triggered:
                    special_cases_found.append({
                        "encounter_id": encounter_id,
                        "special_case_type": result.special_case_type.value if result.special_case_type else "UNKNOWN",
                        "reason": result.reason
                    })
                
                if result.special_case_triggered:
                    status_emoji = "FLAG"
                    logger.warning(f"{status_emoji} {encounter_id}: {result.reason} - MANUAL REVIEW REQUIRED")
                else:
                    status_emoji = "PASS" if result.result == ValidationResult.APPROVED else "PARTIAL" if result.result == ValidationResult.PARTIAL else "FAIL"
                    gdrg_info = ""
                    if result.details and result.details.get('gdrg_summary'):
                        gdrg_summary = result.details['gdrg_summary']
                        gdrg_info = f" → {gdrg_summary['selected_gdrg']} ({gdrg_summary['tariff_amount']} {gdrg_summary['tariff_currency']})"
                        if gdrg_summary.get('dual_evaluation'):
                            gdrg_info += " [DUAL EVAL]"
                        if gdrg_summary.get('validation_applied'):
                            gdrg_info += " [VALIDATED]"
                    logger.info(f"{status_emoji} {encounter_id}: {result.reason}{gdrg_info}")
                
            except Exception as e:
                logger.error(f"Error validating {encounter_id}: {e}")
                results[encounter_id] = ValidationOutcome(
                    result=ValidationResult.PENDING,
                    reason=f"PEND: Validation error - {str(e)}",
                    detailed_reason=f"System error during G-DRG determination for encounter {encounter_id}: {str(e)}",
                    details={"encounter_id": encounter_id}
                )
        
        logger.info(f"BATCH VALIDATION COMPLETE: {len(results)} claims processed")
        logger.info(f"Dual evaluations performed: {dual_evaluations_performed}")
        logger.info(f"Partial approvals (validation rejections): {partial_approvals}")
        
        if special_cases_found:
            logger.warning(f"SPECIAL CASES FOUND: {len(special_cases_found)} claims flagged for manual review")
            for case in special_cases_found:
                logger.warning(f"   FLAG {case['encounter_id']}: {case['special_case_type']} - {case['reason']}")
        
        return results


async def test_dual_gdrg_selection_with_validation():
    validator = EnhancedGDRGDeterminationStep5()
    
    try:
        await validator.initialize()
        
        print("\nTESTING ENHANCED DUAL G-DRG SELECTION WITH INDIVIDUAL VALIDATION")
        print("=" * 80)
        
        mock_claim_validation_test = {
            "encounter_id": "TEST-VALIDATION-001",
            "icd10_code": "I50.9",
            "diagnosis_name": "Heart failure, unspecified",
            "icd10_code_procedure": "5A1221Z",
            "icd10_description_procedure": "Cardiac procedure",
            "gdrg_code": "CARDI03A",
            "calculated_age": 65,
            "encounter_type": "IPD",
            "provider_name": "Test Cardiac Hospital",
            "gender": "M"
        }
        
        result = await validator._a2_dual_gdrg_evaluation_with_validation(mock_claim_validation_test)
        print(f"   Result: {result.result.value}")
        print(f"   Reason: {result.reason}")
        
        return True
        
    except Exception as e:
        print(f"Test failed: {e}")
        return False
    
    finally:
        await validator.close()


async def main():
    print("\nENHANCED G-DRG DETERMINATION WITH INDIVIDUAL VALIDATION")
    print("=" * 90)
    
    test_success = await test_dual_gdrg_selection_with_validation()
    
    if test_success:
        print("\nVALIDATION INTEGRATION COMPLETE")
    else:
        print("\nTEST VERIFICATION FAILED")


if __name__ == "__main__":
    asyncio.run(main())