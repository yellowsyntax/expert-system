

import json
import csv
import os
from typing import Dict, List, Any, Optional
from pathlib import Path
import pandas as pd

from ..core import ReferenceDataError, ValidationError


class CSVProcessor:
    
    
    def __init__(self, output_dir: str = "reference_data"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(exist_ok=True)
        
        # Statistics tracking
        self.stats = {
            'total_records': 0,
            'processed_records': 0,
            'error_records': 0,
            'unique_icd10_codes': 0,
            'unique_gdrg_codes': 0,
            'unique_medicines': 0
        }
    
    def process_clinical_inference_csv(self, csv_file_path: str) -> Dict[str, Any]:
        """
        Main method to process the clinical inference CSV file.
        
        Args:
            csv_file_path: Path to the nhis_clinical_inference.csv file
            
        Returns:
            Processing statistics and results
        """
        
        print(f"🔄 Processing clinical inference CSV: {csv_file_path}")
        
        # Validate input file
        if not os.path.exists(csv_file_path):
            raise ReferenceDataError(f"CSV file not found: {csv_file_path}")
        
        # Read CSV file
        try:
            df = pd.read_csv(csv_file_path)
            self.stats['total_records'] = len(df)
            print(f"📊 Found {self.stats['total_records']} records in CSV")
            
        except Exception as e:
            raise ReferenceDataError(f"Failed to read CSV file: {str(e)}")
        
        # Create lookup structures
        lookup_data = {
            'icd10_gdrg_mapping': {},
            'medicine_formulary': {},
            'chronic_conditions': {},
            'documentation_requirements': {},
            'episode_limits': {},
            'facility_credentialing': {},
            'physiotherapy_conditions': {},
            'exclusions': {},
            'bundling_rules': {},
            'modifier_rules': {}
        }
        
        # Process each row
        for index, row in df.iterrows():
            try:
                self._process_row(row, lookup_data)
                self.stats['processed_records'] += 1
                
            except Exception as e:
                print(f"⚠️ Error processing row {index}: {str(e)}")
                self.stats['error_records'] += 1
                continue
        
        # Generate derived data
        self._generate_derived_data(lookup_data)
        
        # Save all lookup files
        saved_files = self._save_lookup_files(lookup_data)
        
        # Generate statistics
        self._calculate_final_stats(lookup_data)
        self._save_processing_stats()
        
        print(f"Processing complete!")
        print(f"Created {len(saved_files)} reference files")
        print(f"Processed: {self.stats['processed_records']}/{self.stats['total_records']} records")
        
        return {
            'stats': self.stats,
            'files_created': saved_files,
            'lookup_data': lookup_data
        }
    
    def _process_row(self, row: pd.Series, lookup_data: Dict[str, Dict]) -> None:
        """Process a single CSV row and extract data for all lookup structures"""
        
        # Parse JSON fields safely
        facility_levels = self._parse_json_field(row.get('eligible_facility_levels'))
        prescribing_levels = self._parse_json_field(row.get('prescribing_levels'))
        age_restrictions = self._parse_json_field(row.get('age_restrictions'))
        required_docs = self._parse_json_field(row.get('requires_documentation')) or []
        
        # 1. ICD-10 → G-DRG Mapping
        self._add_icd10_gdrg_mapping(row, facility_levels, age_restrictions, required_docs, lookup_data)
        
        # 2. Medicine Formulary
        self._add_medicine_formulary(row, prescribing_levels, age_restrictions, lookup_data)
        
        # 3. Chronic Conditions
        self._add_chronic_condition(row, lookup_data)
        
        # 4. Documentation Requirements
        self._add_documentation_requirements(row, required_docs, lookup_data)
        
        # 5. Facility Credentialing Rules
        self._add_facility_credentialing(row, facility_levels, lookup_data)
    
    def _add_icd10_gdrg_mapping(self, row: pd.Series, facility_levels: List[str], 
                               age_restrictions: Dict[str, Any], required_docs: List[str],
                               lookup_data: Dict[str, Dict]) -> None:
        """Add ICD-10 → G-DRG mapping entry"""
        
        icd10_code = row.get('icd10_code')
        encounter_type = row.get('encounter_type')
        gdrg_code = row.get('gdrg_code')
        
        if not all([icd10_code, encounter_type, gdrg_code]):
            return
        
        mapping_key = f"{icd10_code}_{encounter_type}"
        
        # Create or update mapping
        if mapping_key not in lookup_data['icd10_gdrg_mapping']:
            lookup_data['icd10_gdrg_mapping'][mapping_key] = {
                'icd10_code': icd10_code,
                'encounter_type': encounter_type,
                'gdrg_code': gdrg_code,
                'gdrg_description': row.get('gdrg_description'),
                'diagnosis_name': row.get('diagnosis_name'),
                'eligible_facilities': facility_levels or [],
                'is_chronic': row.get('is_chronic_condition', False),
                'max_visits_per_month': self._safe_int(row.get('max_visits_per_month')),
                'requires_specialist': row.get('requires_specialist', False),
                'age_restrictions': age_restrictions,
                'required_documents': required_docs
            }
    
    def _add_medicine_formulary(self, row: pd.Series, prescribing_levels: List[str],
                              age_restrictions: Dict[str, Any], lookup_data: Dict[str, Dict]) -> None:
        """Add medicine formulary entry"""
        
        medicine_code = row.get('medicine_code')
        if not medicine_code:
            return
        
        medicine_entry = {
            'code': medicine_code,
            'name': row.get('medicine_name'),
            'standard_dosage': row.get('standard_dosage'),
            'frequency': row.get('frequency'),
            'duration_days': self._safe_int(row.get('duration_days')),
            'prescribing_levels': prescribing_levels or [],
            'is_bundled': row.get('is_medicine_bundled', False),
            'separately_billable': row.get('separately_billable', False),
            'indications': [row.get('icd10_code')],  # Will merge duplicates later
            'age_restrictions': age_restrictions,
            'interaction_warnings': row.get('interaction_warnings')
        }
        
        if medicine_code in lookup_data['medicine_formulary']:
            # Merge indications for duplicate medicines
            existing = lookup_data['medicine_formulary'][medicine_code]
            if row.get('icd10_code') not in existing['indications']:
                existing['indications'].append(row.get('icd10_code'))
        else:
            lookup_data['medicine_formulary'][medicine_code] = medicine_entry
    
    def _add_chronic_condition(self, row: pd.Series, lookup_data: Dict[str, Dict]) -> None:
        """Add chronic condition entry"""
        
        if not row.get('is_chronic_condition', False):
            return
        
        icd10_code = row.get('icd10_code')
        if not icd10_code:
            return
        
        chronic_entry = {
            'icd10_code': icd10_code,
            'diagnosis_name': row.get('diagnosis_name'),
            'max_visits_per_month': self._safe_int(row.get('max_visits_per_month')),
            'encounter_types': [row.get('encounter_type')],
            'requires_specialist': row.get('requires_specialist', False)
        }
        
        if icd10_code in lookup_data['chronic_conditions']:
            # Merge encounter types
            existing = lookup_data['chronic_conditions'][icd10_code]
            encounter_type = row.get('encounter_type')
            if encounter_type not in existing['encounter_types']:
                existing['encounter_types'].append(encounter_type)
        else:
            lookup_data['chronic_conditions'][icd10_code] = chronic_entry
    
    def _add_documentation_requirements(self, row: pd.Series, required_docs: List[str],
                                      lookup_data: Dict[str, Dict]) -> None:
        """Add documentation requirements"""
        
        if not required_docs:
            return
        
        icd10_code = row.get('icd10_code')
        encounter_type = row.get('encounter_type')
        
        if not all([icd10_code, encounter_type]):
            return
        
        doc_key = f"{icd10_code}_{encounter_type}"
        
        lookup_data['documentation_requirements'][doc_key] = {
            'icd10_code': icd10_code,
            'encounter_type': encounter_type,
            'diagnosis_name': row.get('diagnosis_name'),
            'gdrg_code': row.get('gdrg_code'),
            'required_documents': required_docs
        }
    
    def _add_facility_credentialing(self, row: pd.Series, facility_levels: List[str],
                                  lookup_data: Dict[str, Dict]) -> None:
        """Add facility credentialing rules"""
        
        gdrg_code = row.get('gdrg_code')
        if not gdrg_code or not facility_levels:
            return
        
        if gdrg_code not in lookup_data['facility_credentialing']:
            lookup_data['facility_credentialing'][gdrg_code] = {
                'gdrg_code': gdrg_code,
                'gdrg_description': row.get('gdrg_description'),
                'eligible_facility_levels': facility_levels,
                'requires_specialist': row.get('requires_specialist', False)
            }
    
    def _generate_derived_data(self, lookup_data: Dict[str, Dict]) -> None:
        """Generate derived reference data not directly in CSV"""
        
        # Episode limits (based on chronic condition patterns)
        lookup_data['episode_limits'] = {
            'ACUTE': {'max_visits': 3, 'period_days': 14},
            'CHRONIC': {'max_visits': 6, 'period_days': 365}, 
            'ANTENATAL': {'max_visits': 6, 'period_days': 280},
            'POSTNATAL': {'max_visits': 3, 'period_days': 42}
        }
        
        # Physiotherapy conditions (based on common rehab conditions)
        lookup_data['physiotherapy_conditions'] = {
            'I67.9': {'condition': 'CVA (Stroke)', 'max_sessions': 12},
            'S72': {'condition': 'Fractures', 'max_sessions': 6},
            'G80': {'condition': 'Cerebral palsy', 'max_sessions': 12},
            'Z89': {'condition': 'Amputation', 'max_sessions': 12},
            'T20': {'condition': 'Burns', 'max_sessions': 6},
            'S06': {'condition': 'Head & spinal cord injury', 'max_sessions': 12}
        }
        
        # Investigation bundling rules
        lookup_data['bundling_rules'] = {
            'ALL_INCLUSIVE': {
                'description': 'All investigations included in G-DRG',
                'separately_billable_items': ['CT_EMERGENCY', 'MRI_EMERGENCY']
            },
            'UNBUNDLED': {
                'description': 'All investigations billable separately',
                'separately_billable_items': []
            }
        }
        
        # Modifier rules
        lookup_data['modifier_rules'] = {
            'BILATERAL_SURGERY': {'percentage': 120, 'description': '120% for bilateral procedures'},
            'DENTAL_MULTI_TOOTH': {'base_percentage': 100, 'additional_percentage': 20},
            'MULTIPLE_PROCEDURES': {'percentages': [100, 20, 20, 0]},
            'EMERGENCY_MODIFIER': {'percentage': 110, 'conditions': ['A&E_AFTER_HOURS']}
        }
        
        # Exclusions (placeholder - would be populated from separate source)
        lookup_data['exclusions'] = {
            'COSMETIC_SURGERY': {'reason': 'Cosmetic procedures not covered'},
            'EXPERIMENTAL_TREATMENTS': {'reason': 'Experimental treatments excluded'}
        }
    
    def _save_lookup_files(self, lookup_data: Dict[str, Dict]) -> List[str]:
        """Save all lookup data as JSON files"""
        
        saved_files = []
        
        for data_type, data in lookup_data.items():
            filename = f"{data_type}.json"
            file_path = self.output_dir / filename
            
            try:
                with open(file_path, 'w', encoding='utf-8') as f:
                    json.dump(data, f, indent=2, ensure_ascii=False, default=str)
                
                print(f" Saved {len(data)} entries to {filename}")
                saved_files.append(str(file_path))
                
            except Exception as e:
                print(f" Failed to save {filename}: {str(e)}")
        
        return saved_files
    
    def _calculate_final_stats(self, lookup_data: Dict[str, Dict]) -> None:
        """Calculate final processing statistics"""
        
        self.stats['unique_icd10_codes'] = len(set(
            mapping['icd10_code'] for mapping in lookup_data['icd10_gdrg_mapping'].values()
        ))
        
        self.stats['unique_gdrg_codes'] = len(set(
            mapping['gdrg_code'] for mapping in lookup_data['icd10_gdrg_mapping'].values()
        ))
        
        self.stats['unique_medicines'] = len(lookup_data['medicine_formulary'])
    
    def _save_processing_stats(self) -> None:
        """Save processing statistics"""
        
        stats_file = self.output_dir / 'processing_stats.json'
        
        try:
            with open(stats_file, 'w') as f:
                json.dump(self.stats, f, indent=2)
            print(f"📊 Saved processing statistics to {stats_file}")
            
        except Exception as e:
            print(f"⚠️ Failed to save statistics: {str(e)}")
    
    def _parse_json_field(self, field_value: Any) -> Any:
        """Safely parse JSON string fields"""
        
        if pd.isna(field_value) or field_value is None:
            return None
        
        field_str = str(field_value).strip()
        
        if not field_str or field_str.lower() in ['null', 'nan', '']:
            return None
        
        try:
            # Handle escaped JSON strings
            if field_str.startswith('[') or field_str.startswith('{'):
                # Remove extra escaping
                cleaned = field_str.replace('\\"', '"')
                return json.loads(cleaned)
            return None
            
        except json.JSONDecodeError:
            # If not valid JSON, return as string
            return field_str if field_str not in ['null', 'nan'] else None
    
    def _safe_int(self, value: Any) -> Optional[int]:
        """Safely convert value to integer"""
        
        if pd.isna(value) or value is None:
            return None
        
        try:
            if isinstance(value, str) and value.lower() in ['null', 'nan', '']:
                return None
            return int(float(value))
            
        except (ValueError, TypeError):
            return None


# Utility function for easy usage
def process_clinical_inference_csv(csv_file_path: str, output_dir: str = "reference_data") -> Dict[str, Any]:
    """
    Convenience function to process the clinical inference CSV.
    
    Args:
        csv_file_path: Path to the nhis_clinical_inference.csv file
        output_dir: Output directory for JSON files
        
    Returns:
        Processing results and statistics
    """
    
    processor = CSVProcessor(output_dir)
    return processor.process_clinical_inference_csv(csv_file_path)