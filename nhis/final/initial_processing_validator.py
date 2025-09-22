import asyncio
import json
import logging
from typing import Dict, List, Optional, Any
from dataclasses import dataclass
from enum import Enum
from datetime import datetime

from neon_db_connection import get_nhis_queries, initialize_database, close_database

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class ValidationResult(Enum):
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    FLAGGED = "FLAGGED"
    PENDING = "PENDING"

@dataclass
class ValidationOutcome:
    result: ValidationResult
    reason: str
    details: Dict[str, Any] = None
    timestamp: datetime = None
    step: str = "Initial Processing"
    
    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.now()

class InitialProcessingValidator:
    
    def __init__(self):
        self.queries = None
        self.is_initialized = False
    
    async def initialize(self):
        if not self.is_initialized:
            await initialize_database()
            self.queries = await get_nhis_queries()
            self.is_initialized = True
            logger.info("Initial Processing Validator initialized")
    
    async def close(self):
        await close_database()
        self.is_initialized = False
        logger.info("Initial Processing Validator closed")
    
    async def process_initial_validation(self, encounter_id: str) -> ValidationOutcome:
        if not self.is_initialized:
            await self.initialize()
        
        try:
            logger.info(f"Starting initial validation for {encounter_id}")
            
            query = """
            SELECT 
                encounter_id, encounter_type, specialty_code, provider_name,
                diagnosis_name, gdrg_code, last_name, other_names,
                date_of_birth, gender, icd10_code,
                EXTRACT(YEARS FROM AGE(CURRENT_DATE, date_of_birth::date)) as calculated_age
            FROM claims_v3 
            WHERE encounter_id = $1
            """
            
            claim = await self.queries.db.fetch_one(query, encounter_id)
            
            if not claim:
                return ValidationOutcome(
                    result=ValidationResult.REJECTED,
                    reason="REJECT: Claim not found",
                    details={"encounter_id": encounter_id}
                )
            
            encounter_type = claim.get('encounter_type')
            
            if encounter_type not in ['IPD', 'OPD', 'A&E']:
                return ValidationOutcome(
                    result=ValidationResult.REJECTED,
                    reason=f"REJECT: Invalid encounter type: {encounter_type}",
                    details={"encounter_id": encounter_id, "encounter_type": encounter_type}
                )
            
            required_fields = ['encounter_id', 'encounter_type', 'gdrg_code', 'icd10_code']
            missing_fields = [f for f in required_fields if not claim.get(f)]
            
            if missing_fields:
                return ValidationOutcome(
                    result=ValidationResult.REJECTED,
                    reason="REJECT: Missing required fields",
                    details={"missing_fields": missing_fields}
                )
            
            logger.info(f"Initial validation passed for {encounter_id}")
            
            return ValidationOutcome(
                result=ValidationResult.APPROVED,
                reason="Initial validation completed",
                details={
                    "encounter_id": encounter_id,
                    "encounter_type": encounter_type,
                    "gdrg_code": claim.get('gdrg_code'),
                    "routing_decision": {
                        "flow_type": encounter_type,
                        "encounter_type": encounter_type
                    }
                }
            )
            
        except Exception as e:
            logger.error(f"Error in initial processing: {e}")
            return ValidationOutcome(
                result=ValidationResult.PENDING,
                reason="PEND: System error during initial processing",
                details={"error": str(e), "encounter_id": encounter_id}
            )
    
    async def validate_multiple_claims(self, encounter_ids: List[str]) -> Dict[str, ValidationOutcome]:
        results = {}
        
        for encounter_id in encounter_ids:
            try:
                result = await self.process_initial_validation(encounter_id)
                results[encounter_id] = result
                logger.info(f"{encounter_id}: {result.reason}")
            except Exception as e:
                logger.error(f"Error validating {encounter_id}: {e}")
                results[encounter_id] = ValidationOutcome(
                    result=ValidationResult.PENDING,
                    reason=f"PEND: Validation error - {str(e)}",
                    details={"encounter_id": encounter_id}
                )
        
        return results


if __name__ == "__main__":
    async def main():
        validator = InitialProcessingValidator()
        
        try:
            await validator.initialize()
            
            test_encounter_id = "LIN-0992-RKLN"
            
            print(f"\nTesting initial processing for: {test_encounter_id}")
            
            result = await validator.process_initial_validation(test_encounter_id)
            
            print(f"Result: {result.result.value}")
            print(f"Reason: {result.reason}")
            
        except Exception as e:
            logger.error(f"Test failed: {e}")
        
        finally:
            await validator.close()
    
    asyncio.run(main())