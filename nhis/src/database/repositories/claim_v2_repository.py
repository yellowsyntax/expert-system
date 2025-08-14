from typing import List, Optional, Dict, Any
from sqlalchemy.orm import Session
from sqlalchemy import and_, or_, func, desc, asc
from datetime import datetime, timedelta
import uuid

from .base_repository import BaseRepository
from ..models.claim_v2 import ClaimV2

class ClaimV2Repository(BaseRepository[ClaimV2]):
    def __init__(self, db_session: Session):
        super().__init__(db_session, ClaimV2)
    
    def get_by_nhis_number(self, nhis_number: str) -> List[ClaimV2]:
        return self.get_many_by_field('nhis_number', nhis_number)
    
    def get_by_provider_id(self, provider_id: uuid.UUID, limit: Optional[int] = None) -> List[ClaimV2]:
        return self.get_many_by_field('provider_id', provider_id, limit=limit)
    
    def get_by_batch_id(self, batch_id: uuid.UUID) -> List[ClaimV2]:
        return self.get_many_by_field('batch_id', batch_id)
    
    def get_by_encounter_id(self, encounter_id: str) -> Optional[ClaimV2]:
        return self.get_by_field('encounter_id', encounter_id)
    
    def get_pending_claims(self, limit: Optional[int] = None) -> List[ClaimV2]:
        return self.get_many_by_fields(
            {'batch_id': None}, 
            limit=limit, 
            order_by='created_at', 
            desc_order=True
        )
    
    def get_claims_by_date_range(self, start_date: datetime, end_date: datetime, limit: Optional[int] = None) -> List[ClaimV2]:
        return self.get_date_range('created_at', start_date, end_date, limit)
    
    def get_claims_by_admission_date_range(self, start_date: datetime, end_date: datetime) -> List[ClaimV2]:
        return self.get_date_range('admission_date', start_date, end_date)
    
    def get_claims_by_discharge_date_range(self, start_date: datetime, end_date: datetime) -> List[ClaimV2]:
        return self.get_date_range('discharge_date', start_date, end_date)
    
    def get_patient_claims_history(self, nhis_number: str, days_back: int = 365) -> List[ClaimV2]:
        cutoff_date = datetime.utcnow() - timedelta(days=days_back)
        
        return self.db_session.query(ClaimV2).filter(
            and_(
                ClaimV2.nhis_number == nhis_number,
                ClaimV2.created_at >= cutoff_date
            )
        ).order_by(desc(ClaimV2.created_at)).all()
    
    def get_recent_visits_by_nhis(self, nhis_number: str, days: int = 14) -> List[ClaimV2]:
        cutoff_date = datetime.utcnow() - timedelta(days=days)
        
        return self.db_session.query(ClaimV2).filter(
            and_(
                ClaimV2.nhis_number == nhis_number,
                ClaimV2.admission_date >= cutoff_date
            )
        ).order_by(desc(ClaimV2.admission_date)).all()
    
    def get_opd_visits_by_nhis(self, nhis_number: str, months_back: int = 12) -> List[ClaimV2]:
        cutoff_date = datetime.utcnow() - timedelta(days=months_back * 30)
        
        return self.db_session.query(ClaimV2).filter(
            and_(
                ClaimV2.nhis_number == nhis_number,
                ClaimV2.service_type_1 == 'OPD',
                ClaimV2.admission_date >= cutoff_date
            )
        ).order_by(desc(ClaimV2.admission_date)).all()
    
    def get_ipd_visits_by_nhis(self, nhis_number: str, months_back: int = 12) -> List[ClaimV2]:
        cutoff_date = datetime.utcnow() - timedelta(days=months_back * 30)
        
        return self.db_session.query(ClaimV2).filter(
            and_(
                ClaimV2.nhis_number == nhis_number,
                ClaimV2.service_type_1 == 'IPD',
                ClaimV2.admission_date >= cutoff_date
            )
        ).order_by(desc(ClaimV2.admission_date)).all()
    
    def get_emergency_visits_by_nhis(self, nhis_number: str, months_back: int = 6) -> List[ClaimV2]:
        cutoff_date = datetime.utcnow() - timedelta(days=months_back * 30)
        
        return self.db_session.query(ClaimV2).filter(
            and_(
                ClaimV2.nhis_number == nhis_number,
                or_(
                    ClaimV2.service_type_1 == 'A&E',
                    ClaimV2.service_type_1 == 'EMERGENCY'
                ),
                ClaimV2.admission_date >= cutoff_date
            )
        ).order_by(desc(ClaimV2.admission_date)).all()
    
    def get_claims_by_diagnosis(self, icd10_code: str, limit: Optional[int] = None) -> List[ClaimV2]:
        return self.get_many_by_field('icd10_diagnosis', icd10_code, limit=limit)
    
    def get_claims_by_procedure(self, procedure_code: str, limit: Optional[int] = None) -> List[ClaimV2]:
        return self.get_many_by_field('icd10_procedure', procedure_code, limit=limit)
    
    def get_claims_by_gdrg(self, gdrg_code: str, limit: Optional[int] = None) -> List[ClaimV2]:
        return self.db_session.query(ClaimV2).filter(
            or_(
                ClaimV2.g_drg_diagnosis == gdrg_code,
                ClaimV2.g_drg_procedure == gdrg_code
            )
        ).limit(limit).all() if limit else self.db_session.query(ClaimV2).filter(
            or_(
                ClaimV2.g_drg_diagnosis == gdrg_code,
                ClaimV2.g_drg_procedure == gdrg_code
            )
        ).all()
    
    def get_claims_with_medicines(self, limit: Optional[int] = None) -> List[ClaimV2]:
        query = self.db_session.query(ClaimV2).filter(
            ClaimV2.medicine_code.isnot(None)
        )
        
        if limit:
            query = query.limit(limit)
            
        return query.all()
    
    def get_claims_with_investigations(self, limit: Optional[int] = None) -> List[ClaimV2]:
        query = self.db_session.query(ClaimV2).filter(
            ClaimV2.g_drg_inve.isnot(None)
        )
        
        if limit:
            query = query.limit(limit)
            
        return query.all()
    
    def get_claims_by_specialty(self, specialty: str, limit: Optional[int] = None) -> List[ClaimV2]:
        return self.get_many_by_field('specialties_attended', specialty, limit=limit)
    
    def get_same_day_visits(self, nhis_number: str, visit_date: datetime) -> List[ClaimV2]:
        start_of_day = visit_date.replace(hour=0, minute=0, second=0, microsecond=0)
        end_of_day = start_of_day + timedelta(days=1)
        
        return self.db_session.query(ClaimV2).filter(
            and_(
                ClaimV2.nhis_number == nhis_number,
                ClaimV2.admission_date >= start_of_day,
                ClaimV2.admission_date < end_of_day
            )
        ).all()
    
    def get_readmission_candidates(self, nhis_number: str, discharge_date: datetime, days_threshold: int = 30) -> List[ClaimV2]:
        start_check = discharge_date
        end_check = discharge_date + timedelta(days=days_threshold)
        
        return self.db_session.query(ClaimV2).filter(
            and_(
                ClaimV2.nhis_number == nhis_number,
                ClaimV2.service_type_1 == 'IPD',
                ClaimV2.admission_date >= start_check,
                ClaimV2.admission_date <= end_check
            )
        ).order_by(asc(ClaimV2.admission_date)).all()
    
    def get_claims_without_discharge_date(self, limit: Optional[int] = None) -> List[ClaimV2]:
        query = self.db_session.query(ClaimV2).filter(
            and_(
                ClaimV2.service_type_1 == 'IPD',
                ClaimV2.discharge_date.is_(None)
            )
        )
        
        if limit:
            query = query.limit(limit)
            
        return query.all()
    
    def get_claims_by_age_group(self, age_threshold: int = 12, is_child: bool = True, limit: Optional[int] = None) -> List[ClaimV2]:
        cutoff_date = datetime.utcnow() - timedelta(days=age_threshold * 365)
        
        if is_child:
            query = self.db_session.query(ClaimV2).filter(
                ClaimV2.date_of_birth >= cutoff_date
            )
        else:
            query = self.db_session.query(ClaimV2).filter(
                ClaimV2.date_of_birth < cutoff_date
            )
        
        if limit:
            query = query.limit(limit)
            
        return query.all()
    
    def count_visits_by_episode_type(self, nhis_number: str, episode_type: str, start_date: datetime, end_date: datetime) -> int:
        episode_filters = {
            'ACUTE': lambda: timedelta(days=14),
            'CHRONIC': lambda: timedelta(days=365),
            'ANTENATAL': lambda: timedelta(days=280),
            'POSTNATAL': lambda: timedelta(days=42)
        }
        
        if episode_type not in episode_filters:
            raise ValueError(f"Invalid episode type: {episode_type}")
        
        count = self.db_session.query(func.count(ClaimV2.id)).filter(
            and_(
                ClaimV2.nhis_number == nhis_number,
                ClaimV2.admission_date >= start_date,
                ClaimV2.admission_date <= end_date
            )
        ).scalar()
        
        return count or 0
    
    def get_provider_claims_summary(self, provider_id: uuid.UUID, start_date: datetime, end_date: datetime) -> Dict[str, Any]:
        claims = self.db_session.query(ClaimV2).filter(
            and_(
                ClaimV2.provider_id == provider_id,
                ClaimV2.created_at >= start_date,
                ClaimV2.created_at <= end_date
            )
        ).all()
        
        total_claims = len(claims)
        opd_claims = len([c for c in claims if c.service_type_1 == 'OPD'])
        ipd_claims = len([c for c in claims if c.service_type_1 == 'IPD'])
        emergency_claims = len([c for c in claims if c.service_type_1 in ['A&E', 'EMERGENCY']])
        
        return {
            'total_claims': total_claims,
            'opd_claims': opd_claims,
            'ipd_claims': ipd_claims,
            'emergency_claims': emergency_claims,
            'claims_with_medicines': len([c for c in claims if c.medicine_code]),
            'claims_with_investigations': len([c for c in claims if c.g_drg_inve]),
            'unique_patients': len(set([c.nhis_number for c in claims if c.nhis_number]))
        }
    
    def bulk_update_batch_id(self, claim_ids: List[uuid.UUID], batch_id: uuid.UUID) -> int:
        return self.db_session.query(ClaimV2).filter(
            ClaimV2.id.in_(claim_ids)
        ).update(
            {'batch_id': batch_id, 'updated_at': datetime.utcnow()},
            synchronize_session=False
        )