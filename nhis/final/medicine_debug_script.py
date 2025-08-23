#!/usr/bin/env python3
"""
Complete Pipeline Debug
This will run each stage individually to see where it actually fails
"""

import asyncio
import sys
import time
from master_orchestrator import EnhancedNHISOrchestrator

async def debug_complete_pipeline(encounter_id):
    """Debug each stage of the pipeline individually"""
    
    print(f"🔍 COMPLETE PIPELINE DEBUG")
    print(f"Encounter: {encounter_id}")
    print("=" * 60)
    
    try:
        # Initialize the orchestrator
        orchestrator = EnhancedNHISOrchestrator()
        await orchestrator.initialize()
        
        print(f"✅ Orchestrator initialized")
        
        # Create pipeline results structure
        pipeline_results = {
            "encounter_id": encounter_id,
            "stages_completed": [],
            "stages_passed": [],
            "stages_failed": [],
            "overall_result": None,
            "processing_path": [],
            "final_decision": None,
            "financial_components": {
                "gdrg_tariff": 0.0,
                "medicine_cost": 0.0,
                "investigation_cost": 0.0,
                "modifier_multiplier": 1.0
            },
            "stage_data": {},
            "enhanced_validations": {},
            "enhanced_medicine_validation": {}
        }
        
        print(f"\n🚀 TESTING EACH STAGE INDIVIDUALLY:")
        print("=" * 50)
        
        # STAGE 1: INITIAL PROCESSING
        print(f"\n1️⃣ STAGE 1: Initial Processing")
        print("-" * 30)
        
        try:
            stage_result = await orchestrator._stage1_initial_processing(encounter_id, pipeline_results)
            success = orchestrator._is_stage_successful(stage_result)
            print(f"   Result: {stage_result.overall_result.value}")
            print(f"   Success: {success}")
            print(f"   Reason: {stage_result.reason}")
            
            if not success:
                print(f"   ❌ PIPELINE FAILS AT STAGE 1")
                await orchestrator.close()
                return
            
            # Extract encounter type for next stages
            encounter_type = stage_result.details.get('encounter_type') if stage_result.details else None
            print(f"   Encounter Type: {encounter_type}")
            
        except Exception as e:
            print(f"   ❌ ERROR in Stage 1: {e}")
            await orchestrator.close()
            return
        
        # STAGE 2: ENHANCED VALIDATIONS
        print(f"\n2️⃣ STAGE 2: Enhanced Validations")
        print("-" * 30)
        
        try:
            stage_result = await orchestrator._stage2_enhanced_validations(encounter_id, pipeline_results)
            success = orchestrator._is_stage_successful(stage_result)
            print(f"   Result: {stage_result.overall_result.value}")
            print(f"   Success: {success}")
            print(f"   Reason: {stage_result.reason}")
            
            if not success:
                print(f"   ❌ PIPELINE FAILS AT STAGE 2")
                await orchestrator.close()
                return
                
        except Exception as e:
            print(f"   ❌ ERROR in Stage 2: {e}")
            await orchestrator.close()
            return
        
        # STAGE 3: ENCOUNTER FLOW
        print(f"\n3️⃣ STAGE 3: Encounter Flow ({encounter_type})")
        print("-" * 30)
        
        try:
            stage_result = await orchestrator._stage3_encounter_flow(encounter_id, encounter_type, pipeline_results)
            success = orchestrator._is_stage_successful(stage_result)
            print(f"   Result: {stage_result.overall_result.value}")
            print(f"   Success: {success}")
            print(f"   Reason: {stage_result.reason}")
            
            if not success:
                print(f"   ❌ PIPELINE FAILS AT STAGE 3")
                await orchestrator.close()
                return
                
        except Exception as e:
            print(f"   ❌ ERROR in Stage 3: {e}")
            await orchestrator.close()
            return
        
        # STAGE 4: CREDENTIALING
        print(f"\n4️⃣ STAGE 4: Credentialing")
        print("-" * 30)
        
        try:
            stage_result = await orchestrator._stage4_credentialing(encounter_id, pipeline_results)
            success = orchestrator._is_stage_successful(stage_result)
            print(f"   Result: {stage_result.overall_result.value}")
            print(f"   Success: {success}")
            print(f"   Reason: {stage_result.reason}")
            
            if not success:
                print(f"   ❌ PIPELINE FAILS AT STAGE 4")
                await orchestrator.close()
                return
                
        except Exception as e:
            print(f"   ❌ ERROR in Stage 4: {e}")
            await orchestrator.close()
            return
        
        # STAGE 5: G-DRG DETERMINATION
        print(f"\n5️⃣ STAGE 5: G-DRG Determination")
        print("-" * 30)
        
        try:
            stage_result = await orchestrator._stage5_gdrg_determination(encounter_id, pipeline_results)
            success = orchestrator._is_stage_successful(stage_result)
            print(f"   Result: {stage_result.overall_result.value}")
            print(f"   Success: {success}")
            print(f"   Reason: {stage_result.reason}")
            
            if not success:
                print(f"   ❌ PIPELINE FAILS AT STAGE 5")
                await orchestrator.close()
                return
                
        except Exception as e:
            print(f"   ❌ ERROR in Stage 5: {e}")
            await orchestrator.close()
            return
        
        # STAGE 6: MEDICINE VALIDATION
        print(f"\n6️⃣ STAGE 6: Medicine Validation")
        print("-" * 30)
        
        try:
            stage_result = await orchestrator._stage6_enhanced_medicine_validation(encounter_id, pipeline_results)
            success = orchestrator._is_stage_successful(stage_result)
            print(f"   Result: {stage_result.overall_result.value}")
            print(f"   Success: {success}")
            print(f"   Reason: {stage_result.reason}")
            
            if not success:
                print(f"   ❌ PIPELINE FAILS AT STAGE 6")
                await orchestrator.close()
                return
                
        except Exception as e:
            print(f"   ❌ ERROR in Stage 6: {e}")
            await orchestrator.close()
            return
        
        print(f"\n✅ ALL STAGES PASSED INDIVIDUALLY!")
        print(f"   This means the issue is in the complete pipeline flow")
        print(f"   or in the error handling/reporting logic")
        
        await orchestrator.close()
        
    except Exception as e:
        print(f"❌ CRITICAL ERROR: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    encounter_id = "LAP-8564-QEHY"
    
    if len(sys.argv) > 1:
        encounter_id = sys.argv[1]
    
    print("🧪 COMPLETE PIPELINE DEBUGGER")
    print("=" * 50)
    print(f"This will test each stage individually")
    print(f"to find where the actual failure occurs.")
    print()
    
    asyncio.run(debug_complete_pipeline(encounter_id))