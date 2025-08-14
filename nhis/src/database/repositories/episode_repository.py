from typing import List, Optional, Dict, Any, Tuple
from sqlalchemy.orm import Session
from sqlalchemy import and_, or_, func, desc, asc, extract
from datetime import datetime, timedelta
import uuid

from .base_repository import BaseRepository
from ..models.claim_v2 import ClaimV2

class EpisodeRepository(BaseRepository[ClaimV2]):
    def __init__(self, db_session: Session):
        super().__init__(db_session, ClaimV2)
    
    def get_patient_episode_history(self, nhis_number: str, months_back: int = 12) -> List[ClaimV2]:
        cutoff_date = datetime.utcnow() - timedelta(days=months_back * 30)
        
        return self.db_session.query(ClaimV2).filter(
            and_(
                ClaimV2.nhis_number == nhis_number,
                ClaimV2.admission_date >= cutoff_date
            )
        ).order_by(desc(ClaimV2.admission_date)).all()
    
    def get_acute_episode_visits(self, nhis_number: str, days_back: int = 14) -> List[ClaimV2]:
        cutoff_date = datetime.utcnow() - timedelta(days=days_back)
        
        return self.db_session.query(ClaimV2).filter(
            and_(
                ClaimV2.nhis_number == nhis_number,
                ClaimV2.service_type_1 == 'OPD',
                ClaimV2.admission_date >= cutoff_date
            )
        ).order_by(desc(ClaimV2.admission_date)).all()
    
    def count_acute_visits(self, nhis_number: str, days_back: int = 14) -> int:
        cutoff_date = datetime.utcnow() - timedelta(days=days_back)
        
        count = self.db_session.query(func.count(ClaimV2.id)).filter(
            and_(
                ClaimV2.nhis_number == nhis_number,
                ClaimV2.service_type_1 == 'OPD',
                ClaimV2.admission_date >= cutoff_date
            )
        ).scalar()
        
        return count or 0
    
    def get_chronic_episode_visits(self, nhis_number: str, months_back: int = 12) -> List[ClaimV2]:
        cutoff_date = datetime.utcnow() - timedelta(days=months_back * 30)
        
        return self.db_session.query(ClaimV2).filter(
            and_(
                ClaimV2.nhis_number == nhis_number,
                ClaimV2.service_type_1 == 'OPD',
                ClaimV2.admission_date >= cutoff_date
            )
        ).order_by(desc(ClaimV2.admission_date)).all()
    
    def count_chronic_visits(self, nhis_number: str, months_back: int = 12) -> int:
        cutoff_date = datetime.utcnow() - timedelta(days=months_back * 30)
        
        count = self.db_session.query(func.count(ClaimV2.id)).filter(
            and_(
                ClaimV2.nhis_number == nhis_number,
                ClaimV2.service_type_1 == 'OPD',
                ClaimV2.admission_date >= cutoff_date
            )
        ).scalar()
        
        return count or 0
    
    def get_antenatal_visits(self, nhis_number: str, months_back: int = 10) -> List[ClaimV2]:
        cutoff_date = datetime.utcnow() - timedelta(days=months_back * 30)
        
        anc_diagnosis_codes = ['Z34', 'Z35', 'Z36', 'O00', 'O09', 'O10', 'O11', 'O12', 'O13', 'O14', 'O15', 'O16']
        
        return self.db_session.query(ClaimV2).filter(
            and_(
                ClaimV2.nhis_number == nhis_number,
                ClaimV2.service_type_1 == 'OPD',
                ClaimV2.admission_date >= cutoff_date,
                or_(*[ClaimV2.icd10_diagnosis.like(f'{code}%') for code in anc_diagnosis_codes])
            )
        ).order_by(desc(ClaimV2.admission_date)).all()
    
    def count_antenatal_visits(self, nhis_number: str, months_back: int = 10) -> int:
        cutoff_date = datetime.utcnow() - timedelta(days=months_back * 30)
        
        anc_diagnosis_codes = ['Z34', 'Z35', 'Z36', 'O00', 'O09', 'O10', 'O11', 'O12', 'O13', 'O14', 'O15', 'O16']
        
        count = self.db_session.query(func.count(ClaimV2.id)).filter(
            and_(
                ClaimV2.nhis_number == nhis_number,
                ClaimV2.service_type_1 == 'OPD',
                ClaimV2.admission_date >= cutoff_date,
                or_(*[ClaimV2.icd10_diagnosis.like(f'{code}%') for code in anc_diagnosis_codes])
            )
        ).scalar()
        
        return count or 0
    
    def get_postnatal_visits(self, nhis_number: str, weeks_back: int = 6) -> List[ClaimV2]:
        cutoff_date = datetime.utcnow() - timedelta(weeks=weeks_back)
        
        pnc_diagnosis_codes = ['Z39', 'O85', 'O86', 'O87', 'O90', 'O91', 'O92']
        
        return self.db_session.query(ClaimV2).filter(
            and_(
                ClaimV2.nhis_number == nhis_number,
                ClaimV2.service_type_1 == 'OPD',
                ClaimV2.admission_date >= cutoff_date,
                or_(*[ClaimV2.icd10_diagnosis.like(f'{code}%') for code in pnc_diagnosis_codes])
            )
        ).order_by(desc(ClaimV2.admission_date)).all()
    
    def count_postnatal_visits(self, nhis_number: str, weeks_back: int = 6) -> int:
        cutoff_date = datetime.utcnow() - timedelta(weeks=weeks_back)
        
        pnc_diagnosis_codes = ['Z39', 'O85', 'O86', 'O87', 'O90', 'O91', 'O92']
        
        count = self.db_session.query(func.count(ClaimV2.id)).filter(
            and_(
                ClaimV2.nhis_number == nhis_number,
                ClaimV2.service_type_1 == 'OPD',
                ClaimV2.admission_date >= cutoff_date,
                or_(*[ClaimV2.icd10_diagnosis.like(f'{code}%') for code in pnc_diagnosis_codes])
            )
        ).scalar()
        
        return count or 0
    
    def validate_episode_limits(self, nhis_number: str, service_type: str, admission_date: datetime) -> Dict[str, Any]:
        current_visit_count = 0
        max_allowed = 0
        episode_type = "UNKNOWN"
        period_description = ""
        
        if service_type == 'OPD':
            acute_count = self.count_acute_visits(nhis_number, 14)
            chronic_count = self.count_chronic_visits(nhis_number, 12 * 30)
            anc_count = self.count_antenatal_visits(nhis_number, 10)
            pnc_count = self.count_postnatal_visits(nhis_number, 6)
            
            if anc_count > 0:
                episode_type = "ANTENATAL"
                current_visit_count = anc_count
                max_allowed = 6
                period_description = "10 months"
            elif pnc_count > 0:
                episode_type = "POSTNATAL"
                current_visit_count = pnc_count
                max_allowed = 3
                period_description = "6 weeks"
            elif acute_count > 0:
                episode_type = "ACUTE"
                current_visit_count = acute_count
                max_allowed = 3
                period_description = "14 days"
            else:
                episode_type = "CHRONIC"
                current_visit_count = chronic_count
                max_allowed = 6
                period_description = "12 months"
        
        is_within_limit = current_visit_count < max_allowed
        visits_remaining = max(0, max_allowed - current_visit_count)
        
        return {
            'episode_type': episode_type,
            'current_visit_count': current_visit_count,
            'max_allowed': max_allowed,
            'is_within_limit': is_within_limit,
            'visits_remaining': visits_remaining,
            'period_description': period_description,
            'will_exceed_if_approved': (current_visit_count + 1) > max_allowed
        }
    
    def get_same_day_multi_specialty_visits(self, nhis_number: str, visit_date: datetime) -> List[ClaimV2]:
        start_of_day = visit_date.replace(hour=0, minute=0, second=0, microsecond=0)
        end_of_day = start_of_day + timedelta(days=1)
        
        return self.db_session.query(ClaimV2).filter(
            and_(
                ClaimV2.nhis_number == nhis_number,
                ClaimV2.service_type_1 == 'OPD',
                ClaimV2.admission_date >= start_of_day,
                ClaimV2.admission_date < end_of_day,
                ClaimV2.specialties_attended.isnot(None)
            )
        ).order_by(asc(ClaimV2.admission_date)).all()
    
    def count_same_day_specialties(self, nhis_number: str, visit_date: datetime) -> int:
        visits = self.get_same_day_multi_specialty_visits(nhis_number, visit_date)
        
        unique_specialties = set()
        for visit in visits:
            if visit.specialties_attended:
                specialties = visit.specialties_attended.split(',')
                for specialty in specialties:
                    unique_specialties.add(specialty.strip())
        
        return len(unique_specialties)
    
    def get_physiotherapy_sessions(self, nhis_number: str, months_back: int = 12) -> List[ClaimV2]:
        cutoff_date = datetime.utcnow() - timedelta(days=months_back * 30)
        
        physio_procedure_codes = ['ZOOM04', 'PHYS01', 'PHYS02', 'PHYS03', 'PHYS04', 'PHYS05']
        
        return self.db_session.query(ClaimV2).filter(
            and_(
                ClaimV2.nhis_number == nhis_number,
                ClaimV2.admission_date >= cutoff_date,
                or_(*[ClaimV2.icd10_procedure.like(f'{code}%') for code in physio_procedure_codes])
            )
        ).order_by(desc(ClaimV2.admission_date)).all()
    
    def count_physiotherapy_sessions(self, nhis_number: str, months_back: int = 12) -> int:
        cutoff_date = datetime.utcnow() - timedelta(days=months_back * 30)
        
        physio_procedure_codes = ['ZOOM04', 'PHYS01', 'PHYS02', 'PHYS03', 'PHYS04', 'PHYS05']
        
        count = self.db_session.query(func.count(ClaimV2.id)).filter(
            and_(
                ClaimV2.nhis_number == nhis_number,
                ClaimV2.admission_date >= cutoff_date,
                or_(*[ClaimV2.icd10_procedure.like(f'{code}%') for code in physio_procedure_codes])
            )
        ).scalar()
        
        return count or 0
    
    def validate_physiotherapy_limits(self, nhis_number: str, condition_icd10: str) -> Dict[str, Any]:
        current_sessions = self.count_physiotherapy_sessions(nhis_number, 12)
        
        physio_eligible_conditions = {
            'M00': 12, 'M01': 12, 'M02': 12, 'M05': 24, 'M06': 24,
            'M15': 12, 'M16': 12, 'M17': 12, 'M19': 12,
            'M79': 8, 'M25': 8,
            'G80': 24, 'G81': 24, 'G82': 24, 'G83': 24,
            'S72': 16, 'S82': 16, 'S92': 12
        }
        
        max_sessions = 0
        is_eligible = False
        
        for condition_prefix, sessions in physio_eligible_conditions.items():
            if condition_icd10.startswith(condition_prefix):
                max_sessions = sessions
                is_eligible = True
                break
        
        if not is_eligible:
            return {
                'is_eligible': False,
                'reason': f'Condition {condition_icd10} not eligible for physiotherapy',
                'current_sessions': current_sessions,
                'max_sessions': 0,
                'sessions_remaining': 0
            }
        
        is_within_limit = current_sessions < max_sessions
        sessions_remaining = max(0, max_sessions - current_sessions)
        
        return {
            'is_eligible': True,
            'is_within_limit': is_within_limit,
            'current_sessions': current_sessions,
            'max_sessions': max_sessions,
            'sessions_remaining': sessions_remaining,
            'will_exceed_if_approved': (current_sessions + 1) > max_sessions
        }
    
    def get_readmission_history(self, nhis_number: str, discharge_date: datetime, days_window: int = 30) -> List[ClaimV2]:
        window_start = discharge_date
        window_end = discharge_date + timedelta(days=days_window)
        
        return self.db_session.query(ClaimV2).filter(
            and_(
                ClaimV2.nhis_number == nhis_number,
                ClaimV2.service_type_1 == 'IPD',
                ClaimV2.admission_date >= window_start,
                ClaimV2.admission_date <= window_end
            )
        ).order_by(asc(ClaimV2.admission_date)).all()
    
    def validate_emergency_readmission_rule(self, nhis_number: str, current_admission: datetime, previous_discharge: datetime) -> Dict[str, Any]:
        days_between = (current_admission - previous_discharge).days
        
        if days_between <= 30:
            recent_admissions = self.get_readmission_history(nhis_number, previous_discharge, 30)
            
            return {
                'is_violation': True,
                'days_between_admissions': days_between,
                'rule': 'Emergency readmission within 30 days',
                'previous_discharge': previous_discharge,
                'current_admission': current_admission,
                'recent_admissions_count': len(recent_admissions),
                'requires_justification': True
            }
        
        return {
            'is_violation': False,
            'days_between_admissions': days_between,
            'rule': 'Emergency readmission rule complied',
            'requires_justification': False
        }
    
    def get_episode_summary_by_patient(self, nhis_number: str, months_back: int = 12) -> Dict[str, Any]:
        cutoff_date = datetime.utcnow() - timedelta(days=months_back * 30)
        
        all_visits = self.db_session.query(ClaimV2).filter(
            and_(
                ClaimV2.nhis_number == nhis_number,
                ClaimV2.admission_date >= cutoff_date
            )
        ).all()
        
        opd_visits = [v for v in all_visits if v.service_type_1 == 'OPD']
        ipd_visits = [v for v in all_visits if v.service_type_1 == 'IPD']
        emergency_visits = [v for v in all_visits if v.service_type_1 in ['A&E', 'EMERGENCY']]
        
        acute_visits = self.count_acute_visits(nhis_number, 14)
        chronic_visits = self.count_chronic_visits(nhis_number, months_back)
        anc_visits = self.count_antenatal_visits(nhis_number, 10)
        pnc_visits = self.count_postnatal_visits(nhis_number, 6)
        physio_sessions = self.count_physiotherapy_sessions(nhis_number, months_back)
        
        return {
            'nhis_number': nhis_number,
            'total_visits': len(all_visits),
            'opd_visits': len(opd_visits),
            'ipd_visits': len(ipd_visits),
            'emergency_visits': len(emergency_visits),
            'acute_episode_visits': acute_visits,
            'chronic_episode_visits': chronic_visits,
            'antenatal_visits': anc_visits,
            'postnatal_visits': pnc_visits,
            'physiotherapy_sessions': physio_sessions,
            'most_recent_visit': max([v.admission_date for v in all_visits]) if all_visits else None,
            'most_common_diagnosis': self._get_most_common_diagnosis(all_visits),
            'most_visited_facilities': self._get_most_visited_facilities(all_visits)
        }
    
    def _get_most_common_diagnosis(self, visits: List[ClaimV2]) -> Optional[str]:
        if not visits:
            return None
        
        diagnosis_counts = {}
        for visit in visits:
            if visit.icd10_diagnosis:
                diagnosis_counts[visit.icd10_diagnosis] = diagnosis_counts.get(visit.icd10_diagnosis, 0) + 1
        
        if diagnosis_counts:
            return max(diagnosis_counts, key=diagnosis_counts.get)
        return None
    
    def _get_most_visited_facilities(self, visits: List[ClaimV2]) -> List[Tuple[str, int]]:
        if not visits:
            return []
        
        facility_counts = {}
        for visit in visits:
            if visit.provider_name:
                facility_counts[visit.provider_name] = facility_counts.get(visit.provider_name, 0) + 1
        
        sorted_facilities = sorted(facility_counts.items(), key=lambda x: x[1], reverse=True)
        return sorted_facilities[:5]
    
    def get_patients_exceeding_limits(self, episode_type: str, limit: Optional[int] = None) -> List[Dict[str, Any]]:
        episode_configs = {
            'ACUTE': {'days_back': 14, 'max_visits': 3},
            'CHRONIC': {'days_back': 365, 'max_visits': 6},
            'ANTENATAL': {'days_back': 280, 'max_visits': 6},
            'POSTNATAL': {'days_back': 42, 'max_visits': 3}
        }
        
        if episode_type not in episode_configs:
            return []
        
        config = episode_configs[episode_type]
        cutoff_date = datetime.utcnow() - timedelta(days=config['days_back'])
        
        patient_visit_counts = self.db_session.query(
            ClaimV2.nhis_number,
            func.count(ClaimV2.id).label('visit_count')
        ).filter(
            and_(
                ClaimV2.service_type_1 == 'OPD',
                ClaimV2.admission_date >= cutoff_date
            )
        ).group_by(ClaimV2.nhis_number).having(
            func.count(ClaimV2.id) > config['max_visits']
        ).all()
        
        if limit:
            patient_visit_counts = patient_visit_counts[:limit]
        
        exceeding_patients = []
        for nhis_number, visit_count in patient_visit_counts:
            exceeding_patients.append({
                'nhis_number': nhis_number,
                'visit_count': visit_count,
                'max_allowed': config['max_visits'],
                'excess_visits': visit_count - config['max_visits'],
                'episode_type': episode_type
            })
        
        return exceeding_patients