from typing import Dict, Any, Optional, List
from decimal import Decimal
from .base_calculator import BaseCalculator, CalculationResult, CalculationStatus, AmountBreakdown
from ..core.models import ClaimProcessingContext
import logging

logger = logging.getLogger(__name__)


class FinalAmountCalculator(BaseCalculator):
    
    def __init__(self):
        super().__init__()
    
    def calculate(self, context: ClaimProcessingContext, **kwargs) -> CalculationResult:
        try:
            # Collect all component amounts
            amount_breakdown = self._calculate_amount_breakdown(context)
            
            # Determine final decision based on business rule results
            final_decision = self._determine_final_decision(context)
            
            # Calculate final amounts based on decision
            final_amounts = self._calculate_final_amounts(amount_breakdown, final_decision, context)
            
            # Update context with final calculations
            context.amount_breakdown = amount_breakdown
            context.final_decision = final_decision
            context.final_approved_amount = final_amounts['approved']
            context.final_denied_amount = final_amounts['denied']
            context.final_pending_amount = final_amounts['pending']
            context.final_total_amount = final_amounts['total']
            
            # Determine overall status
            status = self._determine_calculation_status(final_amounts, final_decision)
            message = self._generate_summary_message(final_amounts, final_decision)
            
            details = {
                "amount_breakdown": {
                    "gdrg_amount": float(amount_breakdown.gdrg_amount),
                    "medicine_amount": float(amount_breakdown.medicine_amount),
                    "investigation_amount": float(amount_breakdown.investigation_amount),
                    "modifier_amount": float(amount_breakdown.modifier_amount),
                    "total_base_amount": float(amount_breakdown.total_amount)
                },
                "final_decision": final_decision,
                "final_amounts": {
                    "approved": float(final_amounts['approved']),
                    "denied": float(final_amounts['denied']),
                    "pending": float(final_amounts['pending']),
                    "total": float(final_amounts['total'])
                },
                "component_details": self._get_component_details(context)
            }
            
            return CalculationResult(
                status=status,
                amount=final_amounts['total'],
                base_amount=amount_breakdown.total_amount,
                adjustments={'modifiers': amount_breakdown.modifier_amount},
                message=message,
                details=details
            )
            
        except Exception as e:
            logger.error(f"Error in FinalAmountCalculator: {str(e)}")
            return self._create_failed_result(
                message=f"Error calculating final amounts: {str(e)}",
                details={"error": str(e)}
            )
    
    def _calculate_amount_breakdown(self, context: ClaimProcessingContext) -> AmountBreakdown:
        breakdown = AmountBreakdown()
        
        # G-DRG amount
        if hasattr(context, 'gdrg_final_amount'):
            breakdown.gdrg_amount = self._validate_amount(context.gdrg_final_amount)
        
        # Medicine amounts
        if hasattr(context, 'medicine_approved_amount'):
            breakdown.medicine_amount += self._validate_amount(context.medicine_approved_amount)
        if hasattr(context, 'medicine_denied_amount'):
            breakdown.medicine_amount += self._validate_amount(context.medicine_denied_amount)
        if hasattr(context, 'medicine_pending_amount'):
            breakdown.medicine_amount += self._validate_amount(context.medicine_pending_amount)
        
        # Investigation amounts
        if hasattr(context, 'investigation_approved_amount'):
            breakdown.investigation_amount += self._validate_amount(context.investigation_approved_amount)
        if hasattr(context, 'investigation_denied_amount'):
            breakdown.investigation_amount += self._validate_amount(context.investigation_denied_amount)
        
        # Modifier amounts
        if hasattr(context, 'total_modifier_amount'):
            breakdown.modifier_amount = self._validate_amount(context.total_modifier_amount)
        
        # Calculate totals
        breakdown.total_amount = (
            breakdown.gdrg_amount + 
            breakdown.medicine_amount + 
            breakdown.investigation_amount + 
            breakdown.modifier_amount
        )
        
        return breakdown
    
    def _determine_final_decision(self, context: ClaimProcessingContext) -> str:
        # Check for critical rejections first
        if hasattr(context, 'processing_results'):
            for result in context.processing_results:
                if hasattr(result, 'result_type') and result.result_type.value == 'REJECT':
                    return 'REJECTED'
        
        # Check for pending items
        has_pending = False
        if hasattr(context, 'processing_results'):
            for result in context.processing_results:
                if hasattr(result, 'result_type') and result.result_type.value == 'PEND':
                    has_pending = True
                    break
        
        if has_pending:
            return 'PENDING'
        
        # Check for partial approvals
        has_denials = False
        if hasattr(context, 'medicine_denied_amount') and context.medicine_denied_amount > 0:
            has_denials = True
        if hasattr(context, 'investigation_denied_amount') and context.investigation_denied_amount > 0:
            has_denials = True
        
        if has_denials:
            return 'PARTIALLY_APPROVED'
        
        return 'APPROVED'
    
    def _calculate_final_amounts(self, breakdown: AmountBreakdown, decision: str, context: ClaimProcessingContext) -> Dict[str, Decimal]:
        final_amounts = {
            'approved': Decimal('0'),
            'denied': Decimal('0'),
            'pending': Decimal('0'),
            'total': breakdown.total_amount
        }
        
        if decision == 'REJECTED':
            final_amounts['denied'] = breakdown.total_amount
            
        elif decision == 'PENDING':
            final_amounts['pending'] = breakdown.total_amount
            
        elif decision == 'APPROVED':
            final_amounts['approved'] = breakdown.total_amount
            
        elif decision == 'PARTIALLY_APPROVED':
            # Calculate component-wise
            
            # G-DRG - usually approved if we got this far
            final_amounts['approved'] += breakdown.gdrg_amount
            
            # Medicines
            if hasattr(context, 'medicine_approved_amount'):
                final_amounts['approved'] += self._validate_amount(context.medicine_approved_amount)
            if hasattr(context, 'medicine_denied_amount'):
                final_amounts['denied'] += self._validate_amount(context.medicine_denied_amount)
            if hasattr(context, 'medicine_pending_amount'):
                final_amounts['pending'] += self._validate_amount(context.medicine_pending_amount)
            
            # Investigations
            if hasattr(context, 'investigation_approved_amount'):
                final_amounts['approved'] += self._validate_amount(context.investigation_approved_amount)
            if hasattr(context, 'investigation_denied_amount'):
                final_amounts['denied'] += self._validate_amount(context.investigation_denied_amount)
            
            # Modifiers apply to approved amounts only
            if breakdown.modifier_amount > 0 and final_amounts['approved'] > 0:
                final_amounts['approved'] += breakdown.modifier_amount
        
        return final_amounts
    
    def _determine_calculation_status(self, final_amounts: Dict[str, Decimal], decision: str) -> CalculationStatus:
        if decision == 'REJECTED':
            return CalculationStatus.FAILED
        elif decision == 'PENDING':
            return CalculationStatus.PENDING
        elif decision == 'PARTIALLY_APPROVED':
            return CalculationStatus.PARTIAL
        else:
            return CalculationStatus.SUCCESS
    
    def _generate_summary_message(self, final_amounts: Dict[str, Decimal], decision: str) -> str:
        if decision == 'REJECTED':
            return f"Claim rejected - Total amount denied: GHS {final_amounts['denied']}"
        elif decision == 'PENDING':
            return f"Claim pending review - Total amount: GHS {final_amounts['pending']}"
        elif decision == 'PARTIALLY_APPROVED':
            return f"Claim partially approved - Approved: GHS {final_amounts['approved']}, Denied: GHS {final_amounts['denied']}"
        else:
            return f"Claim fully approved - Total amount: GHS {final_amounts['approved']}"
    
    def _get_component_details(self, context: ClaimProcessingContext) -> Dict[str, Any]:
        details = {}
        
        # G-DRG details
        if hasattr(context, 'selected_gdrg'):
            details['gdrg'] = {
                'code': context.selected_gdrg,
                'amount': float(getattr(context, 'gdrg_final_amount', 0))
            }
        
        # Medicine details
        if hasattr(context, 'medicine_calculations'):
            details['medicines'] = {
                'total_items': len(context.medicine_calculations),
                'approved_amount': float(getattr(context, 'medicine_approved_amount', 0)),
                'denied_amount': float(getattr(context, 'medicine_denied_amount', 0)),
                'pending_amount': float(getattr(context, 'medicine_pending_amount', 0))
            }
        
        # Investigation details
        if hasattr(context, 'investigation_calculations'):
            details['investigations'] = {
                'total_items': len(context.investigation_calculations),
                'approved_amount': float(getattr(context, 'investigation_approved_amount', 0)),
                'denied_amount': float(getattr(context, 'investigation_denied_amount', 0))
            }
        
        # Modifier details
        if hasattr(context, 'modifier_calculations'):
            details['modifiers'] = {
                'total_modifiers': len(context.modifier_calculations),
                'total_amount': float(getattr(context, 'total_modifier_amount', 0))
            }
        
        return details
    
    def get_payment_summary(self, context: ClaimProcessingContext) -> Dict[str, Any]:
        if not hasattr(context, 'final_decision'):
            return {'status': 'not_calculated'}
        
        return {
            'decision': context.final_decision,
            'approved_amount': float(getattr(context, 'final_approved_amount', 0)),
            'denied_amount': float(getattr(context, 'final_denied_amount', 0)),
            'pending_amount': float(getattr(context, 'final_pending_amount', 0)),
            'total_amount': float(getattr(context, 'final_total_amount', 0)),
            'payment_status': self._get_payment_status(context.final_decision)
        }
    
    def _get_payment_status(self, decision: str) -> str:
        status_map = {
            'APPROVED': 'pay_full',
            'PARTIALLY_APPROVED': 'pay_partial',
            'PENDING': 'hold_payment',
            'REJECTED': 'no_payment'
        }
        return status_map.get(decision, 'unknown')