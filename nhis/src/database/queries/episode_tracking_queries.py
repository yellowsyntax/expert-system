from typing import List, Dict, Any, Optional
from sqlalchemy.orm import Session
from sqlalchemy import text, and_, or_, func
from datetime import datetime, timedelta


class EpisodeTrackingQueries:
    def __init__(self, db_session: Session):
        self.db_session = db_session
    
    def get_acute_episode_count(self, nhis_number: str, days_back: int = 14) -> int:
        query = text("""
            SELECT COUNT(*)
            FROM claims_v2 
            WHERE nhis_number = :nhis_number 
            AND service_type_1 = 'OPD'
            AND admission_date >= :cutoff_date
        """)
        
        cutoff_date = datetime.utcnow() - timedelta(days=days_back)
        result = self.db_session.execute(query, {
            'nhis_number': nhis_number,
            'cutoff_date': cutoff_date
        })
        
        return result.scalar() or 0
    
    def get_chronic_episode_count(self, nhis_number: str, months_back: int = 12) -> int:
        query = text("""
            SELECT COUNT(*)
            FROM claims_v2 
            WHERE nhis_number = :nhis_number 
            AND service_type_1 = 'OPD'
            AND admission_date >= :cutoff_date
        """)
        
        cutoff_date = datetime.utcnow() - timedelta(days=months_back * 30)
        result = self.db_session.execute(query, {
            'nhis_number': nhis_number,
            'cutoff_date': cutoff_date
        })
        
        return result.scalar() or 0
    
    def get_antenatal_visit_count(self, nhis_number: str, months_back: int = 10) -> int:
        query = text("""
            SELECT COUNT(*)
            FROM claims_v2 
            WHERE nhis_number = :nhis_number 
            AND service_type_1 = 'OPD'
            AND admission_date >= :cutoff_date
            AND (icd10_diagnosis LIKE 'Z34%' OR icd10_diagnosis LIKE 'Z35%' 
                 OR icd10_diagnosis LIKE 'Z36%' OR icd10_diagnosis LIKE 'O0%'
                 OR icd10_diagnosis LIKE 'O1%')
        """)
        
        cutoff_date = datetime.utcnow() - timedelta(days=months_back * 30)
        result = self.db_session.execute(query, {
            'nhis_number': nhis_number,
            'cutoff_date': cutoff_date
        })
        
        return result.scalar() or 0
    
    def get_postnatal_visit_count(self, nhis_number: str, weeks_back: int = 6) -> int:
        query = text("""
            SELECT COUNT(*)
            FROM claims_v2 
            WHERE nhis_number = :nhis_number 
            AND service_type_1 = 'OPD'
            AND admission_date >= :cutoff_date
            AND (icd10_diagnosis LIKE 'Z39%' OR icd10_diagnosis LIKE 'O85%'
                 OR icd10_diagnosis LIKE 'O86%' OR icd10_diagnosis LIKE 'O87%'
                 OR icd10_diagnosis LIKE 'O90%' OR icd10_diagnosis LIKE 'O91%'
                 OR icd10_diagnosis LIKE 'O92%')
        """)
        
        cutoff_date = datetime.utcnow() - timedelta(weeks=weeks_back)
        result = self.db_session.execute(query, {
            'nhis_number': nhis_number,
            'cutoff_date': cutoff_date
        })
        
        return result.scalar() or 0
    
    def get_physiotherapy_session_count(self, nhis_number: str, months_back: int = 12) -> int:
        query = text("""
            SELECT COUNT(*)
            FROM claims_v2 
            WHERE nhis_number = :nhis_number 
            AND admission_date >= :cutoff_date
            AND (icd10_procedure LIKE 'ZOOM04%' OR icd10_procedure LIKE 'PHYS%')
        """)
        
        cutoff_date = datetime.utcnow() - timedelta(days=months_back * 30)
        result = self.db_session.execute(query, {
            'nhis_number': nhis_number,
            'cutoff_date': cutoff_date
        })
        
        return result.scalar() or 0
    
    def get_same_day_specialty_visits(self, nhis_number: str, visit_date: datetime) -> List[Dict[str, Any]]:
        query = text("""
            SELECT id, encounter_id, specialties_attended, admission_date, procedure_name
            FROM claims_v2 
            WHERE nhis_number = :nhis_number 
            AND service_type_1 = 'OPD'
            AND DATE(admission_date) = DATE(:visit_date)
            AND specialties_attended IS NOT NULL
            ORDER BY admission_date
        """)
        
        result = self.db_session.execute(query, {
            'nhis_number': nhis_number,
            'visit_date': visit_date
        })
        
        visits = []
        for row in result:
            visits.append({
                'id': row.id,
                'encounter_id': row.encounter_id,
                'specialties_attended': row.specialties_attended,
                'admission_date': row.admission_date,
                'procedure_name': row.procedure_name
            })
        
        return visits
    
    def get_patient_episode_summary(self, nhis_number: str, months_back: int = 12) -> Dict[str, Any]:
        query = text("""
            WITH episode_counts AS (
                SELECT 
                    COUNT(*) FILTER (WHERE service_type_1 = 'OPD' AND admission_date >= :acute_cutoff) as acute_visits,
                    COUNT(*) FILTER (WHERE service_type_1 = 'OPD' AND admission_date >= :chronic_cutoff) as chronic_visits,
                    COUNT(*) FILTER (WHERE service_type_1 = 'IPD' AND admission_date >= :chronic_cutoff) as ipd_visits,
                    COUNT(*) FILTER (WHERE service_type_1 IN ('A&E', 'EMERGENCY') AND admission_date >= :chronic_cutoff) as emergency_visits,
                    COUNT(*) FILTER (WHERE (icd10_diagnosis LIKE 'Z34%' OR icd10_diagnosis LIKE 'Z35%' OR icd10_diagnosis LIKE 'O0%' OR icd10_diagnosis LIKE 'O1%') AND admission_date >= :anc_cutoff) as anc_visits,
                    COUNT(*) FILTER (WHERE (icd10_diagnosis LIKE 'Z39%' OR icd10_diagnosis LIKE 'O85%' OR icd10_diagnosis LIKE 'O90%') AND admission_date >= :pnc_cutoff) as pnc_visits,
                    COUNT(*) FILTER (WHERE (icd10_procedure LIKE 'ZOOM04%' OR icd10_procedure LIKE 'PHYS%') AND admission_date >= :physio_cutoff) as physio_sessions
                FROM claims_v2 
                WHERE nhis_number = :nhis_number
            ),
            recent_claims AS (
                SELECT 
                    icd10_diagnosis,
                    icd10_procedure,
                    provider_name,
                    admission_date,
                    service_type_1
                FROM claims_v2 
                WHERE nhis_number = :nhis_number 
                AND admission_date >= :chronic_cutoff
                ORDER BY admission_date DESC
                LIMIT 10
            )
            SELECT 
                ec.*,
                json_agg(
                    json_build_object(
                        'diagnosis', rc.icd10_diagnosis,
                        'procedure', rc.icd10_procedure,
                        'provider', rc.provider_name,
                        'date', rc.admission_date,
                        'service_type', rc.service_type_1
                    ) ORDER BY rc.admission_date DESC
                ) as recent_visits
            FROM episode_counts ec
            CROSS JOIN recent_claims rc
            GROUP BY ec.acute_visits, ec.chronic_visits, ec.ipd_visits, ec.emergency_visits, ec.anc_visits, ec.pnc_visits, ec.physio_sessions
        """)
        
        now = datetime.utcnow()
        acute_cutoff = now - timedelta(days=14)
        chronic_cutoff = now - timedelta(days=months_back * 30)
        anc_cutoff = now - timedelta(days=10 * 30)
        pnc_cutoff = now - timedelta(weeks=6)
        physio_cutoff = now - timedelta(days=months_back * 30)
        
        result = self.db_session.execute(query, {
            'nhis_number': nhis_number,
            'acute_cutoff': acute_cutoff,
            'chronic_cutoff': chronic_cutoff,
            'anc_cutoff': anc_cutoff,
            'pnc_cutoff': pnc_cutoff,
            'physio_cutoff': physio_cutoff
        })
        
        row = result.fetchone()
        if row:
            return {
                'nhis_number': nhis_number,
                'acute_visits': row.acute_visits or 0,
                'chronic_visits': row.chronic_visits or 0,
                'ipd_visits': row.ipd_visits or 0,
                'emergency_visits': row.emergency_visits or 0,
                'anc_visits': row.anc_visits or 0,
                'pnc_visits': row.pnc_visits or 0,
                'physio_sessions': row.physio_sessions or 0,
                'recent_visits': row.recent_visits or []
            }
        
        return {
            'nhis_number': nhis_number,
            'acute_visits': 0,
            'chronic_visits': 0,
            'ipd_visits': 0,
            'emergency_visits': 0,
            'anc_visits': 0,
            'pnc_visits': 0,
            'physio_sessions': 0,
            'recent_visits': []
        }
    
    def get_patients_exceeding_visit_limits(self, limit_type: str, max_visits: int, period_days: int, limit: Optional[int] = None) -> List[Dict[str, Any]]:
        base_query = """
            SELECT 
                nhis_number,
                COUNT(*) as visit_count,
                MAX(admission_date) as last_visit,
                MIN(admission_date) as first_visit_in_period,
                string_agg(DISTINCT provider_name, ', ') as facilities_visited
            FROM claims_v2 
            WHERE service_type_1 = 'OPD'
            AND admission_date >= :cutoff_date
        """
        
        if limit_type == 'ANTENATAL':
            base_query += """
                AND (icd10_diagnosis LIKE 'Z34%' OR icd10_diagnosis LIKE 'Z35%' 
                     OR icd10_diagnosis LIKE 'O0%' OR icd10_diagnosis LIKE 'O1%')
            """
        elif limit_type == 'POSTNATAL':
            base_query += """
                AND (icd10_diagnosis LIKE 'Z39%' OR icd10_diagnosis LIKE 'O85%'
                     OR icd10_diagnosis LIKE 'O90%')
            """
        
        base_query += """
            GROUP BY nhis_number
            HAVING COUNT(*) > :max_visits
            ORDER BY visit_count DESC
        """
        
        if limit:
            base_query += f" LIMIT {limit}"
        
        query = text(base_query)
        
        cutoff_date = datetime.utcnow() - timedelta(days=period_days)
        result = self.db_session.execute(query, {
            'cutoff_date': cutoff_date,
            'max_visits': max_visits
        })
        
        exceeding_patients = []
        for row in result:
            exceeding_patients.append({
                'nhis_number': row.nhis_number,
                'visit_count': row.visit_count,
                'max_allowed': max_visits,
                'excess_visits': row.visit_count - max_visits,
                'last_visit': row.last_visit,
                'first_visit_in_period': row.first_visit_in_period,
                'facilities_visited': row.facilities_visited,
                'limit_type': limit_type
            })
        
        return exceeding_patients
    
    def get_multi_specialty_violations(self, days_back: int = 30, limit: Optional[int] = None) -> List[Dict[str, Any]]:
        query = text("""
            WITH daily_visits AS (
                SELECT 
                    nhis_number,
                    DATE(admission_date) as visit_date,
                    COUNT(*) as visits_same_day,
                    string_agg(DISTINCT specialties_attended, ', ') as specialties,
                    string_agg(DISTINCT encounter_id, ', ') as encounters
                FROM claims_v2 
                WHERE service_type_1 = 'OPD'
                AND admission_date >= :cutoff_date
                AND specialties_attended IS NOT NULL
                GROUP BY nhis_number, DATE(admission_date)
                HAVING COUNT(*) > 1
            )
            SELECT 
                nhis_number,
                visit_date,
                visits_same_day,
                specialties,
                encounters
            FROM daily_visits
            ORDER BY visit_date DESC, visits_same_day DESC
        """)
        
        if limit:
            query = text(str(query) + f" LIMIT {limit}")
        
        cutoff_date = datetime.utcnow() - timedelta(days=days_back)
        result = self.db_session.execute(query, {
            'cutoff_date': cutoff_date
        })
        
        violations = []
        for row in result:
            violations.append({
                'nhis_number': row.nhis_number,
                'visit_date': row.visit_date,
                'visits_same_day': row.visits_same_day,
                'specialties': row.specialties,
                'encounters': row.encounters,
                'violation_type': 'MULTI_SPECIALTY_SAME_DAY'
            })
        
        return violations
    
    def get_episode_limit_validation(self, nhis_number: str, proposed_visit_date: datetime, service_type: str = 'OPD') -> Dict[str, Any]:
        query = text("""
            WITH episode_analysis AS (
                SELECT 
                    COUNT(*) FILTER (WHERE admission_date >= :acute_cutoff) as acute_count,
                    COUNT(*) FILTER (WHERE admission_date >= :chronic_cutoff) as chronic_count,
                    COUNT(*) FILTER (WHERE (icd10_diagnosis LIKE 'Z34%' OR icd10_diagnosis LIKE 'Z35%' OR icd10_diagnosis LIKE 'O0%' OR icd10_diagnosis LIKE 'O1%') AND admission_date >= :anc_cutoff) as anc_count,
                    COUNT(*) FILTER (WHERE (icd10_diagnosis LIKE 'Z39%' OR icd10_diagnosis LIKE 'O85%' OR icd10_diagnosis LIKE 'O90%') AND admission_date >= :pnc_cutoff) as pnc_count,
                    bool_or(icd10_diagnosis LIKE 'Z34%' OR icd10_diagnosis LIKE 'Z35%' OR icd10_diagnosis LIKE 'O0%' OR icd10_diagnosis LIKE 'O1%') as has_recent_anc,
                    bool_or(icd10_diagnosis LIKE 'Z39%' OR icd10_diagnosis LIKE 'O85%' OR icd10_diagnosis LIKE 'O90%') as has_recent_pnc
                FROM claims_v2 
                WHERE nhis_number = :nhis_number 
                AND service_type_1 = :service_type
            )
            SELECT 
                acute_count,
                chronic_count,
                anc_count,
                pnc_count,
                has_recent_anc,
                has_recent_pnc,
                CASE 
                    WHEN has_recent_anc THEN 'ANTENATAL'
                    WHEN has_recent_pnc THEN 'POSTNATAL'
                    WHEN acute_count > 0 AND chronic_count <= 3 THEN 'ACUTE'
                    ELSE 'CHRONIC'
                END as episode_type
            FROM episode_analysis
        """)
        
        acute_cutoff = proposed_visit_date - timedelta(days=14)
        chronic_cutoff = proposed_visit_date - timedelta(days=365)
        anc_cutoff = proposed_visit_date - timedelta(days=280)
        pnc_cutoff = proposed_visit_date - timedelta(weeks=6)
        
        result = self.db_session.execute(query, {
            'nhis_number': nhis_number,
            'service_type': service_type,
            'acute_cutoff': acute_cutoff,
            'chronic_cutoff': chronic_cutoff,
            'anc_cutoff': anc_cutoff,
            'pnc_cutoff': pnc_cutoff
        })
        
        row = result.fetchone()
        if row:
            episode_type = row.episode_type
            current_count = 0
            max_allowed = 0
            
            if episode_type == 'ACUTE':
                current_count = row.acute_count
                max_allowed = 3
            elif episode_type == 'CHRONIC':
                current_count = row.chronic_count
                max_allowed = 6
            elif episode_type == 'ANTENATAL':
                current_count = row.anc_count
                max_allowed = 6
            elif episode_type == 'POSTNATAL':
                current_count = row.pnc_count
                max_allowed = 3
            
            return {
                'nhis_number': nhis_number,
                'episode_type': episode_type,
                'current_count': current_count,
                'max_allowed': max_allowed,
                'is_within_limit': current_count < max_allowed,
                'visits_remaining': max(0, max_allowed - current_count),
                'will_exceed_if_approved': (current_count + 1) > max_allowed
            }
        
        return {
            'nhis_number': nhis_number,
            'episode_type': 'UNKNOWN',
            'current_count': 0,
            'max_allowed': 0,
            'is_within_limit': True,
            'visits_remaining': 0,
            'will_exceed_if_approved': False
        }