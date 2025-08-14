from typing import List, Dict, Any, Optional
from sqlalchemy.orm import Session
from sqlalchemy import text, and_, or_, func
from datetime import datetime, timedelta
import uuid


class ReadmissionQueries:
    def __init__(self, db_session: Session):
        self.db_session = db_session
    
    def validate_emergency_readmission_rule(self, nhis_number: str, current_admission: datetime, 
                                          current_diagnosis: str, facility_id: uuid.UUID) -> Dict[str, Any]:
        query = text("""
            WITH recent_discharges AS (
                SELECT 
                    id,
                    encounter_id,
                    admission_date,
                    discharge_date,
                    icd10_diagnosis,
                    provider_id,
                    provider_name,
                    (EXTRACT(EPOCH FROM (:current_admission - discharge_date)) / 86400)::int as days_between
                FROM claims_v2
                WHERE nhis_number = :nhis_number
                AND service_type_1 = 'IPD'
                AND discharge_date IS NOT NULL
                AND discharge_date < :current_admission
                AND discharge_date >= :lookback_date
                ORDER BY discharge_date DESC
                LIMIT 3
            ),
            violation_analysis AS (
                SELECT 
                    rd.*,
                    :current_diagnosis as current_diagnosis,
                    :facility_id as current_facility_id,
                    CASE 
                        WHEN days_between <= 30 THEN 'VIOLATION'
                        WHEN days_between <= 90 THEN 'WARNING'
                        ELSE 'COMPLIANT'
                    END as readmission_status,
                    CASE 
                        WHEN rd.icd10_diagnosis = :current_diagnosis THEN 'SAME_DIAGNOSIS'
                        WHEN LEFT(rd.icd10_diagnosis, 3) = LEFT(:current_diagnosis, 3) THEN 'RELATED_DIAGNOSIS'
                        ELSE 'DIFFERENT_DIAGNOSIS'
                    END as diagnosis_relationship,
                    CASE 
                        WHEN rd.provider_id = :facility_id THEN 'SAME_FACILITY'
                        ELSE 'DIFFERENT_FACILITY'
                    END as facility_relationship
                FROM recent_discharges rd
            )
            SELECT 
                va.*,
                CASE 
                    WHEN va.readmission_status = 'VIOLATION' AND va.diagnosis_relationship IN ('SAME_DIAGNOSIS', 'RELATED_DIAGNOSIS') THEN 'HIGH_RISK'
                    WHEN va.readmission_status = 'VIOLATION' THEN 'MEDIUM_RISK'
                    WHEN va.readmission_status = 'WARNING' THEN 'LOW_RISK'
                    ELSE 'NO_RISK'
                END as risk_level,
                CASE 
                    WHEN va.readmission_status = 'VIOLATION' THEN true
                    ELSE false
                END as requires_justification
            FROM violation_analysis va
            ORDER BY va.discharge_date DESC
        """)
        
        lookback_date = current_admission - timedelta(days=120)
        
        result = self.db_session.execute(query, {
            'nhis_number': nhis_number,
            'current_admission': current_admission,
            'current_diagnosis': current_diagnosis,
            'facility_id': facility_id,
            'lookback_date': lookback_date
        })
        
        readmissions = []
        has_violation = False
        highest_risk = 'NO_RISK'
        
        for row in result:
            readmission_data = {
                'previous_claim_id': row.id,
                'encounter_id': row.encounter_id,
                'admission_date': row.admission_date,
                'discharge_date': row.discharge_date,
                'previous_diagnosis': row.icd10_diagnosis,
                'current_diagnosis': row.current_diagnosis,
                'provider_id': row.provider_id,
                'provider_name': row.provider_name,
                'days_between': row.days_between,
                'readmission_status': row.readmission_status,
                'diagnosis_relationship': row.diagnosis_relationship,
                'facility_relationship': row.facility_relationship,
                'risk_level': row.risk_level,
                'requires_justification': row.requires_justification
            }
            
            readmissions.append(readmission_data)
            
            if row.readmission_status == 'VIOLATION':
                has_violation = True
            
            if row.risk_level in ['HIGH_RISK', 'MEDIUM_RISK', 'LOW_RISK'] and row.risk_level != 'NO_RISK':
                if highest_risk == 'NO_RISK' or (row.risk_level == 'HIGH_RISK' and highest_risk != 'HIGH_RISK') or (row.risk_level == 'MEDIUM_RISK' and highest_risk == 'LOW_RISK'):
                    highest_risk = row.risk_level
        
        return {
            'nhis_number': nhis_number,
            'current_admission': current_admission,
            'current_diagnosis': current_diagnosis,
            'facility_id': str(facility_id),
            'has_violation': has_violation,
            'highest_risk_level': highest_risk,
            'requires_justification': has_violation,
            'recent_readmissions': readmissions,
            'readmission_count': len(readmissions),
            'rule_status': 'VIOLATION' if has_violation else 'COMPLIANT'
        }
    
    def get_readmission_patterns(self, days_back: int = 90, min_readmissions: int = 2, 
                               limit: Optional[int] = None) -> List[Dict[str, Any]]:
        query = text("""
            WITH readmission_analysis AS (
                SELECT 
                    c1.nhis_number,
                    c1.id as current_claim_id,
                    c1.admission_date as current_admission,
                    c1.icd10_diagnosis as current_diagnosis,
                    c1.provider_id as current_provider_id,
                    c1.provider_name as current_provider_name,
                    c2.id as previous_claim_id,
                    c2.discharge_date as previous_discharge,
                    c2.icd10_diagnosis as previous_diagnosis,
                    c2.provider_id as previous_provider_id,
                    c2.provider_name as previous_provider_name,
                    (EXTRACT(EPOCH FROM (c1.admission_date - c2.discharge_date)) / 86400)::int as days_between,
                    ROW_NUMBER() OVER (PARTITION BY c1.nhis_number ORDER BY c1.admission_date DESC, c2.discharge_date DESC) as readmission_rank
                FROM claims_v2 c1
                INNER JOIN claims_v2 c2 ON c1.nhis_number = c2.nhis_number
                WHERE c1.service_type_1 = 'IPD'
                AND c2.service_type_1 = 'IPD'
                AND c1.admission_date >= :cutoff_date
                AND c2.discharge_date IS NOT NULL
                AND c1.admission_date > c2.discharge_date
                AND (c1.admission_date - c2.discharge_date) <= INTERVAL '120 days'
            ),
            patient_readmission_stats AS (
                SELECT 
                    nhis_number,
                    COUNT(*) as total_readmissions,
                    COUNT(*) FILTER (WHERE days_between <= 30) as violations_30_days,
                    COUNT(*) FILTER (WHERE days_between <= 90) as readmissions_90_days,
                    AVG(days_between) as avg_days_between,
                    MIN(days_between) as shortest_interval,
                    COUNT(DISTINCT current_provider_id) as facilities_involved,
                    json_agg(
                        json_build_object(
                            'current_admission', current_admission,
                            'previous_discharge', previous_discharge,
                            'days_between', days_between,
                            'current_diagnosis', current_diagnosis,
                            'previous_diagnosis', previous_diagnosis,
                            'same_facility', current_provider_id = previous_provider_id,
                            'same_diagnosis', current_diagnosis = previous_diagnosis
                        ) ORDER BY current_admission DESC
                    ) as readmission_details
                FROM readmission_analysis
                GROUP BY nhis_number
                HAVING COUNT(*) >= :min_readmissions
            )
            SELECT 
                nhis_number,
                total_readmissions,
                violations_30_days,
                readmissions_90_days,
                ROUND(avg_days_between::numeric, 1) as avg_days_between,
                shortest_interval,
                facilities_involved,
                readmission_details,
                CASE 
                    WHEN violations_30_days >= 3 THEN 'HIGH_RISK'
                    WHEN violations_30_days >= 2 THEN 'MEDIUM_RISK'
                    WHEN violations_30_days >= 1 THEN 'LOW_RISK'
                    ELSE 'MONITOR'
                END as risk_category
            FROM patient_readmission_stats
            ORDER BY violations_30_days DESC, total_readmissions DESC
        """)
        
        if limit:
            query = text(str(query) + f" LIMIT {limit}")
        
        cutoff_date = datetime.utcnow() - timedelta(days=days_back)
        
        result = self.db_session.execute(query, {
            'cutoff_date': cutoff_date,
            'min_readmissions': min_readmissions
        })
        
        patterns = []
        for row in result:
            patterns.append({
                'nhis_number': row.nhis_number,
                'total_readmissions': row.total_readmissions,
                'violations_30_days': row.violations_30_days,
                'readmissions_90_days': row.readmissions_90_days,
                'avg_days_between': float(row.avg_days_between or 0),
                'shortest_interval': row.shortest_interval,
                'facilities_involved': row.facilities_involved,
                'risk_category': row.risk_category,
                'readmission_details': row.readmission_details
            })
        
        return patterns
    
    def get_facility_readmission_rates(self, months_back: int = 6, limit: Optional[int] = None) -> List[Dict[str, Any]]:
        query = text("""
            WITH facility_admissions AS (
                SELECT 
                    provider_id,
                    provider_name,
                    COUNT(*) as total_admissions,
                    COUNT(DISTINCT nhis_number) as unique_patients
                FROM claims_v2
                WHERE service_type_1 = 'IPD'
                AND admission_date >= :cutoff_date
                AND discharge_date IS NOT NULL
                GROUP BY provider_id, provider_name
            ),
            facility_readmissions AS (
                SELECT 
                    c1.provider_id,
                    c1.provider_name,
                    COUNT(*) as total_readmissions,
                    COUNT(*) FILTER (WHERE (c1.admission_date - c2.discharge_date) <= INTERVAL '30 days') as readmissions_30_days,
                    COUNT(*) FILTER (WHERE (c1.admission_date - c2.discharge_date) <= INTERVAL '90 days') as readmissions_90_days,
                    AVG(EXTRACT(EPOCH FROM (c1.admission_date - c2.discharge_date)) / 86400) as avg_readmission_interval
                FROM claims_v2 c1
                INNER JOIN claims_v2 c2 ON c1.nhis_number = c2.nhis_number
                WHERE c1.service_type_1 = 'IPD'
                AND c2.service_type_1 = 'IPD'
                AND c1.admission_date >= :cutoff_date
                AND c2.discharge_date IS NOT NULL
                AND c1.admission_date > c2.discharge_date
                AND (c1.admission_date - c2.discharge_date) <= INTERVAL '120 days'
                GROUP BY c1.provider_id, c1.provider_name
            )
            SELECT 
                fa.provider_id,
                fa.provider_name,
                fa.total_admissions,
                fa.unique_patients,
                COALESCE(fr.total_readmissions, 0) as total_readmissions,
                COALESCE(fr.readmissions_30_days, 0) as readmissions_30_days,
                COALESCE(fr.readmissions_90_days, 0) as readmissions_90_days,
                ROUND((COALESCE(fr.readmissions_30_days, 0)::numeric / NULLIF(fa.total_admissions, 0)) * 100, 2) as readmission_rate_30_days,
                ROUND((COALESCE(fr.readmissions_90_days, 0)::numeric / NULLIF(fa.total_admissions, 0)) * 100, 2) as readmission_rate_90_days,
                ROUND(COALESCE(fr.avg_readmission_interval, 0)::numeric, 1) as avg_readmission_interval,
                CASE 
                    WHEN (COALESCE(fr.readmissions_30_days, 0)::numeric / NULLIF(fa.total_admissions, 0)) > 0.15 THEN 'HIGH'
                    WHEN (COALESCE(fr.readmissions_30_days, 0)::numeric / NULLIF(fa.total_admissions, 0)) > 0.10 THEN 'MEDIUM'
                    WHEN (COALESCE(fr.readmissions_30_days, 0)::numeric / NULLIF(fa.total_admissions, 0)) > 0.05 THEN 'LOW'
                    ELSE 'MINIMAL'
                END as risk_level
            FROM facility_admissions fa
            LEFT JOIN facility_readmissions fr ON fa.provider_id = fr.provider_id
            WHERE fa.total_admissions >= 10
            ORDER BY readmission_rate_30_days DESC NULLS LAST
        """)
        
        if limit:
            query = text(str(query) + f" LIMIT {limit}")
        
        cutoff_date = datetime.utcnow() - timedelta(days=months_back * 30)
        
        result = self.db_session.execute(query, {
            'cutoff_date': cutoff_date
        })
        
        facility_rates = []
        for row in result:
            facility_rates.append({
                'provider_id': str(row.provider_id),
                'provider_name': row.provider_name,
                'total_admissions': row.total_admissions,
                'unique_patients': row.unique_patients,
                'total_readmissions': row.total_readmissions,
                'readmissions_30_days': row.readmissions_30_days,
                'readmissions_90_days': row.readmissions_90_days,
                'readmission_rate_30_days': float(row.readmission_rate_30_days or 0),
                'readmission_rate_90_days': float(row.readmission_rate_90_days or 0),
                'avg_readmission_interval': float(row.avg_readmission_interval or 0),
                'risk_level': row.risk_level
            })
        
        return facility_rates
    
    def get_diagnosis_readmission_analysis(self, months_back: int = 6, limit: Optional[int] = None) -> List[Dict[str, Any]]:
        query = text("""
            WITH diagnosis_readmissions AS (
                SELECT 
                    c2.icd10_diagnosis as discharge_diagnosis,
                    c1.icd10_diagnosis as readmission_diagnosis,
                    COUNT(*) as readmission_count,
                    COUNT(*) FILTER (WHERE (c1.admission_date - c2.discharge_date) <= INTERVAL '30 days') as readmissions_30_days,
                    AVG(EXTRACT(EPOCH FROM (c1.admission_date - c2.discharge_date)) / 86400) as avg_days_to_readmission,
                    COUNT(DISTINCT c1.nhis_number) as unique_patients_affected
                FROM claims_v2 c1
                INNER JOIN claims_v2 c2 ON c1.nhis_number = c2.nhis_number
                WHERE c1.service_type_1 = 'IPD'
                AND c2.service_type_1 = 'IPD'
                AND c1.admission_date >= :cutoff_date
                AND c2.discharge_date IS NOT NULL
                AND c1.admission_date > c2.discharge_date
                AND (c1.admission_date - c2.discharge_date) <= INTERVAL '90 days'
                AND c2.icd10_diagnosis IS NOT NULL
                GROUP BY c2.icd10_diagnosis, c1.icd10_diagnosis
            ),
            total_discharges AS (
                SELECT 
                    icd10_diagnosis,
                    COUNT(*) as total_discharge_count
                FROM claims_v2
                WHERE service_type_1 = 'IPD'
                AND discharge_date IS NOT NULL
                AND admission_date >= :cutoff_date
                AND icd10_diagnosis IS NOT NULL
                GROUP BY icd10_diagnosis
            )
            SELECT 
                dr.discharge_diagnosis,
                dr.readmission_diagnosis,
                dr.readmission_count,
                dr.readmissions_30_days,
                ROUND(dr.avg_days_to_readmission::numeric, 1) as avg_days_to_readmission,
                dr.unique_patients_affected,
                td.total_discharge_count,
                ROUND((dr.readmissions_30_days::numeric / NULLIF(td.total_discharge_count, 0)) * 100, 2) as readmission_rate,
                CASE 
                    WHEN dr.discharge_diagnosis = dr.readmission_diagnosis THEN 'SAME_DIAGNOSIS'
                    WHEN LEFT(dr.discharge_diagnosis, 3) = LEFT(dr.readmission_diagnosis, 3) THEN 'RELATED_DIAGNOSIS'
                    ELSE 'DIFFERENT_DIAGNOSIS'
                END as diagnosis_relationship,
                CASE 
                    WHEN (dr.readmissions_30_days::numeric / NULLIF(td.total_discharge_count, 0)) > 0.20 THEN 'HIGH_RISK'
                    WHEN (dr.readmissions_30_days::numeric / NULLIF(td.total_discharge_count, 0)) > 0.10 THEN 'MEDIUM_RISK'
                    WHEN (dr.readmissions_30_days::numeric / NULLIF(td.total_discharge_count, 0)) > 0.05 THEN 'LOW_RISK'
                    ELSE 'MINIMAL_RISK'
                END as risk_category
            FROM diagnosis_readmissions dr
            LEFT JOIN total_discharges td ON dr.discharge_diagnosis = td.icd10_diagnosis
            WHERE dr.readmissions_30_days >= 2
            ORDER BY dr.readmissions_30_days DESC, readmission_rate DESC NULLS LAST
        """)
        
        if limit:
            query = text(str(query) + f" LIMIT {limit}")
        
        cutoff_date = datetime.utcnow() - timedelta(days=months_back * 30)
        
        result = self.db_session.execute(query, {
            'cutoff_date': cutoff_date
        })
        
        diagnosis_analysis = []
        for row in result:
            diagnosis_analysis.append({
                'discharge_diagnosis': row.discharge_diagnosis,
                'readmission_diagnosis': row.readmission_diagnosis,
                'readmission_count': row.readmission_count,
                'readmissions_30_days': row.readmissions_30_days,
                'avg_days_to_readmission': float(row.avg_days_to_readmission or 0),
                'unique_patients_affected': row.unique_patients_affected,
                'total_discharge_count': row.total_discharge_count,
                'readmission_rate': float(row.readmission_rate or 0),
                'diagnosis_relationship': row.diagnosis_relationship,
                'risk_category': row.risk_category
            })
        
        return diagnosis_analysis
    
    def get_emergency_readmission_alerts(self, days_ahead: int = 7, limit: Optional[int] = None) -> List[Dict[str, Any]]:
        query = text("""
            WITH recent_discharges AS (
                SELECT 
                    nhis_number,
                    id as claim_id,
                    encounter_id,
                    discharge_date,
                    icd10_diagnosis,
                    provider_id,
                    provider_name,
                    30 - EXTRACT(DAYS FROM (CURRENT_TIMESTAMP - discharge_date))::int as days_until_30_day_mark
                FROM claims_v2
                WHERE service_type_1 = 'IPD'
                AND discharge_date IS NOT NULL
                AND discharge_date >= (CURRENT_TIMESTAMP - INTERVAL '23 days')
                AND discharge_date <= (CURRENT_TIMESTAMP - INTERVAL ':days_ahead days')
            ),
            patient_history AS (
                SELECT 
                    rd.nhis_number,
                    rd.claim_id,
                    rd.encounter_id,
                    rd.discharge_date,
                    rd.icd10_diagnosis,
                    rd.provider_id,
                    rd.provider_name,
                    rd.days_until_30_day_mark,
                    COUNT(prev.id) as previous_readmissions_count,
                    BOOL_OR(prev.id IS NOT NULL AND (prev.admission_date - prev_discharge.discharge_date) <= INTERVAL '30 days') as has_previous_violations
                FROM recent_discharges rd
                LEFT JOIN claims_v2 prev ON rd.nhis_number = prev.nhis_number 
                    AND prev.service_type_1 = 'IPD' 
                    AND prev.admission_date > rd.discharge_date
                    AND prev.admission_date < (rd.discharge_date + INTERVAL '30 days')
                LEFT JOIN claims_v2 prev_discharge ON prev.nhis_number = prev_discharge.nhis_number
                    AND prev_discharge.service_type_1 = 'IPD'
                    AND prev_discharge.discharge_date < prev.admission_date
                    AND prev_discharge.discharge_date >= (prev.admission_date - INTERVAL '120 days')
                GROUP BY rd.nhis_number, rd.claim_id, rd.encounter_id, rd.discharge_date, 
                         rd.icd10_diagnosis, rd.provider_id, rd.provider_name, rd.days_until_30_day_mark
            )
            SELECT 
                nhis_number,
                claim_id,
                encounter_id,
                discharge_date,
                icd10_diagnosis,
                provider_id,
                provider_name,
                days_until_30_day_mark,
                previous_readmissions_count,
                has_previous_violations,
                CASE 
                    WHEN has_previous_violations AND previous_readmissions_count >= 2 THEN 'HIGH_RISK'
                    WHEN has_previous_violations OR previous_readmissions_count >= 1 THEN 'MEDIUM_RISK'
                    ELSE 'LOW_RISK'
                END as risk_level,
                CASE 
                    WHEN days_until_30_day_mark <= 3 THEN 'IMMEDIATE'
                    WHEN days_until_30_day_mark <= 7 THEN 'URGENT'
                    ELSE 'MONITOR'
                END as alert_priority
            FROM patient_history
            ORDER BY days_until_30_day_mark ASC, risk_level DESC
        """)
        
        if limit:
            query = text(str(query) + f" LIMIT {limit}")
        
        result = self.db_session.execute(query, {
            'days_ahead': days_ahead
        })
        
        alerts = []
        for row in result:
            alerts.append({
                'nhis_number': row.nhis_number,
                'claim_id': row.claim_id,
                'encounter_id': row.encounter_id,
                'discharge_date': row.discharge_date,
                'diagnosis': row.icd10_diagnosis,
                'provider_id': str(row.provider_id),
                'provider_name': row.provider_name,
                'days_until_30_day_mark': row.days_until_30_day_mark,
                'previous_readmissions_count': row.previous_readmissions_count,
                'has_previous_violations': row.has_previous_violations,
                'risk_level': row.risk_level,
                'alert_priority': row.alert_priority
            })
        
        return alerts