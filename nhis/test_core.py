"""
Quick test to verify the core module is working properly.
Run this file to check if all core components can be imported and instantiated.
"""

import sys
from datetime import date, datetime
from decimal import Decimal

def test_core_imports():
    """Test that all core components can be imported"""
    print("Testing core module imports...")
    
    try:
        # Test imports from core module
        from src.core import (
            # Models
            StandardClaim, ClaimDecision, ValidationIssue, ProcessorResult,
            RuleResult, CalculationResult, LineItem,
            
            # Enums
            ClaimStatus, ValidationSeverity, EncounterType, ProcessingStep,
            EpisodeType, DecisionReason, LineItemType,
            
            # Exceptions
            ClaimProcessingError, ValidationError, ReferenceDataError,
            
            # Main classes
            NHISExpertSystem, ClaimV2Adapter
        )
        print("✅ All core imports successful!")
        return True
        
    except ImportError as e:
        print(f"❌ Import failed: {e}")
        return False


def test_enum_usage():
    """Test that enums work correctly"""
    print("\nTesting enum usage...")
    
    try:
        from src.core import ClaimStatus, EncounterType, ValidationSeverity
        
        # Test enum values
        assert ClaimStatus.APPROVED.value == "APPROVED"
        assert EncounterType.OPD.value == "OPD"
        assert ValidationSeverity.CRITICAL.value == "CRITICAL"
        
        print("✅ Enums working correctly!")
        return True
        
    except Exception as e:
        print(f"❌ Enum test failed: {e}")
        return False


def test_model_creation():
    """Test that models can be created and used"""
    print("\nTesting model creation...")
    
    try:
        from src.core import (
            StandardClaim, ClaimDecision, ValidationIssue, CalculationResult,
            ClaimStatus, EncounterType, ValidationSeverity, DecisionReason
        )
        
        # Create a test StandardClaim
        claim = StandardClaim(
            claim_id="test-123",
            facility_id="facility-456",
            patient_age=35,
            visit_date=date.today(),
            encounter_type=EncounterType.OPD,
            icd10_diagnosis="I10"
        )
        
        # Test claim methods
        age_suffix = claim.get_age_suffix()
        assert age_suffix in ['A', 'C']
        
        # Create a test validation issue
        issue = ValidationIssue(
            severity=ValidationSeverity.MINOR,
            code="TEST_ISSUE",
            message="This is a test issue"
        )
        
        # Create a test calculation result
        calc_result = CalculationResult(
            total_approved=Decimal('100.00'),
            total_denied=Decimal('0.00')
        )
        
        # Create a test claim decision
        decision = ClaimDecision(
            claim_id="test-123",
            status=ClaimStatus.APPROVED,
            decision_reason=DecisionReason.ALL_VALIDATIONS_PASSED,
            decision_rationale="Test decision",
            calculation_result=calc_result
        )
        
        # Test decision methods
        assert decision.is_approved() == True
        assert decision.is_rejected() == False
        
        print("✅ Model creation and usage working!")
        return True
        
    except Exception as e:
        print(f"❌ Model test failed: {e}")
        return False


def test_exception_handling():
    """Test that exceptions work correctly"""
    print("\nTesting exception handling...")
    
    try:
        from src.core import ClaimProcessingError, ValidationError
        
        # Test creating exceptions
        processing_error = ClaimProcessingError(
            "Test processing error",
            claim_id="test-123",
            processing_step="test_step"
        )
        
        validation_error = ValidationError(
            "Test validation error",
            field_name="test_field",
            validation_rule="test_rule"
        )
        
        # Test exception attributes
        assert processing_error.claim_id == "test-123"
        assert validation_error.field_name == "test_field"
        
        # Test exception serialization
        error_dict = processing_error.to_dict()
        assert "error_type" in error_dict
        assert "message" in error_dict
        
        print("✅ Exception handling working!")
        return True
        
    except Exception as e:
        print(f"❌ Exception test failed: {e}")
        return False


def test_claim_adapter():
    """Test the ClaimV2Adapter functionality"""
    print("\nTesting ClaimV2Adapter...")
    
    try:
        from src.core import ClaimV2Adapter
        
        # Create adapter instance
        adapter = ClaimV2Adapter()
        
        # Test adapter info
        info = adapter.get_adapter_info()
        assert "name" in info
        assert "supported_input_type" in info
        
        # Test utility functions
        from src.core.claim_adapter import validate_claim_v2_completeness
        
        # Create a mock ClaimV2 record for testing
        class MockClaimV2:
            def __init__(self):
                self.id = "test-123"
                self.provider_id = "provider-456"
                self.icd10_diagnosis = "I10"
                self.date_of_birth = date(1990, 1, 1)
                self.service_type_1 = "OPD"
                self.service_type_2 = None
        
        mock_claim = MockClaimV2()
        
        # Test completeness validation
        issues = validate_claim_v2_completeness(mock_claim)
        # Should have some issues since mock is incomplete
        
        print("✅ ClaimV2Adapter basic functionality working!")
        return True
        
    except Exception as e:
        print(f"❌ ClaimV2Adapter test failed: {e}")
        return False


def test_expert_system_creation():
    """Test that expert system can be created (without full initialization)"""
    print("\nTesting expert system creation...")
    
    try:
        from src.core import NHISExpertSystem, ProcessingStep
        from src.core.interfaces import BaseProcessor, BaseReferenceManager
        
        
        class MockProcessor(BaseProcessor):
            def __init__(self, name, step):
                super().__init__(name, step)
            
            def process(self, claim, context=None):
                from src.core import ProcessorResult
                return ProcessorResult(success=True)
            
            def validate_inputs(self, claim, context=None):
                return []
        
        
        class MockReferenceManager(BaseReferenceManager):
            def load_reference_data(self):
                return True
            
            def get_mapping(self, mapping_type, key):
                return {"test": "data"}
            
            def is_data_loaded(self):
                return True
        
        
        processors = {
            ProcessingStep.INTAKE_NORMALIZATION: MockProcessor("intake", ProcessingStep.INTAKE_NORMALIZATION),
            ProcessingStep.ELIGIBILITY_COVERAGE: MockProcessor("eligibility", ProcessingStep.ELIGIBILITY_COVERAGE),
            ProcessingStep.SETTING_ROUTER: MockProcessor("routing", ProcessingStep.SETTING_ROUTER),
            ProcessingStep.CREDENTIALING_CHECK: MockProcessor("credentialing", ProcessingStep.CREDENTIALING_CHECK),
            ProcessingStep.BUSINESS_RULES_CALCULATION: MockProcessor("business", ProcessingStep.BUSINESS_RULES_CALCULATION)
        }
        
        
        ref_manager = MockReferenceManager()
        
        
        expert_system = NHISExpertSystem(
            processors=processors,
            reference_manager=ref_manager
        )
        
        # Test system info
        system_info = expert_system.get_expert_system_info()
        assert "name" in system_info
        assert system_info["processors_count"] == 5
        
        # Test system status
        status = expert_system.get_system_status()
        assert "system_info" in status
        assert status["system_info"]["is_initialized"] == True
        
        print("✅ Expert system creation working!")
        return True
        
    except Exception as e:
        print(f"❌ Expert system test failed: {e}")
        return False


def run_all_tests():
    """Run all core module tests"""
    print("=" * 50)
    print("NHIS Expert System - Core Module Tests")
    print("=" * 50)
    
    tests = [
        test_core_imports,
        test_enum_usage,
        test_model_creation,
        test_exception_handling,
        test_claim_adapter,
        test_expert_system_creation
    ]
    
    passed = 0
    total = len(tests)
    
    for test in tests:
        try:
            if test():
                passed += 1
        except Exception as e:
            print(f"❌ Test {test.__name__} crashed: {e}")
    
    print("\n" + "=" * 50)
    print(f"TEST RESULTS: {passed}/{total} tests passed")
    
    if passed == total:
        print("🎉 All core module tests PASSED! Core is working correctly.")
        return True
    else:
        print("⚠️  Some tests failed. Check the errors above.")
        return False


if __name__ == "__main__":
    # Run the tests
    success = run_all_tests()
    
    if success:
        print("\n✅ Core module is ready!")
        print("You can now proceed to build other modules (processors, database, etc.)")
    else:
        print("\n❌ Core module has issues that need to be fixed.")
    
    sys.exit(0 if success else 1)