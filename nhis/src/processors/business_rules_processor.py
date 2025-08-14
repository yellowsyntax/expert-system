"""
Business Rules Processor - Step 5: Business Rules & Calculation

Handles the final step of claim processing:
- G-DRG determination (A1-A4)
- Setting-specific rules (OPD: B1-B5, IPD: D1-D3, A&E: C)
- Medicine validation (Step 6)
- Investigation validation (Step 7)
- Documentation checks (Step 8)
- Modifier application (Step 9)
- Final amount calculation (Step 10)

This is the most complex processor that applies all remaining flowchart logic.
"""

from typing import Dict, List, Any
from decimal import Decimal
from datetime import datetime, timedelta

from ..core import (
    StandardClaim, ValidationIssue, ValidationSeverity, ProcessingStep,
    CalculationResult, LineItem, LineItemType, LineItemStatus,
    GDRGDeterminationMethod, EpisodeType
)
from .base_processor import ProcessorBase


class BusinessRulesProcessor(ProcessorBase):
    
    
    def __init__(self):
        super().__init__("BusinessRulesProcessor", ProcessingStep.BUSINESS_RULES_CALCULATION)
    
    def validate_inputs(self, claim: StandardClaim, context: Dict[str, Any] = None) -> List[ValidationIssue]:
        
        
        issues = []
        
        # Call base validation
        issues.extend(super().validate_inputs(claim, context))
        
        # Check that previous steps were successful
        if context:
            credentialing_status = context.get('credentialing_status')
            if credentialing_status in ['FACILITY_NOT_AUTHORIZED', 'MISSING_ACCREDITATION']:
                issues.append(self._create_validation_issue(
                    ValidationSeverity.CRITICAL,
                    "CREDENTIALING_FAILED",
                    f"Credentialing failed: {credentialing_status}",
                    {"credentialing_status": credentialing_status}
                ))
        
        return issues
    
    def _execute_processing(self, claim: StandardClaim, context: Dict[str, Any]) -> Dict[str, Any]:
        
        
        processing_data = {}
        
        # Initialize calculation result
        calculation_result = CalculationResult()
        
        # Step 1: G-DRG Determination (A1-A4 from flowchart)
        gdrg_result = self._perform_gdrg_determination(claim, context)
        processing_data.update(gdrg_result)
        
        if not gdrg_result.get('gdrg_determination_successful', False):
            # G-DRG determination failed
            processing_data['business_rules_status'] = 'GDRG_DETERMINATION_FAILED'
            processing_data['calculation_result'] = calculation_result
            return processing_data
        
        # Step 2: Apply Setting-Specific Rules
        setting_rules_result = self._apply_setting_specific_rules(claim, context, gdrg_result)
        processing_data.update(setting_rules_result)
        
        # Step 3: Medicine Validation (Step 6 from flowchart)
        medicine_result = self._validate_and_calculate_medicines(claim, context)
        processing_data['medicine_validation'] = medicine_result
        calculation_result.medicine_amount = medicine_result['total_amount']
        
        # Add medicine line items
        for line_item in medicine_result['line_items']:
            calculation_result.add_line_item(line_item)
        
        # Step 4: Investigation Validation (Step 7 from flowchart)  
        investigation_result = self._validate_and_calculate_investigations(claim, gdrg_result)
        processing_data['investigation_validation'] = investigation_result
        calculation_result.investigation_amount = investigation_result['total_amount']
        
        # Add investigation line items
        for line_item in investigation_result['line_items']:
            calculation_result.add_line_item(line_item)
        
        # Step 5: Documentation Validation (Step 8 from flowchart)
        documentation_result = self._validate_documentation(claim, context)
        processing_data['documentation_validation'] = documentation_result
        
        # Step 6: Calculate Base G-DRG Amount
        gdrg_amount_result = self._calculate_gdrg_amount(gdrg_result, claim)
        calculation_result.gdrg_amount = gdrg_amount_result['amount']
        
        # Add G-DRG line item
        if gdrg_amount_result['amount'] > 0:
            gdrg_line_item = LineItem(
                type=LineItemType.GDRG_TARIFF,
                code=gdrg_result['final_gdrg'],
                description=f"G-DRG {gdrg_result['final_gdrg']} - {gdrg_result.get('gdrg_description', '')}",
                total_amount=gdrg_amount_result['amount'],
                status=LineItemStatus.APPROVED if not documentation_result.get('has_pending_docs', False) else LineItemStatus.PENDING
            )
            calculation_result.add_line_item(gdrg_line_item)
        
        # Step 7: Apply Modifiers (Step 9 from flowchart)
        modifier_result = self._apply_modifiers(claim, calculation_result, gdrg_result)
        processing_data['modifier_application'] = modifier_result
        calculation_result.modifier_amount = modifier_result['total_modifier_amount']
        
        # Step 8: Final Calculation (Step 10 from flowchart)
        final_calculation = self._perform_final_calculation(
            calculation_result, 
            setting_rules_result, 
            documentation_result
        )
        processing_data.update(final_calculation)
        
        # Update calculation result with final amounts
        processing_data['calculation_result'] = calculation_result
        processing_data['business_rules_status'] = 'COMPLETED'
        
        self._log_processing_step(
            "BUSINESS_RULES_COMPLETE",
            f"Business rules processing completed",
            {
                "final_gdrg": gdrg_result.get('final_gdrg'),
                "total_approved": str(calculation_result.total_approved),
                "total_denied": str(calculation_result.total_denied)
            }
        )
        
        return processing_data
    
    def _perform_gdrg_determination(self, claim: StandardClaim, context: Dict[str, Any]) -> Dict[str, Any]:
       
        
        result = {
            'gdrg_determination_successful': False,
            'final_gdrg': None,
            'gdrg_description': None,
            'determination_method': None,
            'age_suffix_applied': None,
            'tariff_found': False
        }
        
        # A1: ICD-10 Present? (already validated in intake)
        icd10_code = context.get('normalized_icd10', claim.icd10_diagnosis)
        
        # A2: Procedures Present?
        if claim.procedures and len(claim.procedures) > 0:
            # Procedure Path: Dominant procedure determines G-DRG
            result['determination_method'] = GDRGDeterminationMethod.PROCEDURE
            core_gdrg = self._determine_dominant_procedure_gdrg(claim.procedures, context)
        else:
            # Diagnosis Path: Primary diagnosis determines G-DRG  
            result['determination_method'] = GDRGDeterminationMethod.DIAGNOSIS
            core_gdrg = self._determine_diagnosis_gdrg(icd10_code, claim.encounter_type.value)
        
        if not core_gdrg:
            result['error'] = 'Could not determine core G-DRG'
            return result
        
        # A3: Apply Age Split
        age_suffix = claim.get_age_suffix()
        final_gdrg = f"{core_gdrg[:-1]}{age_suffix}"  # Replace last character with age suffix
        
        result['final_gdrg'] = final_gdrg
        result['age_suffix_applied'] = age_suffix
        
        # A4: Get Facility Tariff
        tariff_info = self._get_facility_tariff(final_gdrg, claim.facility_level)
        
        if tariff_info:
            result['tariff_found'] = True
            result['tariff_info'] = tariff_info
            result['gdrg_determination_successful'] = True
            result['gdrg_description'] = tariff_info.get('description', '')
        else:
            result['error'] = f'No tariff found for G-DRG {final_gdrg} at facility level {claim.facility_level}'
        
        return result
    
    def _determine_dominant_procedure_gdrg(self, procedures: List[Dict[str, Any]], 
                                          context: Dict[str, Any]) -> str:
        
        # For now, use the first claimed G-DRG from context
        # In a full implementation, this would analyze procedure codes and resource weights
        candidate_gdrgs = context.get('candidate_gdrgs', [])
        return candidate_gdrgs[0] if candidate_gdrgs else None
    
    def _determine_diagnosis_gdrg(self, icd10_code: str, encounter_type: str) -> str:
        
        
        if not self._check_reference_data_available():
            return None
        
        mapping = self.reference_manager.get_gdrg_for_diagnosis(icd10_code, encounter_type)
        return mapping.get('gdrg_code') if mapping else None
    
    def _get_facility_tariff(self, gdrg_code: str, facility_level: str) -> Dict[str, Any]:
        
        
        # Mock tariff data - in real implementation would come from tariff database
        base_tariffs = {
            'MEDI07A': {'amount': Decimal('2500.00'), 'description': 'Cardiac emergencies'},
            'OPDC06A': {'amount': Decimal('150.00'), 'description': 'General OPD consultation'},
            'MEDI02A': {'amount': Decimal('800.00'), 'description': 'Medical condition'},
            'MEDI06A': {'amount': Decimal('1200.00'), 'description': 'Medical condition'},
        }
        
        base_tariff = base_tariffs.get(gdrg_code)
        if not base_tariff:
            return None
        
        # Apply facility level adjustments
        level_multipliers = {
            'A': 0.8, 'B1': 0.9, 'B2': 0.95, 'C': 1.0, 
            'D1': 1.1, 'D2': 1.2, 'M': 1.15, 'T': 1.3
        }
        
        multiplier = level_multipliers.get(facility_level, 1.0)
        adjusted_amount = base_tariff['amount'] * Decimal(str(multiplier))
        
        return {
            'base_amount': base_tariff['amount'],
            'facility_multiplier': multiplier,
            'final_amount': adjusted_amount,
            'description': base_tariff['description']
        }
    
    def _apply_setting_specific_rules(self, claim: StandardClaim, context: Dict[str, Any],
                                     gdrg_result: Dict[str, Any]) -> Dict[str, Any]:
        
        
        encounter_type = claim.encounter_type.value
        
        if encounter_type == 'OPD':
            return self._apply_opd_rules(claim, context)
        elif encounter_type == 'IPD':
            return self._apply_inpatient_rules(claim, context)
        elif encounter_type in ['A&E', 'EMERGENCY', 'CASUALTY']:
            return self._apply_emergency_rules(claim, context)
        else:
            return {'setting_rules_status': 'NO_SPECIFIC_RULES'}
    
    def _apply_opd_rules(self, claim: StandardClaim, context: Dict[str, Any]) -> Dict[str, Any]:
        
        
        result = {
            'setting_rules_status': 'OPD_RULES_APPLIED',
            'episode_validation': {},
            'multi_specialty_check': {},
            'physiotherapy_validation': {},
            'rule_violations': []
        }
        
        # B2: Episode Type and Limits
        episode_result = self._validate_episode_limits(claim)
        result['episode_validation'] = episode_result
        
        if episode_result.get('limit_exceeded', False):
            result['rule_violations'].append({
                'rule': 'B2_EPISODE_LIMITS',
                'severity': 'CRITICAL' if episode_result['episode_type'] in ['ACUTE', 'ANTENATAL', 'POSTNATAL'] else 'MAJOR',
                'message': episode_result['violation_message']
            })
        
        # B3: Multi-Specialty Same Day (simplified check)
        if len(claim.specialties_attended) > 1:
            result['multi_specialty_check'] = {
                'multiple_specialties': True,
                'specialties_count': len(claim.specialties_attended),
                'rule_applied': 'PAY_HIGHEST_ONLY'
            }
        
        # B5: Physiotherapy Validation
        if self._has_physiotherapy_procedures(claim):
            physio_result = self._validate_physiotherapy(claim)
            result['physiotherapy_validation'] = physio_result
            
            if not physio_result.get('eligible', True):
                result['rule_violations'].append({
                    'rule': 'B5_PHYSIOTHERAPY',
                    'severity': 'CRITICAL',
                    'message': physio_result.get('rejection_reason', 'Physiotherapy not eligible')
                })
        
        return result
    
    def _apply_inpatient_rules(self, claim: StandardClaim, context: Dict[str, Any]) -> Dict[str, Any]:
        
        
        result = {
            'setting_rules_status': 'INPATIENT_RULES_APPLIED',
            'billing_timing_check': {},
            'multiple_procedures_check': {},
            'readmission_check': {},
            'rule_violations': []
        }
        
        # D1: Bill Timing
        if not claim.discharge_date:
            result['rule_violations'].append({
                'rule': 'D1_BILLING_TIMING',
                'severity': 'CRITICAL',
                'message': 'Missing discharge date for inpatient claim'
            })
        elif claim.discharge_date > datetime.now().date():
            result['rule_violations'].append({
                'rule': 'D1_BILLING_TIMING', 
                'severity': 'CRITICAL',
                'message': 'Cannot bill before discharge'
            })
        
        # D2: Multiple Procedures
        if len(claim.procedures) > 1:
            multiple_proc_result = self._calculate_multiple_procedures(claim.procedures)
            result['multiple_procedures_check'] = multiple_proc_result
        
        # D3: Emergency Readmission Rule (simplified)
        if claim.admission_date and claim.discharge_date:
            length_of_stay = (claim.discharge_date.date() - claim.admission_date.date()).days
            result['readmission_check'] = {
                'length_of_stay': length_of_stay,
                'readmission_risk': length_of_stay < 3  # Simplified rule
            }
        
        return result
    
    def _apply_emergency_rules(self, claim: StandardClaim, context: Dict[str, Any]) -> Dict[str, Any]:
        
        
        result = {
            'setting_rules_status': 'EMERGENCY_RULES_APPLIED',
            'ae_classification': 'MANAGED_AS_OPD',  # Default classification
            'emergency_imaging_check': {},
            'rule_violations': []
        }
        
        # Simplified A&E classification
        if claim.admission_date and claim.discharge_date:
            # Requires admission
            result['ae_classification'] = 'REQUIRES_ADMISSION'
        elif hasattr(claim, 'detention_hours') and getattr(claim, 'detention_hours', 0) > 0:
            # Detained less than 24h
            result['ae_classification'] = 'DETENTION_UNDER_24H'
        
        return result
    
    def _validate_episode_limits(self, claim: StandardClaim) -> Dict[str, Any]:
        
        
        result = {
            'episode_type': None,
            'limit_exceeded': False,
            'current_visits': 0,
            'max_visits': 0,
            'violation_message': None
        }
        
        # Determine episode type
        if self._check_reference_data_available():
            is_chronic = self.reference_manager.is_chronic_condition(claim.icd10_diagnosis)
            if is_chronic:
                result['episode_type'] = 'CHRONIC'
                result['max_visits'] = 6  # 6 visits in 12 months
            else:
                result['episode_type'] = 'ACUTE'
                result['max_visits'] = 3  # 3 visits in 14 days
        
        # For now, assume first visit (would query database in real implementation)
        result['current_visits'] = 1
        
        return result
    
    def _validate_physiotherapy(self, claim: StandardClaim) -> Dict[str, Any]:
       
        
        result = {
            'eligible': True,
            'max_sessions': 0,
            'current_sessions': 0,
            'rejection_reason': None
        }
        
        if self._check_reference_data_available():
            is_eligible = self.reference_manager.is_physiotherapy_eligible_condition(claim.icd10_diagnosis)
            
            if not is_eligible:
                result['eligible'] = False
                result['rejection_reason'] = f'Condition {claim.icd10_diagnosis} not eligible for physiotherapy'
            else:
                max_sessions = self.reference_manager.get_physiotherapy_session_limit(claim.icd10_diagnosis)
                result['max_sessions'] = max_sessions or 12
        
        return result
    
    def _has_physiotherapy_procedures(self, claim: StandardClaim) -> bool:
        """Check if claim includes physiotherapy procedures"""
        return any('physio' in proc.get('name', '').lower() for proc in claim.procedures)
    
    def _calculate_multiple_procedures(self, procedures: List[Dict[str, Any]]) -> Dict[str, Any]:
        
        
        # Sort procedures by amount (highest first)
        sorted_procedures = sorted(procedures, key=lambda p: p.get('amount', 0), reverse=True)
        
        result = {
            'total_procedures': len(procedures),
            'payment_breakdown': [],
            'total_payment_amount': Decimal('0.00')
        }
        
        for i, procedure in enumerate(sorted_procedures):
            base_amount = Decimal(str(procedure.get('amount', 0)))
            
            if i == 0:  # Major procedure - 100%
                payment_percentage = 100
                payment_amount = base_amount
            elif i in [1, 2]:  # 2nd and 3rd procedures - 20% each
                payment_percentage = 20
                payment_amount = base_amount * Decimal('0.20')
            else:  # 4th+ procedures - 0%
                payment_percentage = 0
                payment_amount = Decimal('0.00')
            
            result['payment_breakdown'].append({
                'procedure': procedure.get('name', 'Unknown'),
                'base_amount': base_amount,
                'payment_percentage': payment_percentage,
                'payment_amount': payment_amount
            })
            
            result['total_payment_amount'] += payment_amount
        
        return result
    
    def _validate_and_calculate_medicines(self, claim: StandardClaim, context: Dict[str, Any]) -> Dict[str, Any]:
        
        
        result = {
            'total_amount': Decimal('0.00'),
            'approved_amount': Decimal('0.00'),
            'denied_amount': Decimal('0.00'),
            'line_items': [],
            'validation_issues': []
        }
        
        if not claim.medicines:
            return result
        
        for medicine in claim.medicines:
            medicine_result = self._validate_single_medicine(medicine, claim)
            
            # Create line item
            line_item = LineItem(
                type=LineItemType.MEDICINE,
                code=medicine.get('code', 'UNKNOWN'),
                description=medicine.get('name', 'Unknown Medicine'),
                quantity=medicine.get('quantity', 1),
                unit_amount=Decimal(str(medicine.get('unit_price', 0))),
                total_amount=medicine_result['amount'],
                status=medicine_result['status']
            )
            
            result['line_items'].append(line_item)
            result['total_amount'] += medicine_result['amount']
            
            if medicine_result['status'] == LineItemStatus.APPROVED:
                result['approved_amount'] += medicine_result['amount']
            else:
                result['denied_amount'] += medicine_result['amount']
        
        return result
    
    def _validate_single_medicine(self, medicine: Dict[str, Any], claim: StandardClaim) -> Dict[str, Any]:
        
        
        medicine_code = medicine.get('code')
        amount = Decimal(str(medicine.get('amount', 0)))
        
        result = {
            'amount': amount,
            'status': LineItemStatus.APPROVED,
            'validation_notes': []
        }
        
        if not self._check_reference_data_available():
            return result
        
        # Check if medicine is in formulary
        is_in_formulary = self.reference_manager.is_medicine_in_formulary(
            medicine_code, 
            claim.icd10_diagnosis
        )
        
        if not is_in_formulary:
            result['status'] = LineItemStatus.DENIED
            result['validation_notes'].append('Medicine not in NHIS formulary for this indication')
        
        return result
    
    def _validate_and_calculate_investigations(self, claim: StandardClaim, 
                                             gdrg_result: Dict[str, Any]) -> Dict[str, Any]:
        
        
        result = {
            'total_amount': Decimal('0.00'),
            'approved_amount': Decimal('0.00'),
            'denied_amount': Decimal('0.00'),
            'line_items': [],
            'bundling_info': {}
        }
        
        if not claim.investigations:
            return result
        
        # Get bundling rules for the G-DRG
        if self._check_reference_data_available():
            gdrg_code = gdrg_result.get('final_gdrg')
            bundling_rules = self.reference_manager.get_investigation_bundling_rules(gdrg_code)
            result['bundling_info'] = bundling_rules
        
        for investigation in claim.investigations:
            investigation_result = self._validate_single_investigation(investigation, result['bundling_info'])
            
            # Create line item
            line_item = LineItem(
                type=LineItemType.INVESTIGATION,
                code=investigation.get('code', 'UNKNOWN'),
                description=investigation.get('description', 'Unknown Investigation'),
                total_amount=investigation_result['amount'],
                status=investigation_result['status']
            )
            
            result['line_items'].append(line_item)
            result['total_amount'] += investigation_result['amount']
            
            if investigation_result['status'] == LineItemStatus.APPROVED:
                result['approved_amount'] += investigation_result['amount']
            else:
                result['denied_amount'] += investigation_result['amount']
        
        return result
    
    def _validate_single_investigation(self, investigation: Dict[str, Any],
                                     bundling_info: Dict[str, Any]) -> Dict[str, Any]:
        
        
        amount = Decimal(str(investigation.get('amount', 0)))
        
        result = {
            'amount': amount,
            'status': LineItemStatus.APPROVED,
            'validation_notes': []
        }
        
        # Check bundling rules
        bundle_type = bundling_info.get('bundle_type', 'UNBUNDLED')
        
        if bundle_type == 'ALL_INCLUSIVE':
            separately_billable = bundling_info.get('separately_billable_items', [])
            investigation_code = investigation.get('code', '')
            
            if investigation_code not in separately_billable:
                result['status'] = LineItemStatus.DENIED
                result['validation_notes'].append('Investigation included in G-DRG tariff')
        
        return result
    
    def _validate_documentation(self, claim: StandardClaim, context: Dict[str, Any]) -> Dict[str, Any]:
        
        
        result = {
            'has_pending_docs': False,
            'missing_documents': [],
            'provided_documents': claim.provided_documents or [],
            'documentation_issues': []
        }
        
        if self._check_reference_data_available():
            required_docs = self.reference_manager.get_required_documentation(
                claim.icd10_diagnosis,
                claim.encounter_type.value
            )
            
            missing_docs = [doc for doc in required_docs if doc not in result['provided_documents']]
            
            if missing_docs:
                result['has_pending_docs'] = True
                result['missing_documents'] = missing_docs
                result['documentation_issues'].append(f'Missing required documents: {missing_docs}')
        
        return result
    
    def _apply_modifiers(self, claim: StandardClaim, calculation_result: CalculationResult,
                        gdrg_result: Dict[str, Any]) -> Dict[str, Any]:
       
        
        result = {
            'modifiers_applied': [],
            'total_modifier_amount': Decimal('0.00'),
            'modifier_details': []
        }
        
        # Check for bilateral surgery modifier
        if claim.modifiers.get('bilateral_surgery', False):
            bilateral_modifier = self._apply_bilateral_surgery_modifier(calculation_result.gdrg_amount)
            result['modifiers_applied'].append('BILATERAL_SURGERY')
            result['total_modifier_amount'] += bilateral_modifier['modifier_amount']
            result['modifier_details'].append(bilateral_modifier)
        
        # Check for emergency modifier
        if claim.is_emergency_encounter():
            emergency_modifier = self._apply_emergency_modifier(calculation_result.gdrg_amount)
            result['modifiers_applied'].append('EMERGENCY')
            result['total_modifier_amount'] += emergency_modifier['modifier_amount']
            result['modifier_details'].append(emergency_modifier)
        
        return result
    
    def _apply_bilateral_surgery_modifier(self, base_amount: Decimal) -> Dict[str, Any]:
        """Apply 120% modifier for bilateral surgery"""
        modifier_amount = base_amount * Decimal('0.20')
        return {
            'type': 'BILATERAL_SURGERY',
            'base_amount': base_amount,
            'modifier_percentage': 20,
            'modifier_amount': modifier_amount,
            'final_amount': base_amount + modifier_amount
        }
    
    def _apply_emergency_modifier(self, base_amount: Decimal) -> Dict[str, Any]:
        """Apply emergency modifier"""
        modifier_amount = base_amount * Decimal('0.10')  # 10% emergency modifier
        return {
            'type': 'EMERGENCY',
            'base_amount': base_amount,
            'modifier_percentage': 10,
            'modifier_amount': modifier_amount,
            'final_amount': base_amount + modifier_amount
        }
    
    def _calculate_gdrg_amount(self, gdrg_result: Dict[str, Any], claim: StandardClaim) -> Dict[str, Any]:
        
        
        result = {
            'amount': Decimal('0.00'),
            'tariff_details': {},
            'calculation_notes': []
        }
        
        tariff_info = gdrg_result.get('tariff_info')
        if not tariff_info:
            result['calculation_notes'].append('No tariff information available')
            return result
        
        base_amount = tariff_info.get('final_amount', Decimal('0.00'))
        result['amount'] = base_amount
        result['tariff_details'] = {
            'gdrg_code': gdrg_result.get('final_gdrg'),
            'base_amount': tariff_info.get('base_amount'),
            'facility_multiplier': tariff_info.get('facility_multiplier'),
            'final_amount': base_amount
        }
        
        return result
    
    def _perform_final_calculation(self, calculation_result: CalculationResult,
                                  setting_rules_result: Dict[str, Any],
                                  documentation_result: Dict[str, Any]) -> Dict[str, Any]:
       
        
        result = {
            'final_calculation_complete': True,
            'final_decision_factors': [],
            'calculation_summary': {}
        }
        
        # Check for critical rule violations that cause rejection
        rule_violations = setting_rules_result.get('rule_violations', [])
        critical_violations = [v for v in rule_violations if v.get('severity') == 'CRITICAL']
        
        if critical_violations:
            result['final_decision_factors'].append('CRITICAL_RULE_VIOLATIONS')
            # Move approved amounts to denied
            calculation_result.total_denied += calculation_result.total_approved
            calculation_result.total_approved = Decimal('0.00')
        
        # Check for pending documentation
        if documentation_result.get('has_pending_docs', False):
            result['final_decision_factors'].append('MISSING_DOCUMENTATION')
            # Move approved amounts to pending
            calculation_result.total_pending += calculation_result.total_approved
            calculation_result.total_approved = Decimal('0.00')
        
        # Apply multi-specialty same day rule (pay highest only)
        multi_specialty_check = setting_rules_result.get('multi_specialty_check', {})
        if multi_specialty_check.get('multiple_specialties', False):
            result['final_decision_factors'].append('MULTI_SPECIALTY_SAME_DAY')
            # Would implement highest-only payment logic here
        
        # Calculate final totals
        total_claimed = (calculation_result.total_approved + 
                        calculation_result.total_denied + 
                        calculation_result.total_pending)
        
        result['calculation_summary'] = {
            'total_claimed': str(total_claimed),
            'total_approved': str(calculation_result.total_approved),
            'total_denied': str(calculation_result.total_denied),
            'total_pending': str(calculation_result.total_pending),
            'gdrg_amount': str(calculation_result.gdrg_amount),
            'medicine_amount': str(calculation_result.medicine_amount),
            'investigation_amount': str(calculation_result.investigation_amount),
            'modifier_amount': str(calculation_result.modifier_amount)
        }
        
        return result
    
    def get_business_rules_processor_info(self) -> Dict[str, Any]:
        """Get processor-specific information"""
        
        info = self.get_processor_metadata()
        info.update({
            "processing_steps": [
                "G-DRG Determination (A1-A4)",
                "Setting-Specific Rules (B1-B5, D1-D3, C)",
                "Medicine Validation (Step 6)",
                "Investigation Validation (Step 7)", 
                "Documentation Validation (Step 8)",
                "Modifier Application (Step 9)",
                "Final Calculation (Step 10)"
            ],
            "flowchart_nodes": [
                "A1-A4: G-DRG Determination",
                "B1-B5: OPD Rules",
                "C: A&E Rules", 
                "D1-D3: Inpatient Rules",
                "Step 6: Medicine Validation",
                "Step 7: Investigation Validation",
                "Step 8: Documentation Validation",
                "Step 9: Modifier Application",
                "Step 10: Final Calculation"
            ],
            "supported_modifiers": [
                "BILATERAL_SURGERY",
                "EMERGENCY",
                "MULTIPLE_PROCEDURES",
                "DENTAL_MULTI_TOOTH"
            ],
            "episode_types": [
                "ACUTE",
                "CHRONIC", 
                "ANTENATAL",
                "POSTNATAL"
            ]
        })
        
        return info