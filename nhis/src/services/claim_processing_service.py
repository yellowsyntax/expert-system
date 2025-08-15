from typing import Dict, Any, Optional, List
from datetime import datetime
from ..core.expert_system import ExpertSystem
from ..core.models import ClaimProcessingContext
from ..core.claim_adapter import ClaimAdapter
from ..calculators import (
    GDRGTariffCalculator, MedicineCalculator, InvestigationCalculator,
    ModifierCalculator, FinalAmountCalculator
)
from ..database.repositories import (
    ClaimV2Repository, ClaimDecisionRepository, AuditRepository
)
from ..database.models.claim_decision import ClaimDecision
from ..database.models.audit_log import AuditLog
import logging

logger = logging.getLogger(__name__)


class ClaimProcessingService:
    
    def __init__(self, 
                 expert_system: ExpertSystem,
                 claim_repo: ClaimV2Repository,
                 decision_repo: ClaimDecisionRepository,
                 audit_repo: AuditRepository,
                 gdrg_calculator: GDRGTariffCalculator,
                 medicine_calculator: MedicineCalculator,
                 investigation_calculator: InvestigationCalculator,
                 modifier_calculator: ModifierCalculator,
                 final_calculator: FinalAmountCalculator):
        
        self.expert_system = expert_system
        self.claim_repo = claim_repo
        self.decision_repo = decision_repo
        self.audit_repo = audit_repo
        self.gdrg_calculator = gdrg_calculator
        self.medicine_calculator = medicine_calculator
        self.investigation_calculator = investigation_calculator
        self.modifier_calculator = modifier_calculator
        self.final_calculator = final_calculator
        self.claim_adapter = ClaimAdapter()
    
    def process_claim(self, claim_id: str) -> Dict[str, Any]:
        processing_start = datetime.utcnow()
        
        try:
            # Step 1: Retrieve claim from database
            claim_v2 = self.claim_repo.get_by_id(claim_id)
            if not claim_v2:
                return self._create_error_result(claim_id, "Claim not found", processing_start)
            
            # Step 2: Convert to processing format
            processing_claim = self.claim_adapter.convert_to_processing_format(claim_v2)
            
            # Step 3: Create processing context
            context = ClaimProcessingContext(
                claim=processing_claim,
                processing_date=datetime.utcnow(),
                claim_id=claim_id
            )
            
            # Step 4: Run through expert system (5-step pipeline + business rules)
            expert_result = self.expert_system.process_claim(context)
            
            # Step 5: Calculate amounts if processing was successful
            if expert_result.overall_result in ['APPROVED', 'PARTIALLY_APPROVED', 'PENDING']:
                calculation_results = self._run_calculations(context)
            else:
                calculation_results = self._create_zero_calculations()
            
            # Step 6: Create final decision record
            decision = self._create_claim_decision(
                claim_v2, context, expert_result, calculation_results, processing_start
            )
            
            # Step 7: Save decision to database
            saved_decision = self.decision_repo.create(decision)
            
            # Step 8: Create audit trail
            self._create_audit_trail(claim_id, context, expert_result, calculation_results)
            
            # Step 9: Update claim status
            self._update_claim_status(claim_v2, expert_result.overall_result)
            
            # Step 10: Return comprehensive result
            return self._create_success_result(
                claim_id, expert_result, calculation_results, saved_decision, processing_start
            )
            
        except Exception as e:
            logger.error(f"Error processing claim {claim_id}: {str(e)}")
            return self._create_error_result(claim_id, str(e), processing_start)
    
    def _run_calculations(self, context: ClaimProcessingContext) -> Dict[str, Any]:
        calculation_results = {}
        
        try:
            # Calculate G-DRG tariff
            gdrg_result = self.gdrg_calculator.calculate(context)
            calculation_results['gdrg'] = {
                'status': gdrg_result.status.value,
                'amount': float(gdrg_result.amount),
                'details': gdrg_result.details
            }
            
            # Calculate medicine amounts
            medicine_result = self.medicine_calculator.calculate(context)
            calculation_results['medicine'] = {
                'status': medicine_result.status.value,
                'amount': float(medicine_result.amount),
                'details': medicine_result.details
            }
            
            # Calculate investigation amounts
            investigation_result = self.investigation_calculator.calculate(context)
            calculation_results['investigation'] = {
                'status': investigation_result.status.value,
                'amount': float(investigation_result.amount),
                'details': investigation_result.details
            }
            
            # Calculate modifiers
            modifier_result = self.modifier_calculator.calculate(context)
            calculation_results['modifier'] = {
                'status': modifier_result.status.value,
                'amount': float(modifier_result.amount),
                'details': modifier_result.details
            }
            
            # Calculate final amounts
            final_result = self.final_calculator.calculate(context)
            calculation_results['final'] = {
                'status': final_result.status.value,
                'amount': float(final_result.amount),
                'details': final_result.details
            }
            
            return calculation_results
            
        except Exception as e:
            logger.error(f"Error in calculations: {str(e)}")
            return self._create_zero_calculations()
    
    def _create_zero_calculations(self) -> Dict[str, Any]:
        return {
            'gdrg': {'status': 'failed', 'amount': 0.0, 'details': {}},
            'medicine': {'status': 'failed', 'amount': 0.0, 'details': {}},
            'investigation': {'status': 'failed', 'amount': 0.0, 'details': {}},
            'modifier': {'status': 'failed', 'amount': 0.0, 'details': {}},
            'final': {'status': 'failed', 'amount': 0.0, 'details': {}}
        }
    
    def _create_claim_decision(self, claim_v2, context, expert_result, calculation_results, processing_start):
        processing_end = datetime.utcnow()
        processing_time = (processing_end - processing_start).total_seconds()
        
        # Extract final amounts
        final_calc = calculation_results.get('final', {})
        final_details = final_calc.get('details', {})
        final_amounts = final_details.get('final_amounts', {})
        
        return ClaimDecision(
            claim_id=context.claim_id,
            facility_id=context.claim.facility_id,
            patient_id=getattr(context.claim, 'patient_id', None),
            processing_date=context.processing_date,
            decision_type=expert_result.overall_result,
            
            # Amounts
            approved_amount=final_amounts.get('approved', 0.0),
            denied_amount=final_amounts.get('denied', 0.0),
            pending_amount=final_amounts.get('pending', 0.0),
            total_amount=final_amounts.get('total', 0.0),
            
            # G-DRG information
            selected_gdrg=getattr(context, 'selected_gdrg', None),
            gdrg_amount=calculation_results.get('gdrg', {}).get('amount', 0.0),
            
            # Component amounts
            medicine_amount=calculation_results.get('medicine', {}).get('amount', 0.0),
            investigation_amount=calculation_results.get('investigation', {}).get('amount', 0.0),
            modifier_amount=calculation_results.get('modifier', {}).get('amount', 0.0),
            
            # Processing metadata
            processing_time_seconds=processing_time,
            rules_applied=len(expert_result.rule_results),
            
            # Detailed results (JSON)
            expert_system_results=expert_result.to_dict(),
            calculation_results=calculation_results,
            
            # Flags
            has_pending_items=expert_result.overall_result == 'PENDING',
            has_denied_items=expert_result.overall_result in ['REJECTED', 'PARTIALLY_APPROVED'],
            requires_manual_review=expert_result.overall_result in ['PENDING', 'REJECTED']
        )
    
    def _create_audit_trail(self, claim_id: str, context, expert_result, calculation_results):
        try:
            # Main processing audit
            main_audit = AuditLog(
                claim_id=claim_id,
                action='claim_processing',
                user_id='system',
                timestamp=datetime.utcnow(),
                details={
                    'overall_result': expert_result.overall_result,
                    'processing_time': getattr(context, 'processing_time', 0),
                    'rules_executed': len(expert_result.rule_results),
                    'calculations_status': {
                        calc_type: calc_data.get('status', 'unknown')
                        for calc_type, calc_data in calculation_results.items()
                    }
                }
            )
            self.audit_repo.create(main_audit)
            
            # Rule-specific audits for critical decisions
            for rule_result in expert_result.rule_results:
                if rule_result.result_type.value in ['REJECT', 'PEND']:
                    rule_audit = AuditLog(
                        claim_id=claim_id,
                        action=f'rule_{rule_result.rule_id}',
                        user_id='system',
                        timestamp=datetime.utcnow(),
                        details={
                            'rule_id': rule_result.rule_id,
                            'result_type': rule_result.result_type.value,
                            'message': rule_result.message,
                            'details': rule_result.details
                        }
                    )
                    self.audit_repo.create(rule_audit)
                    
        except Exception as e:
            logger.error(f"Error creating audit trail for claim {claim_id}: {str(e)}")
    
    def _update_claim_status(self, claim_v2, decision_result):
        try:
            status_mapping = {
                'APPROVED': 'approved',
                'PARTIALLY_APPROVED': 'partially_approved',
                'PENDING': 'pending_review',
                'REJECTED': 'rejected'
            }
            
            new_status = status_mapping.get(decision_result, 'processed')
            claim_v2.status = new_status
            claim_v2.processing_date = datetime.utcnow()
            
            self.claim_repo.update(claim_v2)
            
        except Exception as e:
            logger.error(f"Error updating claim status: {str(e)}")
    
    def _create_success_result(self, claim_id, expert_result, calculation_results, decision, processing_start):
        processing_end = datetime.utcnow()
        processing_time = (processing_end - processing_start).total_seconds()
        
        final_amounts = calculation_results.get('final', {}).get('details', {}).get('final_amounts', {})
        
        return {
            'status': 'success',
            'claim_id': claim_id,
            'decision_id': decision.id,
            'processing_result': expert_result.overall_result,
            'processing_time_seconds': processing_time,
            
            'amounts': {
                'approved': final_amounts.get('approved', 0.0),
                'denied': final_amounts.get('denied', 0.0),
                'pending': final_amounts.get('pending', 0.0),
                'total': final_amounts.get('total', 0.0)
            },
            
            'summary': {
                'gdrg_code': getattr(expert_result, 'selected_gdrg', None),
                'rules_applied': len(expert_result.rule_results),
                'has_issues': expert_result.overall_result in ['PENDING', 'REJECTED'],
                'requires_review': expert_result.overall_result in ['PENDING', 'REJECTED']
            },
            
            'details': {
                'expert_system_result': expert_result.to_dict(),
                'calculation_results': calculation_results
            }
        }
    
    def _create_error_result(self, claim_id, error_message, processing_start):
        processing_end = datetime.utcnow()
        processing_time = (processing_end - processing_start).total_seconds()
        
        return {
            'status': 'error',
            'claim_id': claim_id,
            'error_message': error_message,
            'processing_time_seconds': processing_time,
            'amounts': {
                'approved': 0.0,
                'denied': 0.0,
                'pending': 0.0,
                'total': 0.0
            }
        }
    
    def get_processing_summary(self, claim_id: str) -> Optional[Dict[str, Any]]:
        try:
            decision = self.decision_repo.get_by_claim_id(claim_id)
            if not decision:
                return None
            
            return {
                'claim_id': claim_id,
                'decision_type': decision.decision_type,
                'processing_date': decision.processing_date.isoformat(),
                'amounts': {
                    'approved': decision.approved_amount,
                    'denied': decision.denied_amount,
                    'pending': decision.pending_amount,
                    'total': decision.total_amount
                },
                'gdrg_info': {
                    'selected_gdrg': decision.selected_gdrg,
                    'gdrg_amount': decision.gdrg_amount
                },
                'processing_stats': {
                    'processing_time': decision.processing_time_seconds,
                    'rules_applied': decision.rules_applied
                }
            }
            
        except Exception as e:
            logger.error(f"Error getting processing summary for claim {claim_id}: {str(e)}")
            return None