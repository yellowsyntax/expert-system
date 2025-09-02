"""
DIAGNOSTIC VERSION - NHIS Master Orchestrator
This version adds detailed debugging to identify the exact issue with stage result checking
"""

import asyncio
import json
import logging
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass
from enum import Enum
from datetime import datetime
import time

# Import all validator modules
from neon_db_connection import get_nhis_queries, initialize_database, close_database
from initial_processing_validator import InitialProcessingValidator

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class ValidationResult(Enum):
    """Validation outcomes"""
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    FLAGGED = "FLAGGED"
    PENDING = "PENDING"
    PARTIAL = "PARTIAL"

class ProcessingStage(Enum):
    """Processing stages in the pipeline"""
    INITIAL_PROCESSING = "INITIAL_PROCESSING"
    ENCOUNTER_FLOW = "ENCOUNTER_FLOW"
    CREDENTIALING = "CREDENTIALING"
    GDRG_DETERMINATION = "GDRG_DETERMINATION"
    MEDICINE_VALIDATION = "MEDICINE_VALIDATION"
    FINAL_PROCESSING = "FINAL_PROCESSING"
    COMPLETED = "COMPLETED"

@dataclass
class ProcessingOutcome:
    """Complete processing result"""
    encounter_id: str
    overall_result: ValidationResult
    processing_stage: ProcessingStage
    reason: str
    details: Dict[str, Any] = None
    timestamp: datetime = None
    processing_time_seconds: float = 0.0
    
    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.now()

class DiagnosticOrchestrator:
    """
    Diagnostic Master Orchestrator - focuses on identifying the stage 1 issue
    """
    
    def __init__(self):
        self.queries = None
        self.is_initialized = False
        self.initial_processor = InitialProcessingValidator()
    
    async def initialize(self):
        """Initialize validator and database connections"""
        if not self.is_initialized:
            await initialize_database()
            self.queries = await get_nhis_queries()
            await self.initial_processor.initialize()
            self.is_initialized = True
            logger.info("🔬 Diagnostic Orchestrator initialized")
    
    async def close(self):
        """Close connections"""
        await self.initial_processor.close()
        await close_database()
        self.is_initialized = False
        logger.info("🔌 Diagnostic Orchestrator closed")
    
    async def diagnose_stage1_issue(self, encounter_id: str):
        """
        Detailed diagnosis of Stage 1 processing issue
        """
        if not self.is_initialized:
            await self.initialize()
        
        print(f"\n🔬 DIAGNOSTIC MODE: Analyzing Stage 1 for {encounter_id}")
        print("=" * 70)
        
        try:
            # Call the initial processor directly
            print(f"\n📋 Step 1: Calling initial_processor.process_initial_validation()")
            result = await self.initial_processor.process_initial_validation(encounter_id)
            
            # Detailed result analysis
            print(f"\n🔍 DETAILED RESULT ANALYSIS:")
            print(f"  Result Object Type: {type(result)}")
            print(f"  Result Object: {result}")
            
            if hasattr(result, 'result'):
                print(f"\n📊 RESULT ATTRIBUTES:")
                print(f"  result.result: {result.result}")
                print(f"  result.result type: {type(result.result)}")
                print(f"  result.result value: {result.result.value if hasattr(result.result, 'value') else 'No value attr'}")
                print(f"  result.reason: {result.reason}")
                print(f"  result.step: {result.step}")
                
                # Check if it's a ValidationResult enum
                print(f"\n🎯 VALIDATION RESULT CHECK:")
                print(f"  Is ValidationResult.APPROVED? {result.result == ValidationResult.APPROVED}")
                print(f"  ValidationResult.APPROVED: {ValidationResult.APPROVED}")
                print(f"  ValidationResult.APPROVED.value: {ValidationResult.APPROVED.value}")
                
                # Check details
                if result.details:
                    print(f"\n📄 RESULT DETAILS:")
                    for key, value in result.details.items():
                        if key == 'routing_decision' and isinstance(value, dict):
                            print(f"  {key}:")
                            for sub_key, sub_value in value.items():
                                print(f"    {sub_key}: {sub_value}")
                        else:
                            print(f"  {key}: {value}")
                
                # Test the success check
                print(f"\n SUCCESS CHECK TESTS:")
                success_states = [ValidationResult.APPROVED, ValidationResult.FLAGGED, ValidationResult.PARTIAL]
                is_successful = result.result in success_states
                print(f"  result.result in success_states: {is_successful}")
                print(f"  success_states: {[s.value for s in success_states]}")
                
                # Test encounter type extraction
                encounter_type = None
                routing_decision = None
                if result.details:
                    encounter_type = result.details.get('encounter_type')
                    routing_decision = result.details.get('routing_decision')
                
                print(f"\n🚏 ROUTING INFORMATION:")
                print(f"  encounter_type: {encounter_type}")
                print(f"  routing_decision: {routing_decision}")
                
                if routing_decision:
                    flow_type = routing_decision.get('flow_type') if isinstance(routing_decision, dict) else None
                    print(f"  flow_type: {flow_type}")
                
                # Now test the orchestrator logic
                print(f"\n🧪 TESTING ORCHESTRATOR LOGIC:")
                
                if result.result == ValidationResult.APPROVED:
                    print(f"   Stage 1 should PASS - result is APPROVED")
                    
                    if encounter_type:
                        print(f"   Encounter type found: {encounter_type}")
                        print(f"   Should proceed to Stage 2: {encounter_type} Flow")
                    else:
                        print(f"   Missing encounter_type - this would cause failure")
                        
                else:
                    print(f"   Stage 1 should FAIL - result is {result.result.value}")
            else:
                print(f"   Result object has no 'result' attribute")
                print(f"  Available attributes: {dir(result)}")
            
        except Exception as e:
            print(f"\n DIAGNOSTIC ERROR: {e}")
            import traceback
            traceback.print_exc()

async def main():
    """
    Run diagnostic analysis
    """
    diagnostics = DiagnosticOrchestrator()
    
    try:
        await diagnostics.initialize()
        
        # Test the problematic encounter
        test_encounter_id = "LIN-3012-BUYW"
        await diagnostics.diagnose_stage1_issue(test_encounter_id)
        
        print(f"\n🔬 DIAGNOSTIC COMPLETE")
        print(f"\n💡 NEXT STEPS:")
        print(f"  1. Review the detailed result analysis above")
        print(f"  2. Check if the result.result comparison is working correctly")
        print(f"  3. Verify encounter_type extraction from result.details")
        print(f"  4. Ensure enum comparisons are working properly")
        
    except Exception as e:
        logger.error(f"Diagnostic failed: {e}")
    
    finally:
        await diagnostics.close()

if __name__ == "__main__":
    asyncio.run(main())