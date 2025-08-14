from typing import List, Optional, Dict, Any
from sqlalchemy.orm import Session
from sqlalchemy import and_, or_, func, desc, asc
from datetime import datetime, timedelta
import uuid

from .base_repository import BaseRepository
from ..models.provider_profile import ProviderProfile

class ProviderRepository(BaseRepository[ProviderProfile]):
    def __init__(self, db_session: Session):
        super().__init__(db_session, ProviderProfile)
    
    def get_by_provider_id(self, provider_id: uuid.UUID) -> Optional[ProviderProfile]:
        return self.get_by_field('provider_id', provider_id)
    
    def get_by_credential_id(self, credential_id: str) -> Optional[ProviderProfile]:
        return self.get_by_field('credential_id', credential_id)
    
    def get_by_facility_name(self, facility_name: str) -> Optional[ProviderProfile]:
        return self.get_by_field('facility_name', facility_name)
    
    def get_by_district(self, district: str, limit: Optional[int] = None) -> List[ProviderProfile]:
        return self.get_many_by_field('district', district, limit=limit)
    
    def get_by_region(self, region: str, limit: Optional[int] = None) -> List[ProviderProfile]:
        return self.get_many_by_field('region', region, limit=limit)
    
    def get_by_facility_type(self, facility_type: str, limit: Optional[int] = None) -> List[ProviderProfile]:
        return self.get_many_by_field('facility_type', facility_type, limit=limit)
    
    def get_by_prescribing_level(self, prescribing_level: str, limit: Optional[int] = None) -> List[ProviderProfile]:
        return self.get_many_by_field('prescribing_level', prescribing_level, limit=limit)
    
    def get_by_credential_status(self, status: str, limit: Optional[int] = None) -> List[ProviderProfile]:
        return self.get_many_by_field('credential_status', status, limit=limit)
    
    def get_active_providers(self, limit: Optional[int] = None) -> List[ProviderProfile]:
        return self.get_many_by_field('credential_status', 'Active', limit=limit)
    
    def get_pending_providers(self, limit: Optional[int] = None) -> List[ProviderProfile]:
        return self.get_many_by_field('credential_status', 'Pending', limit=limit)
    
    def get_suspended_providers(self, limit: Optional[int] = None) -> List[ProviderProfile]:
        return self.get_many_by_field('credential_status', 'Suspended', limit=limit)
    
    def get_expired_providers(self, limit: Optional[int] = None) -> List[ProviderProfile]:
        return self.get_many_by_field('credential_status', 'Expired', limit=limit)
    
    def get_providers_expiring_soon(self, days_ahead: int = 30, limit: Optional[int] = None) -> List[ProviderProfile]:
        cutoff_date = datetime.utcnow() + timedelta(days=days_ahead)
        
        query = self.db_session.query(ProviderProfile).filter(
            and_(
                ProviderProfile.credential_status == 'Active',
                ProviderProfile.expiry_date.isnot(None),
                ProviderProfile.expiry_date <= cutoff_date,
                ProviderProfile.expiry_date > datetime.utcnow()
            )
        ).order_by(asc(ProviderProfile.expiry_date))
        
        if limit:
            query = query.limit(limit)
            
        return query.all()
    
    def get_providers_by_region_and_type(self, region: str, facility_type: str, limit: Optional[int] = None) -> List[ProviderProfile]:
        return self.get_many_by_fields({
            'region': region,
            'facility_type': facility_type
        }, limit=limit)
    
    def get_providers_by_district_and_level(self, district: str, prescribing_level: str, limit: Optional[int] = None) -> List[ProviderProfile]:
        return self.get_many_by_fields({
            'district': district,
            'prescribing_level': prescribing_level
        }, limit=limit)
    
    def search_providers_by_name(self, search_term: str, limit: Optional[int] = None) -> List[ProviderProfile]:
        query = self.db_session.query(ProviderProfile).filter(
            ProviderProfile.facility_name.ilike(f'%{search_term}%')
        ).order_by(asc(ProviderProfile.facility_name))
        
        if limit:
            query = query.limit(limit)
            
        return query.all()
    
    def search_providers_by_contact_person(self, search_term: str, limit: Optional[int] = None) -> List[ProviderProfile]:
        query = self.db_session.query(ProviderProfile).filter(
            ProviderProfile.contact_person_name.ilike(f'%{search_term}%')
        ).order_by(asc(ProviderProfile.contact_person_name))
        
        if limit:
            query = query.limit(limit)
            
        return query.all()
    
    def get_providers_with_valid_credentials(self, limit: Optional[int] = None) -> List[ProviderProfile]:
        current_date = datetime.utcnow()
        
        query = self.db_session.query(ProviderProfile).filter(
            and_(
                ProviderProfile.credential_status == 'Active',
                or_(
                    ProviderProfile.expiry_date.is_(None),
                    ProviderProfile.expiry_date > current_date
                )
            )
        ).order_by(asc(ProviderProfile.facility_name))
        
        if limit:
            query = query.limit(limit)
            
        return query.all()
    
    def validate_provider_for_service(self, provider_id: uuid.UUID, service_type: str) -> Dict[str, Any]:
        provider = self.get_by_provider_id(provider_id)
        
        if not provider:
            return {
                'is_valid': False,
                'reason': 'Provider not found',
                'provider': None
            }
        
        if provider.credential_status != 'Active':
            return {
                'is_valid': False,
                'reason': f'Provider status is {provider.credential_status}',
                'provider': provider
            }
        
        if provider.expiry_date and provider.expiry_date <= datetime.utcnow():
            return {
                'is_valid': False,
                'reason': 'Provider credentials have expired',
                'provider': provider
            }
        
        service_type_requirements = {
            'IPD': ['Hospital', 'Clinic'],
            'OPD': ['Hospital', 'Clinic', 'Health Center'],
            'A&E': ['Hospital'],
            'EMERGENCY': ['Hospital']
        }
        
        if service_type in service_type_requirements:
            allowed_types = service_type_requirements[service_type]
            if provider.facility_type not in allowed_types:
                return {
                    'is_valid': False,
                    'reason': f'Facility type {provider.facility_type} not authorized for {service_type}',
                    'provider': provider
                }
        
        return {
            'is_valid': True,
            'reason': 'Provider is valid for service',
            'provider': provider
        }
    
    def check_prescribing_authority(self, provider_id: uuid.UUID, medicine_level: str) -> Dict[str, Any]:
        provider = self.get_by_provider_id(provider_id)
        
        if not provider:
            return {
                'can_prescribe': False,
                'reason': 'Provider not found'
            }
        
        if not provider.prescribing_level:
            return {
                'can_prescribe': False,
                'reason': 'No prescribing level assigned'
            }
        
        level_hierarchy = {'A': 3, 'B': 2, 'C': 1}
        
        provider_level_value = level_hierarchy.get(provider.prescribing_level, 0)
        required_level_value = level_hierarchy.get(medicine_level, 0)
        
        if provider_level_value >= required_level_value:
            return {
                'can_prescribe': True,
                'reason': f'Provider level {provider.prescribing_level} can prescribe level {medicine_level} medicines'
            }
        else:
            return {
                'can_prescribe': False,
                'reason': f'Provider level {provider.prescribing_level} cannot prescribe level {medicine_level} medicines'
            }
    
    def get_facility_capabilities(self, provider_id: uuid.UUID) -> Dict[str, Any]:
        provider = self.get_by_provider_id(provider_id)
        
        if not provider:
            return {'error': 'Provider not found'}
        
        capabilities = {
            'provider_id': provider.provider_id,
            'facility_name': provider.facility_name,
            'facility_type': provider.facility_type,
            'prescribing_level': provider.prescribing_level,
            'district': provider.district,
            'region': provider.region,
            'credential_status': provider.credential_status,
            'is_active': provider.credential_status == 'Active',
            'credentials_valid': provider.expiry_date is None or provider.expiry_date > datetime.utcnow(),
            'services_authorized': self._get_authorized_services(provider.facility_type),
            'can_prescribe_levels': self._get_prescribing_levels(provider.prescribing_level)
        }
        
        return capabilities
    
    def _get_authorized_services(self, facility_type: str) -> List[str]:
        service_authorization = {
            'Hospital': ['IPD', 'OPD', 'A&E', 'EMERGENCY'],
            'Clinic': ['IPD', 'OPD'],
            'Health Center': ['OPD'],
            'Pharmacy': ['OPD'],
            'Laboratory': ['OPD']
        }
        
        return service_authorization.get(facility_type, [])
    
    def _get_prescribing_levels(self, prescribing_level: str) -> List[str]:
        if not prescribing_level:
            return []
        
        level_access = {
            'A': ['A', 'B', 'C'],
            'B': ['B', 'C'],
            'C': ['C']
        }
        
        return level_access.get(prescribing_level, [])
    
    def update_credential_status(self, provider_id: uuid.UUID, new_status: str, reason: Optional[str] = None) -> bool:
        valid_statuses = ['Active', 'Pending', 'Suspended', 'Expired', 'Revoked']
        
        if new_status not in valid_statuses:
            raise ValueError(f"Invalid credential status: {new_status}")
        
        update_data = {
            'credential_status': new_status,
            'last_updated_date': datetime.utcnow()
        }
        
        result = self.update_by_field('provider_id', provider_id, update_data)
        return result > 0
    
    def extend_credentials(self, provider_id: uuid.UUID, new_expiry_date: datetime) -> bool:
        update_data = {
            'expiry_date': new_expiry_date,
            'last_updated_date': datetime.utcnow()
        }
        
        result = self.update_by_field('provider_id', provider_id, update_data)
        return result > 0
    
    def get_provider_statistics(self) -> Dict[str, Any]:
        total_providers = self.count()
        active_providers = self.count({'credential_status': 'Active'})
        pending_providers = self.count({'credential_status': 'Pending'})
        suspended_providers = self.count({'credential_status': 'Suspended'})
        expired_providers = self.count({'credential_status': 'Expired'})
        
        facility_type_counts = self.db_session.query(
            ProviderProfile.facility_type,
            func.count(ProviderProfile.id)
        ).group_by(ProviderProfile.facility_type).all()
        
        region_counts = self.db_session.query(
            ProviderProfile.region,
            func.count(ProviderProfile.id)
        ).group_by(ProviderProfile.region).all()
        
        return {
            'total_providers': total_providers,
            'active_providers': active_providers,
            'pending_providers': pending_providers,
            'suspended_providers': suspended_providers,
            'expired_providers': expired_providers,
            'facility_types': dict(facility_type_counts),
            'regions': dict(region_counts),
            'credential_utilization_rate': (active_providers / total_providers * 100) if total_providers > 0 else 0
        }