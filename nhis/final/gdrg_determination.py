import asyncio
import json
import logging
from typing import Dict, List, Optional, Any
from dataclasses import dataclass
from enum import Enum
from datetime import datetime

from neon_db_connection import get_nhis_queries, initialize_database, close_database

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class ValidationResult(Enum):
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    FLAGGED = "FLAGGED"
    PENDING = "PENDING"
    PARTIAL = "PARTIAL"

class SpecialCaseType(Enum):
    OPDC13A_SUPPORTING_DOCS = "OPDC13A_SUPPORTING_DOCS"

@dataclass
class ValidationOutcome:
    result: ValidationResult
    reason: str
    financial_impact: Dict[str, Any] = None
    selection_logic: Dict[str, Any] = None
    details: Dict[str, Any] = None
    timestamp: datetime = None
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
                "required_documents": [
                    "Medical practitioner's detailed report",
                    "Laboratory investigation results",
                    "Diagnostic imaging reports (if applicable)",
                    "Specialist consultation notes",
                    "Treatment protocol documentation"
                ],
                "manual_review_required": True
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
        
        self.female_only_icd10_prefixes = [
            'O00', 'O01', 'O02', 'O03', 'O04', 'O05', 'O06', 'O07', 'O08',
            'O10', 'O11', 'O12', 'O13', 'O14', 'O15', 'O16',
            'O20', 'O21', 'O22', 'O23', 'O24', 'O25', 'O26', 'O28', 'O29',
            'O30', 'O31', 'O32', 'O33', 'O34', 'O35', 'O36',
            'O40', 'O41', 'O42', 'O43', 'O44', 'O45', 'O46', 'O47', 'O48',
            'O60', 'O61', 'O62', 'O63', 'O64', 'O65', 'O66', 'O67', 'O68', 'O69',
            'O70', 'O71', 'O72', 'O73', 'O74', 'O75', 'O76', 'O77',
            'O80', 'O81', 'O82', 'O83', 'O84', 'O85', 'O86', 'O87', 'O88', 'O89',
            'O90', 'O91', 'O92', 'O94', 'O95', 'O96', 'O97', 'O98', 'O99', 'O9A',
            'Z30', 'Z31', 'Z32', 'Z33', 'Z34', 'Z35', 'Z36', 'Z37', 'Z38', 'Z39',
            'N70', 'N71', 'N72', 'N73', 'N74', 'N75', 'N76', 'N77',
            'N80', 'N81', 'N82', 'N83', 'N84', 'N85', 'N86', 'N87', 'N88', 'N89',
            'N90', 'N91', 'N92', 'N93', 'N94', 'N95', 'N96', 'N97', 'N98',
            'C51', 'C52', 'C53', 'C54', 'C55', 'C56', 'C57', 'C58',
            'D25', 'D26', 'D27', 'D28',
            'N99.2', 'N99.3',
        ]
        
        self.male_only_icd10_prefixes = [
            'N40', 'N41', 'N42', 'N43', 'N44', 'N45', 'N46', 'N47', 'N48', 'N49', 'N50', 'N51',
            'C60', 'C61', 'C62', 'C63',
            'D29',
            'E29.0', 'E29.1',
            'I86.1',
            'Q53', 'Q54', 'Q55',
            'Z12.5',
        ]
        
        self.female_only_gdrg_patterns = [
            'OBGY', 'OBST', 'GYNE',
        ]
        
        self.male_only_gdrg_patterns = [
            'UROL15', 'UROL16',
        ]
    
    async def initialize(self):
        if not self.is_initialized:
            await initialize_database()
            self.queries = await get_nhis_queries()
            self.is_initialized = True
            logger.info("Enhanced G-DRG Determination Step 5 initialized")
    
    async def close(self):
        await close_database()
        self.is_initialized = False
        logger.info("Enhanced G-DRG Determination Step 5 closed")
    
    async def process_step5_gdrg_determination(self, encounter_id: str, rejected_gdrgs_from_step4: List[str] = None) -> ValidationOutcome:
        if not self.is_initialized:
            await self.initialize()
        
        try:
            logger.info(f"STEP 5: Starting G-DRG determination for {encounter_id}")
            
            claim_data = await self.queries.get_claim_with_calculated_age(encounter_id)
            if not claim_data:
                return ValidationOutcome(
                    result=ValidationResult.REJECTED,
                    reason="REJECT: Claim not found",
                    details={"encounter_id": encounter_id}
                )
            
            opdc13a_check = await self._check_opdc13a_special_case(claim_data)
            if opdc13a_check.special_case_triggered:
                logger.warning(f"OPDC13A FLAGGED for {encounter_id}: Manual review required")
                return opdc13a_check
            
            icd10_code = claim_data.get('icd10_code')
            if not icd10_code or len(icd10_code) < 3:
                return ValidationOutcome(
                    result=ValidationResult.PENDING,
                    reason="PEND: Missing or invalid ICD-10 code",
                    details={"encounter_id": encounter_id}
                )
            
            result = await self._dual_gdrg_evaluation(claim_data, rejected_gdrgs_from_step4 or [])
            
            logger.info(f"STEP 5 COMPLETED for {encounter_id}: {result.reason}")
            return result
            
        except Exception as e:
            logger.error(f"Error in Step 5: {e}")
            return ValidationOutcome(
                result=ValidationResult.PENDING,
                reason=f"PEND: System error - {str(e)}",
                details={"error": str(e), "encounter_id": encounter_id}
            )
    
    async def _check_opdc13a_special_case(self, claim_data: Dict) -> ValidationOutcome:
        try:
            encounter_id = claim_data.get('encounter_id')
            icd10_code = claim_data.get('icd10_code', '').strip().upper()
            gdrg_code = claim_data.get('gdrg_code', '').strip().upper()
            
            if icd10_code == 'OPDC13A' or gdrg_code == 'OPDC13A':
                config = self.special_case_codes["OPDC13A"]
                
                return ValidationOutcome(
                    result=ValidationResult.FLAGGED,
                    reason=f"FLAG: {config['flag_reason']}",
                    details={
                        "encounter_id": encounter_id,
                        "opdc13a_detected_in": "ICD-10" if icd10_code == 'OPDC13A' else "G-DRG",
                        "required_documents": config["required_documents"],
                        "manual_review_required": True
                    },
                    special_case_triggered=True,
                    special_case_type=config["case_type"]
                )
            
            return ValidationOutcome(
                result=ValidationResult.APPROVED,
                reason="OPDC13A check passed",
                details={"opdc13a_detected": False},
                special_case_triggered=False
            )
            
        except Exception as e:
            logger.error(f"Error in OPDC13A check: {e}")
            return ValidationOutcome(
                result=ValidationResult.APPROVED,
                reason="OPDC13A check completed with error",
                details={"error": str(e)},
                special_case_triggered=False
            )
    
    async def _dual_gdrg_evaluation(self, claim_data: Dict, rejected_gdrgs: List[str] = None) -> ValidationOutcome:
        rejected_gdrgs = rejected_gdrgs or []
        
        try:
            encounter_id = claim_data.get('encounter_id')
            icd10_procedure = claim_data.get('icd10_code_procedure')
            primary_icd10 = claim_data.get('icd10_code')
            encounter_type = claim_data.get('encounter_type')
            patient_age = claim_data.get('calculated_age', 0)
            patient_gender = claim_data.get('gender', 'U').upper()
            provider_name = claim_data.get('provider_name')
            
            facility_info = await self.queries.get_facility_info_by_name(provider_name)
            facility_level = facility_info.get('facility_level', '2') if facility_info else '2'
            
            logger.info(f"=== DUAL G-DRG EVALUATION START for {encounter_id} ===")
            logger.info(f"Patient: Age {patient_age}, Gender {patient_gender}")
            logger.info(f"Diagnosis ICD-10: {primary_icd10}")
            logger.info(f"Procedure ICD-10: {icd10_procedure if icd10_procedure else 'None'}")
            logger.info(f"Encounter Type: {encounter_type}")
            
            if rejected_gdrgs:
                logger.info(f"G-DRGs rejected in Step 4: {rejected_gdrgs}")
            
            has_procedure = bool(icd10_procedure and icd10_procedure not in ['NA', '', None] and len(icd10_procedure.strip()) >= 3)
            
            procedure_result = None
            diagnosis_result = None
            
            if has_procedure:
                procedure_gdrg = claim_data.get('gdrg_code_procedure')
                
                if procedure_gdrg in rejected_gdrgs:
                    logger.info(f"⊗ Skipping procedure G-DRG {procedure_gdrg} - already rejected in Step 4 credentialing")
                    procedure_result = {
                        "valid": False,
                        "gdrg": procedure_gdrg,
                        "rejections": ["Failed Step 4 credentialing - facility not authorized"],
                        "tariff": 0
                    }
                else:
                    logger.info(f"--- Evaluating PROCEDURE path: {icd10_procedure} ---")
                    procedure_result = await self._evaluate_single_gdrg(
                        claim_data, icd10_procedure, "procedure", encounter_type, patient_age, provider_name, facility_level
                    )
                    if procedure_result["valid"]:
                        logger.info(f"✓ Procedure G-DRG {procedure_result['gdrg']}: PASSED - {procedure_result['tariff']} GHS")
                    else:
                        logger.warning(f"✗ Procedure G-DRG {procedure_result.get('gdrg', 'N/A')}: FAILED")
                        logger.warning(f"  Rejection reasons: {', '.join(procedure_result.get('rejections', ['Unknown']))}")
            
            diagnosis_gdrg = claim_data.get('gdrg_code')
            
            if diagnosis_gdrg in rejected_gdrgs:
                logger.info(f"⊗ Skipping diagnosis G-DRG {diagnosis_gdrg} - already rejected in Step 4 credentialing")
                diagnosis_result = {
                    "valid": False,
                    "gdrg": diagnosis_gdrg,
                    "rejections": ["Failed Step 4 credentialing - facility not authorized"],
                    "tariff": 0
                }
            else:
                logger.info(f"--- Evaluating DIAGNOSIS path: {primary_icd10} ---")
                diagnosis_result = await self._evaluate_single_gdrg(
                    claim_data, primary_icd10, "diagnosis", encounter_type, patient_age, provider_name, facility_level
                )
                if diagnosis_result["valid"]:
                    logger.info(f"✓ Diagnosis G-DRG {diagnosis_result['gdrg']}: PASSED - {diagnosis_result['tariff']} GHS")
                else:
                    logger.warning(f"✗ Diagnosis G-DRG {diagnosis_result.get('gdrg', 'N/A')}: FAILED")
                    logger.warning(f"  Rejection reasons: {', '.join(diagnosis_result.get('rejections', ['Unknown']))}")
            
            valid_options = []
            
            if procedure_result and procedure_result["valid"]:
                valid_options.append({"type": "procedure", "data": procedure_result})
            
            if diagnosis_result and diagnosis_result["valid"]:
                valid_options.append({"type": "diagnosis", "data": diagnosis_result})
            
            tariff_comparison = {
                "procedure": {
                    "gdrg": procedure_result["gdrg"] if procedure_result else None,
                    "tariff": procedure_result["tariff"] if procedure_result else 0,
                    "available": procedure_result["valid"] if procedure_result else False,
                    "rejection_reasons": procedure_result["rejections"] if procedure_result else []
                },
                "diagnosis": {
                    "gdrg": diagnosis_result["gdrg"] if diagnosis_result else None,
                    "tariff": diagnosis_result["tariff"] if diagnosis_result else 0,
                    "available": diagnosis_result["valid"] if diagnosis_result else False,
                    "rejection_reasons": diagnosis_result["rejections"] if diagnosis_result else []
                }
            }
            
            if not valid_options:
                all_rejections = []
                if procedure_result:
                    all_rejections.extend(procedure_result["rejections"])
                if diagnosis_result:
                    all_rejections.extend(diagnosis_result["rejections"])
                
                is_single_path = not has_procedure
                
                logger.error(f"=== BOTH PATHS REJECTED for {encounter_id} ===")
                logger.error(f"All rejections: {', '.join(set(all_rejections))}")
                
                return ValidationOutcome(
                    result=ValidationResult.REJECTED,
                    reason=f"REJECT: {'Single G-DRG failed validation' if is_single_path else 'Both G-DRGs failed validation'} - {', '.join(set(all_rejections))}",
                    details={
                        "encounter_id": encounter_id,
                        "is_single_path": is_single_path,
                        "procedure_result": procedure_result,
                        "diagnosis_result": diagnosis_result,
                        "tariff_comparison": tariff_comparison,
                        "medicine_instructions": {
                            "procedure_medicines": "REJECTED" if procedure_result else "N/A",
                            "diagnosis_medicines": "REJECTED"
                        }
                    }
                )
            
            elif len(valid_options) == 1:
                selected = valid_options[0]
                
                if has_procedure:
                    rejected_type = "diagnosis" if selected["type"] == "procedure" else "procedure"
                    rejected_data = diagnosis_result if selected["type"] == "procedure" else procedure_result
                    
                    logger.warning(f"=== PARTIAL APPROVAL for {encounter_id} ===")
                    logger.warning(f"REJECTED path: {rejected_type.upper()}")
                    logger.warning(f"  Rejected G-DRG: {rejected_data.get('gdrg', 'N/A')}")
                    logger.warning(f"  Rejection reasons: {', '.join(rejected_data.get('rejections', ['Unknown']))}")
                    logger.info(f"SELECTED path: {selected['type'].upper()}")
                    logger.info(f"  Selected G-DRG: {selected['data']['gdrg']}")
                    logger.info(f"  Selected tariff: {selected['data']['tariff']} GHS")
                    
                    financial_impact = {
                        "procedure_tariff": procedure_result["tariff"] if procedure_result else 0,
                        "diagnosis_tariff": diagnosis_result["tariff"] if diagnosis_result else 0,
                        "selected_tariff": selected["data"]["tariff"],
                        "rejected_tariff": rejected_data["tariff"],
                        "tariff_loss": max(0, rejected_data["tariff"] - selected["data"]["tariff"]),
                        "currency": "GHS"
                    }
                    
                    selection_logic = {
                        "evaluation_method": "dual_gdrg_validation",
                        "both_validated": False,
                        "selection_criteria": "only_valid_option",
                        "winner": selected["type"],
                        "winning_tariff": selected["data"]["tariff"]
                    }
                    
                    medicine_instructions = {
                        "procedure_medicines": "APPROVED" if selected["type"] == "procedure" else "REJECTED",
                        "diagnosis_medicines": "APPROVED" if selected["type"] == "diagnosis" else "REJECTED",
                        "approved_path": selected["type"]
                    }
                    
                    return ValidationOutcome(
                        result=ValidationResult.PARTIAL,
                        reason=f"PARTIAL: {selected['type'].title()} G-DRG approved, {rejected_type} rejected - {', '.join(rejected_data.get('rejections', ['Misapplication of tariffs']))}",
                        financial_impact=financial_impact,
                        selection_logic=selection_logic,
                        details={
                            "encounter_id": encounter_id,
                            "selected_gdrg": selected["data"]["gdrg"],
                            "selected_tariff": selected["data"]["tariff"],
                            "rejected_gdrg": rejected_data["gdrg"],
                            "rejection_reasons": rejected_data["rejections"],
                            "tariff_comparison": tariff_comparison,
                            "medicine_instructions": medicine_instructions,
                            "gdrg_summary": {
                                "selected_gdrg": selected["data"]["gdrg"],
                                "path_used": selected["type"],
                                "tariff_amount": selected["data"]["tariff"],
                                "tariff_currency": "GHS"
                            }
                        }
                    )
                else:
                    logger.info(f"=== SINGLE PATH APPROVAL for {encounter_id} ===")
                    logger.info(f"Selected G-DRG: {selected['data']['gdrg']} - {selected['data']['tariff']} GHS")
                    
                    return ValidationOutcome(
                        result=ValidationResult.APPROVED,
                        reason=f"APPROVED: {selected['type'].title()} G-DRG - {selected['data']['tariff']} GHS",
                        details={
                            "encounter_id": encounter_id,
                            "selected_gdrg": selected["data"]["gdrg"],
                            "selected_tariff": selected["data"]["tariff"],
                            "tariff_comparison": tariff_comparison,
                            "medicine_instructions": {
                                "diagnosis_medicines": "APPROVED"
                            },
                            "gdrg_summary": {
                                "selected_gdrg": selected["data"]["gdrg"],
                                "path_used": selected["type"],
                                "tariff_amount": selected["data"]["tariff"],
                                "tariff_currency": "GHS"
                            }
                        }
                    )
            
            else:
                selected = max(valid_options, key=lambda x: x["data"]["tariff"])
                other = [opt for opt in valid_options if opt != selected][0]
                
                logger.info(f"=== DUAL PATH APPROVAL - HIGHEST TARIFF SELECTED for {encounter_id} ===")
                logger.info(f"Selected: {selected['type'].upper()} G-DRG {selected['data']['gdrg']} - {selected['data']['tariff']} GHS")
                logger.info(f"Rejected: {other['type'].upper()} G-DRG {other['data']['gdrg']} - {other['data']['tariff']} GHS (lower tariff)")
                
                financial_impact = {
                    "procedure_tariff": procedure_result["tariff"] if procedure_result else 0,
                    "diagnosis_tariff": diagnosis_result["tariff"] if diagnosis_result else 0,
                    "selected_tariff": selected["data"]["tariff"],
                    "tariff_difference": abs(selected["data"]["tariff"] - other["data"]["tariff"]),
                    "currency": "GHS"
                }
                
                selection_logic = {
                    "evaluation_method": "dual_gdrg_validation",
                    "both_validated": True,
                    "selection_criteria": "highest_valid_tariff",
                    "winner": selected["type"],
                    "winning_tariff": selected["data"]["tariff"],
                    "runner_up_tariff": other["data"]["tariff"]
                }
                
                medicine_instructions = {
                    "procedure_medicines": "APPROVED" if selected["type"] == "procedure" else "REJECTED",
                    "diagnosis_medicines": "APPROVED" if selected["type"] == "diagnosis" else "REJECTED",
                    "approved_path": selected["type"],
                    "note": "Both G-DRGs valid - highest tariff selected, other path medicines rejected"
                }
                
                return ValidationOutcome(
                    result=ValidationResult.APPROVED,
                    reason=f"APPROVED: {selected['type'].title()} G-DRG selected - higher tariff ({selected['data']['tariff']} GHS)",
                    financial_impact=financial_impact,
                    selection_logic=selection_logic,
                    details={
                        "encounter_id": encounter_id,
                        "selected_gdrg": selected["data"]["gdrg"],
                        "selected_tariff": selected["data"]["tariff"],
                        "tariff_comparison": tariff_comparison,
                        "medicine_instructions": medicine_instructions,
                        "gdrg_summary": {
                            "selected_gdrg": selected["data"]["gdrg"],
                            "path_used": selected["type"],
                            "tariff_amount": selected["data"]["tariff"],
                            "tariff_currency": "GHS"
                        }
                    }
                )
            
        except Exception as e:
            logger.error(f"Error in dual evaluation: {e}")
            return ValidationOutcome(
                result=ValidationResult.PENDING,
                reason=f"PEND: Evaluation error - {str(e)}",
                details={"error": str(e)}
            )
    
    async def _evaluate_single_gdrg(self, claim_data: Dict, icd10_code: str, gdrg_type: str, 
                                   encounter_type: str, patient_age: int, provider_name: str, 
                                   facility_level: str) -> Optional[Dict]:
        try:
            if gdrg_type == "procedure":
                gdrg_code = claim_data.get('gdrg_code_procedure')
                
                if not gdrg_code:
                    return {"valid": False, "gdrg": None, "rejections": ["No procedure G-DRG in claim"], "tariff": 0}
                
                logger.info(f"  Validating procedure: G-DRG={gdrg_code}, ICD-10={icd10_code}, Encounter={encounter_type}")
                
                query = """
                SELECT gdrg_code, gdrg_description, gender_restriction, age_restrictions
                FROM clinical_procedure_inferences 
                WHERE gdrg_code = $1 AND icd10_code = $2 AND encounter_type = $3
                LIMIT 1
                """
                result = await self.queries.db.fetch_one(query, gdrg_code, icd10_code, encounter_type)
                
                if not result:
                    mismatch_query = """
                    SELECT encounter_type 
                    FROM clinical_procedure_inferences 
                    WHERE gdrg_code = $1 AND icd10_code = $2
                    LIMIT 1
                    """
                    mismatch_check = await self.queries.db.fetch_one(mismatch_query, gdrg_code, icd10_code)
                    
                    if mismatch_check:
                        expected_encounter = mismatch_check['encounter_type']
                        rejection_reason = f"Misapplication of tariffs: G-DRG {gdrg_code} requires {expected_encounter} encounter, claim coded as {encounter_type}"
                        logger.warning(f"  ENCOUNTER TYPE MISMATCH: Expected {expected_encounter}, got {encounter_type}")
                    else:
                        rejection_reason = "Procedure G-DRG not in clinical inferences"
                    
                    logger.warning(f"  Procedure G-DRG {gdrg_code} not validated for ICD-10 {icd10_code}")
                    return {"valid": False, "gdrg": gdrg_code, "rejections": [rejection_reason], "tariff": 0}
            
            else:
                gdrg_code = claim_data.get('gdrg_code')
                
                if not gdrg_code:
                    return {"valid": False, "gdrg": None, "rejections": ["No diagnosis G-DRG in claim"], "tariff": 0}
                
                logger.info(f"  Validating diagnosis: G-DRG={gdrg_code}, ICD-10={icd10_code}, Encounter={encounter_type}")
                
                query = """
                SELECT gdrg_code, gdrg_description, gender_restriction, age_restrictions
                FROM clinical_diagnosis_inferences 
                WHERE gdrg_code = $1 AND icd10_code = $2 AND encounter_type = $3
                LIMIT 1
                """
                result = await self.queries.db.fetch_one(query, gdrg_code, icd10_code, encounter_type)
                
                if not result:
                    mismatch_query = """
                    SELECT encounter_type 
                    FROM clinical_diagnosis_inferences 
                    WHERE gdrg_code = $1 AND icd10_code = $2
                    LIMIT 1
                    """
                    mismatch_check = await self.queries.db.fetch_one(mismatch_query, gdrg_code, icd10_code)
                    
                    if mismatch_check:
                        expected_encounter = mismatch_check['encounter_type']
                        rejection_reason = f"Misapplication of tariffs: G-DRG {gdrg_code} requires {expected_encounter} encounter, claim coded as {encounter_type}"
                        logger.warning(f"  ENCOUNTER TYPE MISMATCH: Expected {expected_encounter}, got {encounter_type}")
                    else:
                        rejection_reason = "Diagnosis G-DRG not in clinical inferences"
                    
                    logger.warning(f"  Diagnosis G-DRG {gdrg_code} not validated for ICD-10 {icd10_code}")
                    return {"valid": False, "gdrg": gdrg_code, "rejections": [rejection_reason], "tariff": 0}
            
            inference_data = dict(result)
            
            age_split_gdrg = await self._apply_age_split(claim_data, gdrg_code)
            
            validation = await self._validate_individual_gdrg(claim_data, age_split_gdrg, gdrg_type, icd10_code, inference_data)
            
            if not validation["valid"]:
                return {
                    "valid": False,
                    "gdrg": age_split_gdrg,
                    "rejections": validation["rejections"],
                    "tariff": 0
                }
            
            tariff_info = await self._lookup_tariff(provider_name, facility_level, age_split_gdrg, encounter_type)
            
            if not tariff_info:
                return {"valid": False, "gdrg": age_split_gdrg, "rejections": ["No tariff found"], "tariff": 0}
            
            return {
                "valid": True,
                "gdrg": age_split_gdrg,
                "tariff": tariff_info['amount'],
                "tariff_info": tariff_info,
                "rejections": []
            }
            
        except Exception as e:
            logger.error(f"Error evaluating {gdrg_type} G-DRG: {e}")
            return {"valid": False, "gdrg": None, "rejections": [str(e)], "tariff": 0}
    
    async def _validate_individual_gdrg(self, claim_data: Dict, gdrg_code: str, gdrg_type: str, icd10_code: str, inference_data: Dict) -> Dict:
        try:
            patient_age = claim_data.get('calculated_age', 0)
            patient_gender = claim_data.get('gender', '').upper()
            primary_icd10 = claim_data.get('icd10_code', '')
            
            rejections = []
            
            age_check = await self._validate_gdrg_age_appropriateness_from_inference(gdrg_code, patient_age, primary_icd10, inference_data)
            if not age_check["valid"]:
                rejections.append(f"Age: {age_check['reason']}")
            
            gender_check = await self._validate_gdrg_gender_appropriateness_from_inference(claim_data, gdrg_code, gdrg_type, icd10_code, inference_data)
            if not gender_check["valid"]:
                rejections.append(f"Gender: {gender_check['reason']}")
            
            clinical_check = await self._validate_gdrg_clinical_appropriateness(gdrg_code, primary_icd10, claim_data)
            if not clinical_check["valid"]:
                rejections.append(f"Clinical: {clinical_check['reason']}")
            
            is_valid = len(rejections) == 0
            
            if is_valid:
                logger.info(f"  ✓ G-DRG {gdrg_code} ({gdrg_type}): ALL VALIDATIONS PASSED")
            else:
                logger.warning(f"  ✗ G-DRG {gdrg_code} ({gdrg_type}): VALIDATION FAILED")
                for rejection in rejections:
                    logger.warning(f"    - {rejection}")
            
            return {"valid": is_valid, "rejections": rejections}
            
        except Exception as e:
            logger.error(f"Error validating G-DRG {gdrg_code}: {e}")
            return {"valid": False, "rejections": [f"Validation error: {str(e)}"]}
    
    async def _validate_gdrg_age_appropriateness_from_inference(self, gdrg_code: str, patient_age: int, icd10_code: str, inference_data: Dict) -> Dict:
        try:
            age_restrictions = inference_data.get('age_restrictions')
            
            if age_restrictions:
                if isinstance(age_restrictions, str):
                    try:
                        age_restrictions = json.loads(age_restrictions)
                    except:
                        pass
                
                if isinstance(age_restrictions, dict):
                    min_age = age_restrictions.get('min_age')
                    max_age = age_restrictions.get('max_age')
                    
                    if min_age is not None and patient_age < min_age:
                        return {"valid": False, "reason": f"Patient age {patient_age} below minimum {min_age}"}
                    
                    if max_age is not None and patient_age > max_age:
                        return {"valid": False, "reason": f"Patient age {patient_age} above maximum {max_age}"}
            
            if gdrg_code.endswith('C'):
                if patient_age >= 12:
                    is_cancer = any(icd10_code.startswith(code) for code in self.cancer_icd10_codes)
                    if is_cancer and patient_age < 19:
                        return {"valid": True, "reason": "Childhood cancer exception"}
                    else:
                        return {"valid": False, "reason": f"Pediatric G-DRG inappropriate for age {patient_age}"}
            
            elif gdrg_code.endswith('A'):
                if patient_age < 12:
                    return {"valid": False, "reason": f"Adult G-DRG inappropriate for age {patient_age}"}
            
            return {"valid": True, "reason": "Age appropriate"}
            
        except Exception as e:
            return {"valid": True, "reason": f"Age validation error: {str(e)}"}
    
    async def _validate_gdrg_gender_appropriateness_from_inference(self, claim_data: Dict, gdrg_code: str, gdrg_type: str, icd10_code: str, inference_data: Dict) -> Dict:
        try:
            patient_gender = claim_data.get('gender', '').upper()
            
            gender_restriction = inference_data.get('gender_restriction')
            
            if gender_restriction:
                gender_list = []
                
                if isinstance(gender_restriction, str):
                    cleaned = gender_restriction.strip().strip('[]{}').replace('"', '').replace("'", "")
                    gender_list = [g.strip().upper() for g in cleaned.split() if g.strip()]
                
                elif isinstance(gender_restriction, list):
                    gender_list = [str(g).strip().upper() for g in gender_restriction]
                
                else:
                    gender_list = [str(gender_restriction).strip().upper()]
                
                logger.info(f"    DEBUG: Gender restriction parsed as: {gender_list}")
                
                if patient_gender not in gender_list:
                    logger.warning(f"    INFERENCE GENDER MISMATCH: {patient_gender} not in {gender_list} for G-DRG {gdrg_code}")
                    return {"valid": False, "reason": f"{patient_gender} not in allowed genders {gender_list}"}
            
            base_gdrg = gdrg_code.rstrip('AC')
            
            for female_pattern in self.female_only_gdrg_patterns:
                if female_pattern in base_gdrg:
                    if patient_gender not in ['F', 'FEMALE']:
                        logger.warning(f"    GENDER MISMATCH: G-DRG {base_gdrg} is female-only, patient is {patient_gender}")
                        return {"valid": False, "reason": f"Female-only G-DRG for {patient_gender} patient"}
            
            for male_pattern in self.male_only_gdrg_patterns:
                if male_pattern in base_gdrg:
                    if patient_gender not in ['M', 'MALE']:
                        logger.warning(f"    GENDER MISMATCH: G-DRG {base_gdrg} is male-only, patient is {patient_gender}")
                        return {"valid": False, "reason": f"Male-only G-DRG for {patient_gender} patient"}
            
            for female_prefix in self.female_only_icd10_prefixes:
                if icd10_code.startswith(female_prefix):
                    if patient_gender not in ['F', 'FEMALE']:
                        logger.warning(f"    GENDER MISMATCH: ICD-10 {icd10_code} is female-only, patient is {patient_gender}")
                        return {"valid": False, "reason": f"Female-only diagnosis {icd10_code} for {patient_gender} patient"}
            
            for male_prefix in self.male_only_icd10_prefixes:
                if icd10_code.startswith(male_prefix):
                    if patient_gender not in ['M', 'MALE']:
                        logger.warning(f"    GENDER MISMATCH: ICD-10 {icd10_code} is male-only, patient is {patient_gender}")
                        return {"valid": False, "reason": f"Male-only diagnosis {icd10_code} for {patient_gender} patient"}
            
            return {"valid": True, "reason": "Gender appropriate"}
            
        except Exception as e:
            logger.error(f"Error in gender validation: {e}")
            return {"valid": True, "reason": f"Gender validation error: {str(e)}"}
    
    async def _validate_gdrg_clinical_appropriateness(self, gdrg_code: str, primary_icd10: str, claim_data: Dict) -> Dict:
        try:
            contraindicated = {
                'CARDI': {'inappropriate_with': ['Z51'], 'reason': 'Cardiac G-DRG inappropriate for aftercare'},
                'SURG': {'inappropriate_with': ['Z00', 'Z01'], 'reason': 'Surgical G-DRG inappropriate for examination'}
            }
            
            base_gdrg = gdrg_code.rstrip('AC')
            
            for pattern, rules in contraindicated.items():
                if pattern in base_gdrg:
                    for inappropriate_icd10 in rules['inappropriate_with']:
                        if primary_icd10.startswith(inappropriate_icd10):
                            return {"valid": False, "reason": f"{rules['reason']} (ICD-10: {primary_icd10})"}
            
            return {"valid": True, "reason": "Clinically appropriate"}
            
        except Exception as e:
            return {"valid": True, "reason": f"Clinical validation error: {str(e)}"}
    
    async def _apply_age_split(self, claim_data: Dict, base_gdrg: str) -> str:
        patient_age = claim_data.get('calculated_age', 0)
        icd10_code = claim_data.get('icd10_code', '')
        
        is_cancer = any(icd10_code.startswith(code) for code in self.cancer_icd10_codes)
        
        base_gdrg_clean = base_gdrg.rstrip('AC')
        
        if is_cancer and patient_age < 19:
            suffix = 'C'
            logger.info(f"  Age split: Childhood cancer exception applied (age {patient_age}) → {base_gdrg_clean}C")
        elif patient_age < 12:
            suffix = 'C'
            logger.info(f"  Age split: Pediatric (age {patient_age}) → {base_gdrg_clean}C")
        else:
            suffix = 'A'
            logger.info(f"  Age split: Adult (age {patient_age}) → {base_gdrg_clean}A")
        
        return f"{base_gdrg_clean}{suffix}"
    
    async def _lookup_tariff(self, provider_name: str, facility_level: str, gdrg_code: str, encounter_type: str) -> Optional[Dict]:
        try:
            base_gdrg = gdrg_code.rstrip('AC')
            
            query = """
            SELECT tariff, gdrg_name
            FROM icd10_codes 
            WHERE gdrg_code = $1 AND tariff IS NOT NULL
            LIMIT 1
            """
            
            result = await self.queries.db.fetch_one(query, gdrg_code)
            if not result:
                result = await self.queries.db.fetch_one(query, base_gdrg)
            
            if not result or not result.get('tariff'):
                logger.warning(f"  No tariff found for G-DRG {gdrg_code}")
                return None
            
            amount = float(result['tariff'])
            logger.info(f"  Found tariff for {gdrg_code}: {amount} GHS")
            
            return {
                'gdrg_code': gdrg_code,
                'amount': round(amount, 2),
                'currency': 'GHS',
                'description': result.get('gdrg_name')
            }
            
        except Exception as e:
            logger.error(f"Error looking up tariff: {e}")
            return None
    
    async def validate_multiple_claims(self, encounter_ids: List[str]) -> Dict[str, ValidationOutcome]:
        results = {}
        
        for encounter_id in encounter_ids:
            try:
                result = await self.process_step5_gdrg_determination(encounter_id)
                results[encounter_id] = result
                logger.info(f"{encounter_id}: {result.reason}")
            except Exception as e:
                logger.error(f"Error validating {encounter_id}: {e}")
                results[encounter_id] = ValidationOutcome(
                    result=ValidationResult.PENDING,
                    reason=f"PEND: Error - {str(e)}",
                    details={"encounter_id": encounter_id}
                )
        
        return results


if __name__ == "__main__":
    async def main():
        validator = EnhancedGDRGDeterminationStep5()
        
        try:
            await validator.initialize()
            
            test_encounter = "NSA-2121-DGQY"
            
            print(f"\nTesting Step 5 for: {test_encounter}")
            
            result = await validator.process_step5_gdrg_determination(test_encounter)
            
            print(f"Result: {result.result.value}")
            print(f"Reason: {result.reason}")
            
            if result.details:
                print(f"\nDetails:")
                if result.details.get('tariff_comparison'):
                    print(f"  Tariff Comparison: {result.details['tariff_comparison']}")
                if result.details.get('medicine_instructions'):
                    print(f"  Medicine Instructions: {result.details['medicine_instructions']}")
            
        except Exception as e:
            logger.error(f"Test failed: {e}")
        
        finally:
            await validator.close()
    
    asyncio.run(main())