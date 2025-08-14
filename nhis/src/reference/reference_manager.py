"""
Reference Manager for NHIS Expert System

Runtime interface for accessing reference data during claim processing.
Implements the BaseReferenceManager interface from core.
"""

from typing import Dict, List, Any, Optional
from ..core import BaseReferenceManager, ReferenceDataError
from .reference_loader import ReferenceLoader


class ReferenceManager(BaseReferenceManager):
   
    
    def __init__(self, data_dir: str = "reference_data"):
        self.data_dir = data_dir
        self.loader = ReferenceLoader(data_dir)
        self._is_loaded = False
        
    def load_reference_data(self) -> bool:
        
        print(" Loading NHIS reference data...")
        
        success = self.loader.load_all_reference_files()
        
        if success:
            # Validate data integrity
            validation_report = self.loader.validate_data_integrity()
            
            if validation_report['valid']:
                self._is_loaded = True
                print(" Reference data loaded and validated successfully!")
                
                # Print statistics
                stats = validation_report['statistics']
                if stats:
                    print(f" Loaded {stats.get('total_mappings', 0)} ICD-10 mappings")
                    print(f" Loaded {stats.get('total_medicines', 0)} medicines")
                    print(f" Found {stats.get('unique_gdrg_codes', 0)} unique G-DRGs")
                
            else:
                print(" Reference data loaded but has validation issues:")
                for issue in validation_report['issues']:
                    print(f"   - {issue['message']}")
                self._is_loaded = True  # Still usable despite issues
        else:
            print(" Failed to load reference data")
            errors = self.loader.get_load_errors()
            for error in errors:
                print(f"   - {error}")
        
        return success
    
    def get_mapping(self, mapping_type: str, key: str) -> Optional[Dict[str, Any]]:
        
        
        if not self._is_loaded:
            raise ReferenceDataError("Reference data not loaded")
        
        data = self.loader.get_data(mapping_type)
        if not data:
            return None
        
        return data.get(key)
    
    def is_data_loaded(self) -> bool:
       
        return self._is_loaded
    
    # Specific lookup methods for flowchart decision points
    
    def get_gdrg_for_diagnosis(self, icd10_code: str, encounter_type: str) -> Optional[Dict[str, Any]]:
        
        
        mapping_key = f"{icd10_code}_{encounter_type}"
        return self.get_mapping('icd10_gdrg_mapping', mapping_key)
    
    def is_service_excluded(self, icd10_code: str, encounter_type: str) -> bool:
        
        
        exclusions = self.loader.get_data('exclusions')
        if not exclusions:
            return False
        
        # Check specific exclusions
        specific_key = f"{icd10_code}_{encounter_type}"
        if specific_key in exclusions:
            return True
        
        # Check general exclusions
        general_exclusions = ['COSMETIC_SURGERY', 'EXPERIMENTAL_TREATMENTS']
        for exclusion in general_exclusions:
            if exclusion in exclusions:
                # Could implement logic to match diagnosis patterns
                pass
        
        return False
    
    def is_in_benefit_package(self, icd10_code: str, encounter_type: str) -> bool:
        
        
        # Service is in benefit package if there's a valid G-DRG mapping
        mapping = self.get_gdrg_for_diagnosis(icd10_code, encounter_type)
        return mapping is not None
    
    def get_medicine_info(self, medicine_code: str) -> Optional[Dict[str, Any]]:
        
        
        return self.get_mapping('medicine_formulary', medicine_code)
    
    def is_medicine_in_formulary(self, medicine_code: str, icd10_code: str) -> bool:
        
        
        medicine_info = self.get_medicine_info(medicine_code)
        if not medicine_info:
            return False
        
        # Check if ICD-10 is in medicine's indications
        indications = medicine_info.get('indications', [])
        return icd10_code in indications
    
    def is_chronic_condition(self, icd10_code: str) -> bool:
       
        
        chronic_conditions = self.loader.get_data('chronic_conditions')
        if not chronic_conditions:
            return False
        
        return icd10_code in chronic_conditions
    
    def get_episode_limits(self, episode_type: str) -> Optional[Dict[str, Any]]:
        
        episode_limits = self.loader.get_data('episode_limits')
        if not episode_limits:
            return None
        
        return episode_limits.get(episode_type)
    
    def get_chronic_visit_limits(self, icd10_code: str) -> Optional[int]:
        
        
        chronic_info = self.get_mapping('chronic_conditions', icd10_code)
        return chronic_info.get('max_visits_per_month') if chronic_info else None
    
    def get_required_documentation(self, icd10_code: str, encounter_type: str) -> List[str]:
       
        
        doc_key = f"{icd10_code}_{encounter_type}"
        doc_info = self.get_mapping('documentation_requirements', doc_key)
        
        if doc_info:
            return doc_info.get('required_documents', [])
        
        return []
    
    def get_eligible_facilities(self, icd10_code: str, encounter_type: str) -> List[str]:
        
        
        mapping = self.get_gdrg_for_diagnosis(icd10_code, encounter_type)
        if mapping:
            return mapping.get('eligible_facilities', [])
        
        return []
    
    def is_facility_eligible_for_gdrg(self, gdrg_code: str, facility_level: str) -> bool:
        
        
        facility_rules = self.get_mapping('facility_credentialing', gdrg_code)
        if not facility_rules:
            return False
        
        eligible_levels = facility_rules.get('eligible_facility_levels', [])
        return facility_level in eligible_levels
    
    def is_physiotherapy_eligible_condition(self, icd10_code: str) -> bool:
        
        
        physio_conditions = self.loader.get_data('physiotherapy_conditions')
        if not physio_conditions:
            return False
        
        # Check exact match or prefix match
        if icd10_code in physio_conditions:
            return True
        
        # Check prefix matches (e.g., S72 matches S72.1, S72.2, etc.)
        for condition_code in physio_conditions.keys():
            if icd10_code.startswith(condition_code):
                return True
        
        return False
    
    def get_physiotherapy_session_limit(self, icd10_code: str) -> Optional[int]:
       
        
        physio_conditions = self.loader.get_data('physiotherapy_conditions')
        if not physio_conditions:
            return None
        
        # Check exact match first
        if icd10_code in physio_conditions:
            return physio_conditions[icd10_code].get('max_sessions')
        
        # Check prefix matches
        for condition_code, details in physio_conditions.items():
            if icd10_code.startswith(condition_code):
                return details.get('max_sessions')
        
        return None
    
    def get_investigation_bundling_rules(self, gdrg_code: str) -> Dict[str, Any]:
        
        bundling_rules = self.loader.get_data('bundling_rules')
        if not bundling_rules:
            return {'bundle_type': 'UNBUNDLED', 'separately_billable_items': []}
        
        # Default to ALL_INCLUSIVE for most G-DRGs
        return bundling_rules.get('ALL_INCLUSIVE', {
            'bundle_type': 'ALL_INCLUSIVE',
            'separately_billable_items': ['CT_EMERGENCY', 'MRI_EMERGENCY']
        })
    
    def get_modifier_rules(self, modifier_type: str) -> Optional[Dict[str, Any]]:
        
        
        modifier_rules = self.loader.get_data('modifier_rules')
        if not modifier_rules:
            return None
        
        return modifier_rules.get(modifier_type)
    
    def get_reference_stats(self) -> Dict[str, Any]:
       
        
        if not self._is_loaded:
            return {'loaded': False, 'error': 'Reference data not loaded'}
        
        stats = self.loader.get_loader_stats()
        validation_report = self.loader.validate_data_integrity()
        
        return {
            'loaded': True,
            'loader_stats': stats,
            'validation_report': validation_report,
            'data_directory': self.data_dir
        }