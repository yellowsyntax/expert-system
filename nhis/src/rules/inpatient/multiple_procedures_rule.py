from typing import Dict, Any, List, Tuple
from datetime import datetime
from ..base_rule import BaseRule, RuleResult, RuleDecision, RuleSeverity
from ...database.repositories import TariffRepository

class MultipleProceduresRule(BaseRule):
    def __init__(self, db_session, reference_data_manager):
        super().__init__(db_session, reference_data_manager)
        self.tariff_repo = TariffRepository(db_session)
    
    def validate(self, claim_data: Dict[str, Any], context: Dict[str, Any]) -> RuleResult:
        service_type = claim_data.get('service_type_1')
        procedures = self._extract_procedures(claim_data)
        
        if service_type != 'IPD':
            return self.approve(
                reason="Multiple procedures rule only applies to inpatient (IPD) claims",
                metadata={'service_type': service_type, 'rule_applied': False}
            )
        
        if len(procedures) <= 1:
            return self.approve(
                reason="Single or no procedures - multiple procedure rule not applicable",
                metadata={
                    'procedure_count': len(procedures),
                    'procedures': procedures,
                    'rule_applied': False
                }
            )
        
        try:
            return self._validate_multiple_procedures(procedures, claim_data)
            
        except Exception as e:
            return self.reject(
                reason="Error during multiple procedures validation",
                severity=RuleSeverity.CRITICAL,
                validation_errors=[f"Validation failed: {str(e)}"],
                metadata={'error_type': 'validation_error'}
            )
    
    def _extract_procedures(self, claim_data: Dict[str, Any]) -> List[Dict[str, Any]]:
        procedures = []
        
        main_procedure = claim_data.get('icd10_procedure')
        main_procedure_name = claim_data.get('procedure_name')
        main_gdrg = claim_data.get('g_drg_procedure')
        
        if main_procedure:
            procedures.append({
                'code': main_procedure,
                'name': main_procedure_name or 'Primary procedure',
                'gdrg_code': main_gdrg,
                'type': 'PRIMARY',
                'sequence': 1
            })
        
        additional_procedures = claim_data.get('additional_procedures', [])
        if isinstance(additional_procedures, list):
            for i, proc in enumerate(additional_procedures):
                if isinstance(proc, dict):
                    procedures.append({
                        'code': proc.get('code'),
                        'name': proc.get('name', f'Additional procedure {i+1}'),
                        'gdrg_code': proc.get('gdrg_code'),
                        'type': 'ADDITIONAL',
                        'sequence': i + 2
                    })
                elif isinstance(proc, str):
                    procedures.append({
                        'code': proc,
                        'name': f'Additional procedure {i+1}',
                        'gdrg_code': None,
                        'type': 'ADDITIONAL',
                        'sequence': i + 2
                    })
        
        procedure_fields = ['procedure_2', 'procedure_3', 'procedure_4', 'procedure_5']
        for i, field in enumerate(procedure_fields):
            proc_code = claim_data.get(field)
            if proc_code:
                procedures.append({
                    'code': proc_code,
                    'name': f'Procedure {i+2}',
                    'gdrg_code': claim_data.get(f'gdrg_{field}'),
                    'type': 'ADDITIONAL',
                    'sequence': i + 2
                })
        
        return [p for p in procedures if p.get('code')]
    
    def _validate_multiple_procedures(self, procedures: List[Dict[str, Any]], 
                                    claim_data: Dict[str, Any]) -> RuleResult:
        
        facility_level = claim_data.get('healthcare_level', 'C')
        patient_dob = claim_data.get('date_of_birth')
        
        age_suffix = 'A'
        if patient_dob:
            is_child = self.is_child(patient_dob)
            age_suffix = 'C' if is_child else 'A'
        
        procedure_values = []
        total_base_value = 0.0
        validation_errors = []
        
        for procedure in procedures:
            proc_code = procedure.get('code')
            proc_value = self._get_procedure_value(proc_code, facility_level, age_suffix)
            
            if proc_value is None:
                validation_errors.append(
                    f"Procedure {proc_code} not found in tariff database"
                )
                proc_value = 0.0
            
            procedure_values.append({
                **procedure,
                'base_value': proc_value,
                'validated': proc_value > 0
            })
            total_base_value += proc_value
        
        if validation_errors:
            return self.reject(
                reason="Some procedures could not be validated",
                severity=RuleSeverity.HIGH,
                validation_errors=validation_errors,
                recommendations=[
                    "Verify all procedure codes are correct and in NHIS tariff database",
                    "Check procedure coding standards compliance",
                    "Ensure procedures are appropriate for facility level"
                ],
                metadata={
                    'procedures': procedure_values,
                    'invalid_procedures': len(validation_errors)
                }
            )
        
        multiple_procedure_rules = self.get_reference_data('bundling_rules').get('multiple_procedures', {})
        payment_percentages = multiple_procedure_rules.get('payment_percentages', [100, 20, 20, 20, 20])
        
        sorted_procedures = sorted(procedure_values, key=lambda x: x['base_value'], reverse=True)
        
        calculated_amounts = self._calculate_multiple_procedure_amounts(
            sorted_procedures, payment_percentages
        )
        
        total_calculated_amount = sum(p['calculated_amount'] for p in calculated_amounts)
        total_savings = total_base_value - total_calculated_amount
        
        return self._create_multiple_procedure_result(
            calculated_amounts, total_base_value, total_calculated_amount, 
            total_savings, payment_percentages, claim_data
        )
    
    def _get_procedure_value(self, procedure_code: str, facility_level: str, age_suffix: str) -> float:
        if not procedure_code:
            return None
        
        if procedure_code.startswith('ZOOM'):
            tariff = self.tariff_repo.get_zoom_procedure_tariff(procedure_code, facility_level)
        elif procedure_code.startswith('SURG'):
            tariff = self.tariff_repo.get_surgery_procedure_tariff(procedure_code, facility_level)
        elif procedure_code.startswith('OPD'):
            tariff = self.tariff_repo.get_opd_procedure_tariff(procedure_code, facility_level)
        elif procedure_code.startswith('DENT'):
            tariff = self.tariff_repo.get_dental_procedure_tariff(procedure_code, facility_level)
        elif procedure_code.startswith('ENT'):
            tariff = self.tariff_repo.get_ent_procedure_tariff(procedure_code, facility_level)
        elif procedure_code.startswith('MEDI'):
            tariff = self.tariff_repo.get_medicine_procedure_tariff(procedure_code, facility_level)
        elif procedure_code.startswith('PAED'):
            tariff = self.tariff_repo.get_paediatric_procedure_tariff(procedure_code, facility_level)
        else:
            tariff = self.tariff_repo.get_investigation_tariff(procedure_code)
        
        return float(tariff) if tariff else None
    
    def _calculate_multiple_procedure_amounts(self, sorted_procedures: List[Dict[str, Any]], 
                                           payment_percentages: List[int]) -> List[Dict[str, Any]]:
        
        calculated_procedures = []
        
        for i, procedure in enumerate(sorted_procedures):
            if i < len(payment_percentages):
                percentage = payment_percentages[i]
            else:
                percentage = payment_percentages[-1] if payment_percentages else 20
            
            base_value = procedure['base_value']
            calculated_amount = base_value * (percentage / 100)
            
            calculated_procedures.append({
                **procedure,
                'payment_percentage': percentage,
                'calculated_amount': calculated_amount,
                'rank': i + 1,
                'is_primary_payment': percentage == 100
            })
        
        return calculated_procedures
    
    def _create_multiple_procedure_result(self, calculated_amounts: List[Dict[str, Any]], 
                                        total_base_value: float, total_calculated_amount: float,
                                        total_savings: float, payment_percentages: List[int],
                                        claim_data: Dict[str, Any]) -> RuleResult:
        
        procedure_count = len(calculated_amounts)
        primary_procedure = next(p for p in calculated_amounts if p['is_primary_payment'])
        reduced_procedures = [p for p in calculated_amounts if not p['is_primary_payment']]
        
        savings_percentage = (total_savings / total_base_value * 100) if total_base_value > 0 else 0
        
        metadata = {
            'procedure_count': procedure_count,
            'total_base_value': round(total_base_value, 2),
            'total_calculated_amount': round(total_calculated_amount, 2),
            'total_savings': round(total_savings, 2),
            'savings_percentage': round(savings_percentage, 2),
            'payment_schedule': payment_percentages,
            'primary_procedure': {
                'code': primary_procedure['code'],
                'name': primary_procedure['name'],
                'amount': round(primary_procedure['calculated_amount'], 2)
            },
            'reduced_procedures': [
                {
                    'code': p['code'],
                    'name': p['name'],
                    'base_amount': round(p['base_value'], 2),
                    'calculated_amount': round(p['calculated_amount'], 2),
                    'percentage': p['payment_percentage'],
                    'rank': p['rank']
                }
                for p in reduced_procedures
            ]
        }
        
        warnings = []
        recommendations = []
        
        if procedure_count > 5:
            warnings.append(
                f"High number of procedures ({procedure_count}) - verify all are medically necessary"
            )
            recommendations.append(
                "Review if all procedures could not be performed in a single session"
            )
        
        high_value_procedures = [p for p in calculated_amounts if p['base_value'] > 1000]
        if len(high_value_procedures) > 1:
            warnings.append(
                f"Multiple high-value procedures detected - may require clinical review"
            )
            recommendations.append(
                "Ensure all high-value procedures have appropriate clinical justification"
            )
        
        if savings_percentage > 50:
            warnings.append(
                f"Significant cost reduction applied ({savings_percentage:.1f}%) due to multiple procedures"
            )
        
        reason = f"Multiple procedures rule applied: {procedure_count} procedures, primary at 100%, others at reduced rates"
        
        if warnings:
            return self.flag(
                reason=reason,
                severity=RuleSeverity.LOW if procedure_count <= 3 else RuleSeverity.MEDIUM,
                affected_amount=total_calculated_amount,
                warnings=warnings,
                recommendations=recommendations,
                metadata=metadata
            )
        
        return self.approve(
            reason=reason,
            affected_amount=total_calculated_amount,
            metadata=metadata
        )
    
    def get_procedure_payment_breakdown(self, procedures: List[Dict[str, Any]], 
                                      facility_level: str = 'C') -> Dict[str, Any]:
        if not procedures:
            return {'error': 'No procedures provided'}
        
        try:
            procedure_values = []
            for procedure in procedures:
                proc_code = procedure.get('code')
                proc_value = self._get_procedure_value(proc_code, facility_level, 'A')
                
                procedure_values.append({
                    'code': proc_code,
                    'name': procedure.get('name', 'Unknown procedure'),
                    'base_value': proc_value or 0,
                    'validated': proc_value is not None
                })
            
            sorted_procedures = sorted(procedure_values, key=lambda x: x['base_value'], reverse=True)
            payment_percentages = [100, 20, 20, 20, 20]
            calculated_amounts = self._calculate_multiple_procedure_amounts(sorted_procedures, payment_percentages)
            
            return {
                'procedure_count': len(procedures),
                'procedures': calculated_amounts,
                'total_base_value': sum(p['base_value'] for p in procedure_values),
                'total_calculated_amount': sum(p['calculated_amount'] for p in calculated_amounts),
                'payment_rule': 'Primary procedure 100%, additional procedures 20% each'
            }
            
        except Exception as e:
            return {
                'error': f"Failed to calculate procedure breakdown: {str(e)}",
                'procedures': procedures
            }