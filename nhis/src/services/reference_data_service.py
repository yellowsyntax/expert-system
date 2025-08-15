from typing import Dict, Any, Optional, List
from datetime import datetime
from pathlib import Path
import json
import csv
import shutil
import logging

logger = logging.getLogger(__name__)


class ReferenceDataService:
    
    def __init__(self, reference_data_path: str = "reference_data"):
        self.reference_data_path = Path(reference_data_path)
        self.backup_path = Path(f"{reference_data_path}_backup")
        
        # Ensure directories exist
        self.reference_data_path.mkdir(exist_ok=True)
        self.backup_path.mkdir(exist_ok=True)
        
        self.reference_files = {
            'icd10_gdrg_mapping': 'icd10_gdrg_mapping.json',
            'medicine_formulary': 'medicine_formulary.json',
            'chronic_conditions': 'chronic_conditions.json',
            'documentation_requirements': 'documentation_requirements.json',
            'episode_limits': 'episode_limits.json',
            'facility_credentialing': 'facility_credentialing.json',
            'physiotherapy_conditions': 'physiotherapy_conditions.json',
            'exclusions': 'exclusions.json',
            'bundling_rules': 'bundling_rules.json',
            'modifier_rules': 'modifier_rules.json'
        }
    
    def get_reference_file_info(self, file_key: str) -> Optional[Dict[str, Any]]:
        try:
            if file_key not in self.reference_files:
                return None
            
            file_path = self.reference_data_path / self.reference_files[file_key]
            
            if not file_path.exists():
                return {
                    'file_key': file_key,
                    'filename': self.reference_files[file_key],
                    'exists': False,
                    'status': 'missing'
                }
            
            stat = file_path.stat()
            
            with open(file_path, 'r') as f:
                data = json.load(f)
            
            return {
                'file_key': file_key,
                'filename': self.reference_files[file_key],
                'exists': True,
                'file_size': stat.st_size,
                'last_modified': datetime.fromtimestamp(stat.st_mtime).isoformat(),
                'record_count': self._count_records(data),
                'version': data.get('version', '1.0'),
                'last_updated': data.get('last_updated'),
                'status': 'available'
            }
            
        except Exception as e:
            logger.error(f"Error getting reference file info for {file_key}: {str(e)}")
            return {
                'file_key': file_key,
                'filename': self.reference_files.get(file_key, 'unknown'),
                'exists': False,
                'status': 'error',
                'error': str(e)
            }
    
    def get_all_reference_files_info(self) -> Dict[str, Any]:
        files_info = {}
        total_size = 0
        available_count = 0
        
        for file_key in self.reference_files:
            file_info = self.get_reference_file_info(file_key)
            files_info[file_key] = file_info
            
            if file_info and file_info.get('exists'):
                available_count += 1
                total_size += file_info.get('file_size', 0)
        
        return {
            'files': files_info,
            'summary': {
                'total_files': len(self.reference_files),
                'available_files': available_count,
                'missing_files': len(self.reference_files) - available_count,
                'total_size_bytes': total_size,
                'last_check': datetime.utcnow().isoformat()
            }
        }
    
    def update_reference_file(self, file_key: str, data: Dict[str, Any], 
                             version: str = None, backup: bool = True) -> Dict[str, Any]:
        try:
            if file_key not in self.reference_files:
                return {
                    'status': 'error',
                    'message': f'Unknown reference file key: {file_key}',
                    'valid_keys': list(self.reference_files.keys())
                }
            
            file_path = self.reference_data_path / self.reference_files[file_key]
            
            # Create backup if requested and file exists
            if backup and file_path.exists():
                backup_result = self._create_backup(file_key)
                if backup_result['status'] != 'success':
                    return backup_result
            
            # Add metadata to data
            if not version:
                version = self._increment_version(file_path)
            
            data['version'] = version
            data['last_updated'] = datetime.utcnow().isoformat()
            data['updated_by'] = 'reference_data_service'
            
            # Validate data structure
            validation_result = self._validate_reference_data(file_key, data)
            if validation_result['status'] != 'valid':
                return {
                    'status': 'error',
                    'message': 'Data validation failed',
                    'validation_errors': validation_result['errors']
                }
            
            # Write file
            with open(file_path, 'w') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            
            return {
                'status': 'success',
                'file_key': file_key,
                'filename': self.reference_files[file_key],
                'version': version,
                'record_count': self._count_records(data),
                'file_size': file_path.stat().st_size,
                'backup_created': backup
            }
            
        except Exception as e:
            logger.error(f"Error updating reference file {file_key}: {str(e)}")
            return {
                'status': 'error',
                'message': str(e)
            }
    
    def load_reference_file(self, file_key: str) -> Optional[Dict[str, Any]]:
        try:
            if file_key not in self.reference_files:
                return None
            
            file_path = self.reference_data_path / self.reference_files[file_key]
            
            if not file_path.exists():
                return None
            
            with open(file_path, 'r') as f:
                return json.load(f)
                
        except Exception as e:
            logger.error(f"Error loading reference file {file_key}: {str(e)}")
            return None
    
    def import_from_csv(self, file_key: str, csv_file_path: str, 
                       mapping_config: Dict[str, Any]) -> Dict[str, Any]:
        try:
            if file_key not in self.reference_files:
                return {
                    'status': 'error',
                    'message': f'Unknown reference file key: {file_key}'
                }
            
            # Read CSV file
            with open(csv_file_path, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                csv_data = list(reader)
            
            if not csv_data:
                return {
                    'status': 'error',
                    'message': 'CSV file is empty or has no data rows'
                }
            
            # Transform CSV data using mapping config
            transformed_data = self._transform_csv_data(csv_data, mapping_config)
            
            # Update reference file
            result = self.update_reference_file(file_key, transformed_data)
            
            if result['status'] == 'success':
                result['import_summary'] = {
                    'csv_file': csv_file_path,
                    'csv_rows': len(csv_data),
                    'transformed_records': self._count_records(transformed_data)
                }
            
            return result
            
        except Exception as e:
            logger.error(f"Error importing CSV for {file_key}: {str(e)}")
            return {
                'status': 'error',
                'message': str(e)
            }
    
    def create_backup_all(self) -> Dict[str, Any]:
        results = {}
        success_count = 0
        
        for file_key in self.reference_files:
            result = self._create_backup(file_key)
            results[file_key] = result
            if result['status'] == 'success':
                success_count += 1
        
        return {
            'status': 'success' if success_count == len(self.reference_files) else 'partial',
            'backup_results': results,
            'successful_backups': success_count,
            'total_files': len(self.reference_files),
            'backup_timestamp': datetime.utcnow().isoformat()
        }
    
    def restore_from_backup(self, file_key: str, backup_timestamp: str = None) -> Dict[str, Any]:
        try:
            if file_key not in self.reference_files:
                return {
                    'status': 'error',
                    'message': f'Unknown reference file key: {file_key}'
                }
            
            # Find backup file
            if backup_timestamp:
                backup_filename = f"{file_key}_{backup_timestamp}.json"
            else:
                # Find most recent backup
                backup_files = list(self.backup_path.glob(f"{file_key}_*.json"))
                if not backup_files:
                    return {
                        'status': 'error',
                        'message': f'No backup files found for {file_key}'
                    }
                backup_files.sort(key=lambda x: x.stat().st_mtime, reverse=True)
                backup_filename = backup_files[0].name
            
            backup_file_path = self.backup_path / backup_filename
            
            if not backup_file_path.exists():
                return {
                    'status': 'error',
                    'message': f'Backup file not found: {backup_filename}'
                }
            
            # Copy backup to main reference data
            current_file_path = self.reference_data_path / self.reference_files[file_key]
            shutil.copy2(backup_file_path, current_file_path)
            
            return {
                'status': 'success',
                'file_key': file_key,
                'restored_from': backup_filename,
                'restore_timestamp': datetime.utcnow().isoformat()
            }
            
        except Exception as e:
            logger.error(f"Error restoring backup for {file_key}: {str(e)}")
            return {
                'status': 'error',
                'message': str(e)
            }
    
    def _create_backup(self, file_key: str) -> Dict[str, Any]:
        try:
            file_path = self.reference_data_path / self.reference_files[file_key]
            
            if not file_path.exists():
                return {
                    'status': 'skipped',
                    'message': f'File does not exist: {self.reference_files[file_key]}'
                }
            
            timestamp = datetime.utcnow().strftime('%Y%m%d_%H%M%S')
            backup_filename = f"{file_key}_{timestamp}.json"
            backup_file_path = self.backup_path / backup_filename
            
            shutil.copy2(file_path, backup_file_path)
            
            return {
                'status': 'success',
                'backup_filename': backup_filename,
                'backup_size': backup_file_path.stat().st_size
            }
            
        except Exception as e:
            logger.error(f"Error creating backup for {file_key}: {str(e)}")
            return {
                'status': 'error',
                'message': str(e)
            }
    
    def _increment_version(self, file_path: Path) -> str:
        try:
            if file_path.exists():
                with open(file_path, 'r') as f:
                    data = json.load(f)
                current_version = data.get('version', '1.0')
                
                # Parse version and increment
                version_parts = current_version.split('.')
                major, minor = int(version_parts[0]), int(version_parts[1])
                return f"{major}.{minor + 1}"
            else:
                return "1.0"
        except:
            return "1.0"
    
    def _validate_reference_data(self, file_key: str, data: Dict[str, Any]) -> Dict[str, Any]:
        errors = []
        
        # Basic validation - all files should have version and last_updated
        if 'version' not in data:
            errors.append('Missing version field')
        
        if 'last_updated' not in data:
            errors.append('Missing last_updated field')
        
        # File-specific validation
        if file_key == 'medicine_formulary':
            if 'medicines' not in data:
                errors.append('Missing medicines field')
            elif not isinstance(data['medicines'], dict):
                errors.append('medicines field must be a dictionary')
        
        elif file_key == 'icd10_gdrg_mapping':
            if 'mappings' not in data:
                errors.append('Missing mappings field')
        
        elif file_key == 'bundling_rules':
            required_fields = ['bundled_investigations', 'separately_billable', 'bundling_settings']
            for field in required_fields:
                if field not in data:
                    errors.append(f'Missing {field} field')
        
        return {
            'status': 'valid' if not errors else 'invalid',
            'errors': errors
        }
    
    def _count_records(self, data: Dict[str, Any]) -> int:
        # Count the main data records in the file
        for key in ['medicines', 'mappings', 'conditions', 'procedures', 'rules']:
            if key in data and isinstance(data[key], (dict, list)):
                return len(data[key])
        
        # Default: count top-level keys excluding metadata
        metadata_keys = {'version', 'last_updated', 'updated_by', 'description'}
        data_keys = {k for k in data.keys() if k not in metadata_keys}
        return len(data_keys)
    
    def _transform_csv_data(self, csv_data: List[Dict[str, Any]], 
                           mapping_config: Dict[str, Any]) -> Dict[str, Any]:
        # Transform CSV data based on mapping configuration
        # This is a basic implementation - can be extended for specific transformations
        
        transform_type = mapping_config.get('type', 'key_value')
        
        if transform_type == 'key_value':
            key_field = mapping_config.get('key_field', 'code')
            value_fields = mapping_config.get('value_fields', [])
            
            transformed = {}
            for row in csv_data:
                key = row.get(key_field)
                if key:
                    if len(value_fields) == 1:
                        transformed[key] = row.get(value_fields[0])
                    else:
                        transformed[key] = {field: row.get(field) for field in value_fields}
            
            return {mapping_config.get('output_key', 'data'): transformed}
        
        elif transform_type == 'list':
            return {mapping_config.get('output_key', 'data'): csv_data}
        
        else:
            return {'data': csv_data}