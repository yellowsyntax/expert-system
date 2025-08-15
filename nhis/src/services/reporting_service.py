from typing import Dict, Any, Optional, List
from datetime import datetime, timedelta
from dataclasses import dataclass
from ..database.repositories import (
    ClaimDecisionRepository, BatchRepository, AuditRepository, 
    ClaimV2Repository, ProviderRepository
)
import logging

logger = logging.getLogger(__name__)


@dataclass
class ReportConfig:
    report_type: str
    start_date: datetime
    end_date: datetime
    facility_id: Optional[str] = None
    provider_id: Optional[str] = None
    include_details: bool = True
    group_by: Optional[str] = None


class ReportingService:
    
    def __init__(self,
                 decision_repo: ClaimDecisionRepository,
                 batch_repo: BatchRepository,
                 audit_repo: AuditRepository,
                 claim_repo: ClaimV2Repository,
                 provider_repo: ProviderRepository):
        
        self.decision_repo = decision_repo
        self.batch_repo = batch_repo
        self.audit_repo = audit_repo
        self.claim_repo = claim_repo
        self.provider_repo = provider_repo
    
    def generate_processing_summary_report(self, config: ReportConfig) -> Dict[str, Any]:
        try:
            # Get processed claims in date range
            decisions = self.decision_repo.get_decisions_by_date_range(
                start_date=config.start_date,
                end_date=config.end_date,
                facility_id=config.facility_id
            )
            
            if not decisions:
                return self._create_empty_report(config, "No processed claims found in date range")
            
            # Calculate summary statistics
            summary_stats = self._calculate_summary_statistics(decisions)
            
            # Calculate financial summary
            financial_summary = self._calculate_financial_summary(decisions)
            
            # Calculate performance metrics
            performance_metrics = self._calculate_performance_metrics(decisions)
            
            # Group data if requested
            grouped_data = {}
            if config.group_by:
                grouped_data = self._group_decisions(decisions, config.group_by)
            
            # Generate detailed breakdowns
            detailed_breakdowns = {}
            if config.include_details:
                detailed_breakdowns = self._generate_detailed_breakdowns(decisions)
            
            return {
                'report_type': 'processing_summary',
                'report_config': {
                    'start_date': config.start_date.isoformat(),
                    'end_date': config.end_date.isoformat(),
                    'facility_id': config.facility_id,
                    'include_details': config.include_details
                },
                'generated_at': datetime.utcnow().isoformat(),
                
                'summary_statistics': summary_stats,
                'financial_summary': financial_summary,
                'performance_metrics': performance_metrics,
                'grouped_data': grouped_data,
                'detailed_breakdowns': detailed_breakdowns,
                
                'total_records': len(decisions)
            }
            
        except Exception as e:
            logger.error(f"Error generating processing summary report: {str(e)}")
            return self._create_error_report(config, str(e))
    
    def generate_batch_processing_report(self, config: ReportConfig) -> Dict[str, Any]:
        try:
            # Get batches in date range
            batches = self.batch_repo.get_batches_by_date_range(
                start_date=config.start_date,
                end_date=config.end_date,
                facility_id=config.facility_id
            )
            
            if not batches:
                return self._create_empty_report(config, "No batches found in date range")
            
            # Calculate batch statistics
            batch_stats = self._calculate_batch_statistics(batches)
            
            # Calculate batch performance
            batch_performance = self._calculate_batch_performance(batches)
            
            # Generate batch details
            batch_details = []
            if config.include_details:
                for batch in batches:
                    batch_detail = self._generate_batch_detail(batch)
                    batch_details.append(batch_detail)
            
            return {
                'report_type': 'batch_processing',
                'report_config': {
                    'start_date': config.start_date.isoformat(),
                    'end_date': config.end_date.isoformat(),
                    'facility_id': config.facility_id,
                    'include_details': config.include_details
                },
                'generated_at': datetime.utcnow().isoformat(),
                
                'batch_statistics': batch_stats,
                'batch_performance': batch_performance,
                'batch_details': batch_details,
                
                'total_batches': len(batches)
            }
            
        except Exception as e:
            logger.error(f"Error generating batch processing report: {str(e)}")
            return self._create_error_report(config, str(e))
    
    def generate_financial_report(self, config: ReportConfig) -> Dict[str, Any]:
        try:
            # Get financial data
            decisions = self.decision_repo.get_decisions_by_date_range(
                start_date=config.start_date,
                end_date=config.end_date,
                facility_id=config.facility_id
            )
            
            if not decisions:
                return self._create_empty_report(config, "No financial data found in date range")
            
            # Calculate financial metrics
            financial_metrics = self._calculate_detailed_financial_metrics(decisions)
            
            # Calculate payment summary
            payment_summary = self._calculate_payment_summary(decisions)
            
            # Calculate G-DRG analysis
            gdrg_analysis = self._calculate_gdrg_analysis(decisions)
            
            # Calculate component analysis
            component_analysis = self._calculate_component_analysis(decisions)
            
            # Generate facility comparison if multiple facilities
            facility_comparison = {}
            if not config.facility_id:
                facility_comparison = self._generate_facility_financial_comparison(decisions)
            
            return {
                'report_type': 'financial',
                'report_config': {
                    'start_date': config.start_date.isoformat(),
                    'end_date': config.end_date.isoformat(),
                    'facility_id': config.facility_id
                },
                'generated_at': datetime.utcnow().isoformat(),
                
                'financial_metrics': financial_metrics,
                'payment_summary': payment_summary,
                'gdrg_analysis': gdrg_analysis,
                'component_analysis': component_analysis,
                'facility_comparison': facility_comparison,
                
                'total_claims': len(decisions)
            }
            
        except Exception as e:
            logger.error(f"Error generating financial report: {str(e)}")
            return self._create_error_report(config, str(e))
    
    def generate_audit_report(self, config: ReportConfig) -> Dict[str, Any]:
        try:
            # Get audit logs in date range
            audit_logs = self.audit_repo.get_logs_by_date_range(
                start_date=config.start_date,
                end_date=config.end_date
            )
            
            if not audit_logs:
                return self._create_empty_report(config, "No audit logs found in date range")
            
            # Analyze audit activities
            audit_summary = self._analyze_audit_activities(audit_logs)
            
            # Calculate rule performance
            rule_performance = self._calculate_rule_performance(audit_logs)
            
            # Generate compliance metrics
            compliance_metrics = self._calculate_compliance_metrics(audit_logs)
            
            return {
                'report_type': 'audit',
                'report_config': {
                    'start_date': config.start_date.isoformat(),
                    'end_date': config.end_date.isoformat()
                },
                'generated_at': datetime.utcnow().isoformat(),
                
                'audit_summary': audit_summary,
                'rule_performance': rule_performance,
                'compliance_metrics': compliance_metrics,
                
                'total_audit_entries': len(audit_logs)
            }
            
        except Exception as e:
            logger.error(f"Error generating audit report: {str(e)}")
            return self._create_error_report(config, str(e))
    
    def _calculate_summary_statistics(self, decisions: List) -> Dict[str, Any]:
        total_claims = len(decisions)
        
        decision_counts = {
            'APPROVED': 0,
            'PARTIALLY_APPROVED': 0,
            'PENDING': 0,
            'REJECTED': 0
        }
        
        for decision in decisions:
            decision_type = decision.decision_type
            decision_counts[decision_type] = decision_counts.get(decision_type, 0) + 1
        
        return {
            'total_claims': total_claims,
            'decision_breakdown': decision_counts,
            'approval_rate': (decision_counts['APPROVED'] / total_claims * 100) if total_claims > 0 else 0,
            'rejection_rate': (decision_counts['REJECTED'] / total_claims * 100) if total_claims > 0 else 0,
            'pending_rate': (decision_counts['PENDING'] / total_claims * 100) if total_claims > 0 else 0
        }
    
    def _calculate_financial_summary(self, decisions: List) -> Dict[str, Any]:
        total_amount = sum(decision.total_amount for decision in decisions)
        approved_amount = sum(decision.approved_amount for decision in decisions)
        denied_amount = sum(decision.denied_amount for decision in decisions)
        pending_amount = sum(decision.pending_amount for decision in decisions)
        
        return {
            'total_claimed_amount': total_amount,
            'total_approved_amount': approved_amount,
            'total_denied_amount': denied_amount,
            'total_pending_amount': pending_amount,
            'approval_rate_by_value': (approved_amount / total_amount * 100) if total_amount > 0 else 0,
            'average_claim_value': total_amount / len(decisions) if decisions else 0,
            'average_approved_value': approved_amount / len(decisions) if decisions else 0
        }
    
    def _calculate_performance_metrics(self, decisions: List) -> Dict[str, Any]:
        processing_times = [decision.processing_time_seconds for decision in decisions if decision.processing_time_seconds]
        
        if not processing_times:
            return {'no_timing_data': True}
        
        avg_processing_time = sum(processing_times) / len(processing_times)
        min_processing_time = min(processing_times)
        max_processing_time = max(processing_times)
        
        # Calculate percentiles
        sorted_times = sorted(processing_times)
        p50 = sorted_times[len(sorted_times) // 2]
        p95 = sorted_times[int(len(sorted_times) * 0.95)]
        
        return {
            'average_processing_time_seconds': avg_processing_time,
            'min_processing_time_seconds': min_processing_time,
            'max_processing_time_seconds': max_processing_time,
            'median_processing_time_seconds': p50,
            'p95_processing_time_seconds': p95,
            'total_claims_with_timing': len(processing_times)
        }
    
    def _calculate_detailed_financial_metrics(self, decisions: List) -> Dict[str, Any]:
        # Component-wise financial breakdown
        gdrg_total = sum(decision.gdrg_amount for decision in decisions)
        medicine_total = sum(decision.medicine_amount for decision in decisions)
        investigation_total = sum(decision.investigation_amount for decision in decisions)
        modifier_total = sum(decision.modifier_amount for decision in decisions)
        
        total_amount = sum(decision.total_amount for decision in decisions)
        
        return {
            'component_breakdown': {
                'gdrg_amount': gdrg_total,
                'medicine_amount': medicine_total,
                'investigation_amount': investigation_total,
                'modifier_amount': modifier_total
            },
            'component_percentages': {
                'gdrg_percentage': (gdrg_total / total_amount * 100) if total_amount > 0 else 0,
                'medicine_percentage': (medicine_total / total_amount * 100) if total_amount > 0 else 0,
                'investigation_percentage': (investigation_total / total_amount * 100) if total_amount > 0 else 0,
                'modifier_percentage': (modifier_total / total_amount * 100) if total_amount > 0 else 0
            },
            'total_amount': total_amount
        }
    
    def _calculate_gdrg_analysis(self, decisions: List) -> Dict[str, Any]:
        gdrg_stats = {}
        
        for decision in decisions:
            if decision.selected_gdrg:
                gdrg = decision.selected_gdrg
                if gdrg not in gdrg_stats:
                    gdrg_stats[gdrg] = {
                        'count': 0,
                        'total_amount': 0,
                        'approved_count': 0,
                        'rejected_count': 0
                    }
                
                gdrg_stats[gdrg]['count'] += 1
                gdrg_stats[gdrg]['total_amount'] += decision.gdrg_amount
                
                if decision.decision_type == 'APPROVED':
                    gdrg_stats[gdrg]['approved_count'] += 1
                elif decision.decision_type == 'REJECTED':
                    gdrg_stats[gdrg]['rejected_count'] += 1
        
        # Sort by frequency
        top_gdrgs = sorted(gdrg_stats.items(), key=lambda x: x[1]['count'], reverse=True)[:10]
        
        return {
            'total_unique_gdrgs': len(gdrg_stats),
            'top_10_gdrgs': [
                {
                    'gdrg_code': gdrg,
                    'count': stats['count'],
                    'total_amount': stats['total_amount'],
                    'average_amount': stats['total_amount'] / stats['count'],
                    'approval_rate': (stats['approved_count'] / stats['count'] * 100) if stats['count'] > 0 else 0
                }
                for gdrg, stats in top_gdrgs
            ]
        }
    
    def _calculate_component_analysis(self, decisions: List) -> Dict[str, Any]:
        # Analyze medicine, investigation, and modifier patterns
        medicine_claims = [d for d in decisions if d.medicine_amount > 0]
        investigation_claims = [d for d in decisions if d.investigation_amount > 0]
        modifier_claims = [d for d in decisions if d.modifier_amount > 0]
        
        return {
            'medicine_analysis': {
                'claims_with_medicines': len(medicine_claims),
                'percentage_of_claims': (len(medicine_claims) / len(decisions) * 100) if decisions else 0,
                'average_medicine_amount': sum(d.medicine_amount for d in medicine_claims) / len(medicine_claims) if medicine_claims else 0
            },
            'investigation_analysis': {
                'claims_with_investigations': len(investigation_claims),
                'percentage_of_claims': (len(investigation_claims) / len(decisions) * 100) if decisions else 0,
                'average_investigation_amount': sum(d.investigation_amount for d in investigation_claims) / len(investigation_claims) if investigation_claims else 0
            },
            'modifier_analysis': {
                'claims_with_modifiers': len(modifier_claims),
                'percentage_of_claims': (len(modifier_claims) / len(decisions) * 100) if decisions else 0,
                'average_modifier_amount': sum(d.modifier_amount for d in modifier_claims) / len(modifier_claims) if modifier_claims else 0
            }
        }
    
    def _group_decisions(self, decisions: List, group_by: str) -> Dict[str, Any]:
        grouped = {}
        
        for decision in decisions:
            if group_by == 'facility':
                key = decision.facility_id
            elif group_by == 'decision_type':
                key = decision.decision_type
            elif group_by == 'date':
                key = decision.processing_date.strftime('%Y-%m-%d')
            else:
                key = 'unknown'
            
            if key not in grouped:
                grouped[key] = []
            grouped[key].append(decision)
        
        # Calculate summary for each group
        group_summaries = {}
        for key, group_decisions in grouped.items():
            group_summaries[key] = {
                'count': len(group_decisions),
                'total_amount': sum(d.total_amount for d in group_decisions),
                'approved_amount': sum(d.approved_amount for d in group_decisions),
                'denied_amount': sum(d.denied_amount for d in group_decisions)
            }
        
        return group_summaries
    
    def _create_empty_report(self, config: ReportConfig, message: str) -> Dict[str, Any]:
        return {
            'report_type': config.report_type,
            'status': 'empty',
            'message': message,
            'report_config': {
                'start_date': config.start_date.isoformat(),
                'end_date': config.end_date.isoformat(),
                'facility_id': config.facility_id
            },
            'generated_at': datetime.utcnow().isoformat()
        }
    
    def _create_error_report(self, config: ReportConfig, error: str) -> Dict[str, Any]:
        return {
            'report_type': config.report_type,
            'status': 'error',
            'error': error,
            'report_config': {
                'start_date': config.start_date.isoformat(),
                'end_date': config.end_date.isoformat(),
                'facility_id': config.facility_id
            },
            'generated_at': datetime.utcnow().isoformat()
        }