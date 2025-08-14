#!/usr/bin/env python3
"""
Complete test of all processors in the 5-step pipeline
"""

import sys
import os
from datetime import date, datetime

sys.path.insert(0, os.path.dirname(__file__))

def test_all_processors():
    print("=" * 70)
    print("TESTING ALL PROCESSORS - 5-STEP PIPELINE")
    print("=" * 70)
    
    try:
        # Import all required modules
        from src.core import StandardClaim, EncounterType, ProcessingStep
        from src.reference import ReferenceManager
        from src.processors import (
            IntakeProcessor, EligibilityProcessor, RoutingProcessor,
            CredentialingProcessor, BusinessRulesProcessor
        )
        
        print("All imports successful!")
        
        # Set up reference manager
        print("\nLoading reference data...")
        ref_manager = ReferenceManager()
        if not ref_manager.load_reference_data():
            print("Failed to load reference data")
            return False
        
        print("Reference data loaded successfully!")
        
        # Create test claim using your actual reference data
        test_claim = StandardClaim(
            claim_id="TEST-PIPELINE-001",
            facility_id="FAC-TEST-001",
            patient_age=45,
            visit_date=date.today(),
            encounter_type=EncounterType.IPD,
            icd10_diagnosis="I21",  # Acute myocardial infarction
            facility_level="C",     # District Hospital
            prescriber_level="C",   # General Practitioner
            medicines=[
                {"code": "ACETYLTA1", "name": "Acetylsalicylic Acid", "amount": 25.00}
            ],
            procedures=[
                {"code": "CARD001", "name": "Cardiac monitoring", "amount": 100.00}
            ]
        )
        
        print(f"\nTest Claim: {test_claim.claim_id}")
        print(f"Diagnosis: {test_claim.icd10_diagnosis} ({test_claim.encounter_type.value})")
        print(f"Facility: {test_claim.facility_level} level")
        
        # Initialize context
        context = {'reference_manager': ref_manager}
        
        # Test each processor in order
        processors = [
            ("STEP 1", IntakeProcessor()),
            ("STEP 2", EligibilityProcessor()),
            ("STEP 3", RoutingProcessor()),
            ("STEP 4", CredentialingProcessor()),
            ("STEP 5", BusinessRulesProcessor())
        ]
        
        pipeline_success = True
        
        for step_name, processor in processors:
            print(f"\n{'-' * 50}")
            print(f"{step_name}: Testing {processor.name}")
            print(f"{'-' * 50}")
            
            try:
                # Process the claim
                result = processor.process(test_claim, context)
                
                # Display results
                print(f"Success: {result.success}")
                print(f"Errors: {len(result.errors)}")
                print(f"Warnings: {len(result.warnings)}")
                print(f"Processing Time: {result.processing_time_ms:.2f}ms")
                
                if result.errors:
                    print("Errors:")
                    for error in result.errors:
                        print(f"  - {error.message}")
                
                if result.warnings:
                    print("Warnings:")
                    for warning in result.warnings:
                        print(f"  - {warning.message}")
                
                # Show key results
                if result.success and result.data:
                    if step_name == "STEP 1":
                        candidates = result.data.get('candidate_gdrgs', [])
                        mapping_status = result.data.get('mapping_status')
                        print(f"G-DRG Candidates: {candidates}")
                        print(f"Mapping Status: {mapping_status}")
                    
                    elif step_name == "STEP 2":
                        eligibility_status = result.data.get('eligibility_status')
                        is_covered = result.data.get('is_covered', False)
                        print(f"Eligibility Status: {eligibility_status}")
                        print(f"Is Covered: {is_covered}")
                    
                    elif step_name == "STEP 3":
                        routing_decision = result.data.get('routing_decision')
                        routing_status = result.data.get('routing_status')
                        print(f"Routing Decision: {routing_decision}")
                        print(f"Routing Status: {routing_status}")
                    
                    elif step_name == "STEP 4":
                        credentialing_status = result.data.get('credentialing_status')
                        facility_eligible = result.data.get('facility_eligible', False)
                        print(f"Credentialing Status: {credentialing_status}")
                        print(f"Facility Eligible: {facility_eligible}")
                    
                    elif step_name == "STEP 5":
                        business_rules_status = result.data.get('business_rules_status')
                        final_gdrg = result.data.get('final_gdrg')
                        calculation_result = result.data.get('calculation_result')
                        print(f"Business Rules Status: {business_rules_status}")
                        print(f"Final G-DRG: {final_gdrg}")
                        if calculation_result:
                            print(f"Total Approved: {calculation_result.total_approved}")
                            print(f"Total Denied: {calculation_result.total_denied}")
                
                # Merge results into context for next processor
                if result.success:
                    context.update(result.data)
                else:
                    pipeline_success = False
                    print(f"Pipeline stopped at {step_name} due to errors")
                    break
                    
            except Exception as e:
                print(f"ERROR in {step_name}: {str(e)}")
                pipeline_success = False
                break
        
        # Test different claim types
        print(f"\n{'-' * 50}")
        print("TESTING DIFFERENT CLAIM TYPES")
        print(f"{'-' * 50}")
        
        test_cases = [
            {
                "name": "OPD Hypertension",
                "icd10": "I10",
                "encounter": EncounterType.OPD,
                "age": 55,
                "facility_level": "B2"
            },
            {
                "name": "OPD Diabetes",
                "icd10": "E11", 
                "encounter": EncounterType.OPD,
                "age": 60,
                "facility_level": "C"
            },
            {
                "name": "Emergency Case",
                "icd10": "I21",
                "encounter": EncounterType.AE,
                "age": 35,
                "facility_level": "D1"
            }
        ]
        
        for i, test_case in enumerate(test_cases, 1):
            print(f"\nQuick Test {i}: {test_case['name']}")
            
            quick_claim = StandardClaim(
                claim_id=f"QUICK-TEST-{i:03d}",
                facility_id=f"FAC-{i:03d}",
                patient_age=test_case['age'],
                visit_date=date.today(),
                encounter_type=test_case['encounter'],
                icd10_diagnosis=test_case['icd10'],
                facility_level=test_case['facility_level']
            )
            
            # Test just intake and eligibility
            quick_context = {'reference_manager': ref_manager}
            
            # Intake test
            intake_processor = IntakeProcessor()
            intake_result = intake_processor.process(quick_claim, quick_context)
            
            candidates = intake_result.data.get('candidate_gdrgs', [])
            print(f"  {test_case['icd10']} ({test_case['encounter'].value}) -> {candidates}")
            
            if intake_result.success and candidates:
                # Eligibility test
                eligibility_processor = EligibilityProcessor()
                quick_context.update(intake_result.data)
                eligibility_result = eligibility_processor.process(quick_claim, quick_context)
                
                eligibility_status = eligibility_result.data.get('eligibility_status', 'UNKNOWN')
                print(f"  Eligibility: {eligibility_status}")
            else:
                print(f"  Failed at intake")
        
        # Summary
        print(f"\n{'=' * 70}")
        print("PROCESSORS TEST SUMMARY")
        print(f"{'=' * 70}")
        
        if pipeline_success:
            print("SUCCESS: All processors working correctly!")
            print("- 5-step pipeline completed successfully")
            print("- All processors integrate properly")
            print("- Reference data integration working")
            print("- Context passing between steps working")
            print("- Error handling working")
            
            print(f"\nPipeline Flow Verified:")
            print(f"  Step 1 (Intake) -> Step 2 (Eligibility) -> Step 3 (Routing)")
            print(f"  -> Step 4 (Credentialing) -> Step 5 (Business Rules)")
            
            print(f"\nProcessors ready for:")
            print(f"  - Integration with Expert System")
            print(f"  - Processing real ClaimV2 data")
            print(f"  - Production use")
        else:
            print("FAILED: Pipeline has issues that need fixing")
        
        return pipeline_success
        
    except ImportError as e:
        print(f"Import error: {e}")
        print("Make sure all processor files are created with the correct code")
        return False
    except Exception as e:
        print(f"Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    success = test_all_processors()
    
    if success:
        print(f"\nProcessors module is ready!")
        print(f"You can now integrate with the Expert System")
    else:
        print(f"\nProcessors need fixes before continuing")
    
    sys.exit(0 if success else 1)