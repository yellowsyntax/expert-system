import asyncio
import json
import logging
from typing import List, Dict, Any, Optional, Union
from dataclasses import dataclass
from enum import Enum
from datetime import datetime
import time

from neon_db_connection import get_nhis_queries, initialize_database, close_database
from initial_processing_validator import InitialProcessingValidator
from enhanced_validations import EnhancedValidations
from ae_flow_validator import AEFlowValidator
from opd_flow_validator import OPDFlowValidator
from ipd_flow_validator import IPDFlowValidator
from facility_credentialing_validator import FacilityCredentialingValidator
from gdrg_determination import EnhancedGDRGDeterminationStep5
from medicine_validation import MedicineValidationStep6
from final_processing import FinalProcessingSteps7to10
from updatedb import DatabaseResultsUpdater
from duplicate_claims_detector import DuplicateClaimsDetector, run_duplicate_detection_stage, DuplicateFlag
from duplicate_flag_preserver import preserve_batch_flags
from live_batch_monitor import broadcast_claim_processed, broadcast_batch_progress_update, broadcast_batch_completed, ClaimProgressUpdate

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class ProcessingStage(Enum):
    INITIAL_PROCESSING = "INITIAL_PROCESSING"
    ENHANCED_VALIDATIONS = "ENHANCED_VALIDATIONS"
    ENCOUNTER_FLOW = "ENCOUNTER_FLOW"
    CREDENTIALING = "CREDENTIALING"
    GDRG_DETERMINATION = "GDRG_DETERMINATION"
    MEDICINE_VALIDATION = "MEDICINE_VALIDATION"
    FINAL_PROCESSING = "FINAL_PROCESSING"
    DATABASE_UPDATE = "DATABASE_UPDATE"
    COMPLETED = "COMPLETED"

class ValidationResult(Enum):
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    FLAGGED = "FLAGGED"
    PENDING = "PENDING"
    PARTIAL = "PARTIAL"

@dataclass
class ProcessingOutcome:
    encounter_id: str
    overall_result: ValidationResult
    processing_stage: ProcessingStage
    reason: str
    details: Dict[str, Any] = None
    timestamp: datetime = None
    processing_time_seconds: float = 0.0
    database_updated: bool = False
    financial_impact: Dict[str, Any] = None
    
    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.now()

@dataclass
class BatchInfo:
    batch_id: str
    total_claims: int
    processed_claims: int = 0
    approved_claims: int = 0
    rejected_claims: int = 0
    flagged_claims: int = 0
    partial_claims: int = 0
    error_claims: int = 0
    start_time: datetime = None
    end_time: datetime = None
    duplicate_flagged_claims: int = 0
    duplicate_blocked_claims: int = 0
    clean_claims: int = 0
    duplicate_detection_completed: bool = False
    duplicate_detection_time: datetime = None
    
    def __post_init__(self):
        if self.start_time is None:
            self.start_time = datetime.now()

class AutomatedBatchProcessor:
    
    def __init__(self):
        self.queries = None
        self.is_initialized = False

        self.duplicate_detector = DuplicateClaimsDetector()
        
        self.initial_processor = InitialProcessingValidator()
        self.enhanced_validator = EnhancedValidations()
        self.ae_validator = AEFlowValidator()
        self.opd_validator = OPDFlowValidator()
        self.ipd_validator = IPDFlowValidator()
        self.credentialing_validator = FacilityCredentialingValidator()
        self.gdrg_determiner = EnhancedGDRGDeterminationStep5()
        self.medicine_validator = MedicineValidationStep6()
        self.final_processor = FinalProcessingSteps7to10()
        self.database_updater = DatabaseResultsUpdater()
        
        self.validators = [
            self.duplicate_detector,
            self.initial_processor,
            self.enhanced_validator,
            self.ae_validator,
            self.opd_validator,
            self.ipd_validator,
            self.credentialing_validator,
            self.gdrg_determiner,
            self.medicine_validator,
            self.final_processor,
            self.database_updater
        ]
    
    async def initialize(self):
        if not self.is_initialized:
            await initialize_database()
            self.queries = await get_nhis_queries()

            await self.duplicate_detector.initialize()
            logger.info("Duplicate detection system initialized")
            
            for validator in self.validators[1:]:
                await validator.initialize()
            
            self.is_initialized = True
            logger.info("Automated Batch Processor with Step 0 Duplicate Detection initialized")
    
    async def close(self):
        for validator in self.validators:
            await validator.close()
        
        await close_database()
        self.is_initialized = False
        logger.info("Automated Batch Processor closed")
    
    async def get_batches_to_process(self) -> List[str]:
        try:
            if not self.is_initialized:
                await self.initialize()
            
            query = """
            SELECT batch_id, COUNT(*) as claim_count, MIN(created_at) as earliest_created
            FROM claims_v3 
            WHERE claim_status = 'submitted' 
            AND batch_id IS NOT NULL
            GROUP BY batch_id
            ORDER BY MIN(created_at) ASC
            """
            
            results = await self.queries.db.fetch_all(query)
            
            if results:
                batch_info = []
                for row in results:
                    batch_id = row['batch_id']
                    claim_count = row['claim_count']
                    batch_info.append(batch_id)
                    logger.info(f"Found batch {batch_id} with {claim_count} submitted claims")
                
                logger.info(f"Total batches to process: {len(batch_info)}")
                return batch_info
            else:
                logger.info("No batches with submitted claims found")
                return []
                
        except Exception as e:
            logger.error(f"Error fetching batches to process: {e}")
            return []
    
    async def get_batch_claims(self, batch_id: str) -> List[str]:
        try:
            query = """
            SELECT encounter_id 
            FROM claims_v3 
            WHERE batch_id = $1 
            AND claim_status = 'submitted'
            ORDER BY created_at ASC
            """
            
            results = await self.queries.db.fetch_all(query, batch_id)
            encounter_ids = [row['encounter_id'] for row in results]
            
            logger.info(f"Batch {batch_id}: Found {len(encounter_ids)} claims to process")
            return encounter_ids
            
        except Exception as e:
            logger.error(f"Error getting claims for batch {batch_id}: {e}")
            return []

    async def get_clean_claims_after_duplicate_detection(self, batch_id: str) -> List[str]:
        try:
            query = """
            SELECT encounter_id 
            FROM claims_v3 
            WHERE batch_id = $1 
            AND claim_status = 'submitted'
            AND (processed_status IS NULL OR processed_status NOT IN ('flagged', 'blocked'))
            ORDER BY created_at ASC
            """
            
            results = await self.queries.db.fetch_all(query, batch_id)
            clean_encounter_ids = [row['encounter_id'] for row in results]

            logger.info(f"Retrieved {len(clean_encounter_ids)} clean claims for validation processing")
            return clean_encounter_ids

        except Exception as e:
            logger.error(f"Error getting clean claims for {batch_id}: {e}")
            return []

    async def verify_no_flagged_claims_in_processing(self, clean_encounter_ids: List[str]):
        if not clean_encounter_ids:
            return
        placeholders = ','.join([f'${i+1}' for i in range(len(clean_encounter_ids))])
        query = f"""
        SELECT encounter_id, processed_status 
        FROM claims_v3 
        WHERE encounter_id IN ({placeholders})
        AND processed_status IN ('flagged', 'blocked')
        """

        flagged_claims = await self.queries.db.fetch_all(query, *clean_encounter_ids)
        if flagged_claims:
            logger.error(f"ERROR: {len(flagged_claims)} already flagged claims are about to be processed!")
            for claim in flagged_claims:
                logger.error(f"  {claim['encounter_id']}: {claim['processed_status']}")
            raise Exception("Flagged claims detected in clean processing list")

    async def get_claim_existing_flag_reason(self, encounter_id: str) -> Optional[Dict[str, Any]]:
        try:
            query = """
            SELECT flag_reason, processed_status 
            FROM claims_v3 
            WHERE encounter_id = $1
            """

            result = await self.queries.db.fetch_one(query, encounter_id)
            
            if result and result['flag_reason']:
                if isinstance(result['flag_reason'], str):
                    return json.loads(result['flag_reason'])
                else:
                    return result['flag_reason']

            return None

        except Exception as e:
            logger.error(f"Error getting existing flag reason for {encounter_id}: {e}")
            return None

    async def process_batch(self, batch_id: str) -> BatchInfo:
        try:
            encounter_ids = await self.get_batch_claims(batch_id)
        
            if not encounter_ids:
                logger.warning(f"No submitted claims found for batch {batch_id}")
                return BatchInfo(batch_id=batch_id, total_claims=0)
            
            batch_info = BatchInfo(
                batch_id=batch_id,
                total_claims=len(encounter_ids)
            )

            logger.info(f"Starting processing of batch {batch_id} with {len(encounter_ids)} claims")
            logger.info(f"STEP 0: Starting duplicate detection for batch {batch_id}")
            await self._run_batch_duplicate_detection(batch_id, encounter_ids, batch_info)

            clean_encounter_ids = await self.get_clean_claims_after_duplicate_detection(batch_id)

            if not clean_encounter_ids:
                logger.info(f"Batch {batch_id}: All claims flagged/blocked during duplicate detection")
                batch_info.end_time = datetime.now()
                batch_info.duplicate_detection_completed = True
                return batch_info
            
            await self.verify_no_flagged_claims_in_processing(clean_encounter_ids)

            batch_info.clean_claims = len(clean_encounter_ids)
            logger.info(f"VALIDATION PROCESSING: Starting for {len(clean_encounter_ids)} clean claims")
            await self._update_batch_processing_status(batch_id, "processing")

            for i, encounter_id in enumerate(clean_encounter_ids, 1):
                try:
                    logger.info(f"Processing clean claim {i}/{len(clean_encounter_ids)}: {encounter_id}")
                    result = await self.process_complete_claim(encounter_id, batch_id)

                    batch_info.processed_claims += 1

                    if result.overall_result == ValidationResult.APPROVED:
                        batch_info.approved_claims += 1
                    elif result.overall_result == ValidationResult.REJECTED:
                        batch_info.rejected_claims += 1
                    elif result.overall_result == ValidationResult.FLAGGED:
                        batch_info.flagged_claims += 1
                    elif result.overall_result == ValidationResult.PARTIAL:
                        batch_info.partial_claims += 1
                    else:
                        batch_info.error_claims += 1

                    claim_update = ClaimProgressUpdate(
                        encounter_id=encounter_id,
                        batch_id=batch_id,
                        old_status="submitted",
                        new_status=result.overall_result.value.lower(),
                        processed_by="NHIS_EXPERT_SYSTEM",
                        processing_stage=result.processing_stage.value,
                        updated_at=datetime.now()
                    )
                    await broadcast_claim_processed(claim_update)
                    
                    if batch_info.processed_claims % 5 == 0:
                        await broadcast_batch_progress_update(batch_id, self.queries)

                    if i % 10 == 0 or i == len(clean_encounter_ids):
                        progress = (i / len(clean_encounter_ids)) * 100
                        logger.info(f"Batch {batch_id} progress: {i}/{len(clean_encounter_ids)} ({progress:.1f}%)")

                except Exception as e:
                    logger.error(f"Error processing claim {encounter_id} in batch {batch_id}: {e}")
                    batch_info.error_claims += 1

            batch_info.end_time = datetime.now()
            processing_time = (batch_info.end_time - batch_info.start_time).total_seconds()
            logger.info(f"Batch {batch_id} processing time: {processing_time:.1f}s")

            await self._update_batch_processing_status(batch_id, "completed")

            logger.info(f"Batch {batch_id} processing completed:")
            logger.info(f"  Total Claims: {batch_info.total_claims}")
            logger.info(f"  Clean Claims Processed: {batch_info.clean_claims}")
            logger.info(f"  Duplicate Flagged: {batch_info.duplicate_flagged_claims}")
            logger.info(f"  Approved: {batch_info.approved_claims}")
            logger.info(f"  Rejected: {batch_info.rejected_claims}")
            logger.info(f"  Flagged: {batch_info.flagged_claims}")
            logger.info(f"  Partial: {batch_info.partial_claims}")
            logger.info(f"  Errors: {batch_info.error_claims}")
            logger.info(f"  Processing Time: {processing_time:.1f}s")

            duplicate_rate = ((batch_info.duplicate_flagged_claims + batch_info.duplicate_blocked_claims) / batch_info.total_claims * 100) if batch_info.total_claims > 0 else 0
            approval_rate = (batch_info.approved_claims / batch_info.clean_claims * 100) if batch_info.clean_claims > 0 else 0
            logger.info(f"  Duplicate Detection Rate: {duplicate_rate:.1f}%")
            logger.info(f"  Clean Claims Approval Rate: {approval_rate:.1f}%")

            logger.info(f"Preserving duplicate detection flags for batch {batch_id}")
            await preserve_batch_flags(batch_id)

            await broadcast_batch_completed(batch_id)

            return batch_info

        except Exception as e:
            logger.error(f"Error processing batch {batch_id}: {e}")
            await self._update_batch_processing_status(batch_id, "failed")
            
            return BatchInfo(
                batch_id=batch_id,
                total_claims=0,
                error_claims=1,
                end_time=datetime.now()
            )

    async def _run_batch_duplicate_detection(self, batch_id: str, encounter_ids: List[str], batch_info: BatchInfo):
        try:
            logger.info(f"DUPLICATE DETECTION: Starting for batch {batch_id} with {len(encounter_ids)} claims")
            duplicate_report = await run_duplicate_detection_stage(encounter_ids, batch_id)

            if "error" in duplicate_report:
                logger.error(f"Duplicate detection failed for batch {batch_id}: {duplicate_report['error']}")
                raise Exception(f"Duplicate detection failed: {duplicate_report['error']}")
            
            stats = duplicate_report["summary_statistics"]
            database_updates = duplicate_report["database_updates"]

            batch_info.clean_claims = stats.get("clean_claims", 0)
            flagged_count = stats.get("flagged_claims", 0)
            blocked_count = stats.get("blocked_claims", 0)
            batch_info.duplicate_flagged_claims = flagged_count + blocked_count
            batch_info.duplicate_blocked_claims = 0
            batch_info.duplicate_detection_time = datetime.now()

            logger.info(f"DUPLICATE DETECTION COMPLETED for batch {batch_id}:")
            logger.info(f"  Clean Claims: {stats.get('clean_claims', 0)}")
            logger.info(f"  Total Flagged Claims (flagged + blocked): {batch_info.duplicate_flagged_claims}")
            logger.info(f"  Error Claims: {stats.get('error_claims', 0)}")

            total_duplicates = batch_info.duplicate_flagged_claims
            duplicate_rate = (total_duplicates / batch_info.total_claims * 100) if batch_info.total_claims > 0 else 0
            logger.info(f"  Duplicate Detection Rate: {duplicate_rate:.1f}%")

            all_flagged_claims = database_updates.get("flagged_claims", []) + database_updates.get("blocked_claims", [])
            if all_flagged_claims:
                logger.info("FLAGGED/BLOCKED CLAIMS WITH REASONS:")
                for flagged in all_flagged_claims:
                    logger.info(f"  {flagged['encounter_id']}: {flagged['reason']} (Confidence: {flagged.get('confidence', 0):.3f})")

            if duplicate_report.get("high_confidence_duplicates"):
                logger.warning("HIGH CONFIDENCE DUPLICATES DETECTED:")
                for dup in duplicate_report["high_confidence_duplicates"]:
                    logger.warning(f"  {dup['primary_encounter']} <-> {dup['duplicate_encounter']} ({dup['type']}, {dup['confidence']:.3f})")

            for rec in duplicate_report.get("recommendations", []):
                logger.info(f"RECOMMENDATION: {rec}")

            logger.info(f"DUPLICATE DETECTION PHASE COMPLETE for batch {batch_id}")
            logger.info(f"Ready to proceed with validation for {stats['clean_claims']} clean claims")

            logger.info(f"Pre-validation: Preserving duplicate detection flags for batch {batch_id}")
            await preserve_batch_flags(batch_id)

        except Exception as e:
            logger.error(f"Error in duplicate detection phase for batch {batch_id}: {e}")
            raise

    async def _update_batch_processing_status(self, batch_id: str, status: str):
        try:
            if status == "processing":
                query = """
                UPDATE claims_v3 
                SET processing_started_at = CURRENT_TIMESTAMP,
                    updated_at = CURRENT_TIMESTAMP
                WHERE batch_id = $1 AND claim_status = 'submitted'
                """
            elif status == "completed":
                query = """
                UPDATE claims_v3 
                SET processing_completed_at = CURRENT_TIMESTAMP,
                    updated_at = CURRENT_TIMESTAMP
                WHERE batch_id = $1 AND claim_status = 'submitted'
                """
            elif status == "failed":
                query = """
                UPDATE claims_v3 
                SET processing_completed_at = CURRENT_TIMESTAMP,
                    updated_at = CURRENT_TIMESTAMP
                WHERE batch_id = $1 AND claim_status = 'submitted'
                """
            else:
                return
            
            await self.queries.db.execute(query, batch_id)
            
        except Exception as e:
            logger.error(f"Error updating batch status for {batch_id}: {e}")

    async def process_complete_claim(self, encounter_id: str, batch_id: str) -> ProcessingOutcome:
        if not self.is_initialized:
            await self.initialize()
        
        start_time = time.time()
        
        pipeline_results = {
            "encounter_id": encounter_id,
            "batch_id": batch_id,
            "stages_completed": [],
            "stages_passed": [],
            "stages_failed": [],
            "overall_result": None,
            "flagged_at_stage": None,
            "flag_reason": None,
            "processing_path": [],
            "final_decision": None,
            "amounts": {
                "approved": 0.0,
                "partial": 0.0,
                "denied": 0.0,
                "total_claimed": 0.0,
                "gdrg_tariff": 0.0,
                "medicine_cost_approved": 0.0,
                "medicine_cost_denied": 0.0
            },
            "financial_components": {
                "gdrg_tariff": 0.0,
                "medicine_cost": 0.0,
                "medicine_cost_approved": 0.0,
                "medicine_cost_denied": 0.0,
                "investigation_cost": 0.0,
                "modifier_multiplier": 1.0
            },
            "stage_data": {},
            "enhanced_validations": {},
            "database_update_status": False,
            "existing_duplicate_flag": None,
            "stage5_comprehensive_results": {},
            "stage6_comprehensive_results": {},
            "data_verification": {}
        }
        
        try:
            logger.debug(f"Starting FIXED processing pipeline for {encounter_id}")
            
            existing_flag_reason = await self.get_claim_existing_flag_reason(encounter_id)
            if existing_flag_reason:
                pipeline_results["existing_duplicate_flag"] = existing_flag_reason
                logger.info(f"Found existing duplicate flag for {encounter_id}")
            
            # Stage 1: Initial Processing
            stage_result = await self._stage1_initial_processing(encounter_id, pipeline_results)
            
            if not self._is_stage_successful(stage_result):
                logger.debug(f"Stage 1 failed for {encounter_id}: {stage_result.reason}")
                return await self._finalize_with_database_update(encounter_id, stage_result, pipeline_results, start_time)
            
            encounter_type = stage_result.details.get('encounter_type') if stage_result.details else None
            if not encounter_type:
                error_outcome = self._create_error_outcome(encounter_id, "No encounter type determined", 
                                                        ProcessingStage.INITIAL_PROCESSING, pipeline_results, start_time)
                return await self._finalize_with_database_update(encounter_id, error_outcome, pipeline_results, start_time)
            
            # Stage 2: Enhanced Validations
            stage_result = await self._stage2_enhanced_validations(encounter_id, pipeline_results)
            
            if not self._is_stage_successful(stage_result):
                logger.debug(f"Stage 2 enhanced validations failed for {encounter_id}: {stage_result.reason}")
                return await self._finalize_with_database_update(encounter_id, stage_result, pipeline_results, start_time)
            
            # Stage 3: Encounter Flow
            stage_result = await self._stage3_encounter_flow(encounter_id, encounter_type, pipeline_results)
            
            if not self._is_stage_successful(stage_result):
                logger.debug(f"Stage 3 encounter flow failed for {encounter_id}: {stage_result.reason}")
                return await self._finalize_with_database_update(encounter_id, stage_result, pipeline_results, start_time)
            
            # Stage 4: Credentialing
            stage_result = await self._stage4_credentialing(encounter_id, pipeline_results)
            
            if not self._is_stage_successful(stage_result):
                logger.debug(f"Stage 4 credentialing failed for {encounter_id}: {stage_result.reason}")
                return await self._finalize_with_database_update(encounter_id, stage_result, pipeline_results, start_time)
            
            # Stage 5: G-DRG Determination
            logger.info(f"STAGE 5: Enhanced G-DRG Determination for {encounter_id}")
            stage_result = await self._stage5_gdrg_determination(encounter_id, pipeline_results)
            
            if not self._is_stage_successful(stage_result):
                logger.debug(f"Stage 5 G-DRG determination failed for {encounter_id}: {stage_result.reason}")
                return await self._finalize_with_database_update(encounter_id, stage_result, pipeline_results, start_time)
            
            stage5_comprehensive = await self._extract_stage5_comprehensive(stage_result, encounter_id)
            pipeline_results["stage5_comprehensive_results"] = stage5_comprehensive
            
            if stage5_comprehensive.get("selected_tariff", 0.0) > 0:
                pipeline_results["financial_components"]["gdrg_tariff"] = stage5_comprehensive["selected_tariff"]
                pipeline_results["amounts"]["gdrg_tariff"] = stage5_comprehensive["selected_tariff"]
                pipeline_results["stage_data"]["stage5_gdrg_determination"] = stage5_comprehensive
                
                logger.info(f"CAPTURED Stage 5: G-DRG {stage5_comprehensive['selected_gdrg']} = {stage5_comprehensive['selected_tariff']} GHS")
            else:
                logger.warning(f"No G-DRG tariff extracted from Stage 5 for {encounter_id}")
            
            # Stage 6: Medicine Validation
            logger.info(f"STAGE 6: Enhanced Medicine Validation for {encounter_id}")
            stage_result = await self._stage6_medicine_validation(encounter_id, pipeline_results)
            
            if not self._is_stage_successful(stage_result):
                logger.debug(f"Stage 6 medicine validation failed for {encounter_id}: {stage_result.reason}")
                return await self._finalize_with_database_update(encounter_id, stage_result, pipeline_results, start_time)
            
            stage6_comprehensive = await self._extract_stage6_comprehensive(stage_result, encounter_id)
            pipeline_results["stage6_comprehensive_results"] = stage6_comprehensive
            
            pipeline_results["financial_components"]["medicine_cost_approved"] = stage6_comprehensive.get("medicine_cost_approved", 0.0)
            pipeline_results["financial_components"]["medicine_cost_denied"] = stage6_comprehensive.get("medicine_cost_denied", 0.0)
            pipeline_results["amounts"]["medicine_cost_approved"] = stage6_comprehensive.get("medicine_cost_approved", 0.0)
            pipeline_results["amounts"]["medicine_cost_denied"] = stage6_comprehensive.get("medicine_cost_denied", 0.0)
            pipeline_results["stage_data"]["stage6_medicine_validation"] = stage6_comprehensive
            
            logger.info(f"CAPTURED Stage 6: {stage6_comprehensive['medicine_cost_approved']} GHS approved, {stage6_comprehensive['medicine_cost_denied']} GHS denied")
            
            # Stage 7: Final Processing
            logger.info(f"FINAL PROCESSING: Using captured stage results for {encounter_id}")
            stage_result = await self._stage7_final_processing_fixed(encounter_id, pipeline_results)
            
            self._extract_final_amounts(stage_result, pipeline_results)
            
            verification_results = await self._verify_data_usage_comprehensive(pipeline_results, stage_result, encounter_id)
            pipeline_results["data_verification"] = verification_results
            
            processing_time = time.time() - start_time
            
            final_outcome = ProcessingOutcome(
                encounter_id=encounter_id,
                overall_result=stage_result.overall_result,
                processing_stage=ProcessingStage.COMPLETED,
                reason=f"FIXED Pipeline completed: {stage_result.reason}",
                processing_time_seconds=round(processing_time, 3),
                database_updated=False,
                details={
                    "encounter_type": encounter_type,
                    "enhanced_validations": pipeline_results.get("enhanced_validations", {}),
                    "final_decision": pipeline_results.get("final_decision"),
                    "amounts": pipeline_results.get("amounts", {}),
                    "financial_components": pipeline_results.get("financial_components", {}),
                    "comprehensive_results": pipeline_results,
                    "selected_gdrg": stage5_comprehensive.get("selected_gdrg"),
                    "has_medicine_rejections": stage6_comprehensive.get("has_rejections", False),
                    "data_verification": verification_results,
                    "fixes_applied": [
                        "Comprehensive Stage 5 G-DRG extraction",
                        "Enhanced Stage 6 medicine cost summation",
                        "Fixed Final Processing data usage",
                        "PARTIAL detection for medicine rejections",
                        "Complete verification system"
                    ]
                }
            )
            
            logger.info(f"FIXED PIPELINE COMPLETED for {encounter_id} in {processing_time:.3f}s")
            return await self._finalize_with_database_update(encounter_id, final_outcome, pipeline_results, start_time)
                
        except Exception as e:
            processing_time = time.time() - start_time
            logger.error(f"Pipeline error for {encounter_id}: {e}")
            
            error_outcome = ProcessingOutcome(
                encounter_id=encounter_id,
                overall_result=ValidationResult.FLAGGED,
                processing_stage=ProcessingStage.INITIAL_PROCESSING,
                reason=f"FIXED Pipeline error: {str(e)}",
                processing_time_seconds=round(processing_time, 3),
                database_updated=False,
                details={
                    "error": str(e),
                    "pipeline_results": pipeline_results
                }
            )
            
            return await self._finalize_with_database_update(encounter_id, error_outcome, pipeline_results, start_time)

    async def _extract_stage5_comprehensive(self, stage_result: ProcessingOutcome, encounter_id: str) -> Dict:
        details = stage_result.details or {}
        
        extracted_data = {
            "selected_gdrg": None,
            "selected_tariff": 0.0,
            "base_gdrg": None,
            "tariff_info": {},
            "path_type": None,
            "dual_evaluation": False,
            "extraction_methods_used": []
        }
        
        try:
            stage5_details = details.get('stage5_details', {})
            
            # Method 1: Direct stage5_details extraction
            if stage5_details.get('selected_tariff'):
                extracted_data["selected_tariff"] = float(stage5_details['selected_tariff'])
                extracted_data["selected_gdrg"] = stage5_details.get('selected_gdrg')
                extracted_data["extraction_methods_used"].append("stage5_details_direct")
                logger.info(f"Method 1: Direct extraction - {extracted_data['selected_tariff']} GHS")
            
            # Method 2: G-DRG summary extraction
            gdrg_summary = stage5_details.get('gdrg_summary', {}) or details.get('gdrg_summary', {})
            if gdrg_summary and gdrg_summary.get('tariff_amount', 0.0) > extracted_data["selected_tariff"]:
                extracted_data["selected_tariff"] = float(gdrg_summary['tariff_amount'])
                extracted_data["selected_gdrg"] = gdrg_summary.get('selected_gdrg')
                extracted_data["extraction_methods_used"].append("gdrg_summary")
                logger.info(f"Method 2: G-DRG summary - {extracted_data['selected_tariff']} GHS")
            
            # Method 3: Evaluation summary (dual evaluation winner)
            eval_summary = stage5_details.get('evaluation_summary', {}) or details.get('evaluation_summary', {})
            if eval_summary:
                winning_tariff = eval_summary.get('winning_tariff', 0.0)
                if winning_tariff > extracted_data["selected_tariff"]:
                    extracted_data["selected_tariff"] = float(winning_tariff)
                    extracted_data["selected_gdrg"] = eval_summary.get('winner', extracted_data["selected_gdrg"])
                    extracted_data["dual_evaluation"] = True
                    extracted_data["extraction_methods_used"].append("evaluation_summary_winning")
                    logger.info(f"Method 3: Dual evaluation winner - {extracted_data['selected_tariff']} GHS")
            
            # Method 4: Selected tariff info
            selected_tariff_info = stage5_details.get('selected_tariff_info', {}) or details.get('selected_tariff_info', {})
            if selected_tariff_info:
                tariff_amount = selected_tariff_info.get('amount', 0.0)
                if tariff_amount > extracted_data["selected_tariff"]:
                    extracted_data["selected_tariff"] = float(tariff_amount)
                    extracted_data["tariff_info"] = selected_tariff_info
                    extracted_data["extraction_methods_used"].append("selected_tariff_info")
                    logger.info(f"Method 4: Tariff info - {extracted_data['selected_tariff']} GHS")
            
            # Method 5: Financial impact
            if stage_result.financial_impact:
                financial_selected = stage_result.financial_impact.get('selected_tariff', 0.0)
                if financial_selected > extracted_data["selected_tariff"]:
                    extracted_data["selected_tariff"] = float(financial_selected)
                    extracted_data["extraction_methods_used"].append("financial_impact")
                    logger.info(f"Method 5: Financial impact - {extracted_data['selected_tariff']} GHS")
            
            # Method 6: Tariff comparison
            tariff_comparison = stage5_details.get('tariff_comparison', {}) or details.get('tariff_comparison', {})
            if tariff_comparison:
                for comparison_type, comparison_data in tariff_comparison.items():
                    if isinstance(comparison_data, dict) and comparison_data.get('tariff', 0.0) > extracted_data["selected_tariff"]:
                        extracted_data["selected_tariff"] = float(comparison_data['tariff'])
                        extracted_data["selected_gdrg"] = comparison_data.get('gdrg', extracted_data["selected_gdrg"])
                        extracted_data["extraction_methods_used"].append(f"tariff_comparison_{comparison_type}")
                        logger.info(f"Method 6: Tariff comparison {comparison_type} - {extracted_data['selected_tariff']} GHS")
            
            # Extract additional metadata
            extracted_data["base_gdrg"] = stage5_details.get('selected_base_gdrg') or details.get('selected_base_gdrg')
            extracted_data["path_type"] = stage5_details.get('path_type') or details.get('path_type')
            
            if extracted_data["selected_tariff"] > 0:
                logger.info(f"Stage 5 COMPREHENSIVE EXTRACTION SUCCESS: {extracted_data['selected_gdrg']} = {extracted_data['selected_tariff']} GHS")
                logger.info(f"  Methods used: {', '.join(extracted_data['extraction_methods_used'])}")
            else:
                logger.error(f"Stage 5 COMPREHENSIVE EXTRACTION FAILED: No tariff found for {encounter_id}")
                logger.error(f"  Available details keys: {list(details.keys())}")
                logger.error(f"  Stage5 details keys: {list(stage5_details.keys())}")
            
            return extracted_data
            
        except Exception as e:
            logger.error(f"Error in comprehensive Stage 5 extraction: {e}")
            return extracted_data

    async def _extract_stage6_comprehensive(self, stage_result: ProcessingOutcome, encounter_id: str) -> Dict:
        details = stage_result.details or {}
        stage6_details = details.get('stage6_details', {})

        logger.info(f"DEBUG - Stage 6 data structure for {encounter_id}:")
        logger.info(f"  details keys: {list(details.keys())}")
        logger.info(f"  stage6_details keys: {list(stage6_details.keys())}")

        step_results = details.get('step_by_step_results', {})
        logger.info(f"  step_by_step_results keys: {list(step_results.keys())}")

        logger.info(f"  medicine_outcomes in details: {bool(details.get('medicine_outcomes'))}")
        logger.info(f"  medicine_outcomes in stage6_details: {bool(stage6_details.get('medicine_outcomes'))}")

        dosage_step = None
        for step in step_results.get('steps_passed', []):
            if step.get('step') == 'dosage_duration_validation':
                dosage_step = step
                break
        if dosage_step:
            logger.info(f"  dosage step details keys: {list(dosage_step.get('details', {}).keys())}")
        
        extracted_data = {
            "total_medicine_cost": 0.0,
            "medicine_cost_approved": 0.0,
            "medicine_cost_denied": 0.0,
            "approved_medicines": [],
            "denied_medicines": [],
            "medicine_count": 0,
            "has_rejections": False,
            "extraction_methods_used": []
        }
        
        try:
            stage6_details = details.get('stage6_details', {})
            
            # Method 1: Medicine outcomes extraction
            medicine_outcomes = stage6_details.get('medicine_outcomes', [])
            if medicine_outcomes:
                for outcome in medicine_outcomes:
                    dosage_result = outcome.get('dosage_result', '')
                    tariff_calc = outcome.get('tariff_calculation', {})
                    cost = float(tariff_calc.get('total_cost', 0.0))
                    
                    if dosage_result == 'WITHIN_LIMITS':
                        extracted_data["medicine_cost_approved"] += cost
                        extracted_data["approved_medicines"].append(outcome)
                    elif dosage_result == 'MODERATE_OVERSUPPLY':
                        extracted_data["medicine_cost_approved"] += cost
                        extracted_data["approved_medicines"].append(outcome)
                    elif dosage_result == 'EXCESSIVE_OVERSUPPLY':
                        extracted_data["has_rejections"] = True
                        extracted_data["denied_medicines"].append(outcome)
                        extracted_data["medicine_cost_denied"] += cost
                
                extracted_data["extraction_methods_used"].append("medicine_outcomes")
                logger.info(f"Method 1: Medicine outcomes - {len(medicine_outcomes)} medicines processed")
            
            # Method 2: Step-by-step results
            step_results = details.get('step_by_step_results', {})
            medicine_results = step_results.get('medicine_results', {})
            
            if medicine_results and not extracted_data["medicine_cost_approved"] and not extracted_data["medicine_cost_denied"]:
                if 'approved' in medicine_results:
                    for med in medicine_results['approved']:
                        cost = float(med.get('tariff_calculation', {}).get('total_cost', 0.0))
                        extracted_data["medicine_cost_approved"] += cost
                        extracted_data["approved_medicines"].append(med)
                
                if 'partial' in medicine_results:
                    for med in medicine_results['partial']:
                        cost = float(med.get('tariff_calculation', {}).get('total_cost', 0.0))
                        extracted_data["medicine_cost_approved"] += cost
                        extracted_data["approved_medicines"].append(med)
                
                if 'denied' in medicine_results:
                    for med in medicine_results['denied']:
                        cost = float(med.get('tariff_calculation', {}).get('total_cost', 0.0))
                        denied_cost = cost if cost > 0 else 0.01  # Use nominal amount for zero-cost denials
                        extracted_data["medicine_cost_denied"] += denied_cost
                        extracted_data["denied_medicines"].append(med)
                        extracted_data["has_rejections"] = True
                
                extracted_data["extraction_methods_used"].append("step_results_medicine_results")
                logger.info(f"Method 2: Step results - found {len(medicine_results.get('denied', []))} denied medicines")
            
            # Method 3: Rejection indicators
            if step_results.get('steps_failed') or step_results.get('specific_rejection_reasons'):
                extracted_data["has_rejections"] = True
                extracted_data["extraction_methods_used"].append("step_results_rejection_indicators")
                logger.info(f"Method 3: Rejection indicators found in step results")
            
            # Method 4: Fallback to total cost with estimation
            if not extracted_data["medicine_cost_approved"] and not extracted_data["medicine_cost_denied"]:
                total_cost = float(stage6_details.get('total_medicine_cost', 0.0))
                medicine_outcomes = stage6_details.get('medicine_outcomes', [])
                has_excessive_oversupply = any(
                    outcome.get('dosage_result') == 'EXCESSIVE_OVERSUPPLY'
                    for outcome in medicine_outcomes
                )
                if has_excessive_oversupply or extracted_data["has_rejections"]:
                    extracted_data["medicine_cost_approved"] = total_cost * 0.7
                    extracted_data["medicine_cost_denied"] = total_cost * 0.3
                    extracted_data["has_rejections"] = True
                else:
                    extracted_data["medicine_cost_approved"] = total_cost
                    
                extracted_data["extraction_methods_used"].append("total_medicine_cost_fallback")
                logger.info(f"Method 4: Fallback to total cost - {total_cost} GHS")
            
            # Calculate totals and finalize
            extracted_data["total_medicine_cost"] = extracted_data["medicine_cost_approved"] + extracted_data["medicine_cost_denied"]
            extracted_data["medicine_count"] = len(extracted_data["approved_medicines"]) + len(extracted_data["denied_medicines"])
            
            # Round for consistency
            extracted_data["medicine_cost_approved"] = round(extracted_data["medicine_cost_approved"], 2)
            extracted_data["medicine_cost_denied"] = round(extracted_data["medicine_cost_denied"], 2)
            extracted_data["total_medicine_cost"] = round(extracted_data["total_medicine_cost"], 2)
            
            logger.info(f"Stage 6 COMPREHENSIVE EXTRACTION: {extracted_data['medicine_cost_approved']} GHS approved, {extracted_data['medicine_cost_denied']} GHS denied")
            logger.info(f"  Has rejections: {extracted_data['has_rejections']}")
            logger.info(f"  Methods used: {', '.join(extracted_data['extraction_methods_used'])}")
            
            return extracted_data
            
        except Exception as e:
            logger.error(f"Error in comprehensive Stage 6 extraction: {e}")
            return extracted_data

    async def _stage1_initial_processing(self, encounter_id: str, pipeline_results: Dict) -> ProcessingOutcome:
        try:
            pipeline_results["stages_completed"].append("stage1_initial_processing")
            pipeline_results["processing_path"].append("Initial Processing")
            
            result = await self.initial_processor.process_initial_validation(encounter_id)
            result_value = result.result.value if hasattr(result.result, 'value') else str(result.result)

            if result_value == "FLAGGED":
                if not pipeline_results.get("flagged_at_stage"):
                    pipeline_results["flagged_at_stage"] = "stage1_initial_processing"
                    pipeline_results["flag_reason"] = result.reason
            
            if result_value == "APPROVED":
                pipeline_results["stages_passed"].append({
                    "stage": "stage1_initial_processing",
                    "result": result_value,
                    "reason": result.reason
                })
                
                return ProcessingOutcome(
                    encounter_id=encounter_id,
                    overall_result=ValidationResult.APPROVED,
                    processing_stage=ProcessingStage.INITIAL_PROCESSING,
                    reason="Stage 1 passed: Ready for enhanced validations",
                    details={
                        "encounter_type": result.details.get('encounter_type') if result.details else None,
                        "routing_decision": result.details.get('routing_decision') if result.details else None,
                        "stage1_details": result.details
                    }
                )
            else:
                pipeline_results["stages_failed"].append({
                    "stage": "stage1_initial_processing",
                    "result": result_value,
                    "reason": result.reason
                })
                
                try:
                    result_enum = ValidationResult(result_value)
                except ValueError:
                    result_enum = ValidationResult.FLAGGED
                
                return ProcessingOutcome(
                    encounter_id=encounter_id,
                    overall_result=result_enum,
                    processing_stage=ProcessingStage.INITIAL_PROCESSING,
                    reason=f"Stage 1 failed: {result.reason}",
                    details={"stage1_details": result.details}
                )
        
        except Exception as e:
            logger.error(f"Error in Stage 1: {e}")
            return ProcessingOutcome(
                encounter_id=encounter_id,
                overall_result=ValidationResult.FLAGGED,
                processing_stage=ProcessingStage.INITIAL_PROCESSING,
                reason=f"Stage 1 error: {str(e)}"
            )
    
    async def _stage2_enhanced_validations(self, encounter_id: str, pipeline_results: Dict) -> ProcessingOutcome:
        try:
            pipeline_results["stages_completed"].append("stage2_enhanced_validations")
            pipeline_results["processing_path"].append("Enhanced Validations")
            
            enhanced_results = await self.enhanced_validator.run_all_enhanced_validations(encounter_id)
            pipeline_results["enhanced_validations"] = enhanced_results
            
            if "error" in enhanced_results:
                return ProcessingOutcome(
                    encounter_id=encounter_id,
                    overall_result=ValidationResult.FLAGGED,
                    processing_stage=ProcessingStage.ENHANCED_VALIDATIONS,
                    reason=f"Stage 2 error: {enhanced_results['error'].reason}",
                    details={"stage2_details": enhanced_results}
                )
            
            rejected_validations = []
            flagged_validations = []
            approved_validations = []
            
            for validation_type, result in enhanced_results.items():
                if validation_type == 'summary':
                    continue
                
                if result.result == ValidationResult.REJECTED:
                    rejected_validations.append(validation_type)
                elif result.result == ValidationResult.FLAGGED:
                    flagged_validations.append(validation_type)
                elif result.result == ValidationResult.APPROVED:
                    approved_validations.append(validation_type)
            
            if rejected_validations:
                pipeline_results["stages_failed"].append({
                    "stage": "stage2_enhanced_validations",
                    "result": "REJECTED",
                    "reason": f"Enhanced validations failed: {', '.join(rejected_validations)}"
                })
                
                return ProcessingOutcome(
                    encounter_id=encounter_id,
                    overall_result=ValidationResult.REJECTED,
                    processing_stage=ProcessingStage.ENHANCED_VALIDATIONS,
                    reason=f"Stage 2 failed: Enhanced validations rejected - {', '.join(rejected_validations)}",
                    details={"stage2_details": enhanced_results}
                )
            
            elif flagged_validations:
                pipeline_results["stages_passed"].append({
                    "stage": "stage2_enhanced_validations",
                    "result": "FLAGGED",
                    "reason": f"Enhanced validations passed with flags: {', '.join(flagged_validations)}"
                })
                
                return ProcessingOutcome(
                    encounter_id=encounter_id,
                    overall_result=ValidationResult.FLAGGED,
                    processing_stage=ProcessingStage.ENHANCED_VALIDATIONS,
                    reason=f"Stage 2 passed with flags: {', '.join(flagged_validations)}",
                    details={"stage2_details": enhanced_results}
                )
            
            else:
                pipeline_results["stages_passed"].append({
                    "stage": "stage2_enhanced_validations",
                    "result": "APPROVED",
                    "reason": "All enhanced validations passed"
                })
                
                return ProcessingOutcome(
                    encounter_id=encounter_id,
                    overall_result=ValidationResult.APPROVED,
                    processing_stage=ProcessingStage.ENHANCED_VALIDATIONS,
                    reason="Stage 2 passed: All enhanced validations approved",
                    details={"stage2_details": enhanced_results}
                )
        
        except Exception as e:
            logger.error(f"Error in Stage 2 Enhanced Validations: {e}")
            return ProcessingOutcome(
                encounter_id=encounter_id,
                overall_result=ValidationResult.FLAGGED,
                processing_stage=ProcessingStage.ENHANCED_VALIDATIONS,
                reason=f"Stage 2 error: {str(e)}"
            )
    
    async def _stage3_encounter_flow(self, encounter_id: str, encounter_type: str, pipeline_results: Dict) -> ProcessingOutcome:
        try:
            pipeline_results["stages_completed"].append("stage3_encounter_flow")
            
            if encounter_type == "A&E":
                pipeline_results["processing_path"].append("A&E Flow")
                result = await self.ae_validator.process_ae_flow_validation(encounter_id)
            elif encounter_type == "OPD":
                pipeline_results["processing_path"].append("OPD Flow")
                result = await self.opd_validator.process_opd_flow_validation(encounter_id)
            elif encounter_type == "IPD":
                pipeline_results["processing_path"].append("IPD Flow")
                result = await self.ipd_validator.process_ipd_flow_validation(encounter_id)
            else:
                raise ValueError(f"Unknown encounter type: {encounter_type}")
            
            result_value = result.result.value if hasattr(result.result, 'value') else str(result.result)
            
            if result_value in ["APPROVED", "FLAGGED"]:
                pipeline_results["stages_passed"].append({
                    "stage": "stage3_encounter_flow",
                    "flow_type": encounter_type,
                    "result": result_value,
                    "reason": result.reason
                })
                
                return ProcessingOutcome(
                    encounter_id=encounter_id,
                    overall_result=ValidationResult.APPROVED,
                    processing_stage=ProcessingStage.ENCOUNTER_FLOW,
                    reason=f"Stage 3 passed: {encounter_type} flow completed",
                    details={
                        "encounter_type": encounter_type,
                        "stage3_details": result.details
                    }
                )
            else:
                pipeline_results["stages_failed"].append({
                    "stage": "stage3_encounter_flow",
                    "flow_type": encounter_type,
                    "result": result_value,
                    "reason": result.reason
                })
                
                try:
                    result_enum = ValidationResult(result_value)
                except ValueError:
                    result_enum = ValidationResult.FLAGGED
                
                return ProcessingOutcome(
                    encounter_id=encounter_id,
                    overall_result=result_enum,
                    processing_stage=ProcessingStage.ENCOUNTER_FLOW,
                    reason=f"Stage 3 failed: {result.reason}",
                    details={"stage3_details": result.details}
                )
        
        except Exception as e:
            logger.error(f"Error in Stage 3: {e}")
            return ProcessingOutcome(
                encounter_id=encounter_id,
                overall_result=ValidationResult.FLAGGED,
                processing_stage=ProcessingStage.ENCOUNTER_FLOW,
                reason=f"Stage 3 error: {str(e)}"
            )
    
    async def _stage4_credentialing(self, encounter_id: str, pipeline_results: Dict) -> ProcessingOutcome:
        try:
            pipeline_results["stages_completed"].append("stage4_credentialing")
            pipeline_results["processing_path"].append("Credentialing")
            
            result = await self.credentialing_validator.process_step4_credentialing_check(encounter_id)
            result_value = result.result.value if hasattr(result.result, 'value') else str(result.result)
            
            if result_value == "APPROVED":
                pipeline_results["stages_passed"].append({
                    "stage": "stage4_credentialing",
                    "result": result_value,
                    "reason": result.reason
                })
                
                return ProcessingOutcome(
                    encounter_id=encounter_id,
                    overall_result=ValidationResult.APPROVED,
                    processing_stage=ProcessingStage.CREDENTIALING,
                    reason="Stage 4 passed: Credentialing validated",
                    details={"stage4_details": result.details}
                )
            else:
                pipeline_results["stages_failed"].append({
                    "stage": "stage4_credentialing",
                    "result": result_value,
                    "reason": result.reason
                })
                
                try:
                    result_enum = ValidationResult(result_value)
                except ValueError:
                    result_enum = ValidationResult.FLAGGED
                
                return ProcessingOutcome(
                    encounter_id=encounter_id,
                    overall_result=result_enum,
                    processing_stage=ProcessingStage.CREDENTIALING,
                    reason=f"Stage 4 failed: {result.reason}",
                    details={"stage4_details": result.details}
                )
        
        except Exception as e:
            logger.error(f"Error in Stage 4: {e}")
            return ProcessingOutcome(
                encounter_id=encounter_id,
                overall_result=ValidationResult.FLAGGED,
                processing_stage=ProcessingStage.CREDENTIALING,
                reason=f"Stage 4 error: {str(e)}"
            )
    
    async def _stage5_gdrg_determination(self, encounter_id: str, pipeline_results: Dict) -> ProcessingOutcome:
        try:
            pipeline_results["stages_completed"].append("stage5_gdrg_determination")
            pipeline_results["processing_path"].append("G-DRG Determination")
            
            result = await self.gdrg_determiner.process_step5_gdrg_determination(encounter_id)
            result_value = result.result.value if hasattr(result.result, 'value') else str(result.result)

            if result_value == "FLAGGED":
                if not pipeline_results.get("flagged_at_stage"):
                    pipeline_results["flagged_at_stage"] = "stage5_gdrg_determination"
                    pipeline_results["flag_reason"] = {
                        "stage": "GDRG_DETERMINATION",
                        "reason": "Stage 5 flagged: OPDC13A detected - Manual review required",
                        "timestamp": datetime.now().isoformat(),
                        "category": "GDRG_DETERMINATION",
                        "requires_manual_review": True
                    }
            
            if result_value == "FLAGGED" and result.details:
                gdrg_determination = result.details.get('gdrg_determination', {})
                if gdrg_determination and gdrg_determination.get('final_gdrg') == 'OPDC13A':
                    logger.warning(f"OPDC13A flagged - Will stop processing after this stage for {encounter_id}")

                    pipeline_results["flag_reason"] = {
                        "stage": "GDRG_DETERMINATION",
                        "reason": "Stage 5 flagged: OPDC13A detected - Manual review required",
                        "timestamp": datetime.now().isoformat(),
                        "category": "GDRG_DETERMINATION",
                        "requires_manual_review": True,
                        "gdrg_code": "OPDC13A"
                    }
                    
                    pipeline_results["stages_passed"].append({
                        "stage": "stage5_gdrg_determination", 
                        "result": result_value,
                        "reason": f"{result.reason} - OPDC13A DETECTED",
                        "opdc13a_detected": True
                    })
                    
                    return ProcessingOutcome(
                        encounter_id=encounter_id,
                        overall_result=ValidationResult.FLAGGED,
                        processing_stage=ProcessingStage.GDRG_DETERMINATION,
                        reason="Stage 5 flagged: OPDC13A detected - Manual review required",
                        details={"stage5_details": result.details}
                    )
                
                step_results = result.details.get('step_by_step_results', {})
                if step_results.get('special_case_triggered'):
                    special_case_details = step_results.get('special_case_details', {})
                    if special_case_details.get('special_case_type') == 'OPDC13A_SUPPORTING_DOCS':
                        logger.warning(f"OPDC13A special case flagged - Will stop processing after this stage for {encounter_id}")
                        
                        pipeline_results["flag_reason"] = {
                            "stage": "GDRG_DETERMINATION",
                            "reason": "Stage 5 flagged: OPDC13A special case - Supporting documents required",
                            "timestamp": datetime.now().isoformat(),
                            "category": "GDRG_DETERMINATION",
                            "requires_manual_review": True,
                            "gdrg_code": "OPDC13A",
                            "special_case_type": "OPDC13A_SUPPORTING_DOCS"
                        }
                        
                        pipeline_results["stages_passed"].append({
                            "stage": "stage5_gdrg_determination",
                            "result": result_value,
                            "reason": f"{result.reason} - OPDC13A SPECIAL CASE",
                            "opdc13a_detected": True
                        })
                        
                        return ProcessingOutcome(
                            encounter_id=encounter_id,
                            overall_result=ValidationResult.FLAGGED,
                            processing_stage=ProcessingStage.GDRG_DETERMINATION,
                            reason="Stage 5 flagged: OPDC13A special case - Supporting documents required",
                            details={"stage5_details": result.details}
                        )
            
            if result_value in ["APPROVED", "FLAGGED"]:
                pipeline_results["stages_passed"].append({
                    "stage": "stage5_gdrg_determination",
                    "result": result_value,
                    "reason": result.reason,
                    "flagged": result_value == "FLAGGED"
                })
                
                outcome_result = ValidationResult.FLAGGED if result_value == "FLAGGED" else ValidationResult.APPROVED
                stage_reason = "Stage 5 passed: G-DRG determined" if result_value == "APPROVED" else "Stage 5 flagged: G-DRG requires manual review"
                
                return ProcessingOutcome(
                    encounter_id=encounter_id,
                    overall_result=outcome_result,
                    processing_stage=ProcessingStage.GDRG_DETERMINATION,
                    reason=stage_reason,
                    details={"stage5_details": result.details}
                )
            else:
                pipeline_results["stages_failed"].append({
                    "stage": "stage5_gdrg_determination",
                    "result": result_value,
                    "reason": result.reason
                })
                
                try:
                    result_enum = ValidationResult(result_value)
                except ValueError:
                    result_enum = ValidationResult.FLAGGED
                
                return ProcessingOutcome(
                    encounter_id=encounter_id,
                    overall_result=result_enum,
                    processing_stage=ProcessingStage.GDRG_DETERMINATION,
                    reason=f"Stage 5 failed: {result.reason}",
                    details={"stage5_details": result.details}
                )
        
        except Exception as e:
            logger.error(f"Error in Stage 5: {e}")
            return ProcessingOutcome(
                encounter_id=encounter_id,
                overall_result=ValidationResult.FLAGGED,
                processing_stage=ProcessingStage.GDRG_DETERMINATION,
                reason=f"Stage 5 error: {str(e)}"
            )
    
    async def _stage6_medicine_validation(self, encounter_id: str, pipeline_results: Dict) -> ProcessingOutcome:
        try:
            pipeline_results["stages_completed"].append("stage6_medicine_validation")
            pipeline_results["processing_path"].append("Medicine Validation")
            
            result = await self.medicine_validator.process_step6_medicine_validation(encounter_id)
            result_value = result.result.value if hasattr(result.result, 'value') else str(result.result)
            
            if result_value in ["APPROVED", "PARTIAL"]:
                pipeline_results["stages_passed"].append({
                    "stage": "stage6_medicine_validation",
                    "result": result_value,
                    "reason": result.reason
                })

            if result_value == "PARTIAL":
                pipeline_results["medicine_validation_result"] = "PARTIAL"
                logger.info(f"PARTIAL detected for {encounter_id}")
                
                return ProcessingOutcome(
                    encounter_id=encounter_id,
                    overall_result=ValidationResult.APPROVED,
                    processing_stage=ProcessingStage.MEDICINE_VALIDATION,
                    reason="Stage 6 passed: Medicine validation completed",
                    details={"stage6_details": result.details}
                )
            else:
                pipeline_results["stages_failed"].append({
                    "stage": "stage6_medicine_validation",
                    "result": result_value,
                    "reason": result.reason
                })
                
                try:
                    result_enum = ValidationResult(result_value)
                except ValueError:
                    result_enum = ValidationResult.FLAGGED
                
                return ProcessingOutcome(
                    encounter_id=encounter_id,
                    overall_result=result_enum,
                    processing_stage=ProcessingStage.MEDICINE_VALIDATION,
                    reason=f"Stage 6 failed: {result.reason}",
                    details={"stage6_details": result.details}
                )
        
        except Exception as e:
            logger.error(f"Error in Stage 6: {e}")
            return ProcessingOutcome(
                encounter_id=encounter_id,
                overall_result=ValidationResult.FLAGGED,
                processing_stage=ProcessingStage.MEDICINE_VALIDATION,
                reason=f"Stage 6 error: {str(e)}"
            )

    async def _stage7_final_processing_fixed(self, encounter_id: str, pipeline_results: Dict) -> ProcessingOutcome:
        try:
            pipeline_results["stages_completed"].append("stage7_final_processing_fixed")
            pipeline_results["processing_path"].append("Fixed Final Processing")
            
            # Check Stage 6 result first
            stage6_passed = pipeline_results.get("stages_passed", [])
            stage6_result = None
            for stage in stage6_passed:
                if stage.get("stage") == "stage6_medicine_validation":
                    stage6_result = stage.get("result")
                    break
            
            stage5_data = pipeline_results.get("stage5_comprehensive_results", {})
            stage6_data = pipeline_results.get("stage6_comprehensive_results", {})
            
            gdrg_tariff = float(stage5_data.get("selected_tariff", 0.0))
            selected_gdrg = stage5_data.get("selected_gdrg")
            medicine_approved = float(stage6_data.get("medicine_cost_approved", 0.0))
            medicine_denied = float(stage6_data.get("medicine_cost_denied", 0.0))
            has_rejections = stage6_data.get("has_rejections", False)
            
            # EARLY RETURN for PARTIAL - avoid logic overwrite
            if stage6_result == "PARTIAL":
                total_approved = gdrg_tariff + medicine_approved
                
                amounts = {
                    "gdrg_tariff": round(gdrg_tariff, 2),
                    "medicine_cost_approved": round(medicine_approved, 2),
                    "medicine_cost_denied": round(medicine_denied, 2),
                    "approved": round(total_approved, 2),
                    "partial": round(total_approved, 2),
                    "denied": round(medicine_denied, 2),
                    "total_claimed": round(total_approved + medicine_denied, 2)
                }
                
                pipeline_results["amounts"].update(amounts)
                pipeline_results["final_decision"] = "FINAL_PARTIALLY_APPROVED"
                
                logger.info(f"PARTIAL OVERRIDE for {encounter_id}:")
                logger.info(f"  G-DRG: {selected_gdrg} = {gdrg_tariff:.2f} GHS")
                logger.info(f"  Medicine Approved: {medicine_approved:.2f} GHS")
                logger.info(f"  Medicine Denied: {medicine_denied:.2f} GHS")
                logger.info(f"  Final Decision: FINAL_PARTIALLY_APPROVED")
                logger.info(f"  Total Approved: {total_approved:.2f} GHS")
                
                return ProcessingOutcome(
                    encounter_id=encounter_id,
                    overall_result=ValidationResult.PARTIAL,
                    processing_stage=ProcessingStage.FINAL_PROCESSING,
                    reason=f"Partially Approved: {total_approved:.2f} GHS approved, some medicines rejected",
                    details={
                        "stage7_details": {
                            "final_decision": "FINAL_PARTIALLY_APPROVED",
                            "decision_reason": f"Partially Approved: {total_approved:.2f} GHS approved, some medicines rejected",
                            "amounts": amounts,
                            "selected_gdrg": selected_gdrg,
                            "has_medicine_rejections": True,
                            "stage6_override": True,
                            "calculation_breakdown": {
                                "gdrg_component": f"{selected_gdrg} = {gdrg_tariff:.2f} GHS",
                                "medicine_approved": f"{medicine_approved:.2f} GHS",
                                "medicine_denied": f"{medicine_denied:.2f} GHS",
                                "total_approved": f"{total_approved:.2f} GHS"
                            },
                            "data_sources": {
                                "gdrg_source": "Stage 5 Comprehensive Extraction",
                                "medicine_source": "Stage 6 Comprehensive Extraction",
                                "override_reason": "Stage 6 returned PARTIAL"
                            }
                        }
                    }
                )
            
            total_approved = gdrg_tariff + medicine_approved
            total_denied = medicine_denied
            total_claimed = total_approved + total_denied
            
            if has_rejections or medicine_denied > 0:
                final_decision = "FINAL_PARTIALLY_APPROVED"
                result = ValidationResult.PARTIAL
                decision_reason = f"Partially Approved: {total_approved:.2f} GHS approved, {total_denied:.2f} GHS denied"
            elif total_approved > 0:
                final_decision = "FINAL_APPROVED"
                result = ValidationResult.APPROVED
                decision_reason = f"Fully Approved: {total_approved:.2f} GHS"
            else:
                final_decision = "FINAL_REJECTED"
                result = ValidationResult.REJECTED
                decision_reason = "Rejected: No approved amounts"
            
            amounts = {
                "gdrg_tariff": round(gdrg_tariff, 2),
                "medicine_cost_approved": round(medicine_approved, 2),
                "medicine_cost_denied": round(medicine_denied, 2),
                "approved": round(total_approved, 2) if result == ValidationResult.APPROVED else 0.0,
                "partial": round(total_approved, 2) if result == ValidationResult.PARTIAL else 0.0,
                "denied": round(total_denied, 2),
                "total_claimed": round(total_claimed, 2)
            }
            
            pipeline_results["amounts"].update(amounts)
            pipeline_results["final_decision"] = final_decision
            
            logger.info(f"FIXED FINAL CALCULATION for {encounter_id}:")
            logger.info(f"  G-DRG: {selected_gdrg} = {gdrg_tariff:.2f} GHS")
            logger.info(f"  Medicine Approved: {medicine_approved:.2f} GHS")
            logger.info(f"  Medicine Denied: {medicine_denied:.2f} GHS")
            logger.info(f"  Final Decision: {final_decision}")
            logger.info(f"  Total Approved: {total_approved:.2f} GHS")
            
            return ProcessingOutcome(
                encounter_id=encounter_id,
                overall_result=result,
                processing_stage=ProcessingStage.FINAL_PROCESSING,
                reason=f"Fixed final processing: {decision_reason}",
                details={
                    "stage7_details": {
                        "final_decision": final_decision,
                        "decision_reason": decision_reason,
                        "amounts": amounts,
                        "selected_gdrg": selected_gdrg,
                        "has_medicine_rejections": has_rejections,
                        "calculation_breakdown": {
                            "gdrg_component": f"{selected_gdrg} = {gdrg_tariff:.2f} GHS",
                            "medicine_approved": f"{medicine_approved:.2f} GHS",
                            "medicine_denied": f"{medicine_denied:.2f} GHS",
                            "total_approved": f"{total_approved:.2f} GHS"
                        },
                        "data_sources": {
                            "gdrg_source": "Stage 5 Comprehensive Extraction",
                            "medicine_source": "Stage 6 Comprehensive Extraction",
                            "fallback_used": False
                        }
                    }
                }
            )
            
        except Exception as e:
            logger.error(f"Error in fixed final processing: {e}")
            return ProcessingOutcome(
                encounter_id=encounter_id,
                overall_result=ValidationResult.PENDING,
                processing_stage=ProcessingStage.FINAL_PROCESSING,
                reason="PEND: Error in fixed final processing",
                details={"error": str(e)}
            )
            
          
            
           
            
        except Exception as e:
            logger.error(f"Error in fixed final processing: {e}")
            return ProcessingOutcome(
                encounter_id=encounter_id,
                overall_result=ValidationResult.PENDING,
                processing_stage=ProcessingStage.FINAL_PROCESSING,
                reason="PEND: Error in fixed final processing",
                details={"error": str(e)}
            )

    def _is_stage_successful(self, stage_result: ProcessingOutcome) -> bool:
        if stage_result is None:
            return False
        
        result_value = None
        if hasattr(stage_result.overall_result, 'value'):
            result_value = stage_result.overall_result.value
        else:
            result_value = str(stage_result.overall_result)
        
        if result_value == "FLAGGED" and stage_result.details:
            
            if (stage_result.details.get('special_case_details') and 
                stage_result.details['special_case_details'].get('special_case_type') == 'OPDC13A_SUPPORTING_DOCS'):
                logger.warning(f"OPDC13A special case detected: Stopping processing for {stage_result.encounter_id}")
                return False
            
            # Check step results for special case
            step_results = stage_result.details.get('step_by_step_results', {})
            if step_results.get('special_case_triggered'):
                special_case_details = step_results.get('special_case_details', {})
                if special_case_details.get('special_case_type') == 'OPDC13A_SUPPORTING_DOCS':
                    logger.warning(f"OPDC13A detected in step results: Stopping processing for {stage_result.encounter_id}")
                    return False
            
            # Check stage5 details for OPDC13A
            stage5_details = stage_result.details.get('stage5_details', {})
            if stage5_details:
                gdrg_determination = stage5_details.get('gdrg_determination', {})
                if gdrg_determination and gdrg_determination.get('final_gdrg') == 'OPDC13A':
                    logger.warning(f"OPDC13A detected in G-DRG determination: Stopping processing for {stage_result.encounter_id}")
                    return False
        
        success_values = ["APPROVED", "FLAGGED", "PARTIAL"]
        return result_value in success_values

    def _extract_final_amounts(self, result: ProcessingOutcome, pipeline_results: Dict):
        try:
            if not result.details:
                logger.warning("No details in final processing result")
                return
            
            stage7_data = result.details.get('stage7_details')
            if not stage7_data:
                logger.warning("No stage7_details in final processing result")
                return
            
            if stage7_data.get('amounts'):
                final_amounts = stage7_data['amounts']
                pipeline_results["amounts"].update(final_amounts)
                logger.info(f"Extracted final amounts: {final_amounts}")
            
            if stage7_data.get('final_decision'):
                pipeline_results["final_decision"] = stage7_data['final_decision']
                logger.info(f"Final decision: {stage7_data['final_decision']}")
            
            logger.info(f"Final amounts in pipeline: {pipeline_results['amounts']}")
            
        except Exception as e:
            logger.error(f"Error extracting final amounts: {e}")
            logger.error(f"Stage7 result details: {result.details}")

    async def _verify_data_usage_comprehensive(self, pipeline_results: Dict, final_result: ProcessingOutcome, encounter_id: str) -> Dict:
        verification = {
            "gdrg_verification": "UNKNOWN",
            "medicine_verification": "UNKNOWN", 
            "partial_detection": "UNKNOWN",
            "overall_status": "UNKNOWN",
            "issues_found": []
        }
        
        try:
            stage5_data = pipeline_results.get("stage5_comprehensive_results", {})
            stage6_data = pipeline_results.get("stage6_comprehensive_results", {})
            
            if final_result.details and final_result.details.get('stage7_details', {}).get('amounts'):
                amounts = final_result.details['stage7_details']['amounts']
                
                # Verify G-DRG tariff usage
                stage5_tariff = stage5_data.get("selected_tariff", 0.0)
                final_gdrg_tariff = amounts.get("gdrg_tariff", 0.0)
                
                if abs(stage5_tariff - final_gdrg_tariff) <= 0.01:
                    verification["gdrg_verification"] = "PASSED"
                    logger.info(f"VERIFICATION PASSED: G-DRG tariff correctly used ({stage5_tariff} GHS)")
                else:
                    verification["gdrg_verification"] = "FAILED"
                    verification["issues_found"].append(f"G-DRG tariff mismatch: Stage 5 = {stage5_tariff}, Final = {final_gdrg_tariff}")
                    logger.error(f"VERIFICATION FAILED: G-DRG tariff mismatch!")
                    logger.error(f"  Stage 5 selected: {stage5_tariff} GHS")
                    logger.error(f"  Final used: {final_gdrg_tariff} GHS")
                
                # Verify medicine cost usage
                stage6_approved = stage6_data.get("medicine_cost_approved", 0.0)
                final_medicine = amounts.get("medicine_cost_approved", 0.0)
                
                if abs(stage6_approved - final_medicine) <= 0.01:
                    verification["medicine_verification"] = "PASSED"
                    logger.info(f"VERIFICATION PASSED: Medicine cost correctly used ({stage6_approved} GHS)")
                else:
                    verification["medicine_verification"] = "FAILED"
                    verification["issues_found"].append(f"Medicine cost mismatch: Stage 6 = {stage6_approved}, Final = {final_medicine}")
                    logger.error(f"VERIFICATION FAILED: Medicine cost mismatch!")
                    logger.error(f"  Stage 6 approved: {stage6_approved} GHS")
                    logger.error(f"  Final used: {final_medicine} GHS")
                
                # Verify partial detection
                has_rejections = stage6_data.get("has_rejections", False)
                final_decision = final_result.details.get('stage7_details', {}).get('final_decision', '')
                
                if has_rejections and "PARTIAL" in final_decision:
                    verification["partial_detection"] = "PASSED"
                    logger.info(f"VERIFICATION PASSED: PARTIAL correctly detected")
                elif not has_rejections and "PARTIAL" not in final_decision:
                    verification["partial_detection"] = "PASSED"
                    logger.info(f"VERIFICATION PASSED: No rejections, no PARTIAL detected")
                else:
                    verification["partial_detection"] = "FAILED"
                    verification["issues_found"].append(f"PARTIAL detection mismatch: Has rejections = {has_rejections}, Decision = {final_decision}")
                    logger.error(f"VERIFICATION FAILED: PARTIAL detection!")
                    logger.error(f"  Stage 6 has rejections: {has_rejections}")
                    logger.error(f"  Final decision: {final_decision}")
            
            if verification["gdrg_verification"] == "PASSED" and verification["medicine_verification"] == "PASSED" and verification["partial_detection"] == "PASSED":
                verification["overall_status"] = "PASSED"
            else:
                verification["overall_status"] = "FAILED"
            
            return verification
            
        except Exception as e:
            logger.error(f"Error in comprehensive verification: {e}")
            verification["overall_status"] = "ERROR"
            verification["issues_found"].append(f"Verification error: {str(e)}")
            return verification

    def _create_error_outcome(self, encounter_id: str, reason: str, stage: ProcessingStage, 
                            pipeline_results: Dict, start_time: float) -> ProcessingOutcome:
        processing_time = time.time() - start_time
        
        return ProcessingOutcome(
            encounter_id=encounter_id,
            overall_result=ValidationResult.FLAGGED,
            processing_stage=stage,
            reason=reason,
            processing_time_seconds=round(processing_time, 3),
            database_updated=False,
            details={
                "pipeline_results": pipeline_results,
                "error_stage": stage.value
            }
        )

    async def _finalize_with_database_update(self, encounter_id: str, processing_outcome: ProcessingOutcome,
                                            pipeline_results: Dict, start_time: float) -> ProcessingOutcome:
        try:
            logger.debug(f"Updating database for {encounter_id}")

            existing_duplicate_flag = pipeline_results.get("existing_duplicate_flag")
            self.database_updater._current_batch_id = pipeline_results.get("batch_id")

            if pipeline_results.get("flagged_at_stage"):
                processing_outcome.overall_result = ValidationResult.FLAGGED
                processing_outcome.reason = f"Flagged: Manual document review required"

                if processing_outcome.details is None:
                    processing_outcome.details = {}

                processing_outcome.details.update({
                    "flagged_at_stage": pipeline_results['flagged_at_stage'],
                    "flag_reason": pipeline_results.get('flag_reason', 'Issues detected'),
                    "requires_manual_review": True
                })
            
            if processing_outcome.overall_result == ValidationResult.FLAGGED:
                flagged_db_outcome = ProcessingOutcome(
                    encounter_id=encounter_id,
                    overall_result=ValidationResult.FLAGGED,
                    processing_stage=processing_outcome.processing_stage,
                    reason="Flagged: Manual review required",
                    details=processing_outcome.details
                )
                db_update_success = await self.database_updater.update_claim_processing_results(flagged_db_outcome)
            else:
                db_update_success = await self.database_updater.update_claim_processing_results(processing_outcome)
            
           # if db_update_success:
            #    await self._update_claim_status_to_processed(encounter_id, processing_outcome, pipeline_results, existing_duplicate_flag)
            
            processing_outcome.database_updated = db_update_success
            processing_outcome.processing_stage = ProcessingStage.DATABASE_UPDATE if db_update_success else ProcessingStage.COMPLETED
            
            pipeline_results["database_update_status"] = db_update_success
            
            total_time = time.time() - start_time
            processing_outcome.processing_time_seconds = round(total_time, 3)
            
            if processing_outcome.overall_result == ValidationResult.FLAGGED:
                logger.debug(f"Flagged claim completed for {encounter_id}: Manual review required (DB: {'success' if db_update_success else 'failed'}) in {total_time:.3f}s")
            else:
                logger.debug(f"Pipeline completed for {encounter_id}: {processing_outcome.overall_result.value} (DB: {'success' if db_update_success else 'failed'}) in {total_time:.3f}s")
            
            return processing_outcome
            
        except Exception as e:
            logger.error(f"Error during database update for {encounter_id}: {e}")
            
            processing_outcome.database_updated = False
            processing_outcome.processing_stage = ProcessingStage.COMPLETED
            
            if processing_outcome.details:
                processing_outcome.details["database_update_error"] = str(e)
                processing_outcome.details["database_updated"] = False
            
            return processing_outcome

    async def _update_claim_status_to_processed(self, encounter_id: str, processing_outcome: ProcessingOutcome, 
                                          pipeline_results: Dict, existing_duplicate_flag: Optional[Dict[str, Any]] = None):
        try:
            result_mapping = {
                ValidationResult.APPROVED: 'approved',
                ValidationResult.REJECTED: 'rejected', 
                ValidationResult.FLAGGED: 'flagged',
                ValidationResult.PARTIAL: 'partially_approved',
                ValidationResult.PENDING: 'pending'
            }
            
            processed_status = result_mapping.get(processing_outcome.overall_result, 'flagged')
            amounts = pipeline_results.get('amounts', {})
            
            amount_breakdown = {
                'total_claimed': amounts.get('total_claimed', 0.0),
                'approved': amounts.get('approved', 0.0),
                'rejected': amounts.get('rejected', 0.0),
                'pending': amounts.get('pending', 0.0),
                'flagged': amounts.get('flagged', 0.0),
                'gdrg_tariff': amounts.get('gdrg_tariff', 0.0),
                'medicine_cost': amounts.get('medicine_cost', 0.0)
            }
            
            validation_results = {
                'overall_result': processing_outcome.overall_result.value,
                'processing_time_seconds': processing_outcome.processing_time_seconds,
                'stages_completed': pipeline_results.get('stages_completed', []),
                'stages_passed': pipeline_results.get('stages_passed', []),
                'enhanced_validations': pipeline_results.get('enhanced_validations', {}),
                'processing_path': pipeline_results.get('processing_path', [])
            }
            
            total_approved = amount_breakdown['approved'] if processed_status == 'approved' else 0.0
            total_rejected = amount_breakdown['rejected'] if processed_status == 'rejected' else 0.0
            total_flagged = amount_breakdown['flagged'] if processed_status == 'flagged' else 0.0
            total_pending = amount_breakdown['pending'] if processed_status == 'partially_approved' else 0.0
            
            rejection_reasons = None
            flag_reasons = None
            clinical_flags = None
            review_required = False
            
            if processed_status == 'flagged':
                if existing_duplicate_flag:
                    logger.info(f"Preserving existing duplicate flag reason for {encounter_id}")
                    flag_reasons = None
                else:
                    flag_reasons = {
                        'reason': processing_outcome.reason,
                        'details': pipeline_results,
                        'flagged_at_stage': pipeline_results.get('flagged_at_stage'),
                        'flag_reason': pipeline_results.get('flag_reason')
                    }
                    clinical_flags = pipeline_results.get('enhanced_validations', {})
                    review_required = True
            elif processed_status == 'rejected':
                rejection_reasons = {
                    'reason': processing_outcome.reason,
                    'details': pipeline_results,
                    'failed_stage': pipeline_results.get('stages_failed', [])[-1] if pipeline_results.get('stages_failed') else None
                }

            if existing_duplicate_flag and processed_status == 'flagged':
                query = """
                UPDATE claims_v3 
                SET claim_status = 'processed',
                    processed_status = $2,
                    total_claimed_amount = $3,
                    total_approved_amount = $4,
                    total_rejected_amount = $5,
                    total_pending_amount = $6,
                    total_flagged_amount = $7,
                    amount_breakdown = $8,
                    validation_results = $9,
                    rejection_reasons = $10,
                    clinical_flags = $11,
                    processing_engine_version = 'v2.0',
                    processed_by = 'NHIS_EXPERT_SYSTEM',
                    auto_processed = true,
                    review_required = $12,
                    processing_completed_at = CURRENT_TIMESTAMP,
                    updated_at = CURRENT_TIMESTAMP
                WHERE encounter_id = $1
                """
                
                await self.queries.db.execute(
                    query,
                    encounter_id,
                    processed_status,
                    amount_breakdown['total_claimed'],
                    total_approved,
                    total_rejected,
                    total_pending,
                    total_flagged,
                    json.dumps(amount_breakdown),
                    json.dumps(validation_results),
                    json.dumps(rejection_reasons) if rejection_reasons else None,
                    json.dumps(clinical_flags) if clinical_flags else None,
                    review_required
                )
            else:
                query = """
                UPDATE claims_v3 
                SET claim_status = 'processed',
                    processed_status = $2,
                    total_claimed_amount = $3,
                    total_approved_amount = $4,
                    total_rejected_amount = $5,
                    total_pending_amount = $6,
                    total_flagged_amount = $7,
                    amount_breakdown = $8,
                    validation_results = $9,
                    rejection_reasons = $10,
                    flag_reasons = $11,
                    clinical_flags = $12,
                    processing_engine_version = 'v2.0',
                    processed_by = 'NHIS_EXPERT_SYSTEM',
                    auto_processed = true,
                    review_required = $13,
                    processing_completed_at = CURRENT_TIMESTAMP,
                    updated_at = CURRENT_TIMESTAMP
                WHERE encounter_id = $1
                """
                await self.queries.db.execute(
                    query,
                    encounter_id,
                    processed_status,
                    amount_breakdown['total_claimed'],
                    total_approved,
                    total_rejected,
                    total_pending,
                    total_flagged,
                    json.dumps(amount_breakdown),
                    json.dumps(validation_results),
                    json.dumps(rejection_reasons) if rejection_reasons else None,
                    json.dumps(flag_reasons) if flag_reasons else None,
                    json.dumps(clinical_flags) if clinical_flags else None,
                    review_required
                )
            logger.debug(f"Claim {encounter_id} status updated: claim_status='processed', processed_status='{processed_status}' (preserved duplicate flag: {existing_duplicate_flag is not None})")
            
        except Exception as e:
            logger.error(f"Error updating claim status for {encounter_id}: {e}")
            raise

    async def process_all_batches(self) -> List[BatchInfo]:
        try:
            batch_ids = await self.get_batches_to_process()
            
            if not batch_ids:
                logger.info("No batches with submitted claims found for processing")
                return []
            
            logger.info(f"Starting automated processing of {len(batch_ids)} batches")
            
            processed_batches = []
            
            for i, batch_id in enumerate(batch_ids, 1):
                try:
                    logger.info(f"Processing batch {i}/{len(batch_ids)}: {batch_id}")
                    
                    batch_info = await self.process_batch(batch_id)
                    processed_batches.append(batch_info)
                    
                    logger.info(f"Batch {batch_id} completed: {batch_info.approved_claims} approved, "
                              f"{batch_info.rejected_claims} rejected, {batch_info.flagged_claims} flagged, "
                              f"{batch_info.partial_claims} partial, {batch_info.error_claims} errors")
                
                except Exception as e:
                    logger.error(f"Error processing batch {batch_id}: {e}")
                    
                    error_batch = BatchInfo(
                        batch_id=batch_id,
                        total_claims=0,
                        error_claims=1,
                        end_time=datetime.now()
                    )
                    processed_batches.append(error_batch)
            
            total_claims = sum(batch.total_claims for batch in processed_batches)
            total_approved = sum(batch.approved_claims for batch in processed_batches)
            total_rejected = sum(batch.rejected_claims for batch in processed_batches)
            total_flagged = sum(batch.flagged_claims for batch in processed_batches)
            total_partial = sum(batch.partial_claims for batch in processed_batches)
            total_errors = sum(batch.error_claims for batch in processed_batches)
            
            logger.info(f"All batches processing completed:")
            logger.info(f"  Total Batches: {len(processed_batches)}")
            logger.info(f"  Total Claims: {total_claims}")
            logger.info(f"  Approved: {total_approved}")
            logger.info(f"  Rejected: {total_rejected}")
            logger.info(f"  Flagged: {total_flagged}")
            logger.info(f"  Partial: {total_partial}")
            logger.info(f"  Errors: {total_errors}")
            
            approval_rate = (total_approved / total_claims * 100) if total_claims > 0 else 0
            logger.info(f"  Overall Approval Rate: {approval_rate:.1f}%")
            
            return processed_batches
            
        except Exception as e:
            logger.error(f"Error in automated batch processing: {e}")
            return []

    async def process_specific_batch(self, batch_id: str) -> BatchInfo:
        try:
            logger.info(f"Starting processing of specific batch: {batch_id}")
            
            batch_info = await self.process_batch(batch_id)
            
            logger.info(f"Batch {batch_id} processing completed:")
            logger.info(f"  Total Claims: {batch_info.total_claims}")
            logger.info(f"  Approved: {batch_info.approved_claims}")
            logger.info(f"  Rejected: {batch_info.rejected_claims}")
            logger.info(f"  Flagged: {batch_info.flagged_claims}")
            logger.info(f"  Partial: {batch_info.partial_claims}")
            logger.info(f"  Errors: {batch_info.error_claims}")
            
            return batch_info
            
        except Exception as e:
            logger.error(f"Error processing specific batch {batch_id}: {e}")
            return BatchInfo(
                batch_id=batch_id,
                total_claims=0,
                error_claims=1,
                end_time=datetime.now()
            )


async def main():
    processor = AutomatedBatchProcessor()
    
    try:
        await processor.initialize()
        
        logger.info("NHIS Automated Batch Claims Processor Started")
        logger.info("Processing all batches with submitted claims...")
        
        processed_batches = await processor.process_all_batches()
        
        if processed_batches:
            logger.info(f"Processing completed for {len(processed_batches)} batches")
        else:
            logger.info("No batches were processed")
        
    except Exception as e:
        logger.error(f"Critical error in automated processing: {e}")
        raise
    
    finally:
        await processor.close()


async def process_specific_batch_main(batch_id: str):
    processor = AutomatedBatchProcessor()
    
    try:
        await processor.initialize()
        
        logger.info(f"NHIS Automated Batch Claims Processor Started for batch: {batch_id}")
        
        batch_info = await processor.process_specific_batch(batch_id)
        
        return batch_info
        
    except Exception as e:
        logger.error(f"Critical error processing batch {batch_id}: {e}")
        raise
    
    finally:
        await processor.close()


if __name__ == "__main__":
    import sys
    
    if len(sys.argv) > 1:
        batch_id = sys.argv[1]
        logger.info(f"Processing specific batch: {batch_id}")
        asyncio.run(process_specific_batch_main(batch_id))
    else:
        logger.info("Processing all available batches")
        asyncio.run(main())