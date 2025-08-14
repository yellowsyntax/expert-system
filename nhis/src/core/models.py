"""
NHIS Expert System - Core Models

Data classes and structures used throughout the expert system.
These models define the standard format for claims, decisions, and processing results.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Any, Optional, Union
from datetime import datetime, date
from decimal import Decimal
from uuid import UUID

from .enums import (
    ClaimStatus, ValidationSeverity, EncounterType, EpisodeType,
    GDRGDeterminationMethod, ModifierType, DecisionReason,
    LineItemType, LineItemStatus, ProcessingStep
)


@dataclass
class ValidationIssue:
    """
    Represents a single validation issue found during claim processing.
    Maps to validation failures in the flowchart decision nodes.
    """
    severity: ValidationSeverity
    code: str
    message: str
    details: Dict[str, Any] = field(default_factory=dict)
    processing_step: Optional[ProcessingStep] = None
    rule_reference: Optional[str] = None  # e.g., "B2", "D1", "A3"
    
    def is_critical(self) -> bool:
        """Check if this issue causes claim rejection"""
        return self.severity == ValidationSeverity.CRITICAL
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization"""
        return {
            "severity": self.severity.value,
            "code": self.code,
            "message": self.message,
            "details": self.details,
            "processing_step": self.processing_step.value if self.processing_step else None,
            "rule_reference": self.rule_reference
        }


@dataclass
class LineItem:
    """
    Represents a single line item in the claim calculation breakdown.
    Used for detailed financial calculations and reporting.
    """
    type: LineItemType
    code: str
    description: str
    quantity: Optional[int] = 1
    unit_amount: Optional[Decimal] = None
    total_amount: Decimal = Decimal('0.00')
    status: LineItemStatus = LineItemStatus.APPROVED
    reason: Optional[str] = None
    modifier_applied: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization"""
        return {
            "type": self.type.value,
            "code": self.code,
            "description": self.description,
            "quantity": self.quantity,
            "unit_amount": str(self.unit_amount) if self.unit_amount else None,
            "total_amount": str(self.total_amount),
            "status": self.status.value,
            "reason": self.reason,
            "modifier_applied": self.modifier_applied
        }


@dataclass
class CalculationResult:
    """
    Result of amount calculations including breakdown by component.
    Provides detailed financial analysis of the claim.
    """
    total_claimed: Decimal = Decimal('0.00')
    total_approved: Decimal = Decimal('0.00')
    total_denied: Decimal = Decimal('0.00')
    total_pending: Decimal = Decimal('0.00')
    
    # Breakdown by component type
    gdrg_amount: Decimal = Decimal('0.00')
    medicine_amount: Decimal = Decimal('0.00')
    investigation_amount: Decimal = Decimal('0.00')
    procedure_amount: Decimal = Decimal('0.00')
    modifier_amount: Decimal = Decimal('0.00')
    
    # Detailed line items
    line_items: List[LineItem] = field(default_factory=list)
    
    # Calculation metadata
    calculation_method: Optional[str] = None
    tariff_version: Optional[str] = None
    calculation_timestamp: datetime = field(default_factory=datetime.utcnow)
    
    def add_line_item(self, line_item: LineItem) -> None:
        """Add a line item and update totals"""
        self.line_items.append(line_item)
        
        # Update totals based on status
        if line_item.status == LineItemStatus.APPROVED:
            self.total_approved += line_item.total_amount
        elif line_item.status == LineItemStatus.DENIED:
            self.total_denied += line_item.total_amount
        elif line_item.status == LineItemStatus.PENDING:
            self.total_pending += line_item.total_amount
        
        self.total_claimed += line_item.total_amount
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization"""
        return {
            "total_claimed": str(self.total_claimed),
            "total_approved": str(self.total_approved),
            "total_denied": str(self.total_denied),
            "total_pending": str(self.total_pending),
            "gdrg_amount": str(self.gdrg_amount),
            "medicine_amount": str(self.medicine_amount),
            "investigation_amount": str(self.investigation_amount),
            "procedure_amount": str(self.procedure_amount),
            "modifier_amount": str(self.modifier_amount),
            "line_items": [item.to_dict() for item in self.line_items],
            "calculation_method": self.calculation_method,
            "tariff_version": self.tariff_version,
            "calculation_timestamp": self.calculation_timestamp.isoformat()
        }


@dataclass
class ProcessorResult:
    """
    Result returned by each processor in the 5-step pipeline.
    Standardizes communication between processing steps.
    """
    success: bool
    data: Dict[str, Any] = field(default_factory=dict)
    errors: List[ValidationIssue] = field(default_factory=list)
    warnings: List[ValidationIssue] = field(default_factory=list)
    processing_step: Optional[ProcessingStep] = None
    processing_time_ms: Optional[float] = None
    
    def add_error(self, severity: ValidationSeverity, code: str, message: str, 
                  details: Dict[str, Any] = None, rule_reference: str = None) -> None:
        """Add a validation error"""
        issue = ValidationIssue(
            severity=severity,
            code=code,
            message=message,
            details=details or {},
            processing_step=self.processing_step,
            rule_reference=rule_reference
        )
        
        if severity == ValidationSeverity.CRITICAL:
            self.errors.append(issue)
            self.success = False
        else:
            self.warnings.append(issue)
    
    def has_critical_errors(self) -> bool:
        """Check if there are critical errors that prevent processing"""
        return any(error.is_critical() for error in self.errors)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization"""
        return {
            "success": self.success,
            "data": self.data,
            "errors": [error.to_dict() for error in self.errors],
            "warnings": [warning.to_dict() for warning in self.warnings],
            "processing_step": self.processing_step.value if self.processing_step else None,
            "processing_time_ms": self.processing_time_ms
        }


@dataclass
class RuleResult:
    """
    Result returned by individual business rules.
    Provides detailed information about rule evaluation.
    """
    passed: bool
    rule_name: str
    rule_reference: Optional[str] = None  # Flowchart node reference (e.g., "B2", "D1")
    issues: List[ValidationIssue] = field(default_factory=list)
    data: Dict[str, Any] = field(default_factory=dict)
    execution_time_ms: Optional[float] = None
    
    def add_issue(self, severity: ValidationSeverity, code: str, message: str,
                  details: Dict[str, Any] = None) -> None:
        """Add a validation issue for this rule"""
        issue = ValidationIssue(
            severity=severity,
            code=code,
            message=message,
            details=details or {},
            rule_reference=self.rule_reference
        )
        self.issues.append(issue)
        
        # Mark rule as failed if critical issue
        if severity == ValidationSeverity.CRITICAL:
            self.passed = False
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization"""
        return {
            "passed": self.passed,
            "rule_name": self.rule_name,
            "rule_reference": self.rule_reference,
            "issues": [issue.to_dict() for issue in self.issues],
            "data": self.data,
            "execution_time_ms": self.execution_time_ms
        }


@dataclass
class StandardClaim:
    # ALL REQUIRED FIELDS FIRST (no defaults)
    claim_id: str
    facility_id: str
    patient_age: int
    visit_date: date
    encounter_type: EncounterType
    icd10_diagnosis: str
    
    # ALL OPTIONAL FIELDS AFTER (with defaults)
    encounter_id: Optional[str] = None
    batch_id: Optional[str] = None
    
    # Provider information
    facility_name: Optional[str] = None
    facility_level: Optional[str] = None
    prescriber_level: Optional[str] = None
    district: Optional[str] = None
    provider_type: Optional[str] = None
    
    # Patient information
    patient_id: Optional[str] = None  # nhis_number
    gender: Optional[str] = None
    date_of_birth: Optional[date] = None
    
    # Encounter details
    admission_date: Optional[datetime] = None
    discharge_date: Optional[datetime] = None
    service_outcome: Optional[str] = None
    attendance_type: Optional[str] = None
    specialties_attended: Optional[List[str]] = field(default_factory=list)
    
    # Clinical information
    diagnosis_name: Optional[str] = None
    claimed_gdrgs: List[str] = field(default_factory=list)
    
    # Procedures
    procedures: List[Dict[str, Any]] = field(default_factory=list)
    
    # Medicines
    medicines: List[Dict[str, Any]] = field(default_factory=list)
    
    # Investigations
    investigations: List[Dict[str, Any]] = field(default_factory=list)
    
    # Episode and tracking
    episode_id: Optional[str] = None
    episode_type: Optional[EpisodeType] = None
    
    # Documentation
    provided_documents: List[str] = field(default_factory=list)
    
    # Modifiers and flags
    modifiers: Dict[str, Any] = field(default_factory=dict)
    special_flags: Dict[str, Any] = field(default_factory=dict)
    
    # Metadata
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: Optional[datetime] = None
    
    def get_age_suffix(self) -> str:
        """Get age suffix for G-DRG determination (A3 from flowchart)"""
        # Check for childhood cancer special rule
        is_childhood_cancer = self.icd10_diagnosis.startswith(('C81', 'C82', 'C83', 'C84', 'C85', 'C91', 'C92', 'C93', 'C94', 'C95'))
        
        if is_childhood_cancer and self.patient_age < 19:
            return 'C'
        elif self.patient_age < 12:
            return 'C'
        else:
            return 'A'
    
    def is_emergency_encounter(self) -> bool:
        """Check if this is an emergency encounter"""
        emergency_types = {EncounterType.AE, EncounterType.EMERGENCY}
        return self.encounter_type in emergency_types
    
    def get_length_of_stay(self) -> Optional[int]:
        """Calculate length of stay for inpatient encounters"""
        if self.encounter_type == EncounterType.IPD and self.admission_date and self.discharge_date:
            delta = self.discharge_date.date() - self.admission_date.date()
            return delta.days
        return None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization"""
        return {
            "claim_id": self.claim_id,
            "encounter_id": self.encounter_id,
            "batch_id": self.batch_id,
            "facility_id": self.facility_id,
            "facility_name": self.facility_name,
            "facility_level": self.facility_level,
            "prescriber_level": self.prescriber_level,
            "district": self.district,
            "provider_type": self.provider_type,
            "patient_id": self.patient_id,
            "patient_age": self.patient_age,
            "gender": self.gender,
            "date_of_birth": self.date_of_birth.isoformat() if self.date_of_birth else None,
            "visit_date": self.visit_date.isoformat(),
            "encounter_type": self.encounter_type.value,
            "admission_date": self.admission_date.isoformat() if self.admission_date else None,
            "discharge_date": self.discharge_date.isoformat() if self.discharge_date else None,
            "service_outcome": self.service_outcome,
            "attendance_type": self.attendance_type,
            "specialties_attended": self.specialties_attended,
            "icd10_diagnosis": self.icd10_diagnosis,
            "diagnosis_name": self.diagnosis_name,
            "claimed_gdrgs": self.claimed_gdrgs,
            "procedures": self.procedures,
            "medicines": self.medicines,
            "investigations": self.investigations,
            "episode_id": self.episode_id,
            "episode_type": self.episode_type.value if self.episode_type else None,
            "provided_documents": self.provided_documents,
            "modifiers": self.modifiers,
            "special_flags": self.special_flags,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat() if self.updated_at else None
        }


@dataclass
class ClaimDecision:
    """
    Final decision result for a processed claim.
    This is the ultimate output of the expert system.
    """
    # Core decision information
    claim_id: str
    status: ClaimStatus
    decision_reason: DecisionReason
    decision_rationale: str
    
    # Financial results
    calculation_result: CalculationResult
    
    # Validation details
    validation_issues: List[ValidationIssue] = field(default_factory=list)
    rules_applied: List[RuleResult] = field(default_factory=list)
    
    # Processing metadata
    processing_steps: List[ProcessorResult] = field(default_factory=list)
    total_processing_time_ms: Optional[float] = None
    decision_timestamp: datetime = field(default_factory=datetime.utcnow)
    
    # Required actions
    required_documents: List[str] = field(default_factory=list)
    recommended_actions: List[str] = field(default_factory=list)
    
    # G-DRG determination details
    final_gdrg: Optional[str] = None
    gdrg_determination_method: Optional[GDRGDeterminationMethod] = None
    age_suffix_applied: Optional[str] = None
    
    # Episode tracking
    episode_information: Dict[str, Any] = field(default_factory=dict)
    
    def is_approved(self) -> bool:
        """Check if claim is fully approved"""
        return self.status == ClaimStatus.APPROVED
    
    def is_rejected(self) -> bool:
        """Check if claim is rejected"""
        return self.status == ClaimStatus.REJECTED
    
    def requires_action(self) -> bool:
        """Check if claim requires manual action"""
        return self.status == ClaimStatus.PENDING or bool(self.required_documents)
    
    def get_critical_issues(self) -> List[ValidationIssue]:
        """Get all critical validation issues"""
        return [issue for issue in self.validation_issues if issue.is_critical()]
    
    def add_validation_issue(self, issue: ValidationIssue) -> None:
        """Add a validation issue to the decision"""
        self.validation_issues.append(issue)
        
        # Update status based on issue severity
        if issue.is_critical() and self.status != ClaimStatus.REJECTED:
            self.status = ClaimStatus.REJECTED
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization"""
        return {
            "claim_id": self.claim_id,
            "status": self.status.value,
            "decision_reason": self.decision_reason.value,
            "decision_rationale": self.decision_rationale,
            "calculation_result": self.calculation_result.to_dict(),
            "validation_issues": [issue.to_dict() for issue in self.validation_issues],
            "rules_applied": [rule.to_dict() for rule in self.rules_applied],
            "processing_steps": [step.to_dict() for step in self.processing_steps],
            "total_processing_time_ms": self.total_processing_time_ms,
            "decision_timestamp": self.decision_timestamp.isoformat(),
            "required_documents": self.required_documents,
            "recommended_actions": self.recommended_actions,
            "final_gdrg": self.final_gdrg,
            "gdrg_determination_method": self.gdrg_determination_method.value if self.gdrg_determination_method else None,
            "age_suffix_applied": self.age_suffix_applied,
            "episode_information": self.episode_information
        }


# Utility functions for model operations

def create_validation_issue(severity: ValidationSeverity, code: str, message: str,
                          details: Dict[str, Any] = None, rule_reference: str = None) -> ValidationIssue:
    """Helper function to create validation issues"""
    return ValidationIssue(
        severity=severity,
        code=code,
        message=message,
        details=details or {},
        rule_reference=rule_reference
    )


def create_line_item(item_type: LineItemType, code: str, description: str,
                    amount: Decimal, status: LineItemStatus = LineItemStatus.APPROVED,
                    quantity: int = 1) -> LineItem:
    """Helper function to create line items"""
    return LineItem(
        type=item_type,
        code=code,
        description=description,
        quantity=quantity,
        unit_amount=amount / quantity if quantity > 0 else amount,
        total_amount=amount,
        status=status
    )