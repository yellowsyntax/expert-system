from typing import Dict, Any, List, Tuple
from datetime import datetime
from ..base_rule import BaseRule, RuleResult, RuleDecision, RuleSeverity
from ...database.queries import EpisodeTrackingQueries

class MultiSpecialtyRule(BaseRule):
    def __init__(self, db_session, reference_data_manager):
        super().__init__(db_session, reference_data_manager)
        self.episode_queries = EpisodeTrackingQueries(db_session)
    
    def validate(self, claim_data: Dict[str, Any], context: Dict[str, Any]) -> RuleResult:
        nhis_number = claim_data.get('nhis_number')
        service_type = claim_data.get('service_type_1')
        admission_date = claim_data.get('admission_date')
        specialties_attended = claim_data.get('specialties_attended')
        current_gdrg = claim_data.get('g_drg_diagnosis') or claim_data.get('g_drg_procedure')
        
        if not nhis_number:
            return self.reject(
                reason="NHIS number is required for multi-specialty validation",
                validation_errors=["Missing NHIS number"]
            )
        
        if service_type != 'OPD':
            return self.approve(
                reason="Multi-specialty rule only applies to OPD visits",
                metadata={'service_type': service_type, 'rule_applied': False}
            )
        
        if not admission_date:
            admission_date = datetime.utcnow()
        
        try:
            same_day_visits = self.episode_queries.get_same_day_specialty_visits(
                nhis_number=nhis_number,
                visit_date=admission_date
            )
            
            if not same_day_visits:
                return self.approve(
                    reason="No other visits found on the same day",
                    metadata={'same_day_visits': 0, 'rule_applied': False}
                )
            
            if len(same_day_visits) == 1 and same_day_visits[0].get('id') == claim_data.get('id'):
                return self.approve(
                    reason="Only visit on this date",
                    metadata={'same_day_visits': 1, 'rule_applied': False}
                )
            
            return self._validate_multi_specialty_visits(
                claim_data, same_day_visits, current_gdrg, admission_date
            )
            
        except Exception as e:
            return self.reject(
                reason="Error during multi-specialty validation",
                severity=RuleSeverity.CRITICAL,
                validation_errors=[f"Database query failed: {str(e)}"],
                metadata={'error_type': 'database_error'}
            )
    
    def _validate_multi_specialty_visits(self, current_claim: Dict[str, Any], 
                                       same_day_visits: List[Dict[str, Any]], 
                                       current_gdrg: str, admission_date: datetime) -> RuleResult:
        
        multi_specialty_rules = self.get_reference_data('bundling_rules').get('multi_specialty', {})
        
        specialty_visits = []
        current_claim_specialty = self._extract_specialty(current_claim.get('specialties_attended', ''))
        
        for visit in same_day_visits:
            if visit.get('id') != current_claim.get('id'):
                visit_specialty = self._extract_specialty(visit.get('specialties_attended', ''))
                specialty_visits.append({
                    'id': visit.get('id'),
                    'encounter_id': visit.get('encounter_id'),
                    'specialty': visit_specialty,
                    'procedure_name': visit.get('procedure_name'),
                    'admission_date': visit.get('admission_date')
                })
        
        if not specialty_visits:
            return self.approve(
                reason="No other specialty visits found on the same day",
                metadata={'same_day_visits': len(same_day_visits), 'rule_applied': False}
            )
        
        all_specialties = [current_claim_specialty] + [v['specialty'] for v in specialty_visits]
        unique_specialties = list(set([s for s in all_specialties if s]))
        
        if len(unique_specialties) <= 1:
            return self.approve(
                reason="All visits are for the same specialty - no multi-specialty conflict",
                metadata={
                    'specialties': unique_specialties,
                    'same_day_visits': len(same_day_visits),
                    'rule_applied': False
                }
            )
        
        highest_value_visit = self._determine_highest_value_visit(
            current_claim, specialty_visits, current_gdrg
        )
        
        data_used = {
            'nhis_number': current_claim.get('nhis_number'),
            'visit_date': admission_date.isoformat() if admission_date else None,
            'current_claim_id': current_claim.get('id'),
            'current_specialty': current_claim_specialty,
            'same_day_visits': specialty_visits,
            'all_specialties': unique_specialties,
            'highest_value_visit': highest_value_visit
        }
        
        if highest_value_visit['is_current_claim']:
            return self._approve_highest_value_visit(
                current_claim, specialty_visits, highest_value_visit, data_used
            )
        else:
            return self._reject_lower_value_visit(
                current_claim, specialty_visits, highest_value_visit, data_used
            )
    
    def _extract_specialty(self, specialties_string: str) -> str:
        if not specialties_string:
            return "GENERAL"
        
        specialties = [s.strip().upper() for s in specialties_string.split(',')]
        return specialties[0] if specialties else "GENERAL"
    
    def _determine_highest_value_visit(self, current_claim: Dict[str, Any], 
                                     other_visits: List[Dict[str, Any]], 
                                     current_gdrg: str) -> Dict[str, Any]:
        
        current_value = self._estimate_visit_value(current_claim, current_gdrg)
        
        highest_visit = {
            'is_current_claim': True,
            'visit_id': current_claim.get('id'),
            'encounter_id': current_claim.get('encounter_id'),
            'estimated_value': current_value,
            'specialty': self._extract_specialty(current_claim.get('specialties_attended', '')),
            'reason': 'Current claim has highest estimated value'
        }
        
        for visit in other_visits:
            visit_value = self._estimate_visit_value(visit, visit.get('gdrg_code'))
            
            if visit_value > highest_visit['estimated_value']:
                highest_visit = {
                    'is_current_claim': False,
                    'visit_id': visit.get('id'),
                    'encounter_id': visit.get('encounter_id'),
                    'estimated_value': visit_value,
                    'specialty': visit.get('specialty'),
                    'reason': f'Other visit has higher estimated value ({visit_value} vs {highest_visit["estimated_value"]})'
                }
        
        return highest_visit
    
    def _estimate_visit_value(self, visit_data: Dict[str, Any], gdrg_code: str) -> float:
        gdrg_mapping = self.get_reference_data('icd10_gdrg_mapping')
        
        if gdrg_code and gdrg_mapping:
            for mapping in gdrg_mapping.values():
                if mapping.get('gdrg_code') == gdrg_code:
                    return mapping.get('estimated_value', 0.0)
        
        specialty = self._extract_specialty(visit_data.get('specialties_attended', ''))
        
        specialty_values = {
            'SURGERY': 500.0,
            'CARDIOLOGY': 400.0,
            'NEUROLOGY': 350.0,
            'ONCOLOGY': 350.0,
            'ORTHOPEDICS': 300.0,
            'OPHTHALMOLOGY': 250.0,
            'ENT': 250.0,
            'DERMATOLOGY': 200.0,
            'PSYCHIATRY': 200.0,
            'PEDIATRICS': 150.0,
            'OBSTETRICS': 150.0,
            'GYNECOLOGY': 150.0,
            'INTERNAL_MEDICINE': 100.0,
            'FAMILY_MEDICINE': 80.0,
            'GENERAL': 50.0
        }
        
        return specialty_values.get(specialty, 50.0)
    
    def _approve_highest_value_visit(self, current_claim: Dict[str, Any], 
                                   other_visits: List[Dict[str, Any]],
                                   highest_visit: Dict[str, Any], 
                                   data_used: Dict[str, Any]) -> RuleResult:
        
        other_visit_count = len(other_visits)
        other_specialties = [v['specialty'] for v in other_visits]
        
        return self.approve(
            reason=f"Multi-specialty rule: Current claim approved as highest value visit on {current_claim.get('admission_date', 'this date')}",
            metadata={
                'multi_specialty_rule_applied': True,
                'is_highest_value': True,
                'other_visits_count': other_visit_count,
                'other_specialties': other_specialties,
                'estimated_value': highest_visit['estimated_value'],
                'payment_status': 'FULL_PAYMENT'
            },
            data_used=data_used,
            warnings=[
                f"Other visits on same day will be denied due to multi-specialty rule",
                f"Only highest value visit (estimated: {highest_visit['estimated_value']}) will be paid"
            ]
        )
    
    def _reject_lower_value_visit(self, current_claim: Dict[str, Any],
                                other_visits: List[Dict[str, Any]],
                                highest_visit: Dict[str, Any],
                                data_used: Dict[str, Any]) -> RuleResult:
        
        current_value = self._estimate_visit_value(current_claim, 
                                                 current_claim.get('g_drg_diagnosis') or 
                                                 current_claim.get('g_drg_procedure'))
        
        return self.reject(
            reason=f"Multi-specialty rule: Current claim rejected - not the highest value visit on {current_claim.get('admission_date', 'this date')}",
            severity=RuleSeverity.MEDIUM,
            validation_errors=[
                f"Multiple specialties visited on same day",
                f"Current visit estimated value: {current_value}",
                f"Highest value visit estimated value: {highest_visit['estimated_value']}",
                f"Only highest value visit will be paid per multi-specialty rule"
            ],
            data_used=data_used,
            recommendations=[
                "Review if visits can be scheduled on different days",
                "Verify if all specialties were medically necessary",
                "Consider consolidating care where clinically appropriate"
            ],
            metadata={
                'multi_specialty_rule_applied': True,
                'is_highest_value': False,
                'current_estimated_value': current_value,
                'highest_estimated_value': highest_visit['estimated_value'],
                'highest_value_encounter': highest_visit['encounter_id'],
                'payment_status': 'DENIED_LOWER_VALUE'
            }
        )
    
    def get_same_day_visit_summary(self, nhis_number: str, visit_date: datetime) -> Dict[str, Any]:
        try:
            same_day_visits = self.episode_queries.get_same_day_specialty_visits(
                nhis_number=nhis_number,
                visit_date=visit_date
            )
            
            specialty_count = self.episode_queries.count_same_day_specialties(
                nhis_number=nhis_number,
                visit_date=visit_date
            )
            
            return {
                'nhis_number': nhis_number,
                'visit_date': visit_date.isoformat() if visit_date else None,
                'total_visits': len(same_day_visits),
                'unique_specialties': specialty_count,
                'has_multi_specialty_conflict': specialty_count > 1,
                'visits': same_day_visits
            }
            
        except Exception as e:
            return {
                'error': f"Failed to retrieve same-day visit summary: {str(e)}",
                'nhis_number': nhis_number,
                'visit_date': visit_date.isoformat() if visit_date else None
            }