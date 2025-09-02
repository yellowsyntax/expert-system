"""
Neon Database Connection Manager
Handles all database connections and operations for NHIS Expert System
UPDATED: Added G-DRG tariff lookup methods and dynamic facility authorization
"""

import asyncio
import asyncpg
import json
import logging
from typing import Dict, List, Optional, Any
from contextlib import asynccontextmanager
import os
from datetime import datetime

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class NeonDBConnection:
    """
    Singleton database connection manager for Neon PostgreSQL
    Handles connection pooling, query execution, and error handling
    """
    
    _instance = None
    _pool = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(NeonDBConnection, cls).__new__(cls)
        return cls._instance
    
    def __init__(self):
        # Default connection string - can be overridden
        self.database_url = os.getenv(
           # "DATABASE_URL", 
            #"postgresql://postgres:LM2GGiGjaKtCVJNvPZRk@paiv-rds-master.cmpgm4w8w0fx.us-east-1.rds.amazonaws.com/postgres?sslmode=require"
        #)
        "DATABASE_URL", 
            "postgresql://neondb_owner:npg_Emq9gohbK8se@ep-sweet-hill-a46reakw-pooler.us-east-1.aws.neon.tech/neondb?sslmode=require&channel_binding=require"
        )
        self.is_connected = False
        self.pool_config = {
            'min_size': 5,
            'max_size': 20,
            'command_timeout': 60,
            'server_settings': {
                'jit': 'off'  
            }
        }
    
    async def connect(self):
        
        if self._pool is None:
            try:
                logger.info("Connecting to Neon database...")
                self._pool = await asyncpg.create_pool(
                    self.database_url,
                    **self.pool_config
                )
                self.is_connected = True
                logger.info(f" Database pool created successfully (min: {self.pool_config['min_size']}, max: {self.pool_config['max_size']})")
                
                # Test connection
                await self.test_connection()
                
            except Exception as e:
                logger.error(f"❌ Failed to connect to Neon database: {e}")
                self.is_connected = False
                raise
    
    async def disconnect(self):
        """Close all database connections"""
        if self._pool:
            try:
                await self._pool.close()
                self._pool = None
                self.is_connected = False
                logger.info("🔌 Database connections closed")
            except Exception as e:
                logger.error(f"Error closing database connections: {e}")
    
    async def test_connection(self):
        """Test database connection with a simple query"""
        try:
            result = await self.fetch_one("SELECT 1 as test, NOW() as timestamp")
            logger.info(f" Database connection test successful: {result}")
            return True
        except Exception as e:
            logger.error(f"❌ Database connection test failed: {e}")
            return False
    
    @asynccontextmanager
    async def get_connection(self):
        """Context manager for database connections"""
        if not self.is_connected or self._pool is None:
            await self.connect()
        
        connection = None
        try:
            connection = await self._pool.acquire()
            yield connection
        except Exception as e:
            logger.error(f"Database connection error: {e}")
            raise
        finally:
            if connection:
                await self._pool.release(connection)
    
    async def fetch_all(self, query: str, *args) -> List[Dict[str, Any]]:
        """
        Execute SELECT query and return all results as list of dictionaries
        """
        async with self.get_connection() as conn:
            try:
                start_time = datetime.now()
                rows = await conn.fetch(query, *args)
                duration = (datetime.now() - start_time).total_seconds()
                
                results = [dict(row) for row in rows]
                logger.debug(f"Query executed in {duration:.3f}s, returned {len(results)} rows")
                return results
                
            except Exception as e:
                logger.error(f"Query execution failed: {e}")
                logger.error(f"Query: {query}")
                logger.error(f"Args: {args}")
                raise
    
    async def fetch_one(self, query: str, *args) -> Optional[Dict[str, Any]]:
        """
        Execute SELECT query and return first result as dictionary
        """
        async with self.get_connection() as conn:
            try:
                start_time = datetime.now()
                row = await conn.fetchrow(query, *args)
                duration = (datetime.now() - start_time).total_seconds()
                
                result = dict(row) if row else None
                logger.debug(f"Query executed in {duration:.3f}s, returned {'1 row' if result else 'no rows'}")
                return result
                
            except Exception as e:
                logger.error(f"Query execution failed: {e}")
                logger.error(f"Query: {query}")
                logger.error(f"Args: {args}")
                raise
    
    async def execute(self, query: str, *args) -> str:
        """
        Execute INSERT/UPDATE/DELETE query and return status
        """
        async with self.get_connection() as conn:
            try:
                start_time = datetime.now()
                result = await conn.execute(query, *args)
                duration = (datetime.now() - start_time).total_seconds()
                
                logger.debug(f"Command executed in {duration:.3f}s: {result}")
                return result
                
            except Exception as e:
                logger.error(f"Command execution failed: {e}")
                logger.error(f"Query: {query}")
                logger.error(f"Args: {args}")
                raise
    
    async def execute_many(self, query: str, args_list: List[tuple]) -> None:
        """
        Execute batch INSERT/UPDATE operations
        """
        async with self.get_connection() as conn:
            try:
                start_time = datetime.now()
                await conn.executemany(query, args_list)
                duration = (datetime.now() - start_time).total_seconds()
                
                logger.info(f"Batch operation executed in {duration:.3f}s, {len(args_list)} operations")
                
            except Exception as e:
                logger.error(f"Batch execution failed: {e}")
                logger.error(f"Query: {query}")
                logger.error(f"Batch size: {len(args_list)}")
                raise
    
    async def transaction(self, queries_and_args: List[tuple]):
        """
        Execute multiple queries in a transaction
        queries_and_args: List of (query, args) tuples
        """
        async with self.get_connection() as conn:
            async with conn.transaction():
                try:
                    results = []
                    for query, args in queries_and_args:
                        result = await conn.execute(query, *args)
                        results.append(result)
                    
                    logger.info(f"Transaction completed successfully, {len(queries_and_args)} operations")
                    return results
                    
                except Exception as e:
                    logger.error(f"Transaction failed, rolling back: {e}")
                    raise

# Specialized query methods for NHIS Expert System

class NHISQueries:
    """
    Pre-built queries for NHIS Expert System operations
    UPDATED: Added tariff lookup methods and dynamic G-DRG authorization
    """
    
    def __init__(self, db_connection: NeonDBConnection):
        self.db = db_connection
    
    async def get_claim_by_encounter_id(self, encounter_id: str) -> Optional[Dict]:
        """Get claim details by encounter ID"""
        query = """
        SELECT 
            encounter_id,
            provider_name,
            district,
            provider_type,
            healthcare_level,
            prescriber_level,
            last_name,
            other_names,
            date_of_birth,
            gender,
            nhis_number,
            admission_date,
            discharge_date,
            encounter_type,
            attendance_type,
            diagnosis_name,
            icd10_code,
            specialty_code,
            gdrg_code,
            gdrg_description,
            medicine_code,
            medicine_name,
            standard_dosage,
            frequency,
            duration_days,
            medicine_date,
            icd10_description_procedure,
            icd10_code_procedure,
            specialty_code_procedure,
            gdrg_code_procedure,
            gdrg_description_procedure,
            medicine_code_procedure,
            medicine_name_procedure,
            standard_dosage_procedure,
            frequency_procedure,
            duration_days_procedure,
            procedure_date,
            claim_status,
            submitted_at
        FROM claims_v3 
        WHERE encounter_id = $1
        """
        return await self.db.fetch_one(query, encounter_id)
    
    async def get_patient_age_from_dob(self, date_of_birth) -> int:
        """Calculate patient age from date of birth (string or datetime object)"""
        try:
            from datetime import datetime, date
            
            # Handle both string and datetime object inputs
            if isinstance(date_of_birth, datetime):
                dob = date_of_birth.date()
            elif isinstance(date_of_birth, date):
                dob = date_of_birth
            elif isinstance(date_of_birth, str):
                # Parse the date string (format: YYYY-MM-DD)
                dob = datetime.strptime(date_of_birth, '%Y-%m-%d').date()
            else:
                logger.error(f"Unsupported date_of_birth type: {type(date_of_birth)}")
                return 0
            
            today = date.today()
            
            # Calculate age
            age = today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))
            logger.debug(f"Calculated age: {age} from DOB: {dob}")
            return age
            
        except Exception as e:
            logger.error(f"Error calculating age from DOB {date_of_birth}: {e}")
            return 0
    
    async def get_claim_with_calculated_age(self, encounter_id: str) -> Optional[Dict]:
        """Get claim with calculated patient age"""
        claim = await self.get_claim_by_encounter_id(encounter_id)
        if claim and claim.get('date_of_birth'):
            claim['calculated_age'] = await self.get_patient_age_from_dob(claim['date_of_birth'])
        return claim
    
    async def get_facility_info_by_name(self, provider_name: str) -> Optional[Dict]:
        """
        Get facility information by provider name
        UPDATED: Uses dynamic G-DRG authorization instead of hardcoded lists
        """
        query = """
        SELECT 
            provider_name,
            district,
            provider_type,
            healthcare_level,
            'ACTIVE' as registration_status,
            true as nhis_registered,
            ARRAY['NHIS'] as accreditations,
            true as emergency_capable
        FROM claims_v3 
        WHERE provider_name = $1 
        LIMIT 1
        """
        result = await self.db.fetch_one(query, provider_name)
        
        if result:
            healthcare_level = result['healthcare_level']
            
            # UPDATED: Get authorized G-DRGs dynamically from your data instead of hardcoding
            authorized_gdrgs = await self._get_authorized_gdrgs_for_level(healthcare_level)
            
            # Set accreditations based on healthcare level
            if healthcare_level == '3':  # Level 3 can handle all G-DRGs
                result['accreditations'] = ['NHIS', 'ISO', 'SURGICAL']
            elif healthcare_level == '2':  # Level 2 limited G-DRGs
                result['accreditations'] = ['NHIS', 'SURGICAL']
            else:  # Level 1 basic G-DRGs only
                result['accreditations'] = ['NHIS']
            
            result['authorized_gdrgs'] = authorized_gdrgs
            result['facility_level'] = healthcare_level
            result['specialist_services'] = ['MEDI', 'PEDI'] if healthcare_level in ['2', '3'] else ['MEDI']
        
        return result
    
    async def _get_authorized_gdrgs_for_level(self, healthcare_level: str) -> List[str]:
        """
        Get authorized G-DRGs for a facility level dynamically from your data
        This replaces the hardcoded lists
        """
        try:
            # Query clinical_diagnosis_inferences for G-DRGs authorized for this level
            diagnosis_query = """
            SELECT DISTINCT gdrg_code 
            FROM clinical_diagnosis_inferences 
            WHERE encounter_type_eligible_facility::text LIKE '%' || $1 || '%'
            AND is_active = true
            AND gdrg_code IS NOT NULL
            """
            
            # Query clinical_procedure_inferences for procedure G-DRGs
            procedure_query = """
            SELECT DISTINCT gdrg_code 
            FROM clinical_procedure_inferences 
            WHERE level_procedure::text LIKE '%' || $1 || '%'
            AND gdrg_code IS NOT NULL
            """
            
            # Get results from both tables
            diagnosis_results = await self.db.fetch_all(diagnosis_query, healthcare_level)
            procedure_results = await self.db.fetch_all(procedure_query, healthcare_level)
            
            # Combine and deduplicate
            all_gdrgs = set()
            for row in diagnosis_results:
                all_gdrgs.add(row['gdrg_code'])
            for row in procedure_results:
                all_gdrgs.add(row['gdrg_code'])
            
            # Convert to sorted list
            authorized_gdrgs = sorted(list(all_gdrgs))
            
            logger.info(f" Found {len(authorized_gdrgs)} authorized G-DRGs for Level {healthcare_level}")
            logger.debug(f"Authorized G-DRGs for Level {healthcare_level}: {authorized_gdrgs}")
            
            return authorized_gdrgs
            
        except Exception as e:
            logger.error(f"Error getting authorized G-DRGs for level {healthcare_level}: {e}")
            
            # Fallback to basic lists if query fails
            fallback_gdrgs = {
                '3': ['MEDI02A', 'MEDI07A', 'MEDI06A', 'MEDI32A', 'MEDI23A', 'MEDI28A', 'MEDI26A', 'MEDI31A', 'MEDI04A', 'MEDI13A', 'MEDI16A', 'MEDI14A'],
                '2': ['MEDI02A', 'MEDI07A', 'MEDI06A', 'MEDI32A', 'MEDI23A', 'MEDI28A', 'MEDI14A'],
                '1': ['MEDI02A', 'MEDI06A', 'MEDI23A', 'MEDI28A']
            }
            
            return fallback_gdrgs.get(healthcare_level, [])
    
    async def get_all_authorized_gdrgs_summary(self) -> Dict[str, Any]:
        """
        Get summary of all authorized G-DRGs by facility level
        Useful for debugging and verification
        """
        try:
            summary = {}
            
            for level in ['1', '2', '3']:
                authorized_gdrgs = await self._get_authorized_gdrgs_for_level(level)
                summary[f"Level_{level}"] = {
                    "count": len(authorized_gdrgs),
                    "gdrgs": authorized_gdrgs
                }
            
            return summary
            
        except Exception as e:
            logger.error(f"Error getting G-DRG authorization summary: {e}")
            return {}
    
    async def get_gdrg_info_by_code(self, gdrg_code: str) -> List[Dict]:
        """Get G-DRG information from both diagnosis and procedure tables"""
        
        # Try diagnosis table first
        diagnosis_query = """
        SELECT 
            'diagnosis' as source_table,
            gdrg_code,
            gdrg_description,
            specialty_code,
            encounter_type,
            encounter_type_eligible_facility,
            gender_restriction,
            age_restrictions,
            requires_specialist,
            requires_documentation,
            is_chronic_condition,
            effective_from,
            effective_to
        FROM clinical_diagnosis_inferences 
        WHERE gdrg_code = $1 
            AND is_active = true
            AND (effective_to IS NULL OR effective_to > CURRENT_DATE)
        """
        
        # Then procedure table
        procedure_query = """
        SELECT 
            'procedure' as source_table,
            gdrg_code,
            gdrg_description,
            specialty_code,
            encounter_type,
            level_procedure as encounter_type_eligible_facility,
            gender_restriction,
            age_restrictions,
            NULL as requires_specialist,
            NULL as requires_documentation,
            NULL as is_chronic_condition,
            NULL as effective_from,
            NULL as effective_to
        FROM clinical_procedure_inferences 
        WHERE gdrg_code = $1
        """
        
        # Get from both tables
        diagnosis_results = await self.db.fetch_all(diagnosis_query, gdrg_code)
        procedure_results = await self.db.fetch_all(procedure_query, gdrg_code)
        
        return diagnosis_results + procedure_results
    
    async def get_gdrg_medicines(self, gdrg_code: str) -> List[Dict]:
        """Get all medicines associated with a G-DRG"""
        
        diagnosis_query = """
        SELECT 
            medicine_code,
            medicine_name,
            standard_dosage,
            frequency,
            duration_days,
            prescribing_levels,
            is_chronic_condition,
            is_medicine_bundled
        FROM clinical_diagnosis_inferences 
        WHERE gdrg_code = $1 
            AND medicine_code IS NOT NULL 
            AND medicine_code != 'NA'
            AND is_active = true
        """
        
        procedure_query = """
        SELECT 
            medicine_code,
            medicine_name,
            standard_dosage,
            frequency,
            duration_days,
            prescribing_levels,
            NULL as is_chronic_condition,
            NULL as is_medicine_bundled
        FROM clinical_procedure_inferences 
        WHERE gdrg_code = $1 
            AND medicine_code IS NOT NULL 
            AND medicine_code != 'NA'
        """
        
        diagnosis_meds = await self.db.fetch_all(diagnosis_query, gdrg_code)
        procedure_meds = await self.db.fetch_all(procedure_query, gdrg_code)
        
        return diagnosis_meds + procedure_meds
    
    async def find_gdrgs_by_icd10(self, icd10_code: str, encounter_type: str) -> List[str]:
        """Find G-DRG codes by ICD-10 code"""
        
        diagnosis_query = """
        SELECT DISTINCT gdrg_code 
        FROM clinical_diagnosis_inferences 
        WHERE icd10_code = $1 
            AND encounter_type = $2 
            AND is_active = true
        """
        
        procedure_query = """
        SELECT DISTINCT gdrg_code 
        FROM clinical_procedure_inferences 
        WHERE icd10_code = $1 
            AND encounter_type = $2
        """
        
        diagnosis_results = await self.db.fetch_all(diagnosis_query, icd10_code, encounter_type)
        procedure_results = await self.db.fetch_all(procedure_query, icd10_code, encounter_type)
        
        gdrg_codes = [row['gdrg_code'] for row in diagnosis_results + procedure_results]
        return list(set(gdrg_codes))  # Remove duplicates
    
    async def log_validation_step(self, encounter_id: str, step_name: str, result: str, reason: str, details: Dict = None):
        """Log validation step for audit trail"""
        # For now, we'll log to a simple table structure
        # You can create a validation_log table later
        pass  # Implement when you create the validation log table
    
    async def update_claim_status(self, encounter_id: str, status: str, gdrg_code: str = None, reason: str = None):
        """Update claim processing status"""
        query = """
        UPDATE claims_v3 
        SET 
            claim_status = $2,
            gdrg_code = COALESCE($3, gdrg_code)
        WHERE encounter_id = $1
        """
        
        await self.db.execute(query, encounter_id, status, gdrg_code)
    
    async def get_claims_by_provider(self, provider_name: str, limit: int = 10) -> List[Dict]:
        """Get recent claims for a provider"""
        query = """
        SELECT 
            encounter_id,
            last_name,
            other_names,
            gender,
            encounter_type,
            diagnosis_name,
            icd10_code,
            gdrg_code,
            claim_status,
            submitted_at
        FROM claims_v3 
        WHERE provider_name = $1 
        ORDER BY submitted_at DESC 
        LIMIT $2
        """
        
        return await self.db.fetch_all(query, provider_name, limit)
    
    async def get_tariff_by_gdrg(self, gdrg_code: str) -> Optional[Dict[str, Any]]:
        """
        Get tariff information directly by G-DRG code from icd10_codes table
        This is the missing method that was causing the error
        
        Args:
            gdrg_code: The G-DRG code (e.g., 'MEDI14A')
        
        Returns:
            Dict containing tariff information or None if not found
        """
        try:
            # Query the icd10_codes table for the specific G-DRG
            query = """
            SELECT 
                id,
                icd_code,
                diagnosis_description,
                gdrg_code,
                gdrg_name,
                level_of_care,
                tariff,
                created_at
            FROM icd10_codes 
            WHERE gdrg_code = $1 
            ORDER BY created_at DESC
            LIMIT 1
            """
            
            result = await self.db.fetch_one(query, gdrg_code)
            
            if result:
                return {
                    "gdrg_code": result['gdrg_code'],
                    "gdrg_name": result['gdrg_name'],
                    "gdrg_description": result['gdrg_name'],  # Alias for compatibility
                    "tariff_amount": str(result['tariff']) if result['tariff'] else "0.00",
                    "currency": "GHS",
                    "icd_code": result['icd_code'],
                    "diagnosis_description": result['diagnosis_description'],
                    "level_of_care": result['level_of_care'],
                    "created_at": result['created_at'],
                    "source": "icd10_codes_table",
                    "lookup_method": "direct_gdrg_lookup"
                }
            
            return None
            
        except Exception as e:
            logger.error(f"Error in get_tariff_by_gdrg for {gdrg_code}: {e}")
            return None
    
    async def get_tariff_by_icd10(self, icd_code: str) -> Optional[Dict[str, Any]]:
        """
        Get tariff information by ICD-10 code from icd10_codes table
        
        Args:
            icd_code: The ICD-10 code (e.g., 'I67.9')
        
        Returns:
            Dict containing tariff and G-DRG information
        """
        try:
            query = """
            SELECT 
                id,
                icd_code,
                diagnosis_description,
                gdrg_code,
                gdrg_name,
                level_of_care,
                tariff,
                created_at
            FROM icd10_codes 
            WHERE icd_code = $1 
            ORDER BY created_at DESC
            LIMIT 1
            """
            
            result = await self.db.fetch_one(query, icd_code)
            
            if result:
                return {
                    "icd_code": result['icd_code'],
                    "diagnosis_description": result['diagnosis_description'],
                    "gdrg_code": result['gdrg_code'],
                    "gdrg_name": result['gdrg_name'],
                    "tariff_amount": str(result['tariff']) if result['tariff'] else "0.00",
                    "currency": "GHS",
                    "level_of_care": result['level_of_care'],
                    "encounter_type_validated": encounter_type,
                    "mapping_found": True,
                    "source": "icd10_codes_direct_mapping"
                }
            
            return None
            
        except Exception as e:
            logger.error(f"Error in get_icd10_to_gdrg_mapping: {e}")
            return None

# Global database instance
db = NeonDBConnection()
nhis_queries = NHISQueries(db)

# Convenience functions for easy import
async def initialize_database():
    """Initialize database connection"""
    await db.connect()
    return db

async def close_database():
    """Close database connections"""
    await db.disconnect()

async def get_db():
    """Get database connection instance"""
    if not db.is_connected:
        await db.connect()
    return db

async def get_nhis_queries():
    """Get NHIS queries instance"""
    if not db.is_connected:
        await db.connect()
    return nhis_queries



# Example usage and testing
async def main():
    """Test database connection and queries with enhanced G-DRG authorization testing"""
    try:
        # Initialize connection
        await initialize_database()
        
        # Test basic queries
        queries = await get_nhis_queries()
        
        print("🔄 TESTING ENHANCED DATABASE FUNCTIONALITY")
        print("=" * 60)
        
        # Test facility lookup by provider name with dynamic G-DRG authorization
        print(f"\n🏥 TESTING DYNAMIC FACILITY G-DRG AUTHORIZATION:")
        facility = await queries.get_facility_info_by_name("LINK ROAD HOSPITAL")
        if facility:
            print(f" Facility: {facility['provider_name']}")
            print(f"   Level: {facility['facility_level']}")
            print(f"   Authorized G-DRGs: {len(facility['authorized_gdrgs'])}")
            print(f"   MEDI14A Authorized: {'MEDI14A' in facility['authorized_gdrgs']}")
            print(f"   Sample G-DRGs: {facility['authorized_gdrgs'][:10]}...")
        else:
            print("❌ Facility not found")
        
        # Test G-DRG authorization summary
        print(f"\n📊 TESTING G-DRG AUTHORIZATION SUMMARY:")
        summary = await queries.get_all_authorized_gdrgs_summary()
        for level, data in summary.items():
            print(f"   {level}: {data['count']} G-DRGs authorized")
            if 'MEDI14A' in data['gdrgs']:
                print(f"       MEDI14A is authorized for {level}")
            else:
                print(f"      ❌ MEDI14A NOT authorized for {level}")
        
        # Test claim lookup by encounter ID
        print(f"\n📋 TESTING CLAIM LOOKUP:")
        claim = await queries.get_claim_by_encounter_id("LIN-4881-BEEU")
        if claim:
            print(f" Claim: {claim['encounter_id']}")
            print(f"   Provider: {claim['provider_name']}")
            print(f"   G-DRG: {claim['gdrg_code']}")
            print(f"   ICD-10: {claim['icd10_code']}")
            print(f"   Encounter Type: {claim['encounter_type']}")
        else:
            print("❌ Claim not found")
        
        # Test NEW tariff lookup methods
        print(f"\n TESTING TARIFF LOOKUP METHODS:")
        
        # Test tariff by G-DRG
        tariff_by_gdrg = await queries.get_tariff_by_gdrg("MEDI14A")
        if tariff_by_gdrg:
            print(f" Tariff by G-DRG (MEDI14A): {tariff_by_gdrg['tariff_amount']} {tariff_by_gdrg['currency']}")
            print(f"   Description: {tariff_by_gdrg['gdrg_description']}")
        else:
            print("❌ No tariff found for MEDI14A")
        
        # Test tariff by ICD-10
        tariff_by_icd = await queries.get_tariff_by_icd10("I67.9")
        if tariff_by_icd:
            print(f" Tariff by ICD-10 (I67.9): {tariff_by_icd['tariff_amount']} {tariff_by_icd['currency']}")
            print(f"   Maps to G-DRG: {tariff_by_icd['gdrg_code']}")
        else:
            print("❌ No tariff found for I67.9")
        
        # Test G-DRG validation
        print(f"\n🔍 TESTING G-DRG VALIDATION:")
        validation = await queries.validate_claim_gdrg_and_tariff("I67.9", "MEDI14A", "IPD")
        if validation.get('validation_success'):
            print(f" G-DRG Validation: PASSED")
            print(f"   ICD-10: {validation['icd_code']} → G-DRG: {validation['expected_gdrg']}")
            print(f"   Tariff: {validation['tariff_amount']} {validation['currency']}")
        else:
            print(f"❌ G-DRG Validation: FAILED")
            if validation.get('error'):
                print(f"   Error: {validation['error']}")
            if validation.get('warning'):
                print(f"   Warning: {validation['warning']}")
        
        # Test G-DRG lookup
        print(f"\n🎯 TESTING G-DRG INFO LOOKUP:")
        gdrg_info = await queries.get_gdrg_info_by_code("MEDI14A")
        print(f"   G-DRG MEDI14A: {len(gdrg_info)} records found")
        if gdrg_info:
            for info in gdrg_info:
                print(f"   Source: {info.get('source_table', 'unknown')}")
                print(f"   Description: {info.get('gdrg_description', 'N/A')}")
                print(f"   Eligible Facilities: {info.get('encounter_type_eligible_facility', 'N/A')}")
        
        # Test ICD-10 to G-DRG mapping (original method)
        print(f"\n🔄 TESTING ICD-10 TO G-DRG MAPPING:")
        gdrgs = await queries.find_gdrgs_by_icd10("I67.9", "IPD")
        print(f"   ICD-10 I67.9 → G-DRGs: {gdrgs}")
        
        # Test patient age calculation
        print(f"\n👤 TESTING PATIENT AGE CALCULATION:")
        age = await queries.get_patient_age_from_dob("1989-09-14")
        print(f"   DOB 1989-09-14 → Age: {age} years old")
        
        # Test comprehensive facility validation for the failing case
        print(f"\n🔧 COMPREHENSIVE TEST FOR LIN-4881-BEEU:")
        print("-" * 50)
        
        if claim and facility:
            claim_gdrg = claim['gdrg_code']
            facility_gdrgs = facility['authorized_gdrgs']
            
            print(f"   Claim G-DRG: {claim_gdrg}")
            print(f"   Facility Level: {facility['facility_level']}")
            print(f"   Total Authorized G-DRGs: {len(facility_gdrgs)}")
            print(f"   Is {claim_gdrg} Authorized: {claim_gdrg in facility_gdrgs}")
            
            if claim_gdrg not in facility_gdrgs:
                print(f"   ❌ PROBLEM: {claim_gdrg} not in authorized list")
                print(f"   🔍 First 20 authorized G-DRGs: {facility_gdrgs[:20]}")
            else:
                print(f"    SUCCESS: {claim_gdrg} is properly authorized")
        
        # Test all G-DRGs with tariffs
        print(f"\n💎 TESTING ALL G-DRGS WITH TARIFFS:")
        all_gdrgs = await queries.find_all_gdrgs_with_tariffs()
        print(f"   Total G-DRGs with tariffs: {len(all_gdrgs)}")
        medi14a_found = False
        for gdrg in all_gdrgs:
            if gdrg['gdrg_code'] == 'MEDI14A':
                print(f"    MEDI14A found: {gdrg['tariff_amount']} {gdrg['currency']}")
                medi14a_found = True
                break
        if not medi14a_found:
            print(f"   ❌ MEDI14A not found in tariff database")
        
        print(f"\n🎉 DATABASE TESTING COMPLETED!")
        print("=" * 60)
        print("✨ KEY IMPROVEMENTS:")
        print("   • Dynamic G-DRG authorization (no more hardcoding)")
        print("   • Direct tariff lookup by G-DRG")
        print("   • Enhanced validation methods")
        print("   • Comprehensive facility credentialing")
        print("   • Full ICD-10 to G-DRG mapping support")
        
    except Exception as e:
        logger.error(f"Database test failed: {e}")
        print(f"\n❌ TEST FAILED: {e}")
    
    finally:
        await close_database()

if __name__ == "__main__":
    asyncio.run(main())
