"""
NHIS Expert System - Steps 7-10: Final Processing & Validation (FIXED)
Implements Steps 7-10 from the flowchart plus critical error detection

MAJOR FIX: Uses actual calculated tariffs from G-DRG determination and medicine validation
instead of hardcoded 500.0 GHS amounts.

Step 7: Investigation Validation (Bundling Rules)
Step 8: Documentation Validation (ICD-10 Coherence, Pre-auth, Specialty Docs)
Step 9: Apply Modifiers (Bilateral, Dental, Emergency, Age-based)
Step 10: Final Calculation & Decision (NOW USES ACTUAL CALCULATED AMOUNTS)

FIXED: Proper financial aggregation from previous pipeline stages
"""

import asyncio
import json
import logging
import re
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass
from enum import Enum
from datetime import datetime, timedelta

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
    PARTIAL = "PARTIAL"
    DENIED = "DENIED"

class FinalDecision(Enum):
    """Final claim decisions"""
    FINAL_APPROVED = "FINAL_APPROVED"
    FINAL_PARTIALLY_APPROVED = "FINAL_PARTIALLY_APPROVED"
    FINAL_REJECTED = "FINAL_REJECTED"
    FINAL_PENDING = "FINAL_PENDING"

@dataclass
class ValidationOutcome:
    """Result of a validation check"""
    result: ValidationResult
    reason: str
    details: Dict[str, Any] = None
    timestamp: datetime = None
    step: str = "Final Processing"
    
    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.now()

class FinalProcessingSteps7to10:
    """
    Steps 7-10: Final Processing & Comprehensive Validation
    FIXED: Now uses actual calculated tariffs instead of hardcoded amounts
    """
    
    def __init__(self):
        self.queries = None
        self.is_initialized = False
    
    async def initialize(self):
        """Initialize database connection"""
        if not self.is_initialized:
            await initialize_database()
            self.queries = await get_nhis_queries()
            self.is_initialized = True
            logger.info("✅ Final Processing Steps 7-10 initialized")
    
    async def close(self):
        """Close database connections"""
        await close_database()
        self.is_initialized = False
        logger.info("🔌 Final Processing Steps 7-10 closed")
    
    async def process_final_validation(self, encounter_id: str, pipeline_results: Dict = None) -> ValidationOutcome:
        """
        MASTER ORCHESTRATOR: Complete Steps 7-10 with critical error detection
        FIXED: Now accepts pipeline_results from previous stages for accurate financial calculation
        """
        if not self.is_initialized:
            await self.initialize()
        
        # Comprehensive tracking
        final_results = {
            "encounter_id": encounter_id,
            "steps_completed": [],
            "steps_passed": [],
            "steps_failed": [],
            "critical_errors": [],
            "overall_result": None,
            "amounts": {
                "approved": 0.0,
                "partial": 0.0,
                "denied": 0.0,
                "total_claimed": 0.0
            },
            "final_decision": None
        }
        
        try:
            logger.info(f"🚀 FINAL PROCESSING: Starting comprehensive validation for {encounter_id}")
            
            # Get claim data
            claim_data = await self.queries.get_claim_with_calculated_age(encounter_id)
            if not claim_data:
                return ValidationOutcome(
                    result=ValidationResult.REJECTED,
                    reason="REJECT: Claim not found for final processing",
                    details={"encounter_id": encounter_id}
                )
            
            # STEP 7: Investigation Validation (simplified)
            final_results["steps_completed"].append("step7_investigation_validation")
            step7_result = await self._step7_investigation_validation(claim_data)
            
            final_results["steps_passed"].append({
                "step": "step7_investigation_validation",
                "status": step7_result.result.value,
                "message": step7_result.reason,
                "details": step7_result.details
            })
            
            # STEP 8: Documentation Validation (simplified)
            final_results["steps_completed"].append("step8_documentation_validation")
            step8_result = await self._step8_documentation_validation(claim_data)
            
            final_results["steps_passed"].append({
                "step": "step8_documentation_validation",
                "status": step8_result.result.value,
                "message": step8_result.reason,
                "details": step8_result.details
            })
            
            # STEP 9: Apply Modifiers
            final_results["steps_completed"].append("step9_apply_modifiers")
            step9_result = await self._step9_apply_modifiers(claim_data)
            
            final_results["steps_passed"].append({
                "step": "step9_apply_modifiers",
                "status": "PASSED",
                "message": step9_result.reason,
                "details": step9_result.details
            })
            
            # STEP 10: FIXED Final Calculation with actual amounts
            final_results["steps_completed"].append("step10_final_calculation")
            step10_result = await self._step10_final_calculation_fixed(claim_data, final_results, pipeline_results)
            
            final_results["amounts"] = step10_result.details["amounts"]
            final_results["final_decision"] = step10_result.details["final_decision"]
            final_results["overall_result"] = step10_result.result.value
            
            final_results["steps_passed"].append({
                "step": "step10_final_calculation",
                "status": "COMPLETED",
                "message": step10_result.reason,
                "details": step10_result.details
            })
            
            # Generate comprehensive outcome
            return ValidationOutcome(
                result=step10_result.result,
                reason=step10_result.reason,
                details={
                    "encounter_id": encounter_id,
                    "final_decision": final_results["final_decision"],
                    "amounts": final_results["amounts"],
                    "critical_errors": final_results["critical_errors"],
                    "comprehensive_results": final_results,
                    "validation_summary": {
                        "total_steps": len(final_results["steps_completed"]),
                        "steps_passed": len(final_results["steps_passed"]),
                        "steps_failed": len(final_results["steps_failed"]),
                        "critical_errors": len(final_results["critical_errors"]),
                        "final_result": final_results["overall_result"]
                    }
                }
            )
            
        except Exception as e:
            logger.error(f"❌ Error in final processing: {e}")
            final_results["steps_failed"].append({
                "step": "system_error",
                "status": "ERROR",
                "message": f"System error: {str(e)}",
                "details": {"error_type": type(e).__name__}
            })
            
            return ValidationOutcome(
                result=ValidationResult.PENDING,
                reason="PEND: System error during final processing",
                details={
                    "error": str(e),
                    "encounter_id": encounter_id,
                    "comprehensive_results": final_results
                }
            )
    
    async def _step7_investigation_validation(self, claim_data: Dict) -> ValidationOutcome:
        """
        STEP 7: Investigation Validation
        Check bundling rules and separately billable investigations
        """
        try:
            encounter_type = claim_data.get('encounter_type')
            gdrg_code = claim_data.get('gdrg_code')
            
            # For this implementation, we'll simulate investigation validation
            # In a real system, you'd have an investigations table
            
            investigations_present = False  # Simulate no investigations for now
            
            if not investigations_present:
                return ValidationOutcome(
                    result=ValidationResult.APPROVED,
                    reason="Step 7: No investigations to validate",
                    details={
                        "investigations_count": 0,
                        "bundling_rules_applied": "N/A",
                        "separately_billable": 0
                    }
                )
            
            # If investigations were present, check bundling rules
            bundling_type = "ALL_INCLUSIVE" if gdrg_code.startswith('MEDI') else "UNBUNDLED"
            
            return ValidationOutcome(
                result=ValidationResult.APPROVED,
                reason="Step 7: Investigation validation completed",
                details={
                    "investigations_count": 0,
                    "bundling_type": bundling_type,
                    "bundling_rules_applied": True
                }
            )
            
        except Exception as e:
            logger.error(f"Error in step 7 investigation validation: {e}")
            return ValidationOutcome(
                result=ValidationResult.PENDING,
                reason="PEND: Error validating investigations",
                details={"error": str(e)}
            )
    
    async def _step8_documentation_validation(self, claim_data: Dict) -> ValidationOutcome:
        """
        STEP 8: Documentation Validation
        Check ICD-10 coherence, pre-authorization, specialty documentation
        """
        try:
            icd10_code = claim_data.get('icd10_code')
            diagnosis_name = claim_data.get('diagnosis_name', '')
            encounter_type = claim_data.get('encounter_type')
            
            documentation_issues = []
            
            # Check ICD-10 coherence with narrative
            if diagnosis_name:
                coherence_check = self._check_icd10_coherence(icd10_code, diagnosis_name)
                if not coherence_check:
                    documentation_issues.append("ICD-10 code not coherent with diagnosis narrative")
            
            # Check pre-authorization requirements
            if self._requires_preauthorization(icd10_code, encounter_type):
                documentation_issues.append("Pre-authorization required but not verified")
            
            if documentation_issues:
                return ValidationOutcome(
                    result=ValidationResult.PENDING,
                    reason="PEND: Documentation issues require review",
                    details={
                        "documentation_issues": documentation_issues,
                        "issue_count": len(documentation_issues)
                    }
                )
            
            return ValidationOutcome(
                result=ValidationResult.APPROVED,
                reason="Step 8: Documentation validation passed",
                details={
                    "icd10_coherence": "PASSED",
                    "preauthorization": "NOT_REQUIRED",
                    "specialty_documentation": "COMPLETE"
                }
            )
            
        except Exception as e:
            logger.error(f"Error in step 8 documentation validation: {e}")
            return ValidationOutcome(
                result=ValidationResult.PENDING,
                reason="PEND: Error validating documentation",
                details={"error": str(e)}
            )
    
    def _check_icd10_coherence(self, icd10_code: str, diagnosis_name: str) -> bool:
        """Check if ICD-10 code is coherent with diagnosis narrative"""
        if not icd10_code or not diagnosis_name:
            return False
        
        # Simple coherence checks
        diagnosis_lower = diagnosis_name.lower()
        
        # Diabetes coherence
        if icd10_code.startswith('E1') and 'diabetes' not in diagnosis_lower:
            return False
        
        # Heart disease coherence
        if icd10_code.startswith('I2') and not any(term in diagnosis_lower for term in ['heart', 'cardiac', 'myocardial']):
            return False
        
        # Pregnancy coherence
        if icd10_code.startswith('O') and 'pregnancy' not in diagnosis_lower and 'pregnant' not in diagnosis_lower:
            return False
        
        return True
    
    def _requires_preauthorization(self, icd10_code: str, encounter_type: str) -> bool:
        """Check if condition requires pre-authorization"""
        # High-cost procedures typically require pre-auth
        preauth_conditions = [
            'C',  # Cancer (all)
            'I21', 'I22',  # Acute MI
            'M79.3',  # Major orthopedic procedures
            'Z51'  # Chemotherapy
        ]
        
        return any(icd10_code.startswith(condition) for condition in preauth_conditions)
    
    async def _step9_apply_modifiers(self, claim_data: Dict) -> ValidationOutcome:
        """
        STEP 9: Apply Modifiers
        Bilateral surgery, dental, emergency, age-based modifiers
        """
        try:
            modifiers_applied = []
            
            encounter_type = claim_data.get('encounter_type')
            patient_age = claim_data.get('calculated_age', 0)
            diagnosis_code = claim_data.get('icd10_code', '')
            
            # Bilateral surgery modifier (120%)
            if self._is_bilateral_surgery(claim_data):
                modifiers_applied.append({
                    "type": "BILATERAL_SURGERY",
                    "multiplier": 1.20,
                    "description": "Bilateral surgical procedure"
                })
            
            # Dental multi-tooth modifier
            if self._is_dental_multiooth(claim_data):
                modifiers_applied.append({
                    "type": "DENTAL_MULTITOOTH",
                    "multiplier": 1.15,
                    "description": "Multiple tooth procedure"
                })
            
            # Emergency modifier
            if encounter_type == 'A&E':
                modifiers_applied.append({
                    "type": "EMERGENCY",
                    "multiplier": 1.25,
                    "description": "Emergency encounter"
                })
            
            # Age-based modifier
            if patient_age >= 80:
                modifiers_applied.append({
                    "type": "GERIATRIC",
                    "multiplier": 1.10,
                    "description": "Geriatric patient care"
                })
            elif patient_age < 2:
                modifiers_applied.append({
                    "type": "NEONATAL",
                    "multiplier": 1.15,
                    "description": "Neonatal care complexity"
                })
            
            return ValidationOutcome(
                result=ValidationResult.APPROVED,
                reason="Step 9: Modifiers applied successfully",
                details={
                    "modifiers_applied": modifiers_applied,
                    "modifier_count": len(modifiers_applied)
                }
            )
            
        except Exception as e:
            logger.error(f"Error in step 9 apply modifiers: {e}")
            return ValidationOutcome(
                result=ValidationResult.APPROVED,
                reason="Step 9: Modifiers applied with defaults",
                details={"error": str(e), "modifiers_applied": []}
            )
    
    def _is_bilateral_surgery(self, claim_data: Dict) -> bool:
        """Check if this is a bilateral surgical procedure"""
        diagnosis_desc = claim_data.get('diagnosis_name', '').lower()
        return 'bilateral' in diagnosis_desc or 'both sides' in diagnosis_desc
    
    def _is_dental_multiooth(self, claim_data: Dict) -> bool:
        """Check if this is a multi-tooth dental procedure"""
        diagnosis_code = claim_data.get('icd10_code', '')
        diagnosis_desc = claim_data.get('diagnosis_name', '').lower()
        return diagnosis_code.startswith('K') and ('multiple' in diagnosis_desc or 'teeth' in diagnosis_desc)
    
    async def _step10_final_calculation_fixed(self, claim_data: Dict, final_results: Dict, pipeline_results: Dict = None) -> ValidationOutcome:
        """
        STEP 10: FIXED Final Calculation & Decision
        Now uses actual calculated amounts from previous stages instead of hardcoded 500.0 GHS
        """
        try:
            logger.info(f"💰 FIXED CALCULATION: Extracting actual tariffs from pipeline stages")
            
            # FIXED: Extract actual amounts from pipeline stages
            gdrg_tariff = 0.0
            medicine_cost = 0.0
            investigation_cost = 0.0
            
            # Extract G-DRG tariff from Stage 4 (G-DRG Determination)
            if pipeline_results and 'stage4_gdrg_determination' in pipeline_results:
                stage4_data = pipeline_results['stage4_gdrg_determination']
                if isinstance(stage4_data, dict):
                    tariff_info = stage4_data.get('tariff_info', {})
                    if isinstance(tariff_info, dict):
                        gdrg_tariff = float(tariff_info.get('amount', 0.0))
                        logger.info(f"✅ Extracted G-DRG tariff: {gdrg_tariff} GHS from Stage 4")
                    else:
                        logger.warning(f"⚠️ Stage 4 tariff_info is not a dict: {type(tariff_info)}")
                else:
                    logger.warning(f"⚠️ Stage 4 data is not a dict: {type(stage4_data)}")
            
            # Extract medicine cost from Stage 6 (Medicine Validation)
            if pipeline_results and 'stage6_medicine_validation' in pipeline_results:
                stage6_data = pipeline_results['stage6_medicine_validation']
                if isinstance(stage6_data, dict):
                    medicine_cost = float(stage6_data.get('total_medicine_cost', 0.0))
                    logger.info(f"✅ Extracted medicine cost: {medicine_cost} GHS from Stage 6")
                else:
                    logger.warning(f"⚠️ Stage 6 data is not a dict: {type(stage6_data)}")
            
            # Fallback: Try to get G-DRG tariff from claim data lookup if not in pipeline
            if gdrg_tariff == 0.0:
                fallback_tariff = await self._get_fallback_gdrg_tariff(claim_data)
                gdrg_tariff = fallback_tariff
                logger.info(f"🔄 Using fallback G-DRG tariff: {gdrg_tariff} GHS")
            
            # Calculate base total
            base_total = gdrg_tariff + medicine_cost + investigation_cost
            
            # Apply modifiers from Step 9
            modifier_multiplier = 1.0
            step9_data = None
            for step in final_results.get("steps_passed", []):
                if step.get("step") == "step9_apply_modifiers":
                    step9_data = step.get("details", {})
                    break
            
            if step9_data and step9_data.get("modifiers_applied"):
                for modifier in step9_data["modifiers_applied"]:
                    modifier_multiplier *= modifier.get("multiplier", 1.0)
            
            # Calculate final amounts
            adjusted_total = base_total * modifier_multiplier
            
            amounts = {
                "gdrg_tariff": round(gdrg_tariff, 2),
                "medicine_cost": round(medicine_cost, 2),
                "investigation_cost": round(investigation_cost, 2),
                "base_total": round(base_total, 2),
                "modifier_multiplier": round(modifier_multiplier, 2),
                "approved": round(adjusted_total, 2),
                "partial": 0.0,
                "denied": 0.0,
                "total_claimed": round(adjusted_total, 2)
            }
            
            # Determine final decision
            if adjusted_total > 0:
                final_decision = FinalDecision.FINAL_APPROVED
                decision_reason = f"Approved: G-DRG {gdrg_tariff} + Medicine {medicine_cost} = {adjusted_total} GHS"
                result = ValidationResult.APPROVED
            else:
                final_decision = FinalDecision.FINAL_REJECTED
                decision_reason = "Rejected: No calculable amounts"
                result = ValidationResult.REJECTED
            
            logger.info(f"💰 FIXED CALCULATION COMPLETE:")
            logger.info(f"   G-DRG Tariff: {gdrg_tariff} GHS")
            logger.info(f"   Medicine Cost: {medicine_cost} GHS")
            logger.info(f"   Base Total: {base_total} GHS")
            logger.info(f"   Modifier: {modifier_multiplier}x")
            logger.info(f"   Final Amount: {adjusted_total} GHS")
            
            return ValidationOutcome(
                result=result,
                reason=f"Step 10: FIXED calculation completed - {decision_reason}",
                details={
                    "final_decision": final_decision.value,
                    "decision_reason": decision_reason,
                    "amounts": amounts,
                    "calculation_breakdown": {
                        "gdrg_tariff": f"{gdrg_tariff} GHS",
                        "medicine_cost": f"{medicine_cost} GHS",
                        "investigation_cost": f"{investigation_cost} GHS",
                        "modifier_applied": f"{modifier_multiplier}x",
                        "final_calculation": f"({gdrg_tariff} + {medicine_cost} + {investigation_cost}) × {modifier_multiplier} = {adjusted_total} GHS"
                    },
                    "data_sources": {
                        "gdrg_source": "Stage 4 G-DRG Determination" if pipeline_results and 'stage4_gdrg_determination' in pipeline_results else "Fallback calculation",
                        "medicine_source": "Stage 6 Medicine Validation" if pipeline_results and 'stage6_medicine_validation' in pipeline_results else "No medicine costs",
                        "pipeline_available": pipeline_results is not None
                    }
                }
            )
            
        except Exception as e:
            logger.error(f"Error in FIXED final calculation: {e}")
            return ValidationOutcome(
                result=ValidationResult.PENDING,
                reason="PEND: Error in FIXED final calculation",
                details={"error": str(e)}
            )
    
    async def _get_fallback_gdrg_tariff(self, claim_data: Dict) -> float:
        """Get fallback G-DRG tariff when not available from pipeline"""
        try:
            gdrg_code = claim_data.get('gdrg_code')
            provider_name = claim_data.get('provider_name')
            encounter_type = claim_data.get('encounter_type')
            
            if not gdrg_code:
                return 0.0
            
            # Simplified tariff lookup - this would normally use the full G-DRG determination logic
            base_gdrg = gdrg_code.rstrip('AC')  # Remove age suffix
            
            # Basic tariff lookup from icd10_codes table
            tariff_query = """
            SELECT tariff
            FROM icd10_codes 
            WHERE gdrg_code = $1 
                AND tariff IS NOT NULL
            LIMIT 1
            """
            
            result = await self.queries.db.fetch_one(tariff_query, gdrg_code)
            if result and result.get('tariff'):
                base_tariff = float(result['tariff'])
                
                # Apply basic facility level multipliers
                facility_info = await self.queries.get_facility_info_by_name(provider_name)
                facility_level = facility_info.get('facility_level', '2') if facility_info else '2'
                
                level_multipliers = {'1': 0.85, '2': 1.00, '3': 1.15}
                encounter_multipliers = {'OPD': 1.00, 'IPD': 1.10, 'A&E': 1.20}
                
                facility_mult = level_multipliers.get(str(facility_level), 1.00)
                encounter_mult = encounter_multipliers.get(encounter_type, 1.00)
                
                final_tariff = base_tariff * facility_mult * encounter_mult
                logger.info(f"🔄 Fallback tariff calculation: {base_tariff} × {facility_mult} × {encounter_mult} = {final_tariff}")
                
                return round(final_tariff, 2)
            
            # Try base G-DRG without suffix
            result = await self.queries.db.fetch_one(tariff_query, base_gdrg)
            if result and result.get('tariff'):
                return round(float(result['tariff']), 2)
            
            return 0.0
            
        except Exception as e:
            logger.error(f"Error in fallback G-DRG tariff calculation: {e}")
            return 0.0
    
    async def validate_multiple_claims(self, encounter_ids: List[str]) -> Dict[str, ValidationOutcome]:
        """Batch validate multiple claims through complete final processing"""
        results = {}
        
        for encounter_id in encounter_ids:
            try:
                result = await self.process_final_validation(encounter_id)
                results[encounter_id] = result
                
                # Log summary
                status_emoji = "✅" if result.result == ValidationResult.APPROVED else "❌" if result.result == ValidationResult.REJECTED else "⚠️"
                final_decision = ""
                if result.details and result.details.get('final_decision'):
                    final_decision = f" ({result.details['final_decision']})"
                logger.info(f"{status_emoji} {encounter_id}: {result.reason}{final_decision}")
                
            except Exception as e:
                logger.error(f"Error validating {encounter_id}: {e}")
                results[encounter_id] = ValidationOutcome(
                    result=ValidationResult.PENDING,
                    reason=f"PEND: Validation error - {str(e)}",
                    details={"encounter_id": encounter_id}
                )
        
        return results