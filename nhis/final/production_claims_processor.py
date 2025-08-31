import asyncio
import json
import logging
from typing import Dict, List, Optional, Any, Tuple
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

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class ProcessingStage(Enum):
    """Processing stages in the pipeline"""
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
    """Validation outcomes"""
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    FLAGGED = "FLAGGED"
    PENDING = "PENDING"
    PARTIAL = "PARTIAL"

@dataclass
class ProcessingOutcome:
    """Complete processing result"""
    encounter_id: str
    overall_result: ValidationResult
    processing_stage: ProcessingStage
    reason: str
    details: Dict[str, Any] = None
    timestamp: datetime = None
    processing_time_seconds: float = 0.0
    database_updated: bool = False
    
    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.now()

@dataclass
class BatchInfo:
    """Batch processing information"""
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
    start_time: datetime = None
    end_time: datetime = None
    duplicate_detection_time: datetime = None
    
    def __post_init__(self):
        if self.start_time is None:
            self.start_time = datetime.now()

class AutomatedBatchProcessor:
    """
    Automated batch claims processor that processes claims by batch_id
    with claim_status = 'submitted' without user interaction
    """
    
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
        """Initialize all validators and database connections"""
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
        """Close all validators and database connections"""
        for validator in self.validators:
            await validator.close()
        
        await close_database()
        self.is_initialized = False
        logger.info("Automated Batch Processor closed")
    
    async def get_batches_to_process(self) -> List[str]:
        """Get list of batch_ids that have claims with status 'submitted'"""
        try:
            if not self.is_initialized:
                await self.initialize()
            
            query = """
            SELECT DISTINCT batch_id, COUNT(*) as claim_count
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
        """Get all encounter_ids for a specific batch with status 'submitted'"""
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


    async def process_batch(self, batch_id: str) -> BatchInfo:
        """Process all claims in a specific batch"""
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
            
            batch_info.clean_claims = len(clean_encounter_ids)

            logger.info(f"VALIDATION PROCESSING: Starting for {len(clean_encounter_ids)} clean claims")
            
            
            await self._update_batch_processing_status(batch_id, "processing")
            
            # Process each claim
            for i, encounter_id in enumerate(encounter_ids, 1):
                try:
                    logger.info(f"Processing claim {i}/{len(encounter_ids)}: {encounter_id}")
                    
                    result = await self.process_complete_claim(encounter_id)
                    
                    # Update batch statistics
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
                    
                    # Log progress
                    if i % 10 == 0 or i == len(encounter_ids):
                        progress = (i / len(encounter_ids)) * 100
                        logger.info(f"Batch {batch_id} progress: {i}/{len(encounter_ids)} ({progress:.1f}%)")
                
                except Exception as e:
                    logger.error(f"Error processing claim {encounter_id} in batch {batch_id}: {e}")
                    batch_info.error_claims += 1
            
            batch_info.end_time = datetime.now()
            processing_time = (batch_info.end_time - batch_info.start_time).total_seconds()
            logger.info(f"Batch {batch_id} processing time: {processing_time:.1f}s")

            # Update batch status to completed
            await self._update_batch_processing_status(batch_id, "completed")
            
            logger.info(f"Batch {batch_id} processing completed:")
            logger.info(f"  Total Claims: {batch_info.total_claims}")
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
            duplicate_report = await run_duplicate_detection_stage(encounter_ids)

            if "error" in duplicate_report:
                logger.error(f"Duplicate detection failed for batch {batch_id}: {duplicate_report['error']}")
                raise Exception(f"Duplicate detection failed: {duplicate_report['error']}")
            
            stats = duplicate_report["summary_statistics"]
            database_updates = duplicate_report["database_updates"]

            batch_info.clean_claims = stats["clean_claims"]
            batch_info.duplicate_flagged_claims = stats["flagged_claims"]
            batch_info.duplicate_blocked_claims = stats["blocked_claims"]
            batch_info.duplicate_detection_completed = True
            batch_info.duplicate_detection_time = datetime.now()

            logger.info(f"DUPLICATE DETECTION COMPLETED for batch {batch_id}:")
            logger.info(f"  Clean Claims: {stats['clean_claims']}")
            logger.info(f"  Flagged Claims: {stats['flagged_claims']}")
            logger.info(f"  Blocked Claims: {stats['blocked_claims']}")
            logger.info(f"  Error Claims: {stats.get('error_claims', 0)}")
            logger.info(f"  Duplicate Detection Rate: {stats['duplicate_detection_rate']}%")

            if database_updates["flagged_claims"]:
                logger.info("FLAGGED CLAIMS WITH REASONS:")
                for flagged in database_updates["flagged_claims"]:
                    logger.info(f"  {flagged['encounter_id']}: {flagged['reason']} (Confidence: {flagged['confidence']:.3f})")

            if database_updates["blocked_claims"]:
                logger.info("BLOCKED CLAIMS WITH REASONS:")
                for blocked in database_updates["blocked_claims"]:
                    logger.info(f"  {blocked['encounter_id']}: {blocked['reason']} (Confidence: {blocked['confidence']:.3f})")

            if duplicate_report.get("high_confidence_duplicates"):
                logger.warning("HIGH CONFIDENCE DUPLICATES DETECTED:")
                for dup in duplicate_report["high_confidence_duplicates"]:
                    logger.warning(f"  {dup['primary_encounter']} <-> {dup['duplicate_encounter']} ({dup['type']}, {dup['confidence']:.3f})")


            for rec in duplicate_report.get("recommendations", []):
                logger.info(f"RECOMMENDATION: {rec}")

            logger.info(f"DUPLICATE DETECTION PHASE COMPLETE for batch {batch_id}")
            logger.info(f"Ready to proceed with validation for {stats['clean_claims']} clean claims")

        except Exception as e:
            logger.error(f"Error in duplicate detection phase for batch {batch_id}: {e}")
            raise
    

    async def _update_batch_processing_status(self, batch_id: str, status: str):
        """Update the processing status of all claims in a batch"""
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
    
    async def process_complete_claim(self, encounter_id: str) -> ProcessingOutcome:
        """Process a single claim through the complete pipeline"""
        if not self.is_initialized:
            await self.initialize()
        
        start_time = time.time()
        
        # Enhanced pipeline tracking
        pipeline_results = {
            "encounter_id": encounter_id,
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
                "total_claimed": 0.0
            },
            "financial_components": {
                "gdrg_tariff": 0.0,
                "medicine_cost": 0.0,
                "investigation_cost": 0.0,
                "modifier_multiplier": 1.0
            },
            "stage_data": {},
            "enhanced_validations": {},
            "database_update_status": False
        }
        
        try:
            logger.debug(f"Starting complete processing pipeline for {encounter_id}")
            
            # STAGE 1: INITIAL PROCESSING
            stage_result = await self._stage1_initial_processing(encounter_id, pipeline_results)
            
            if not self._is_stage_successful(stage_result):
                logger.debug(f"Stage 1 failed for {encounter_id}: {stage_result.reason}")
                return await self._finalize_with_database_update(encounter_id, stage_result, pipeline_results, start_time)
            
            encounter_type = stage_result.details.get('encounter_type')
            if not encounter_type:
                error_outcome = self._create_error_outcome(encounter_id, "No encounter type determined", 
                                                        ProcessingStage.INITIAL_PROCESSING, pipeline_results, start_time)
                return await self._finalize_with_database_update(encounter_id, error_outcome, pipeline_results, start_time)
            
            # STAGE 2: ENHANCED VALIDATIONS
            stage_result = await self._stage2_enhanced_validations(encounter_id, pipeline_results)
            
            if not self._is_stage_successful(stage_result):
                logger.debug(f"Stage 2 enhanced validations failed for {encounter_id}: {stage_result.reason}")
                return await self._finalize_with_database_update(encounter_id, stage_result, pipeline_results, start_time)
            
            # STAGE 3: ENCOUNTER-SPECIFIC FLOW
            stage_result = await self._stage3_encounter_flow(encounter_id, encounter_type, pipeline_results)
            
            if not self._is_stage_successful(stage_result):
                logger.debug(f"Stage 3 encounter flow failed for {encounter_id}: {stage_result.reason}")
                return await self._finalize_with_database_update(encounter_id, stage_result, pipeline_results, start_time)
            
            # STAGE 4: CREDENTIALING
            stage_result = await self._stage4_credentialing(encounter_id, pipeline_results)
            
            if not self._is_stage_successful(stage_result):
                logger.debug(f"Stage 4 credentialing failed for {encounter_id}: {stage_result.reason}")
                return await self._finalize_with_database_update(encounter_id, stage_result, pipeline_results, start_time)
            
            # STAGE 5: G-DRG DETERMINATION
            stage_result = await self._stage5_gdrg_determination(encounter_id, pipeline_results)
            
            if not self._is_stage_successful(stage_result):
                logger.debug(f"Stage 5 G-DRG determination failed for {encounter_id}: {stage_result.reason}")
                return await self._finalize_with_database_update(encounter_id, stage_result, pipeline_results, start_time)
            
            # Extract G-DRG tariff from Stage 5 results
            self._extract_gdrg_tariff(stage_result, pipeline_results)
            
            # STAGE 6: MEDICINE VALIDATION
            stage_result = await self._stage6_medicine_validation(encounter_id, pipeline_results)
            
            if not self._is_stage_successful(stage_result):
                logger.debug(f"Stage 6 medicine validation failed for {encounter_id}: {stage_result.reason}")
                return await self._finalize_with_database_update(encounter_id, stage_result, pipeline_results, start_time)
            
            # Extract medicine cost from Stage 6 results
            self._extract_medicine_cost(stage_result, pipeline_results)
            
            # STAGE 7: FINAL PROCESSING
            stage_result = await self._stage7_final_processing(encounter_id, pipeline_results)
            
            # Extract final amounts from Stage 7
            self._extract_final_amounts(stage_result, pipeline_results)
            
            # Calculate total processing time
            processing_time = time.time() - start_time
            
            # Create final outcome BEFORE database update
            final_outcome = ProcessingOutcome(
                encounter_id=encounter_id,
                overall_result=stage_result.overall_result,
                processing_stage=ProcessingStage.COMPLETED,
                reason=f"Pipeline completed: {stage_result.reason}",
                processing_time_seconds=round(processing_time, 3),
                database_updated=False,
                details={
                    "encounter_type": encounter_type,
                    "enhanced_validations": pipeline_results.get("enhanced_validations", {}),
                    "final_decision": pipeline_results.get("final_decision"),
                    "amounts": pipeline_results.get("amounts", {}),
                    "financial_components": pipeline_results.get("financial_components", {}),
                    "comprehensive_results": pipeline_results
                }
            )
            
            # STAGE 8: DATABASE UPDATE
            return await self._finalize_with_database_update(encounter_id, final_outcome, pipeline_results, start_time)
                
        except Exception as e:
            processing_time = time.time() - start_time
            logger.error(f"Pipeline error for {encounter_id}: {e}")
            
            error_outcome = ProcessingOutcome(
                encounter_id=encounter_id,
                overall_result=ValidationResult.FLAGGED,
                processing_stage=ProcessingStage.INITIAL_PROCESSING,
                reason=f"Pipeline error: {str(e)}",
                processing_time_seconds=round(processing_time, 3),
                database_updated=False,
                details={
                    "error": str(e),
                    "pipeline_results": pipeline_results
                }
            )
            
            return await self._finalize_with_database_update(encounter_id, error_outcome, pipeline_results, start_time)
    
    async def _finalize_with_database_update(self, encounter_id: str, processing_outcome: ProcessingOutcome, 
                                           pipeline_results: Dict, start_time: float) -> ProcessingOutcome:
        """Finalize processing with database update"""
        try:
            logger.debug(f"Updating database for {encounter_id}")

            if pipeline_results.get("flagged_at_stage"):
                processing_outcome.overall_result = ValidationResult.FLAGGED
                processing_outcome.reason = f"Flagged: Manual review required"

                if processing_outcome.details is None:
                    processing_outcome.details = {}

                processing_outcome.details.update({
                    "flagged_at_stage": pipeline_results['flagged_at_stage'],
                    "flag_reason": pipeline_results.get('flag_reason', 'Issues detected'),
                    "requires_manual_review": True
                })
            
            # Update database with results using the database updater
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
            
            # CRITICAL: Update claim_status to 'processed' after successful processing
            if db_update_success:
                await self._update_claim_status_to_processed(encounter_id, processing_outcome, pipeline_results)
            
            # Update the outcome with database status
            processing_outcome.database_updated = db_update_success
            processing_outcome.processing_stage = ProcessingStage.DATABASE_UPDATE if db_update_success else ProcessingStage.COMPLETED
            
            pipeline_results["database_update_status"] = db_update_success
            
            # Final processing time including database update
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
    
    async def _update_claim_status_to_processed(self, encounter_id: str, processing_outcome: ProcessingOutcome, pipeline_results: Dict):
        """Update claim_status to 'processed' and set processed_status with proper reasons"""
        try:
            # Map ValidationResult to database processed_status values
            result_mapping = {
                ValidationResult.APPROVED: 'approved',
                ValidationResult.REJECTED: 'rejected', 
                ValidationResult.FLAGGED: 'flagged',
                ValidationResult.PARTIAL: 'partially_approved',
                ValidationResult.PENDING: 'pending'
            }
            
            processed_status = result_mapping.get(processing_outcome.overall_result, 'flagged')
            amounts = pipeline_results.get('amounts', {})
            
            # Build amount breakdown
            amount_breakdown = {
                'total_claimed': amounts.get('total_claimed', 0.0),
                'approved': amounts.get('approved', 0.0),
                'rejected': amounts.get('rejected', 0.0),
                'pending': amounts.get('pending', 0.0),
                'flagged': amounts.get('flagged', 0.0),
                'gdrg_tariff': amounts.get('gdrg_tariff', 0.0),
                'medicine_cost': amounts.get('medicine_cost', 0.0)
            }
            
            # Build validation results
            validation_results = {
                'overall_result': processing_outcome.overall_result.value,
                'processing_time_seconds': processing_outcome.processing_time_seconds,
                'stages_completed': pipeline_results.get('stages_completed', []),
                'stages_passed': pipeline_results.get('stages_passed', []),
                'enhanced_validations': pipeline_results.get('enhanced_validations', {}),
                'processing_path': pipeline_results.get('processing_path', [])
            }
            
            # Set amounts based on result
            total_approved = amount_breakdown['approved'] if processed_status == 'approved' else 0.0
            total_rejected = amount_breakdown['rejected'] if processed_status == 'rejected' else 0.0
            total_flagged = amount_breakdown['flagged'] if processed_status == 'flagged' else 0.0
            total_pending = amount_breakdown['pending'] if processed_status == 'partially_approved' else 0.0
            
            # Build rejection/flag reasons
            rejection_reasons = None
            flag_reasons = None
            clinical_flags = None
            review_required = False
            
            if processed_status == 'rejected':
                rejection_reasons = {
                    'reason': processing_outcome.reason, 
                    'details': pipeline_results,
                    'failed_stage': pipeline_results.get('stages_failed', [])[-1] if pipeline_results.get('stages_failed') else None
                }
            elif processed_status == 'flagged':
                flag_reasons = {
                    'reason': processing_outcome.reason, 
                    'details': pipeline_results,
                    'flagged_at_stage': pipeline_results.get('flagged_at_stage'),
                    'flag_reason': pipeline_results.get('flag_reason')
                }
                clinical_flags = pipeline_results.get('enhanced_validations', {})
                review_required = True
            
            # CRITICAL UPDATE: Change claim_status to 'processed' and set all required fields
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
            
            logger.debug(f"Claim {encounter_id} status updated: claim_status='processed', processed_status='{processed_status}'")
            
        except Exception as e:
            logger.error(f"Error updating claim status for {encounter_id}: {e}")
            raise
    
    def _is_stage_successful(self, stage_result: ProcessingOutcome) -> bool:
        """Determine if a stage result indicates success"""
        if stage_result is None:
            return False
        
        result_value = None
        if hasattr(stage_result.overall_result, 'value'):
            result_value = stage_result.overall_result.value
        else:
            result_value = str(stage_result.overall_result)
        
        # Check for OPDC13A special case that should stop processing
        if result_value == "FLAGGED" and stage_result.details:
            # Check for OPDC13A special case
            if (stage_result.details.get('special_case_details') and 
                stage_result.details['special_case_details'].get('special_case_type') == 'OPDC13A_SUPPORTING_DOCS'):
                logger.warning(f"OPDC13A special case detected: Stopping processing for {stage_result.encounter_id}")
                return False
            
            # Check step-by-step results
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
        
        # For non-OPDC13A cases, continue with normal logic
        success_values = ["APPROVED", "FLAGGED", "PARTIAL"]
        return result_value in success_values
    
    def _create_error_outcome(self, encounter_id: str, reason: str, stage: ProcessingStage, 
                            pipeline_results: Dict, start_time: float) -> ProcessingOutcome:
        """Helper method to create standardized error outcomes"""
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
    
    def _extract_gdrg_tariff(self, result: Dict, pipeline_results: Dict):
        """Extract G-DRG tariff from stage 5 results"""
        if not result.details:
            return
        
        details = result.details
        stage5_details = details.get('stage5_details') or details
        
        selected_tariff = 0.0
        
        if stage5_details.get('selected_tariff'):
            selected_tariff = float(stage5_details['selected_tariff'])
        elif stage5_details.get('evaluation_summary', {}).get('winning_tariff'):
            selected_tariff = float(stage5_details['evaluation_summary']['winning_tariff'])
        elif stage5_details.get('gdrg_summary', {}).get('tariff_amount'):
            selected_tariff = float(stage5_details['gdrg_summary']['tariff_amount'])
        
        if selected_tariff > 0:
            pipeline_results["financial_components"]["gdrg_tariff"] = selected_tariff
            pipeline_results["amounts"]["gdrg_tariff"] = selected_tariff
    
    def _extract_medicine_cost(self, result: ProcessingOutcome, pipeline_results: Dict):
        """Extract medicine cost from stage 6 results"""
        try:
            if not result.details:
                logger.warning("No details in medicine validation result")
                return
            
            stage6_data = result.details.get('stage6_details')
            if not stage6_data:
                logger.warning("No stage6_details in medicine validation result")
                return
            
            # Try multiple extraction paths
            medicine_cost = 0.0
            
            # Path 1: Direct total_medicine_cost
            if stage6_data.get('total_medicine_cost'):
                medicine_cost = float(stage6_data['total_medicine_cost'])
                logger.info(f"Extracted medicine cost (direct): {medicine_cost} GHS")
            
            # Path 2: Sum from medicine_breakdown
            elif stage6_data.get('medicine_breakdown'):
                breakdown = stage6_data['medicine_breakdown']
                approved_cost = breakdown.get('total_approved_cost', 0.0)
                partial_cost = breakdown.get('total_partial_cost', 0.0)
                medicine_cost = float(approved_cost) + float(partial_cost)
                logger.info(f"Extracted medicine cost (breakdown): approved={approved_cost}, partial={partial_cost}, total={medicine_cost} GHS")
            
            # Path 3: From medicines list
            elif stage6_data.get('medicines'):
                total_cost = 0.0
                for med in stage6_data['medicines']:
                    if isinstance(med, dict):
                        med_cost = med.get('approved_cost', 0.0) or med.get('calculated_cost', 0.0) or med.get('cost', 0.0)
                        total_cost += float(med_cost) if med_cost else 0.0
                medicine_cost = total_cost
                logger.info(f"Extracted medicine cost (medicines list): {medicine_cost} GHS")
            
            if medicine_cost > 0:
                pipeline_results["financial_components"]["medicine_cost"] = medicine_cost
                pipeline_results["amounts"]["medicine_cost"] = medicine_cost
                pipeline_results["stage_data"]["stage6_medicine_validation"] = {
                    "total_medicine_cost": medicine_cost,
                    "source": "extracted_from_stage6"
                }
                logger.info(f"Successfully captured medicine cost: {medicine_cost} GHS")
            else:
                logger.warning("Medicine cost extraction resulted in 0.0 - no valid medicine costs found")
                logger.debug(f"Stage6 data keys: {list(stage6_data.keys()) if stage6_data else 'None'}")
                
        except Exception as e:
            logger.error(f"Error extracting medicine cost: {e}")
            logger.error(f"Stage6 result details: {result.details}")
    
    
    def _extract_final_amounts(self, result: ProcessingOutcome, pipeline_results: Dict):
        """Extract final amounts from stage 7 results"""
        try:
            if not result.details:
                logger.warning("No details in final processing result")
                return
            
            stage7_data = result.details.get('stage7_details')
            if not stage7_data:
                logger.warning("No stage7_details in final processing result")
                return
            
            # Extract final amounts
            if stage7_data.get('amounts'):
                final_amounts = stage7_data['amounts']
                pipeline_results["amounts"].update(final_amounts)
                logger.info(f"Extracted final amounts: {final_amounts}")
            
            # Extract final decision
            if stage7_data.get('final_decision'):
                pipeline_results["final_decision"] = stage7_data['final_decision']
                logger.info(f"Final decision: {stage7_data['final_decision']}")
            
            # Log what we extracted
            logger.info(f"Final amounts in pipeline: {pipeline_results['amounts']}")
            
        except Exception as e:
            logger.error(f"Error extracting final amounts: {e}")
            logger.error(f"Stage7 result details: {result.details}")
    
    
    # Individual stage processing methods (simplified versions of the original)
    
    async def _stage1_initial_processing(self, encounter_id: str, pipeline_results: Dict) -> ProcessingOutcome:
        """Stage 1: Initial Processing"""
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
        """Stage 2: Enhanced Validations"""
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
            
            # Analyze enhanced validation results
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
        """Stage 3: Encounter-Specific Flow"""
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
        """Stage 4: Credentialing Check"""
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
        """Stage 5: G-DRG Determination with OPDC13A handling"""
        try:
            pipeline_results["stages_completed"].append("stage5_gdrg_determination")
            pipeline_results["processing_path"].append("G-DRG Determination")
            
            result = await self.gdrg_determiner.process_step5_gdrg_determination(encounter_id)
            result_value = result.result.value if hasattr(result.result, 'value') else str(result.result)

            if result_value == "FLAGGED":
                if not pipeline_results.get("flagged_at_stage"):
                    pipeline_results["flagged_at_stage"] = "stage5_gdrg_determination"
                    pipeline_results["flag_reason"] = result.reason
            
            # Check for OPDC13A special case
            if result_value == "FLAGGED" and result.details:
                # Check for OPDC13A in G-DRG determination
                gdrg_determination = result.details.get('gdrg_determination', {})
                if gdrg_determination and gdrg_determination.get('final_gdrg') == 'OPDC13A':
                    logger.warning(f"OPDC13A flagged - Will stop processing after this stage for {encounter_id}")
                    
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
                
                # Check step-by-step results for OPDC13A
                step_results = result.details.get('step_by_step_results', {})
                if step_results.get('special_case_triggered'):
                    special_case_details = step_results.get('special_case_details', {})
                    if special_case_details.get('special_case_type') == 'OPDC13A_SUPPORTING_DOCS':
                        logger.warning(f"OPDC13A special case flagged - Will stop processing after this stage for {encounter_id}")
                        
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
            
            # Handle successful results (APPROVED and non-OPDC13A FLAGGED)
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
        """Stage 6: Medicine Validation"""
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
    
    async def _stage7_final_processing(self, encounter_id: str, pipeline_results: Dict) -> ProcessingOutcome:
        """Stage 7: Final Processing"""
        try:
            pipeline_results["stages_completed"].append("stage7_final_processing")
            pipeline_results["processing_path"].append("Final Processing")
            
            result = await self.final_processor.process_final_validation(encounter_id, pipeline_results["stage_data"])
            
            # Extract financial information
            if result.details and result.details.get('amounts'):
                pipeline_results["amounts"] = result.details['amounts']
            
            if result.details and result.details.get('final_decision'):
                pipeline_results["final_decision"] = result.details['final_decision']
            
            result_value = result.result.value if hasattr(result.result, 'value') else str(result.result)
            pipeline_results["overall_result"] = result_value
            
            pipeline_results["stages_passed"].append({
                "stage": "stage7_final_processing",
                "result": result_value,
                "reason": result.reason
            })
            
            return ProcessingOutcome(
                encounter_id=encounter_id,
                overall_result=result.result,
                processing_stage=ProcessingStage.FINAL_PROCESSING,
                reason="Stage 7 completed: Final processing finished",
                details={"stage7_details": result.details}
            )
        
        except Exception as e:
            logger.error(f"Error in Stage 7: {e}")
            return ProcessingOutcome(
                encounter_id=encounter_id,
                overall_result=ValidationResult.FLAGGED,
                processing_stage=ProcessingStage.FINAL_PROCESSING,
                reason=f"Stage 7 error: {str(e)}"
            )
    
    async def process_all_batches(self) -> List[BatchInfo]:
        """Process all available batches automatically"""
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
                    
                    # Log batch completion
                    logger.info(f"Batch {batch_id} completed: {batch_info.approved_claims} approved, "
                              f"{batch_info.rejected_claims} rejected, {batch_info.flagged_claims} flagged, "
                              f"{batch_info.partial_claims} partial, {batch_info.error_claims} errors")
                
                except Exception as e:
                    logger.error(f"Error processing batch {batch_id}: {e}")
                    
                    # Create error batch info
                    error_batch = BatchInfo(
                        batch_id=batch_id,
                        total_claims=0,
                        error_claims=1,
                        end_time=datetime.now()
                    )
                    processed_batches.append(error_batch)
            
            # Summary statistics
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
        """Process a specific batch by batch_id"""
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
    """Main entry point for automated batch processing"""
    processor = AutomatedBatchProcessor()
    
    try:
        await processor.initialize()
        
        logger.info("NHIS Automated Batch Claims Processor Started")
        logger.info("Processing all batches with submitted claims...")
        
        # Process all available batches
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
    """Process a specific batch by batch_id"""
    processor = AutomatedBatchProcessor()
    
    try:
        await processor.initialize()
        
        logger.info(f"NHIS Automated Batch Claims Processor Started for batch: {batch_id}")
        
        # Process specific batch
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
        # Process specific batch if batch_id provided as argument
        batch_id = sys.argv[1]
        logger.info(f"Processing specific batch: {batch_id}")
        asyncio.run(process_specific_batch_main(batch_id))
    else:
        # Process all available batches
        logger.info("Processing all available batches")
        asyncio.run(main())