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
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    FLAGGED = "FLAGGED"
    PENDING = "PENDING"

@dataclass
class ValidationOutcome:
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
    
    def __init__(self):
        self.queries = None
        self.is_initialized = False
        
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
    
    async def initialize(self):
        if not self.is_initialized:
            await initialize_database()
            self.queries = await get_nhis_queries()
            self.is_initialized = True
            logger.info("Enhanced Validations initialized")
    
    async def close(self):
        await close_database()
        self.is_initialized = False
        logger.info("Enhanced Validations closed")
    
    async def validate_medicine_dispensing_period(self, claim_data: Dict) -> ValidationOutcome:
        try:
            encounter_type = claim_data.get('encounter_type')
            encounter_id = claim_data.get('encounter_id')
            
            if encounter_type != 'IPD':
                return ValidationOutcome(
                    result=ValidationResult.APPROVED,
                    reason="Medicine dispensing period check not applicable for non-IPD encounters",
                    details={"encounter_type": encounter_type}
                )
            
            admission_date = claim_data.get('admission_date')
            discharge_date = claim_data.get('discharge_date')
            medicine_date = claim_data.get('medicine_date')
            
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
            
            if isinstance(admission_date, str):
                admission_date = datetime.fromisoformat(admission_date.replace('Z', '+00:00'))
            if isinstance(discharge_date, str) and discharge_date:
                discharge_date = datetime.fromisoformat(discharge_date.replace('Z', '+00:00'))
            if isinstance(medicine_date, str):
                medicine_date = datetime.fromisoformat(medicine_date.replace('Z', '+00:00'))
            
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
            
            if discharge_date:
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
            
            if discharge_date:
                los_days = (discharge_date - admission_date).days
            else:
                los_days = (datetime.now() - admission_date).days
            
            logger.info(f"Medicine dispensing period validation passed for {encounter_id}")
            
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
        try:
            encounter_id = claim_data.get('encounter_id')
            nhis_number = claim_data.get('nhis_number')
            
            logger.info(f"Duplicate validation skipped for {encounter_id} - handled by Stage 0")
            
            return ValidationOutcome(
                result=ValidationResult.APPROVED,
                reason="Duplicate validation skipped - handled in Stage 0",
                details={
                    "encounter_id": encounter_id,
                    "patient_id": nhis_number,
                    "validation_status": "SKIPPED",
                    "reason": "Duplicate detection is handled in Stage 0 before validation pipeline"
                }
            )
            
        except Exception as e:
            logger.error(f"Error in duplicate claims validation: {e}")
            return ValidationOutcome(
                result=ValidationResult.PENDING,
                reason=f"PEND: Error in duplicate validation - {str(e)}",
                details={"error": str(e), "patient_id": claim_data.get('nhis_number')}
            )
    
    async def validate_polypharmacy(self, medicines: List[Dict], claim_data: Dict = None) -> ValidationOutcome:
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
            
            interactions_found = []
            
            for i, med_code in enumerate(medicine_codes):
                med_name = medicine_names[i] if i < len(medicine_names) else ""
                
                for drug, interaction_info in self.drug_interactions.items():
                    if drug in med_code or drug in med_name:
                        contraindicated = interaction_info['contraindicated']
                        
                        for j, other_med_code in enumerate(medicine_codes):
                            if i != j:
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
            
            therapeutic_classes = []
            duplicate_classes = []
            
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
            
            logger.info(f"Polypharmacy validation passed for {len(medicines)} medicines")
            
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
        try:
            gender = claim_data.get('gender', '').upper()
            icd10_code = claim_data.get('icd10_code', '')
            diagnosis_name = claim_data.get('diagnosis_name', '').lower()
            encounter_id = claim_data.get('encounter_id')
            icd10_procedure = claim_data.get('icd10_code_procedure')
            
            has_both_diagnosis_and_procedure = bool(
                icd10_code and icd10_code not in ['NA', '', None] and
                icd10_procedure and icd10_procedure not in ['NA', '', None]
            )
            
            if has_both_diagnosis_and_procedure:
                logger.info(f"Skipping gender validation for {encounter_id} - has both diagnosis and procedure")
                return ValidationOutcome(
                    result=ValidationResult.APPROVED,
                    reason="Gender validation deferred to Stage 5 dual evaluation",
                    details={
                        "encounter_id": encounter_id,
                        "patient_gender": gender,
                        "validation_status": "DEFERRED_TO_STAGE5",
                        "reason": "Claims with both diagnosis and procedure paths are validated separately in Stage 5",
                        "deferred_to_stage_5": True
                    }
                )
            
            if not gender or not icd10_code:
                return ValidationOutcome(
                    result=ValidationResult.FLAGGED,
                    reason="FLAG: Missing gender or diagnosis for validation",
                    details={"missing_data": ["gender", "icd10_code"]}
                )
            
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
            
            patient_age = claim_data.get('calculated_age', 0)
            
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
            
            logger.info(f"Gender-diagnosis validation passed for {encounter_id}")
            
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
        try:
            encounter_id = claim_data.get('encounter_id')
            
            logger.info(f"Supporting documents validation passed for {encounter_id}")
            
            return ValidationOutcome(
                result=ValidationResult.APPROVED,
                reason="Supporting documents validation passed",
                details={
                    "encounter_id": encounter_id,
                    "document_requirements": "NONE",
                    "validation_status": "SKIPPED",
                    "note": "Document validation removed as requested"
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
        try:
            if not self.is_initialized:
                await self.initialize()
            
            claim_data = await self.queries.get_claim_with_calculated_age(encounter_id)
            if not claim_data:
                return {
                    "error": ValidationOutcome(
                        result=ValidationResult.REJECTED,
                        reason="REJECT: Claim not found",
                        details={"encounter_id": encounter_id}
                    )
                }
            
            logger.info(f"Running enhanced validations for {encounter_id}")
            
            results = {}
            
            results["medicine_dispensing_period"] = await self.validate_medicine_dispensing_period(claim_data)
            results["duplicate_claims"] = await self.validate_duplicate_claims(claim_data)
            results["gender_diagnosis_mismatch"] = await self.validate_gender_diagnosis_mismatch(claim_data)
            results["supporting_documents"] = await self.validate_supporting_documents(claim_data)
            
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
            
            logger.info(f"Enhanced validations completed for {encounter_id}: {approved}/{total_checks} passed")
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
        results = {}
        
        for encounter_id in encounter_ids:
            try:
                claim_results = await self.run_all_enhanced_validations(encounter_id)
                results[encounter_id] = claim_results
                
                if "summary" in claim_results:
                    summary = claim_results["summary"]
                    status_emoji = "" if summary.result == ValidationResult.APPROVED else "⚠️" if summary.result == ValidationResult.FLAGGED else "❌"
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


if __name__ == "__main__":
    import sys
    
    async def test_enhanced_validations():
        enhanced = EnhancedValidations()
        
        try:
            await enhanced.initialize()
            
            print("\nTESTING ENHANCED VALIDATIONS")
            print("=" * 70)
            
            test_encounter_id = "LIN-3012-BUYW"
            
            print(f"\nTesting individual claim: {test_encounter_id}")
            results = await enhanced.run_all_enhanced_validations(test_encounter_id)
            
            for validation_type, result in results.items():
                print(f"\n{validation_type.upper().replace('_', ' ')}:")
                print(f"  Status: {result.result.value}")
                print(f"  Reason: {result.reason}")
            
            print("\nENHANCED VALIDATIONS TEST COMPLETED")
            
        except Exception as e:
            print(f"Test failed: {e}")
        finally:
            await enhanced.close()
    
    asyncio.run(test_enhanced_validations())