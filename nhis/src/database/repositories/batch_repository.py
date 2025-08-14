from typing import List, Optional, Dict, Any, Tuple
from sqlalchemy.orm import Session
from sqlalchemy import and_, or_, func, desc, asc, extract
from datetime import datetime, timedelta
import uuid
from decimal import Decimal

from .base_repository import BaseRepository
from ..models.claim_batch import ClaimBatch

class BatchRepository(BaseRepository[ClaimBatch]):
    def __init__(self, db_session: Session):
        super().__init__(db_session, ClaimBatch)
    
    def get_by_facility_and_period(self, facility_id: uuid.UUID, month: int, year: int) -> Optional[ClaimBatch]:
        return self.get_by_fields({
            'facility_id': facility_id,
            'month': month,
            'year': year
        })
    
    def get_batches_by_facility(self, facility_id: uuid.UUID, limit: Optional[int] = None) -> List[ClaimBatch]:
        return self.get_many_by_field('facility_id', facility_id, limit=limit)
    
    def get_batches_by_status(self, status: str, limit: Optional[int] = None) -> List[ClaimBatch]:
        return self.get_many_by_field('status', status, limit=limit)
    
    def get_pending_batches(self, limit: Optional[int] = None) -> List[ClaimBatch]:
        return self.get_batches_by_status('pending', limit=limit)
    
    def get_submitted_batches(self, limit: Optional[int] = None) -> List[ClaimBatch]:
        return self.get_batches_by_status('submitted', limit=limit)
    
    def get_processing_batches(self, limit: Optional[int] = None) -> List[ClaimBatch]:
        return self.get_batches_by_status('processing', limit=limit)
    
    def get_processed_batches(self, limit: Optional[int] = None) -> List[ClaimBatch]:
        return self.get_batches_by_status('processed', limit=limit)
    
    def get_rejected_batches(self, limit: Optional[int] = None) -> List[ClaimBatch]:
        return self.get_batches_by_status('rejected', limit=limit)
    
    def get_batches_by_month_year(self, month: int, year: int, limit: Optional[int] = None) -> List[ClaimBatch]:
        return self.get_many_by_fields({
            'month': month,
            'year': year
        }, limit=limit, order_by='created_at', desc_order=True)
    
    def get_batches_by_year(self, year: int, limit: Optional[int] = None) -> List[ClaimBatch]:
        return self.get_many_by_field('year', year, limit=limit)
    
    def get_batches_by_date_range(self, start_date: datetime, end_date: datetime) -> List[ClaimBatch]:
        return self.get_date_range('created_at', start_date, end_date)
    
    def get_batches_submitted_in_range(self, start_date: datetime, end_date: datetime) -> List[ClaimBatch]:
        return self.db_session.query(ClaimBatch).filter(
            and_(
                ClaimBatch.submitted_at >= start_date,
                ClaimBatch.submitted_at <= end_date,
                ClaimBatch.submitted_at.isnot(None)
            )
        ).order_by(desc(ClaimBatch.submitted_at)).all()
    
    def create_batch(self, facility_id: uuid.UUID, month: int, year: int) -> ClaimBatch:
        existing_batch = self.get_by_facility_and_period(facility_id, month, year)
        
        if existing_batch:
            raise ValueError(f"Batch already exists for facility {facility_id} for {month}/{year}")
        
        if not (1 <= month <= 12):
            raise ValueError(f"Invalid month: {month}. Must be between 1 and 12")
        
        if year < 2020 or year > datetime.now().year + 1:
            raise ValueError(f"Invalid year: {year}")
        
        batch_data = {
            'facility_id': facility_id,
            'month': month,
            'year': year,
            'status': 'pending',
            'claim_count': 0,
            'total_amount': Decimal('0.00'),
            'created_at': datetime.utcnow()
        }
        
        return self.create(batch_data)
    
    def submit_batch(self, batch_id: uuid.UUID, nhis_reference: Optional[str] = None) -> bool:
        batch = self.get_by_id(batch_id)
        
        if not batch:
            return False
        
        if batch.status != 'pending':
            raise ValueError(f"Cannot submit batch with status: {batch.status}")
        
        if batch.claim_count == 0:
            raise ValueError("Cannot submit batch with no claims")
        
        update_data = {
            'status': 'submitted',
            'submitted_at': datetime.utcnow(),
            'nhis_reference': nhis_reference
        }
        
        result = self.update(batch_id, update_data)
        return result is not None
    
    def start_processing(self, batch_id: uuid.UUID) -> bool:
        batch = self.get_by_id(batch_id)
        
        if not batch:
            return False
        
        if batch.status != 'submitted':
            raise ValueError(f"Cannot start processing batch with status: {batch.status}")
        
        update_data = {
            'status': 'processing'
        }
        
        result = self.update(batch_id, update_data)
        return result is not None
    
    def complete_processing(self, batch_id: uuid.UUID) -> bool:
        batch = self.get_by_id(batch_id)
        
        if not batch:
            return False
        
        if batch.status != 'processing':
            raise ValueError(f"Cannot complete processing batch with status: {batch.status}")
        
        update_data = {
            'status': 'processed',
            'processed_at': datetime.utcnow()
        }
        
        result = self.update(batch_id, update_data)
        return result is not None
    
    def reject_batch(self, batch_id: uuid.UUID, reason: Optional[str] = None) -> bool:
        batch = self.get_by_id(batch_id)
        
        if not batch:
            return False
        
        if batch.status in ['processed']:
            raise ValueError(f"Cannot reject batch with status: {batch.status}")
        
        update_data = {
            'status': 'rejected'
        }
        
        if reason:
            update_data['rejection_reason'] = reason
        
        result = self.update(batch_id, update_data)
        return result is not None
    
    def add_claims_to_batch(self, batch_id: uuid.UUID, claim_ids: List[uuid.UUID]) -> bool:
        from ..models.claim_v2 import ClaimV2
        
        batch = self.get_by_id(batch_id)
        
        if not batch:
            return False
        
        if batch.status != 'pending':
            raise ValueError(f"Cannot add claims to batch with status: {batch.status}")
        
        claims_added = self.db_session.query(ClaimV2).filter(
            and_(
                ClaimV2.id.in_(claim_ids),
                ClaimV2.batch_id.is_(None)
            )
        ).update(
            {'batch_id': batch_id},
            synchronize_session=False
        )
        
        if claims_added > 0:
            self.recalculate_batch_totals(batch_id)
        
        return claims_added > 0
    
    def remove_claims_from_batch(self, batch_id: uuid.UUID, claim_ids: List[uuid.UUID]) -> bool:
        from ..models.claim_v2 import ClaimV2
        
        batch = self.get_by_id(batch_id)
        
        if not batch:
            return False
        
        if batch.status != 'pending':
            raise ValueError(f"Cannot remove claims from batch with status: {batch.status}")
        
        claims_removed = self.db_session.query(ClaimV2).filter(
            and_(
                ClaimV2.id.in_(claim_ids),
                ClaimV2.batch_id == batch_id
            )
        ).update(
            {'batch_id': None},
            synchronize_session=False
        )
        
        if claims_removed > 0:
            self.recalculate_batch_totals(batch_id)
        
        return claims_removed > 0
    
    def recalculate_batch_totals(self, batch_id: uuid.UUID) -> bool:
        from ..models.claim_v2 import ClaimV2
        
        batch = self.get_by_id(batch_id)
        
        if not batch:
            return False
        
        claim_stats = self.db_session.query(
            func.count(ClaimV2.id).label('claim_count'),
            func.coalesce(func.sum(ClaimV2.total_amount), 0).label('total_amount')
        ).filter(ClaimV2.batch_id == batch_id).first()
        
        update_data = {
            'claim_count': claim_stats.claim_count or 0,
            'total_amount': Decimal(str(claim_stats.total_amount or 0))
        }
        
        result = self.update(batch_id, update_data)
        return result is not None
    
    def get_batch_summary(self, batch_id: uuid.UUID) -> Dict[str, Any]:
        from ..models.claim_v2 import ClaimV2
        
        batch = self.get_by_id(batch_id)
        
        if not batch:
            return {'error': 'Batch not found'}
        
        claims_summary = self.db_session.query(
            func.count(ClaimV2.id).label('total_claims'),
            func.count(func.distinct(ClaimV2.nhis_number)).label('unique_patients'),
            func.sum(func.case([(ClaimV2.service_type_1 == 'OPD', 1)], else_=0)).label('opd_claims'),
            func.sum(func.case([(ClaimV2.service_type_1 == 'IPD', 1)], else_=0)).label('ipd_claims'),
            func.sum(func.case([(ClaimV2.service_type_1.in_(['A&E', 'EMERGENCY']), 1)], else_=0)).label('emergency_claims')
        ).filter(ClaimV2.batch_id == batch_id).first()
        
        return {
            'batch_id': batch_id,
            'facility_id': batch.facility_id,
            'month': batch.month,
            'year': batch.year,
            'status': batch.status,
            'created_at': batch.created_at,
            'submitted_at': batch.submitted_at,
            'processed_at': batch.processed_at,
            'claim_count': batch.claim_count,
            'total_amount': float(batch.total_amount) if batch.total_amount else 0,
            'nhis_reference': batch.nhis_reference,
            'claims_breakdown': {
                'total_claims': claims_summary.total_claims or 0,
                'unique_patients': claims_summary.unique_patients or 0,
                'opd_claims': claims_summary.opd_claims or 0,
                'ipd_claims': claims_summary.ipd_claims or 0,
                'emergency_claims': claims_summary.emergency_claims or 0
            }
        }
    
    def get_facility_batch_history(self, facility_id: uuid.UUID, months_back: int = 12) -> List[Dict[str, Any]]:
        cutoff_date = datetime.utcnow() - timedelta(days=months_back * 30)
        
        batches = self.db_session.query(ClaimBatch).filter(
            and_(
                ClaimBatch.facility_id == facility_id,
                ClaimBatch.created_at >= cutoff_date
            )
        ).order_by(desc(ClaimBatch.year), desc(ClaimBatch.month)).all()
        
        history = []
        for batch in batches:
            history.append({
                'batch_id': batch.id,
                'month': batch.month,
                'year': batch.year,
                'status': batch.status,
                'claim_count': batch.claim_count,
                'total_amount': float(batch.total_amount) if batch.total_amount else 0,
                'submitted_at': batch.submitted_at,
                'processed_at': batch.processed_at,
                'days_to_process': (batch.processed_at - batch.submitted_at).days if batch.processed_at and batch.submitted_at else None
            })
        
        return history
    
    def get_monthly_batch_statistics(self, month: int, year: int) -> Dict[str, Any]:
        batches = self.get_batches_by_month_year(month, year)
        
        total_batches = len(batches)
        status_counts = {}
        total_claims = 0
        total_amount = Decimal('0.00')
        
        for batch in batches:
            status = batch.status
            status_counts[status] = status_counts.get(status, 0) + 1
            total_claims += batch.claim_count
            total_amount += batch.total_amount or Decimal('0.00')
        
        return {
            'month': month,
            'year': year,
            'total_batches': total_batches,
            'total_claims': total_claims,
            'total_amount': float(total_amount),
            'status_breakdown': status_counts,
            'average_claims_per_batch': total_claims / total_batches if total_batches > 0 else 0,
            'average_amount_per_batch': float(total_amount) / total_batches if total_batches > 0 else 0
        }
    
    def get_processing_queue(self) -> List[Dict[str, Any]]:
        submitted_batches = self.get_submitted_batches()
        processing_batches = self.get_processing_batches()
        
        queue = []
        
        for batch in submitted_batches:
            queue.append({
                'batch_id': batch.id,
                'facility_id': batch.facility_id,
                'month': batch.month,
                'year': batch.year,
                'claim_count': batch.claim_count,
                'total_amount': float(batch.total_amount) if batch.total_amount else 0,
                'submitted_at': batch.submitted_at,
                'queue_position': 'SUBMITTED',
                'waiting_days': (datetime.utcnow() - batch.submitted_at).days if batch.submitted_at else 0
            })
        
        for batch in processing_batches:
            queue.append({
                'batch_id': batch.id,
                'facility_id': batch.facility_id,
                'month': batch.month,
                'year': batch.year,
                'claim_count': batch.claim_count,
                'total_amount': float(batch.total_amount) if batch.total_amount else 0,
                'submitted_at': batch.submitted_at,
                'queue_position': 'PROCESSING',
                'processing_days': (datetime.utcnow() - batch.submitted_at).days if batch.submitted_at else 0
            })
        
        return sorted(queue, key=lambda x: x.get('submitted_at') or datetime.min)
    
    def get_overdue_batches(self, days_threshold: int = 30) -> List[Dict[str, Any]]:
        cutoff_date = datetime.utcnow() - timedelta(days=days_threshold)
        
        overdue_batches = self.db_session.query(ClaimBatch).filter(
            and_(
                ClaimBatch.status.in_(['submitted', 'processing']),
                ClaimBatch.submitted_at < cutoff_date,
                ClaimBatch.submitted_at.isnot(None)
            )
        ).order_by(asc(ClaimBatch.submitted_at)).all()
        
        overdue_list = []
        for batch in overdue_batches:
            days_overdue = (datetime.utcnow() - batch.submitted_at).days if batch.submitted_at else 0
            
            overdue_list.append({
                'batch_id': batch.id,
                'facility_id': batch.facility_id,
                'month': batch.month,
                'year': batch.year,
                'status': batch.status,
                'claim_count': batch.claim_count,
                'total_amount': float(batch.total_amount) if batch.total_amount else 0,
                'submitted_at': batch.submitted_at,
                'days_overdue': days_overdue,
                'urgency_level': 'HIGH' if days_overdue > 60 else 'MEDIUM' if days_overdue > 45 else 'LOW'
            })
        
        return overdue_list
    
    def get_batch_performance_metrics(self, start_date: datetime, end_date: datetime) -> Dict[str, Any]:
        batches_in_period = self.get_batches_submitted_in_range(start_date, end_date)
        
        if not batches_in_period:
            return {'error': 'No batches found in the specified period'}
        
        processed_batches = [b for b in batches_in_period if b.status == 'processed' and b.processed_at]
        
        processing_times = []
        for batch in processed_batches:
            if batch.submitted_at and batch.processed_at:
                processing_time = (batch.processed_at - batch.submitted_at).days
                processing_times.append(processing_time)
        
        total_batches = len(batches_in_period)
        total_claims = sum([b.claim_count for b in batches_in_period])
        total_amount = sum([float(b.total_amount) for b in batches_in_period if b.total_amount])
        
        return {
            'period_start': start_date,
            'period_end': end_date,
            'total_batches_submitted': total_batches,
            'total_batches_processed': len(processed_batches),
            'processing_completion_rate': (len(processed_batches) / total_batches * 100) if total_batches > 0 else 0,
            'total_claims_processed': total_claims,
            'total_amount_processed': total_amount,
            'average_processing_time_days': sum(processing_times) / len(processing_times) if processing_times else 0,
            'fastest_processing_time_days': min(processing_times) if processing_times else 0,
            'slowest_processing_time_days': max(processing_times) if processing_times else 0
        }
    
    def delete_empty_pending_batches(self, older_than_days: int = 30) -> int:
        cutoff_date = datetime.utcnow() - timedelta(days=older_than_days)
        
        deleted_count = self.db_session.query(ClaimBatch).filter(
            and_(
                ClaimBatch.status == 'pending',
                ClaimBatch.claim_count == 0,
                ClaimBatch.created_at < cutoff_date
            )
        ).delete()
        
        self.db_session.commit()
        return deleted_count