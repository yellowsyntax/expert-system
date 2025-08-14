from typing import List, Dict, Any, Optional
from sqlalchemy.orm import Session
from sqlalchemy import text, and_, or_, func

import uuid


class ProviderCapabilityQueries:
    def __init__(self, db_session: Session):
        self.db_session = db_session
    
    def validate_provider_for_service(self, provider_id: uuid.UUID, service_type: str) -> Dict[str, Any]:
        query = text("""
            SELECT 
                provider_id,
                facility_name,
                facility_type,
                prescribing_level,
                credential_status,
                expiry_date,
                district,
                region,
                CASE 
                    WHEN credential_status != 'Active' THEN 'INACTIVE_CREDENTIALS'
                    WHEN expiry_date IS NOT NULL AND expiry_date <= CURRENT_TIMESTAMP THEN 'EXPIRED_CREDENTIALS'
                    WHEN :service_type = 'IPD' AND facility_type NOT IN ('Hospital', 'Clinic') THEN 'FACILITY_NOT_AUTHORIZED_IPD'
                    WHEN :service_type = 'A&E' AND facility_type != 'Hospital' THEN 'FACILITY_NOT_AUTHORIZED_AE'
                    WHEN :service_type = 'EMERGENCY' AND facility_type != 'Hospital' THEN 'FACILITY_NOT_AUTHORIZED_EMERGENCY'
                    ELSE 'AUTHORIZED'
                END as authorization_status,
                CASE 
                    WHEN :service_type = 'IPD' THEN ARRAY['Hospital', 'Clinic']
                    WHEN :service_type = 'OPD' THEN ARRAY['Hospital', 'Clinic', 'Health Center']
                    WHEN :service_type = 'A&E' THEN ARRAY['Hospital']
                    WHEN :service_type = 'EMERGENCY' THEN ARRAY['Hospital']
                    ELSE ARRAY['Hospital', 'Clinic', 'Health Center']
                END as allowed_facility_types
            FROM provider_profiles 
            WHERE provider_id = :provider_id
        """)
        
        result = self.db_session.execute(query, {
            'provider_id': provider_id,
            'service_type': service_type
        })
        
        row = result.fetchone()
        if row:
            is_authorized = row.authorization_status == 'AUTHORIZED'
            
            return {
                'provider_id': str(row.provider_id),
                'facility_name': row.facility_name,
                'facility_type': row.facility_type,
                'prescribing_level': row.prescribing_level,
                'credential_status': row.credential_status,
                'expiry_date': row.expiry_date,
                'district': row.district,
                'region': row.region,
                'is_authorized': is_authorized,
                'authorization_status': row.authorization_status,
                'allowed_facility_types': row.allowed_facility_types,
                'service_type_requested': service_type
            }
        
        return {
            'provider_id': str(provider_id),
            'is_authorized': False,
            'authorization_status': 'PROVIDER_NOT_FOUND',
            'error': 'Provider not found in system'
        }
    
    def check_prescribing_authority(self, provider_id: uuid.UUID, medicine_level: str) -> Dict[str, Any]:
        query = text("""
            SELECT 
                provider_id,
                facility_name,
                prescribing_level,
                credential_status,
                CASE 
                    WHEN credential_status != 'Active' THEN 'INACTIVE_CREDENTIALS'
                    WHEN prescribing_level IS NULL THEN 'NO_PRESCRIBING_LEVEL'
                    WHEN prescribing_level = 'A' AND :medicine_level IN ('A', 'B', 'C') THEN 'AUTHORIZED'
                    WHEN prescribing_level = 'B' AND :medicine_level IN ('B', 'C') THEN 'AUTHORIZED'
                    WHEN prescribing_level = 'C' AND :medicine_level = 'C' THEN 'AUTHORIZED'
                    ELSE 'INSUFFICIENT_LEVEL'
                END as prescribing_authorization,
                CASE 
                    WHEN prescribing_level = 'A' THEN ARRAY['A', 'B', 'C']
                    WHEN prescribing_level = 'B' THEN ARRAY['B', 'C']
                    WHEN prescribing_level = 'C' THEN ARRAY['C']
                    ELSE ARRAY[]::text[]
                END as can_prescribe_levels
            FROM provider_profiles 
            WHERE provider_id = :provider_id
        """)
        
        result = self.db_session.execute(query, {
            'provider_id': provider_id,
            'medicine_level': medicine_level
        })
        
        row = result.fetchone()
        if row:
            can_prescribe = row.prescribing_authorization == 'AUTHORIZED'
            
            return {
                'provider_id': str(row.provider_id),
                'facility_name': row.facility_name,
                'prescribing_level': row.prescribing_level,
                'credential_status': row.credential_status,
                'can_prescribe': can_prescribe,
                'prescribing_authorization': row.prescribing_authorization,
                'can_prescribe_levels': row.can_prescribe_levels,
                'medicine_level_requested': medicine_level
            }
        
        return {
            'provider_id': str(provider_id),
            'can_prescribe': False,
            'prescribing_authorization': 'PROVIDER_NOT_FOUND',
            'error': 'Provider not found in system'
        }
    
    def get_providers_by_capability(self, service_type: str, region: Optional[str] = None, 
                                   district: Optional[str] = None, limit: Optional[int] = None) -> List[Dict[str, Any]]:
        base_query = """
            SELECT 
                provider_id,
                facility_name,
                facility_type,
                prescribing_level,
                credential_status,
                district,
                region,
                expiry_date,
                CASE 
                    WHEN credential_status = 'Active' AND (expiry_date IS NULL OR expiry_date > CURRENT_TIMESTAMP) THEN true
                    ELSE false
                END as is_currently_valid
            FROM provider_profiles 
            WHERE credential_status = 'Active'
            AND (expiry_date IS NULL OR expiry_date > CURRENT_TIMESTAMP)
        """
        
        if service_type == 'IPD':
            base_query += " AND facility_type IN ('Hospital', 'Clinic')"
        elif service_type in ['A&E', 'EMERGENCY']:
            base_query += " AND facility_type = 'Hospital'"
        elif service_type == 'OPD':
            base_query += " AND facility_type IN ('Hospital', 'Clinic', 'Health Center')"
        
        if region:
            base_query += " AND region = :region"
        
        if district:
            base_query += " AND district = :district"
        
        base_query += " ORDER BY facility_name"
        
        if limit:
            base_query += f" LIMIT {limit}"
        
        query = text(base_query)
        
        params = {'service_type': service_type}
        if region:
            params['region'] = region
        if district:
            params['district'] = district
        
        result = self.db_session.execute(query, params)
        
        providers = []
        for row in result:
            providers.append({
                'provider_id': str(row.provider_id),
                'facility_name': row.facility_name,
                'facility_type': row.facility_type,
                'prescribing_level': row.prescribing_level,
                'credential_status': row.credential_status,
                'district': row.district,
                'region': row.region,
                'expiry_date': row.expiry_date,
                'is_currently_valid': row.is_currently_valid,
                'authorized_service_type': service_type
            })
        
        return providers
    
    def get_providers_expiring_soon(self, days_ahead: int = 30, limit: Optional[int] = None) -> List[Dict[str, Any]]:
        query = text("""
            SELECT 
                provider_id,
                facility_name,
                facility_type,
                credential_status,
                expiry_date,
                district,
                region,
                contact_person_name,
                contact_person_email,
                (expiry_date - CURRENT_TIMESTAMP) as time_until_expiry,
                EXTRACT(DAYS FROM (expiry_date - CURRENT_TIMESTAMP)) as days_until_expiry
            FROM provider_profiles 
            WHERE credential_status = 'Active'
            AND expiry_date IS NOT NULL
            AND expiry_date <= (CURRENT_TIMESTAMP + INTERVAL ':days_ahead days')
            AND expiry_date > CURRENT_TIMESTAMP
            ORDER BY expiry_date ASC
        """)
        
        if limit:
            query = text(str(query) + f" LIMIT {limit}")
        
        result = self.db_session.execute(query, {
            'days_ahead': days_ahead
        })
        
        expiring_providers = []
        for row in result:
            expiring_providers.append({
                'provider_id': str(row.provider_id),
                'facility_name': row.facility_name,
                'facility_type': row.facility_type,
                'credential_status': row.credential_status,
                'expiry_date': row.expiry_date,
                'district': row.district,
                'region': row.region,
                'contact_person_name': row.contact_person_name,
                'contact_person_email': row.contact_person_email,
                'days_until_expiry': int(row.days_until_expiry or 0),
                'urgency_level': 'HIGH' if row.days_until_expiry <= 7 else 'MEDIUM' if row.days_until_expiry <= 14 else 'LOW'
            })
        
        return expiring_providers
    
    def get_facility_authorization_matrix(self, facility_type: Optional[str] = None) -> List[Dict[str, Any]]:
        query = text("""
            SELECT 
                facility_type,
                COUNT(*) as total_facilities,
                COUNT(*) FILTER (WHERE credential_status = 'Active') as active_facilities,
                COUNT(*) FILTER (WHERE credential_status = 'Active' AND (expiry_date IS NULL OR expiry_date > CURRENT_TIMESTAMP)) as valid_facilities,
                COUNT(*) FILTER (WHERE prescribing_level = 'A') as level_a_prescribers,
                COUNT(*) FILTER (WHERE prescribing_level = 'B') as level_b_prescribers,
                COUNT(*) FILTER (WHERE prescribing_level = 'C') as level_c_prescribers,
                CASE 
                    WHEN facility_type = 'Hospital' THEN ARRAY['IPD', 'OPD', 'A&E', 'EMERGENCY']
                    WHEN facility_type = 'Clinic' THEN ARRAY['IPD', 'OPD']
                    WHEN facility_type = 'Health Center' THEN ARRAY['OPD']
                    ELSE ARRAY[]::text[]
                END as authorized_services
            FROM provider_profiles 
            WHERE (:facility_type IS NULL OR facility_type = :facility_type)
            GROUP BY facility_type
            ORDER BY facility_type
        """)
        
        result = self.db_session.execute(query, {
            'facility_type': facility_type
        })
        
        authorization_matrix = []
        for row in result:
            authorization_matrix.append({
                'facility_type': row.facility_type,
                'total_facilities': row.total_facilities,
                'active_facilities': row.active_facilities,
                'valid_facilities': row.valid_facilities,
                'level_a_prescribers': row.level_a_prescribers,
                'level_b_prescribers': row.level_b_prescribers,
                'level_c_prescribers': row.level_c_prescribers,
                'authorized_services': row.authorized_services,
                'ipd_authorized': 'IPD' in row.authorized_services,
                'opd_authorized': 'OPD' in row.authorized_services,
                'ae_authorized': 'A&E' in row.authorized_services,
                'emergency_authorized': 'EMERGENCY' in row.authorized_services
            })
        
        return authorization_matrix
    
    def get_regional_capability_analysis(self, service_type: str) -> List[Dict[str, Any]]:
        query = text("""
            WITH regional_stats AS (
                SELECT 
                    region,
                    COUNT(*) as total_providers,
                    COUNT(*) FILTER (WHERE credential_status = 'Active' AND (expiry_date IS NULL OR expiry_date > CURRENT_TIMESTAMP)) as active_providers,
                    COUNT(*) FILTER (WHERE facility_type = 'Hospital') as hospitals,
                    COUNT(*) FILTER (WHERE facility_type = 'Clinic') as clinics,
                    COUNT(*) FILTER (WHERE facility_type = 'Health Center') as health_centers,
                    COUNT(*) FILTER (WHERE prescribing_level = 'A') as level_a_count,
                    COUNT(*) FILTER (WHERE prescribing_level = 'B') as level_b_count,
                    COUNT(*) FILTER (WHERE prescribing_level = 'C') as level_c_count
                FROM provider_profiles
                WHERE CASE 
                    WHEN :service_type = 'IPD' THEN facility_type IN ('Hospital', 'Clinic')
                    WHEN :service_type IN ('A&E', 'EMERGENCY') THEN facility_type = 'Hospital'
                    WHEN :service_type = 'OPD' THEN facility_type IN ('Hospital', 'Clinic', 'Health Center')
                    ELSE true
                END
                GROUP BY region
            )
            SELECT 
                region,
                total_providers,
                active_providers,
                hospitals,
                clinics,
                health_centers,
                level_a_count,
                level_b_count,
                level_c_count,
                ROUND((active_providers::numeric / NULLIF(total_providers, 0)) * 100, 2) as active_percentage,
                CASE 
                    WHEN active_providers >= 10 THEN 'HIGH'
                    WHEN active_providers >= 5 THEN 'MEDIUM'
                    ELSE 'LOW'
                END as coverage_level
            FROM regional_stats
            ORDER BY active_providers DESC, region
        """)
        
        result = self.db_session.execute(query, {
            'service_type': service_type
        })
        
        regional_analysis = []
        for row in result:
            regional_analysis.append({
                'region': row.region,
                'service_type': service_type,
                'total_providers': row.total_providers,
                'active_providers': row.active_providers,
                'hospitals': row.hospitals,
                'clinics': row.clinics,
                'health_centers': row.health_centers,
                'level_a_prescribers': row.level_a_count,
                'level_b_prescribers': row.level_b_count,
                'level_c_prescribers': row.level_c_count,
                'active_percentage': float(row.active_percentage or 0),
                'coverage_level': row.coverage_level
            })
        
        return regional_analysis
    
    def validate_facility_for_gdrg(self, provider_id: uuid.UUID, gdrg_code: str) -> Dict[str, Any]:
        query = text("""
            WITH provider_info AS (
                SELECT 
                    pp.provider_id,
                    pp.facility_name,
                    pp.facility_type,
                    pp.credential_status,
                    pp.expiry_date,
                    CASE 
                        WHEN pp.credential_status != 'Active' THEN 'INACTIVE_CREDENTIALS'
                        WHEN pp.expiry_date IS NOT NULL AND pp.expiry_date <= CURRENT_TIMESTAMP THEN 'EXPIRED_CREDENTIALS'
                        ELSE 'ACTIVE'
                    END as credential_validation
                FROM provider_profiles pp
                WHERE pp.provider_id = :provider_id
            ),
            gdrg_requirements AS (
                SELECT 
                    ic.gdrg_code,
                    ic.gdrg_name,
                    ic.level_of_care,
                    CASE 
                        WHEN :gdrg_code LIKE '%A' THEN 'ADULT'
                        WHEN :gdrg_code LIKE '%C' THEN 'CHILD'
                        ELSE 'UNKNOWN'
                    END as age_category
                FROM icd10_codes ic
                WHERE ic.gdrg_code = :gdrg_code
                LIMIT 1
            )
            SELECT 
                pi.provider_id,
                pi.facility_name,
                pi.facility_type,
                pi.credential_status,
                pi.credential_validation,
                gr.gdrg_code,
                gr.gdrg_name,
                gr.age_category,
                gr.level_of_care,
                CASE 
                    WHEN pi.credential_validation != 'ACTIVE' THEN false
                    WHEN gr.level_of_care IS NULL THEN true
                    WHEN pi.facility_type = 'Hospital' AND (gr.level_of_care ? 'A' OR gr.level_of_care ? 'B' OR gr.level_of_care ? 'C') THEN true
                    WHEN pi.facility_type = 'Clinic' AND (gr.level_of_care ? 'B' OR gr.level_of_care ? 'C') THEN true
                    WHEN pi.facility_type = 'Health Center' AND gr.level_of_care ? 'C' THEN true
                    ELSE false
                END as is_authorized_for_gdrg
            FROM provider_info pi
            CROSS JOIN gdrg_requirements gr
        """)
        
        result = self.db_session.execute(query, {
            'provider_id': provider_id,
            'gdrg_code': gdrg_code
        })
        
        row = result.fetchone()
        if row:
            return {
                'provider_id': str(row.provider_id),
                'facility_name': row.facility_name,
                'facility_type': row.facility_type,
                'credential_status': row.credential_status,
                'credential_validation': row.credential_validation,
                'gdrg_code': row.gdrg_code,
                'gdrg_name': row.gdrg_name,
                'age_category': row.age_category,
                'level_of_care_requirements': row.level_of_care,
                'is_authorized_for_gdrg': row.is_authorized_for_gdrg,
                'authorization_reason': self._get_gdrg_authorization_reason(
                    row.facility_type, 
                    row.credential_validation, 
                    row.level_of_care, 
                    row.is_authorized_for_gdrg
                )
            }
        
        return {
            'provider_id': str(provider_id),
            'gdrg_code': gdrg_code,
            'is_authorized_for_gdrg': False,
            'authorization_reason': 'PROVIDER_OR_GDRG_NOT_FOUND'
        }
    
    def _get_gdrg_authorization_reason(self, facility_type: str, credential_validation: str, 
                                      level_of_care: dict, is_authorized: bool) -> str:
        if credential_validation != 'ACTIVE':
            return credential_validation
        
        if not level_of_care:
            return 'NO_LEVEL_RESTRICTIONS'
        
        if is_authorized:
            return 'FACILITY_AUTHORIZED_FOR_GDRG'
        
        if facility_type == 'Hospital':
            return 'HOSPITAL_SHOULD_BE_AUTHORIZED'
        elif facility_type == 'Clinic':
            if level_of_care.get('A', False):
                return 'CLINIC_NOT_AUTHORIZED_FOR_LEVEL_A'
            else:
                return 'CLINIC_AUTHORIZED_FOR_LEVEL_BC'
        elif facility_type == 'Health Center':
            if level_of_care.get('A', False) or level_of_care.get('B', False):
                return 'HEALTH_CENTER_NOT_AUTHORIZED_FOR_LEVEL_AB'
            else:
                return 'HEALTH_CENTER_AUTHORIZED_FOR_LEVEL_C'
        
        return 'AUTHORIZATION_CHECK_FAILED'