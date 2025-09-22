import asyncio
import json
import logging
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass
from enum import Enum
from datetime import datetime, timedelta

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
    step: str = "IPD Flow"
    
    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.now()

class IPDFlowValidator:
    
    def __init__(self):
        self.queries = None
        self.is_initialized = False
    
    async def initialize(self):
        if not self.is_initialized:
            await initialize_database()
            self.queries = await get_nhis_queries()
            self.is_initialized = True
            logger.info("IPD Flow Validator initialized")
    
    async def close(self):
        await close_database()
        self.is_initialized = False
        logger.info("IPD Flow Validator closed")
    
    async def process_ipd_flow_validation(self, encounter_id: str) -> ValidationOutcome:
        if not self.is_initialized:
            await self.initialize()
        
        try:
            logger.info(f"IPD FLOW: Starting validation for {encounter_id}")
            
            claim_data = await self.queries.get_claim_with_calculated_age(encounter_id)
            if not claim_data:
                return ValidationOutcome(
                    result=ValidationResult.REJECTED,
                    reason="REJECT: Claim not found",
                    details={"encounter_id": encounter_id}
                )
            
            if claim_data.get('encounter_type') != 'IPD':
                return ValidationOutcome(
                    result=ValidationResult.REJECTED,
                    reason=f"REJECT: Not an IPD encounter - found {claim_data.get('encounter_type')}",
                    details={"encounter_id": encounter_id, "encounter_type": claim_data.get('encounter_type')}
                )
            
            discharge_date = claim_data.get('discharge_date')
            admission_date = claim_data.get('admission_date')
            
            if not discharge_date:
                return ValidationOutcome(
                    result=ValidationResult.REJECTED,
                    reason="REJECT: Missing discharge date",
                    details={
                        "encounter_id": encounter_id,
                        "requirement": "IPD encounters must have discharge date"
                    }
                )
            
            if isinstance(admission_date, str):
                admission_date = datetime.fromisoformat(admission_date.replace('Z', '+00:00'))
            if isinstance(discharge_date, str):
                discharge_date = datetime.fromisoformat(discharge_date.replace('Z', '+00:00'))
            
            if discharge_date < admission_date:
                return ValidationOutcome(
                    result=ValidationResult.REJECTED,
                    reason="REJECT: Discharge date before admission date",
                    details={"encounter_id": encounter_id}
                )
            
            length_of_stay = self._calculate_length_of_stay(claim_data)
            
            logger.info(f"IPD FLOW COMPLETED for {encounter_id}")
            
            return ValidationOutcome(
                result=ValidationResult.APPROVED,
                reason="IPD flow validation passed",
                details={
                    "encounter_id": encounter_id,
                    "encounter_type": "IPD",
                    "admission_date": admission_date,
                    "discharge_date": discharge_date,
                    "length_of_stay": length_of_stay
                }
            )
            
        except Exception as e:
            logger.error(f"Error in IPD flow validation: {e}")
            return ValidationOutcome(
                result=ValidationResult.PENDING,
                reason="PEND: System error during IPD flow validation",
                details={"error": str(e), "encounter_id": encounter_id}
            )
    
    def _calculate_length_of_stay(self, claim_data: Dict) -> int:
        try:
            admission_date = claim_data.get('admission_date')
            discharge_date = claim_data.get('discharge_date')
            
            if not admission_date or not discharge_date:
                return 0
            
            if isinstance(admission_date, str):
                admission_date = datetime.fromisoformat(admission_date.replace('Z', '+00:00'))
            if isinstance(discharge_date, str):
                discharge_date = datetime.fromisoformat(discharge_date.replace('Z', '+00:00'))
            
            los = (discharge_date - admission_date).days
            return max(los, 1)
            
        except Exception as e:
            logger.error(f"Error calculating length of stay: {e}")
            return 0
    
    async def validate_multiple_claims(self, encounter_ids: List[str]) -> Dict[str, ValidationOutcome]:
        results = {}
        
        for encounter_id in encounter_ids:
            try:
                result = await self.process_ipd_flow_validation(encounter_id)
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
        validator = IPDFlowValidator()
        
        try:
            await validator.initialize()
            
            test_encounter_id = "LIN-3012-BUYW"
            
            print(f"\nTesting IPD flow for: {test_encounter_id}")
            
            result = await validator.process_ipd_flow_validation(test_encounter_id)
            
            print(f"Result: {result.result.value}")
            print(f"Reason: {result.reason}")
            
        except Exception as e:
            logger.error(f"Test failed: {e}")
        
        finally:
            await validator.close()
    
    asyncio.run(main())