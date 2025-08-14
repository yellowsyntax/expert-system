from typing import List, Optional, Dict, Any, Union
from sqlalchemy.orm import Session
from sqlalchemy import and_, or_, func, desc, asc, text
from datetime import datetime, timedelta
import uuid
import json

from .base_repository import BaseRepository

class AuditRepository(BaseRepository):
    def __init__(self, db_session: Session):
        from ..models.audit_log import AuditLog
        super().__init__(db_session, AuditLog)
    
    def log_claim_processing_start(self, claim_id: uuid.UUID, processor_name: str, input_data: Dict[str, Any]) -> uuid.UUID:
        audit_data = {
            'claim_id': claim_id,
            'event_type': 'PROCESSING_START',
            'processor_name': processor_name,
            'event_description': f'Started processing claim with {processor_name}',
            'input_data': input_data,
            'created_at': datetime.utcnow()
        }
        
        audit_record = self.create(audit_data)
        return audit_record.id
    
    def log_claim_processing_step(self, claim_id: uuid.UUID, step_number: int, step_name: str, decision: str, 
                                 decision_reason: str, rules_applied: List[str], input_data: Dict[str, Any], 
                                 output_data: Dict[str, Any], processing_time_ms: int) -> uuid.UUID:
        audit_data = {
            'claim_id': claim_id,
            'event_type': 'PROCESSING_STEP',
            'processor_name': step_name,
            'step_number': step_number,
            'decision': decision,
            'decision_reason': decision_reason,
            'event_description': f'Step {step_number}: {step_name} - {decision}',
            'rules_applied': rules_applied,
            'input_data': input_data,
            'output_data': output_data,
            'processing_time_ms': processing_time_ms,
            'created_at': datetime.utcnow()
        }
        
        audit_record = self.create(audit_data)
        return audit_record.id
    
    def log_claim_processing_complete(self, claim_id: uuid.UUID, final_status: str, total_processing_time_ms: int,
                                    approved_amount: float, denied_amount: float, pending_amount: float) -> uuid.UUID:
        audit_data = {
            'claim_id': claim_id,
            'event_type': 'PROCESSING_COMPLETE',
            'processor_name': 'EXPERT_SYSTEM',
            'decision': final_status,
            'event_description': f'Claim processing completed with status: {final_status}',
            'output_data': {
                'final_status': final_status,
                'approved_amount': approved_amount,
                'denied_amount': denied_amount,
                'pending_amount': pending_amount,
                'total_processing_time_ms': total_processing_time_ms
            },
            'processing_time_ms': total_processing_time_ms,
            'created_at': datetime.utcnow()
        }
        
        audit_record = self.create(audit_data)
        return audit_record.id
    
    def log_validation_error(self, claim_id: uuid.UUID, processor_name: str, error_type: str, 
                           error_message: str, error_data: Dict[str, Any]) -> uuid.UUID:
        audit_data = {
            'claim_id': claim_id,
            'event_type': 'VALIDATION_ERROR',
            'processor_name': processor_name,
            'error_type': error_type,
            'error_message': error_message,
            'event_description': f'Validation error in {processor_name}: {error_type}',
            'input_data': error_data,
            'created_at': datetime.utcnow()
        }
        
        audit_record = self.create(audit_data)
        return audit_record.id
    
    def log_business_rule_application(self, claim_id: uuid.UUID, rule_name: str, rule_result: str,
                                    rule_data: Dict[str, Any], affected_amount: Optional[float] = None) -> uuid.UUID:
        audit_data = {
            'claim_id': claim_id,
            'event_type': 'BUSINESS_RULE',
            'processor_name': 'BUSINESS_RULES_PROCESSOR',
            'rule_name': rule_name,
            'decision': rule_result,
            'event_description': f'Applied business rule: {rule_name} - {rule_result}',
            'input_data': rule_data,
            'output_data': {'affected_amount': affected_amount} if affected_amount else {},
            'created_at': datetime.utcnow()
        }
        
        audit_record = self.create(audit_data)
        return audit_record.id
    
    def log_gdrg_determination(self, claim_id: uuid.UUID, icd10_code: str, candidate_gdrgs: List[str],
                             final_gdrg: str, determination_path: str, age_suffix: str) -> uuid.UUID:
        audit_data = {
            'claim_id': claim_id,
            'event_type': 'GDRG_DETERMINATION',
            'processor_name': 'INTAKE_PROCESSOR',
            'event_description': f'G-DRG determined: {final_gdrg} via {determination_path}',
            'input_data': {
                'icd10_code': icd10_code,
                'candidate_gdrgs': candidate_gdrgs,
                'determination_path': determination_path,
                'age_suffix': age_suffix
            },
            'output_data': {
                'final_gdrg': final_gdrg
            },
            'created_at': datetime.utcnow()
        }
        
        audit_record = self.create(audit_data)
        return audit_record.id
    
    def log_episode_limit_check(self, claim_id: uuid.UUID, nhis_number: str, episode_type: str,
                               current_count: int, max_allowed: int, is_within_limit: bool) -> uuid.UUID:
        audit_data = {
            'claim_id': claim_id,
            'event_type': 'EPISODE_LIMIT_CHECK',
            'processor_name': 'BUSINESS_RULES_PROCESSOR',
            'decision': 'WITHIN_LIMIT' if is_within_limit else 'EXCEEDED_LIMIT',
            'event_description': f'Episode limit check: {episode_type} - {current_count}/{max_allowed}',
            'input_data': {
                'nhis_number': nhis_number,
                'episode_type': episode_type,
                'current_count': current_count,
                'max_allowed': max_allowed
            },
            'output_data': {
                'is_within_limit': is_within_limit,
                'visits_remaining': max(0, max_allowed - current_count)
            },
            'created_at': datetime.utcnow()
        }
        
        audit_record = self.create(audit_data)
        return audit_record.id
    
    def log_tariff_calculation(self, claim_id: uuid.UUID, gdrg_code: str, facility_level: str,
                             base_tariff: float, modifiers_applied: List[Dict[str, Any]], final_amount: float) -> uuid.UUID:
        audit_data = {
            'claim_id': claim_id,
            'event_type': 'TARIFF_CALCULATION',
            'processor_name': 'BUSINESS_RULES_PROCESSOR',
            'event_description': f'Tariff calculated: {gdrg_code} = {final_amount}',
            'input_data': {
                'gdrg_code': gdrg_code,
                'facility_level': facility_level,
                'base_tariff': base_tariff,
                'modifiers_applied': modifiers_applied
            },
            'output_data': {
                'final_amount': final_amount
            },
            'created_at': datetime.utcnow()
        }
        
        audit_record = self.create(audit_data)
        return audit_record.id
    
    def log_system_error(self, claim_id: Optional[uuid.UUID], error_type: str, error_message: str,
                        stack_trace: str, context_data: Dict[str, Any]) -> uuid.UUID:
        audit_data = {
            'claim_id': claim_id,
            'event_type': 'SYSTEM_ERROR',
            'processor_name': 'EXPERT_SYSTEM',
            'error_type': error_type,
            'error_message': error_message,
            'event_description': f'System error: {error_type}',
            'input_data': context_data,
            'output_data': {'stack_trace': stack_trace},
            'created_at': datetime.utcnow()
        }
        
        audit_record = self.create(audit_data)
        return audit_record.id
    
    def get_claim_audit_trail(self, claim_id: uuid.UUID) -> List[Dict[str, Any]]:
        audit_records = self.get_many_by_field('claim_id', claim_id)
        
        trail = []
        for record in audit_records:
            trail.append({
                'id': record.id,
                'timestamp': record.created_at,
                'event_type': record.event_type,
                'processor_name': record.processor_name,
                'step_number': record.step_number,
                'decision': record.decision,
                'decision_reason': record.decision_reason,
                'event_description': record.event_description,
                'rule_name': record.rule_name,
                'input_data': record.input_data,
                'output_data': record.output_data,
                'processing_time_ms': record.processing_time_ms
            })
        
        return sorted(trail, key=lambda x: x['timestamp'])
    
    def get_processing_summary(self, claim_id: uuid.UUID) -> Dict[str, Any]:
        audit_records = self.get_many_by_field('claim_id', claim_id)
        
        if not audit_records:
            return {'error': 'No audit records found for claim'}
        
        start_record = next((r for r in audit_records if r.event_type == 'PROCESSING_START'), None)
        complete_record = next((r for r in audit_records if r.event_type == 'PROCESSING_COMPLETE'), None)
        
        step_records = [r for r in audit_records if r.event_type == 'PROCESSING_STEP']
        error_records = [r for r in audit_records if r.event_type in ['VALIDATION_ERROR', 'SYSTEM_ERROR']]
        business_rule_records = [r for r in audit_records if r.event_type == 'BUSINESS_RULE']
        
        total_processing_time = 0
        if start_record and complete_record:
            total_processing_time = (complete_record.created_at - start_record.created_at).total_seconds() * 1000
        
        return {
            'claim_id': claim_id,
            'processing_started': start_record.created_at if start_record else None,
            'processing_completed': complete_record.created_at if complete_record else None,
            'total_processing_time_ms': total_processing_time,
            'final_status': complete_record.decision if complete_record else 'INCOMPLETE',
            'steps_completed': len(step_records),
            'errors_encountered': len(error_records),
            'business_rules_applied': len(business_rule_records),
            'step_breakdown': [
                {
                    'step_number': r.step_number,
                    'step_name': r.processor_name,
                    'decision': r.decision,
                    'processing_time_ms': r.processing_time_ms
                } for r in step_records
            ],
            'final_amounts': complete_record.output_data if complete_record else {}
        }
    
    def get_processor_performance_stats(self, processor_name: str, days_back: int = 30) -> Dict[str, Any]:
        cutoff_date = datetime.utcnow() - timedelta(days=days_back)
        
        processor_records = self.db_session.query(self.model_class).filter(
            and_(
                self.model_class.processor_name == processor_name,
                self.model_class.event_type == 'PROCESSING_STEP',
                self.model_class.created_at >= cutoff_date
            )
        ).all()
        
        if not processor_records:
            return {'error': f'No records found for processor {processor_name}'}
        
        processing_times = [r.processing_time_ms for r in processor_records if r.processing_time_ms]
        decisions = [r.decision for r in processor_records if r.decision]
        
        decision_counts = {}
        for decision in decisions:
            decision_counts[decision] = decision_counts.get(decision, 0) + 1
        
        return {
            'processor_name': processor_name,
            'total_executions': len(processor_records),
            'avg_processing_time_ms': sum(processing_times) / len(processing_times) if processing_times else 0,
            'min_processing_time_ms': min(processing_times) if processing_times else 0,
            'max_processing_time_ms': max(processing_times) if processing_times else 0,
            'decision_breakdown': decision_counts,
            'success_rate': (decision_counts.get('APPROVE', 0) / len(decisions) * 100) if decisions else 0
        }
    
    def get_daily_processing_volume(self, days_back: int = 30) -> List[Dict[str, Any]]:
        cutoff_date = datetime.utcnow() - timedelta(days=days_back)
        
        daily_counts = self.db_session.query(
            func.date(self.model_class.created_at).label('processing_date'),
            func.count(func.distinct(self.model_class.claim_id)).label('claims_processed'),
            func.count(self.model_class.id).label('total_events')
        ).filter(
            and_(
                self.model_class.event_type == 'PROCESSING_COMPLETE',
                self.model_class.created_at >= cutoff_date
            )
        ).group_by(
            func.date(self.model_class.created_at)
        ).order_by(
            func.date(self.model_class.created_at)
        ).all()
        
        return [
            {
                'date': str(row.processing_date),
                'claims_processed': row.claims_processed,
                'total_events': row.total_events
            } for row in daily_counts
        ]
    
    def get_error_analysis(self, days_back: int = 7) -> Dict[str, Any]:
        cutoff_date = datetime.utcnow() - timedelta(days=days_back)
        
        error_records = self.db_session.query(self.model_class).filter(
            and_(
                self.model_class.event_type.in_(['VALIDATION_ERROR', 'SYSTEM_ERROR']),
                self.model_class.created_at >= cutoff_date
            )
        ).all()
        
        error_type_counts = {}
        processor_error_counts = {}
        
        for record in error_records:
            error_type = record.error_type or 'UNKNOWN'
            processor = record.processor_name or 'UNKNOWN'
            
            error_type_counts[error_type] = error_type_counts.get(error_type, 0) + 1
            processor_error_counts[processor] = processor_error_counts.get(processor, 0) + 1
        
        return {
            'total_errors': len(error_records),
            'error_by_type': error_type_counts,
            'error_by_processor': processor_error_counts,
            'error_rate_per_day': len(error_records) / days_back if days_back > 0 else 0
        }
    
    def get_business_rule_effectiveness(self, rule_name: Optional[str] = None, days_back: int = 30) -> Dict[str, Any]:
        cutoff_date = datetime.utcnow() - timedelta(days=days_back)
        
        query = self.db_session.query(self.model_class).filter(
            and_(
                self.model_class.event_type == 'BUSINESS_RULE',
                self.model_class.created_at >= cutoff_date
            )
        )
        
        if rule_name:
            query = query.filter(self.model_class.rule_name == rule_name)
        
        rule_records = query.all()
        
        if not rule_records:
            return {'error': 'No business rule records found'}
        
        rule_results = {}
        rule_names = set()
        
        for record in rule_records:
            name = record.rule_name or 'UNKNOWN'
            result = record.decision or 'UNKNOWN'
            
            rule_names.add(name)
            
            if name not in rule_results:
                rule_results[name] = {}
            
            rule_results[name][result] = rule_results[name].get(result, 0) + 1
        
        return {
            'total_rule_applications': len(rule_records),
            'unique_rules_applied': len(rule_names),
            'rule_breakdown': rule_results,
            'most_applied_rule': max(rule_names, key=lambda x: sum(rule_results.get(x, {}).values())) if rule_names else None
        }
    
    def cleanup_old_audit_logs(self, days_to_keep: int = 365) -> int:
        cutoff_date = datetime.utcnow() - timedelta(days=days_to_keep)
        
        deleted_count = self.db_session.query(self.model_class).filter(
            self.model_class.created_at < cutoff_date
        ).delete()
        
        self.db_session.commit()
        return deleted_count
    
    def export_audit_trail(self, claim_id: uuid.UUID, format_type: str = 'json') -> Union[str, Dict[str, Any]]:
        audit_trail = self.get_claim_audit_trail(claim_id)
        processing_summary = self.get_processing_summary(claim_id)
        
        export_data = {
            'claim_id': str(claim_id),
            'export_timestamp': datetime.utcnow().isoformat(),
            'processing_summary': processing_summary,
            'detailed_audit_trail': audit_trail
        }
        
        if format_type.lower() == 'json':
            return json.dumps(export_data, indent=2, default=str)
        else:
            return export_data