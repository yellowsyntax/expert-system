from typing import Dict, Any, Optional, List
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from .claim_processing_service import ClaimProcessingService
from ..database.repositories import (
    BatchRepository, ClaimV2Repository, ClaimDecisionRepository
)
from ..database.models.claim_batch import ClaimBatch
import logging

logger = logging.getLogger(__name__)


class BatchProcessingService:
    
    def __init__(self,
                 claim_processing_service: ClaimProcessingService,
                 batch_repo: BatchRepository,
                 claim_repo: ClaimV2Repository,
                 decision_repo: ClaimDecisionRepository,
                 max_workers: int = 4):
        
        self.claim_processing_service = claim_processing_service
        self.batch_repo = batch_repo
        self.claim_repo = claim_repo
        self.decision_repo = decision_repo
        self.max_workers = max_workers
    
    def process_batch(self, batch_id: str, parallel: bool = True) -> Dict[str, Any]:
        processing_start = datetime.utcnow()
        
        try:
            # Step 1: Retrieve batch from database
            batch = self.batch_repo.get_by_id(batch_id)
            if not batch:
                return self._create_error_result(batch_id, "Batch not found", processing_start)
            
            # Step 2: Update batch status to processing
            batch.status = 'processing'
            batch.processing_start_time = processing_start
            self.batch_repo.update(batch)
            
            # Step 3: Get all claims in the batch
            claims = self.claim_repo.get_by_batch_id(batch_id)
            if not claims:
                return self._create_error_result(batch_id, "No claims found in batch", processing_start)
            
            # Step 4: Process claims (parallel or sequential)
            if parallel and len(claims) > 1:
                processing_results = self._process_claims_parallel(claims)
            else:
                processing_results = self._process_claims_sequential(claims)
            
            # Step 5: Analyze batch results
            batch_summary = self._analyze_batch_results(processing_results)
            
            # Step 6: Update batch with final status and results
            self._finalize_batch(batch, batch_summary, processing_start)
            
            # Step 7: Return comprehensive batch result
            return self._create_success_result(
                batch_id, batch_summary, processing_results, processing_start
            )
            
        except Exception as e:
            logger.error(f"Error processing batch {batch_id}: {str(e)}")
            self._mark_batch_failed(batch_id, str(e))
            return self._create_error_result(batch_id, str(e), processing_start)
    
    def _process_claims_parallel(self, claims: List) -> List[Dict[str, Any]]:
        results = []
        
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            # Submit all claims for processing
            future_to_claim = {
                executor.submit(self.claim_processing_service.process_claim, claim.id): claim
                for claim in claims
            }
            
            # Collect results as they complete
            for future in as_completed(future_to_claim):
                claim = future_to_claim[future]
                try:
                    result = future.result()
                    result['claim_info'] = {
                        'claim_id': claim.id,
                        'facility_id': claim.facility_id,
                        'patient_id': getattr(claim, 'patient_id', None),
                        'service_date': claim.service_date.isoformat() if claim.service_date else None
                    }
                    results.append(result)
                except Exception as e:
                    logger.error(f"Error processing claim {claim.id}: {str(e)}")
                    results.append({
                        'status': 'error',
                        'claim_id': claim.id,
                        'error_message': str(e),
                        'claim_info': {
                            'claim_id': claim.id,
                            'facility_id': claim.facility_id,
                            'patient_id': getattr(claim, 'patient_id', None)
                        }
                    })
        
        return results
    
    def _process_claims_sequential(self, claims: List) -> List[Dict[str, Any]]:
        results = []
        
        for claim in claims:
            try:
                result = self.claim_processing_service.process_claim(claim.id)
                result['claim_info'] = {
                    'claim_id': claim.id,
                    'facility_id': claim.facility_id,
                    'patient_id': getattr(claim, 'patient_id', None),
                    'service_date': claim.service_date.isoformat() if claim.service_date else None
                }
                results.append(result)
            except Exception as e:
                logger.error(f"Error processing claim {claim.id}: {str(e)}")
                results.append({
                    'status': 'error',
                    'claim_id': claim.id,
                    'error_message': str(e),
                    'claim_info': {
                        'claim_id': claim.id,
                        'facility_id': claim.facility_id,
                        'patient_id': getattr(claim, 'patient_id', None)
                    }
                })
        
        return results
    
    def _analyze_batch_results(self, processing_results: List[Dict[str, Any]]) -> Dict[str, Any]:
        total_claims = len(processing_results)
        
        # Count by status
        status_counts = {
            'success': 0,
            'error': 0
        }
        
        # Count by decision type
        decision_counts = {
            'APPROVED': 0,
            'PARTIALLY_APPROVED': 0,
            'PENDING': 0,
            'REJECTED': 0,
            'ERROR': 0
        }
        
        # Sum amounts
        total_amounts = {
            'approved': 0.0,
            'denied': 0.0,
            'pending': 0.0,
            'total': 0.0
        }
        
        # Collect processing times
        processing_times = []
        errors = []
        
        for result in processing_results:
            # Status counting
            status = result.get('status', 'error')
            status_counts[status] = status_counts.get(status, 0) + 1
            
            # Decision counting
            if status == 'success':
                decision = result.get('processing_result', 'ERROR')
                decision_counts[decision] = decision_counts.get(decision, 0) + 1
                
                # Amount summing
                amounts = result.get('amounts', {})
                for amount_type in total_amounts:
                    total_amounts[amount_type] += amounts.get(amount_type, 0.0)
                
                # Processing time
                proc_time = result.get('processing_time_seconds', 0)
                processing_times.append(proc_time)
            else:
                decision_counts['ERROR'] += 1
                errors.append({
                    'claim_id': result.get('claim_id'),
                    'error': result.get('error_message', 'Unknown error')
                })
        
        # Calculate statistics
        avg_processing_time = sum(processing_times) / len(processing_times) if processing_times else 0
        max_processing_time = max(processing_times) if processing_times else 0
        
        # Determine overall batch status
        error_rate = status_counts['error'] / total_claims
        if error_rate == 0:
            batch_status = 'completed'
        elif error_rate < 0.1:  # Less than 10% errors
            batch_status = 'completed_with_errors'
        else:
            batch_status = 'failed'
        
        return {
            'batch_status': batch_status,
            'total_claims': total_claims,
            'status_counts': status_counts,
            'decision_counts': decision_counts,
            'total_amounts': total_amounts,
            'processing_statistics': {
                'average_processing_time': avg_processing_time,
                'max_processing_time': max_processing_time,
                'total_processing_time': sum(processing_times),
                'error_rate': error_rate
            },
            'errors': errors
        }
    
    def _finalize_batch(self, batch: ClaimBatch, batch_summary: Dict[str, Any], processing_start: datetime):
        processing_end = datetime.utcnow()
        total_processing_time = (processing_end - processing_start).total_seconds()
        
        batch.status = batch_summary['batch_status']
        batch.processing_end_time = processing_end
        batch.total_processing_time_seconds = total_processing_time
        
        # Update statistics
        batch.total_claims = batch_summary['total_claims']
        batch.approved_claims = batch_summary['decision_counts']['APPROVED']
        batch.rejected_claims = batch_summary['decision_counts']['REJECTED']
        batch.pending_claims = batch_summary['decision_counts']['PENDING']
        batch.error_claims = batch_summary['status_counts']['error']
        
        # Update amounts
        batch.total_approved_amount = batch_summary['total_amounts']['approved']
        batch.total_denied_amount = batch_summary['total_amounts']['denied']
        batch.total_pending_amount = batch_summary['total_amounts']['pending']
        
        # Store detailed results
        batch.processing_results = batch_summary
        
        self.batch_repo.update(batch)
    
    def _mark_batch_failed(self, batch_id: str, error_message: str):
        try:
            batch = self.batch_repo.get_by_id(batch_id)
            if batch:
                batch.status = 'failed'
                batch.processing_end_time = datetime.utcnow()
                batch.processing_results = {
                    'error': error_message,
                    'failed_at': datetime.utcnow().isoformat()
                }
                self.batch_repo.update(batch)
        except Exception as e:
            logger.error(f"Error marking batch {batch_id} as failed: {str(e)}")
    
    def _create_success_result(self, batch_id: str, batch_summary: Dict[str, Any], 
                              processing_results: List[Dict[str, Any]], processing_start: datetime):
        processing_end = datetime.utcnow()
        total_time = (processing_end - processing_start).total_seconds()
        
        return {
            'status': 'success',
            'batch_id': batch_id,
            'batch_status': batch_summary['batch_status'],
            'total_processing_time_seconds': total_time,
            
            'summary': batch_summary,
            
            'claim_results': processing_results,
            
            'statistics': {
                'total_claims': batch_summary['total_claims'],
                'success_rate': (batch_summary['status_counts']['success'] / 
                               batch_summary['total_claims']) * 100,
                'avg_processing_time': batch_summary['processing_statistics']['average_processing_time'],
                'claims_per_second': batch_summary['total_claims'] / total_time if total_time > 0 else 0
            }
        }
    
    def _create_error_result(self, batch_id: str, error_message: str, processing_start: datetime):
        processing_end = datetime.utcnow()
        total_time = (processing_end - processing_start).total_seconds()
        
        return {
            'status': 'error',
            'batch_id': batch_id,
            'error_message': error_message,
            'total_processing_time_seconds': total_time
        }
    
    def get_batch_status(self, batch_id: str) -> Optional[Dict[str, Any]]:
        try:
            batch = self.batch_repo.get_by_id(batch_id)
            if not batch:
                return None
            
            return {
                'batch_id': batch_id,
                'status': batch.status,
                'facility_id': batch.facility_id,
                'submission_date': batch.submission_date.isoformat() if batch.submission_date else None,
                'processing_start_time': batch.processing_start_time.isoformat() if batch.processing_start_time else None,
                'processing_end_time': batch.processing_end_time.isoformat() if batch.processing_end_time else None,
                
                'statistics': {
                    'total_claims': batch.total_claims,
                    'approved_claims': batch.approved_claims,
                    'rejected_claims': batch.rejected_claims,
                    'pending_claims': batch.pending_claims,
                    'error_claims': batch.error_claims
                },
                
                'amounts': {
                    'total_approved': batch.total_approved_amount,
                    'total_denied': batch.total_denied_amount,
                    'total_pending': batch.total_pending_amount
                },
                
                'processing_time_seconds': batch.total_processing_time_seconds
            }
            
        except Exception as e:
            logger.error(f"Error getting batch status for {batch_id}: {str(e)}")
            return None
    
    def reprocess_failed_claims(self, batch_id: str) -> Dict[str, Any]:
        try:
            # Get failed claims from the batch
            failed_claims = self.claim_repo.get_failed_claims_by_batch(batch_id)
            
            if not failed_claims:
                return {
                    'status': 'success',
                    'message': 'No failed claims to reprocess',
                    'reprocessed_claims': 0
                }
            
            # Reprocess failed claims
            reprocess_results = []
            for claim in failed_claims:
                result = self.claim_processing_service.process_claim(claim.id)
                reprocess_results.append(result)
            
            # Analyze reprocessing results
            success_count = sum(1 for r in reprocess_results if r.get('status') == 'success')
            
            return {
                'status': 'success',
                'batch_id': batch_id,
                'reprocessed_claims': len(failed_claims),
                'successful_reprocessing': success_count,
                'still_failed': len(failed_claims) - success_count,
                'results': reprocess_results
            }
            
        except Exception as e:
            logger.error(f"Error reprocessing failed claims for batch {batch_id}: {str(e)}")
            return {
                'status': 'error',
                'error_message': str(e)
            }