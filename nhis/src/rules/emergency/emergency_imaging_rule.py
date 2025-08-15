from datetime import datetime, timedelta
from typing import List, Optional, Dict, Any
from ..base_rule import BaseRule, RuleResult, RuleResultType
from ...core.models import ClaimProcessingContext
import logging

logger = logging.getLogger(__name__)


class EmergencyImagingRule(BaseRule):
    
    def __init__(self):
        super().__init__(
            rule_id="AE_IMAGING",
            name="Emergency Imaging Rule",
            description="Validate emergency CT/MRI justification requirements"
        )
        
        self.emergency_imaging_codes = {
            'ZOOM03A': 'Emergency CT Scan',
            'ZOOM03B': 'Emergency MRI Scan',
            'ZOOM03C': 'Emergency CT Angiography',
            'ZOOM03D': 'Emergency MR Angiography'
        }
        
        self.justification_deadline_days = 5
    
    def _get_emergency_imaging_procedures(self, claim) -> List[Dict[str, Any]]:
        emergency_imaging = []
        
        if not hasattr(claim, 'procedures') or not claim.procedures:
            return emergency_imaging
        
        for procedure in claim.procedures:
            procedure_code = procedure.get('code', '')
            if procedure_code in self.emergency_imaging_codes:
                emergency_imaging.append({
                    'code': procedure_code,
                    'name': self.emergency_imaging_codes[procedure_code],
                    'procedure_data': procedure
                })
        
        return emergency_imaging
    
    def _check_justification_documentation(self, claim, procedure_code: str) -> tuple[bool, Optional[datetime]]:
        justification_fields = [
            f'{procedure_code.lower()}_justification',
            f'{procedure_code.lower()}_clinical_notes',
            'emergency_imaging_justification',
            'clinical_justification'
        ]
        
        for field in justification_fields:
            if hasattr(claim, field) and getattr(claim, field):
                justification_date = getattr(claim, f'{field}_date', None)
                return True, justification_date
        
        if hasattr(claim, 'clinical_notes') and claim.clinical_notes:
            emergency_keywords = ['emergency', 'urgent', 'acute', 'trauma', 'critical']
            imaging_keywords = ['ct', 'mri', 'scan', 'imaging']
            
            notes_lower = claim.clinical_notes.lower()
            has_emergency = any(keyword in notes_lower for keyword in emergency_keywords)
            has_imaging = any(keyword in notes_lower for keyword in imaging_keywords)
            
            if has_emergency and has_imaging:
                return True, getattr(claim, 'clinical_notes_date', None)
        
        return False, None
    
    def _validate_justification_timing(self, service_date: datetime, justification_date: Optional[datetime]) -> tuple[bool, str]:
        if not justification_date:
            return True, "Justification timing cannot be validated (no date provided)"
        
        days_diff = (justification_date - service_date).days
        
        if days_diff < 0:
            return False, f"Justification provided {abs(days_diff)} days before imaging (should be after)"
        
        if days_diff > self.justification_deadline_days:
            return False, f"Justification provided {days_diff} days after imaging (deadline: {self.justification_deadline_days} days)"
        
        return True, f"Justification provided within {days_diff} days (compliant)"
    
    def evaluate(self, context: ClaimProcessingContext) -> RuleResult:
        try:
            claim = context.claim
            
            emergency_imaging = self._get_emergency_imaging_procedures(claim)
            
            if not emergency_imaging:
                return RuleResult(
                    rule_id=self.rule_id,
                    result_type=RuleResultType.APPROVE,
                    message="No emergency imaging procedures found - rule skipped",
                    details={"reason": "no_emergency_imaging"}
                )
            
            validation_results = []
            overall_compliant = True
            missing_justifications = []
            timing_violations = []
            
            for imaging in emergency_imaging:
                procedure_code = imaging['code']
                
                has_justification, justification_date = self._check_justification_documentation(claim, procedure_code)
                
                if not has_justification:
                    overall_compliant = False
                    missing_justifications.append(procedure_code)
                    validation_results.append({
                        'procedure_code': procedure_code,
                        'procedure_name': imaging['name'],
                        'has_justification': False,
                        'justification_date': None,
                        'timing_compliant': False,
                        'timing_message': "No justification provided"
                    })
                else:
                    timing_compliant, timing_message = self._validate_justification_timing(claim.service_date, justification_date)
                    
                    if not timing_compliant:
                        overall_compliant = False
                        timing_violations.append(procedure_code)
                    
                    validation_results.append({
                        'procedure_code': procedure_code,
                        'procedure_name': imaging['name'],
                        'has_justification': True,
                        'justification_date': justification_date,
                        'timing_compliant': timing_compliant,
                        'timing_message': timing_message
                    })
            
            details = {
                "emergency_imaging_procedures": [img['code'] for img in emergency_imaging],
                "validation_results": validation_results,
                "missing_justifications": missing_justifications,
                "timing_violations": timing_violations,
                "justification_deadline_days": self.justification_deadline_days
            }
            
            if missing_justifications:
                return RuleResult(
                    rule_id=self.rule_id,
                    result_type=RuleResultType.FLAG,
                    message=f"Missing emergency imaging justification for: {', '.join(missing_justifications)}",
                    details=details
                )
            
            if timing_violations:
                return RuleResult(
                    rule_id=self.rule_id,
                    result_type=RuleResultType.FLAG,
                    message=f"Emergency imaging justification timing violations: {', '.join(timing_violations)}",
                    details=details
                )
            
            context.emergency_imaging_validated = True
            
            return RuleResult(
                rule_id=self.rule_id,
                result_type=RuleResultType.APPROVE,
                message=f"Emergency imaging justification validated for {len(emergency_imaging)} procedures",
                details=details
            )
            
        except Exception as e:
            logger.error(f"Error in EmergencyImagingRule evaluation: {str(e)}")
            return RuleResult(
                rule_id=self.rule_id,
                result_type=RuleResultType.FLAG,
                message=f"Error during emergency imaging validation: {str(e)}",
                details={"error": str(e)}
            )