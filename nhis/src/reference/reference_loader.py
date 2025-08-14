
import json
import os
from typing import Dict, Any, Optional, List
from pathlib import Path

from ..core import ReferenceDataError


class ReferenceLoader:
    
    
    def __init__(self, data_dir: str = "reference_data"):
        self.data_dir = Path(data_dir)
        self.loaded_files: Dict[str, Dict[str, Any]] = {}
        self.load_errors: List[str] = []
        
    def load_all_reference_files(self) -> bool:
       
        
       
        reference_files = [
            'icd10_gdrg_mapping.json',
            'medicine_formulary.json',
            'chronic_conditions.json', 
            'documentation_requirements.json',
            'episode_limits.json',
            'facility_credentialing.json',
            'physiotherapy_conditions.json',
            'exclusions.json',
            'bundling_rules.json',
            'modifier_rules.json'
        ]
        
        success_count = 0
        
        print(f"📂 Loading reference data from: {self.data_dir}")
        
        for filename in reference_files:
            try:
                if self.load_file(filename):
                    success_count += 1
                    print(f" Loaded {filename}")
                else:
                    print(f" Failed to load {filename}")
                    
            except Exception as e:
                error_msg = f"Error loading {filename}: {str(e)}"
                self.load_errors.append(error_msg)
                print(f" {error_msg}")
        
        total_files = len(reference_files)
        print(f" Loaded {success_count}/{total_files} reference files")
        
        return success_count == total_files
    
    def load_file(self, filename: str) -> bool:
       
        
        file_path = self.data_dir / filename
        
        if not file_path.exists():
            self.load_errors.append(f"File not found: {filename}")
            return False
        
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
           
            if not isinstance(data, dict):
                self.load_errors.append(f"Invalid format in {filename}: expected dictionary")
                return False
            
            
            file_key = filename.replace('.json', '')
            self.loaded_files[file_key] = data
            
            return True
            
        except json.JSONDecodeError as e:
            self.load_errors.append(f"JSON parsing error in {filename}: {str(e)}")
            return False
            
        except Exception as e:
            self.load_errors.append(f"Unexpected error loading {filename}: {str(e)}")
            return False
    
    def get_data(self, data_type: str) -> Optional[Dict[str, Any]]:
       
        
        return self.loaded_files.get(data_type)
    
    def is_loaded(self, data_type: str) -> bool:
       
        
        return data_type in self.loaded_files
    
    def get_loaded_files(self) -> List[str]:
       
        return list(self.loaded_files.keys())
    
    def get_load_errors(self) -> List[str]:
        
        return self.load_errors.copy()
    
    def reload_file(self, filename: str) -> bool:
       
        file_key = filename.replace('.json', '')
        if file_key in self.loaded_files:
            del self.loaded_files[file_key]
        
       
        self.load_errors = [
            error for error in self.load_errors 
            if filename not in error
        ]
        
        
        return self.load_file(filename)
    
    def validate_data_integrity(self) -> Dict[str, Any]:
        
        validation_report = {
            'valid': True,
            'issues': [],
            'statistics': {}
        }
        
        try:
            # Check ICD-10 → G-DRG mapping consistency
            icd10_mapping = self.get_data('icd10_gdrg_mapping')
            medicine_formulary = self.get_data('medicine_formulary')
            
            if icd10_mapping:
                # Count unique ICD-10 codes and G-DRGs
                icd10_codes = set()
                gdrg_codes = set()
                
                for mapping in icd10_mapping.values():
                    icd10_codes.add(mapping.get('icd10_code'))
                    gdrg_codes.add(mapping.get('gdrg_code'))
                
                validation_report['statistics']['unique_icd10_codes'] = len(icd10_codes)
                validation_report['statistics']['unique_gdrg_codes'] = len(gdrg_codes)
                validation_report['statistics']['total_mappings'] = len(icd10_mapping)
            
            if medicine_formulary:
                validation_report['statistics']['total_medicines'] = len(medicine_formulary)
                
                # Check for medicines without indications
                medicines_without_indications = [
                    code for code, data in medicine_formulary.items()
                    if not data.get('indications')
                ]
                
                if medicines_without_indications:
                    validation_report['issues'].append({
                        'type': 'missing_indications',
                        'count': len(medicines_without_indications),
                        'message': f"{len(medicines_without_indications)} medicines have no indications"
                    })
            
            # Check for cross-reference consistency
            chronic_conditions = self.get_data('chronic_conditions')
            if chronic_conditions and icd10_mapping:
                # Verify chronic conditions exist in ICD-10 mappings
                chronic_icd10s = set(chronic_conditions.keys())
                mapping_icd10s = set(mapping['icd10_code'] for mapping in icd10_mapping.values())
                
                missing_chronic = chronic_icd10s - mapping_icd10s
                if missing_chronic:
                    validation_report['issues'].append({
                        'type': 'missing_chronic_mappings',
                        'codes': list(missing_chronic),
                        'message': f"Chronic conditions without ICD-10 mappings: {missing_chronic}"
                    })
            
            if validation_report['issues']:
                validation_report['valid'] = False
            
        except Exception as e:
            validation_report['valid'] = False
            validation_report['issues'].append({
                'type': 'validation_error',
                'message': f"Validation failed: {str(e)}"
            })
        
        return validation_report
    
    def get_loader_stats(self) -> Dict[str, Any]:
        """Get statistics about the loaded reference data"""
        
        return {
            'data_directory': str(self.data_dir),
            'loaded_files_count': len(self.loaded_files),
            'loaded_files': list(self.loaded_files.keys()),
            'load_errors_count': len(self.load_errors),
            'load_errors': self.load_errors.copy()
        }