from typing import List, Dict, Any, Optional, Set
from ..base_rule import BaseRule, RuleResult, RuleResultType
from ...core.models import ClaimProcessingContext
import json
import logging

logger = logging.getLogger(__name__)


class SpecialtyDocsRule(BaseRule):
    
    def __init__(self, reference_data_path: str = "reference_data/documentation_requirements.json"):
        super().__init__(
            rule_id="DOC_SPECIALTY",
            name="Specialty Documentation Rule",
            description="Validate specialty-specific documentation requirements"
        )
        self.reference_data = self._load_specialty_requirements(reference_data_path)
    
    def _load_specialty_requirements(self, file_path: str) -> Dict[str, Any]:
        try:
            with open(file_path, 'r') as f:
                data = json.load(f)
                return data.get('specialty_documentation', {})
        except Exception as e:
            logger.warning(f"Could not load specialty documentation reference data: {str(e)}")
            return self._get_default_specialty_data()
    
    def _get_default_specialty_data(self) -> Dict[str, Any]:
        return {
            "cardiology": {
                "required_docs": ["ecg", "echo_report", "cardiac_catheter_report"],
                "procedures": ["CARDIAC001", "CARDIAC002", "CARDIAC003"],
                "conditions": ["I20-I25", "I30-I52"]
            },
            "orthopedics": {
                "required_docs": ["xray_report", "mri_report", "operative_note"],
                "procedures": ["ORTHO001", "ORTHO002", "ORTHO003"],
                "conditions": ["M00-M25", "S72-S82"]
            },
            "neurology": {
                "required_docs": ["ct_scan", "mri_brain", "eeg_report"],
                "procedures": ["NEURO001", "NEURO002"],
                "conditions": ["G00-G99"]
            },
            "obstetrics": {
                "required_docs": ["anc_card", "ultrasound_report", "delivery_note"],
                "procedures": ["OBS001", "OBS002", "OBS003"],
                "conditions": ["O00-O9A"]
            },
            "pediatrics": {
                "required_docs": ["growth_chart", "immunization_record", "developmental_assessment"],
                "procedures": ["PEDS001", "PEDS002"],
                "conditions": ["P00-P96"]
            },
            "surgery": {
                "required_docs": ["operative_note", "anesthesia_record", "post_op_note"],
                "procedures": ["SURG001", "SURG002", "SURG003", "SURG004"],
                "conditions": ["K80-K87", "N20-N23"]
            },
            "ophthalmology": {
                "required_docs": ["visual_acuity", "fundoscopy_report", "iop_measurement"],
                "procedures": ["OPHT001", "OPHT002"],
                "conditions": ["H00-H59"]
            },
            "psychiatry": {
                "required_docs": ["mental_status_exam", "psychiatric_assessment", "treatment_plan"],
                "procedures": ["PSYCH001", "PSYCH002"],
                "conditions": ["F00-F99"]
            }
        }
    
    def _determine_specialty(self, claim) -> Set[str]:
        specialties = set()
        
        # Check by procedures
        if hasattr(claim, 'procedures') and claim.procedures:
            for procedure in claim.procedures:
                procedure_code = procedure.get('code', '')
                for specialty, requirements in self.reference_data.items():
                    specialty_procedures = requirements.get('procedures', [])
                    if any(proc in procedure_code for proc in specialty_procedures):
                        specialties.add(specialty)
        
        # Check by diagnosis
        if claim.primary_diagnosis:
            icd10_prefix = claim.primary_diagnosis[:3].upper()
            for specialty, requirements in self.reference_data.items():
                specialty_conditions = requirements.get('conditions', [])
                for condition_range in specialty_conditions:
                    if '-' in condition_range:
                        start_code, end_code = condition_range.split('-')
                        if start_code <= icd10_prefix <= end_code:
                            specialties.add(specialty)
                    elif condition_range == icd10_prefix:
                        specialties.add(specialty)
        
        # Check by provider specialty
        if hasattr(claim, 'provider_specialty') and claim.provider_specialty:
            provider_specialty = claim.provider_specialty.lower()
            if provider_specialty in self.reference_data:
                specialties.add(provider_specialty)
        
        return specialties
    
    def _get_required_docs_for_specialty(self, specialty: str) -> List[str]:
        specialty_data = self.reference_data.get(specialty, {})
        return specialty_data.get('required_docs', [])
    
    def _check_document_availability(self, claim, doc_name: str) -> tuple[bool, Optional[str]]:
        # Direct field check
        if hasattr(claim, doc_name) and getattr(claim, doc_name):
            return True, getattr(claim, doc_name)
        
        # Check in attachments
        if hasattr(claim, 'attachments') and claim.attachments:
            for attachment in claim.attachments:
                if isinstance(attachment, dict):
                    attachment_type = attachment.get('type', '').lower()
                    attachment_name = attachment.get('name', '').lower()
                    if doc_name in attachment_type or doc_name in attachment_name:
                        return True, attachment.get('filename', 'Available')
        
        # Check in documents list
        if hasattr(claim, 'documents') and claim.documents:
            for document in claim.documents:
                if isinstance(document, dict):
                    doc_type = document.get('document_type', '').lower()
                    if doc_name in doc_type:
                        return True, document.get('document_id', 'Available')
                elif isinstance(document, str) and doc_name in document.lower():
                    return True, document
        
        # Check variations of document names
        doc_variations = {
            'ecg': ['electrocardiogram', 'ekg'],
            'echo_report': ['echocardiogram', 'echo'],
            'xray_report': ['x-ray', 'radiograph'],
            'ct_scan': ['computed_tomography', 'ct'],
            'mri_report': ['magnetic_resonance', 'mri'],
            'anc_card': ['antenatal_card', 'prenatal_card'],
            'operative_note': ['surgery_note', 'operation_note']
        }
        
        variations = doc_variations.get(doc_name, [])
        for variation in variations:
            if hasattr(claim, variation) and getattr(claim, variation):
                return True, getattr(claim, variation)
        
        return False, None
    
    def evaluate(self, context: ClaimProcessingContext) -> RuleResult:
        try:
            claim = context.claim
            
            specialties = self._determine_specialty(claim)
            
            if not specialties:
                return RuleResult(
                    rule_id=self.rule_id,
                    result_type=RuleResultType.APPROVE,
                    message="No specialty-specific documentation requirements identified",
                    details={"reason": "no_specialty_identified"}
                )
            
            all_missing_docs = []
            specialty_results = {}
            
            for specialty in specialties:
                required_docs = self._get_required_docs_for_specialty(specialty)
                missing_docs = []
                available_docs = []
                
                for doc_name in required_docs:
                    is_available, doc_reference = self._check_document_availability(claim, doc_name)
                    if is_available:
                        available_docs.append({
                            'document': doc_name,
                            'reference': doc_reference
                        })
                    else:
                        missing_docs.append(doc_name)
                        all_missing_docs.append(f"{specialty}:{doc_name}")
                
                specialty_results[specialty] = {
                    'required_docs': required_docs,
                    'available_docs': available_docs,
                    'missing_docs': missing_docs,
                    'compliance_rate': (len(available_docs) / len(required_docs)) if required_docs else 1.0
                }
            
            details = {
                "identified_specialties": list(specialties),
                "specialty_results": specialty_results,
                "total_missing_docs": len(all_missing_docs),
                "missing_docs_list": all_missing_docs
            }
            
            if all_missing_docs:
                return RuleResult(
                    rule_id=self.rule_id,
                    result_type=RuleResultType.PEND,
                    message=f"Missing specialty documentation: {', '.join(all_missing_docs)}",
                    details=details
                )
            
            context.specialty_docs_validated = True
            context.validated_specialties = list(specialties)
            
            return RuleResult(
                rule_id=self.rule_id,
                result_type=RuleResultType.APPROVE,
                message=f"All specialty documentation requirements met for: {', '.join(specialties)}",
                details=details
            )
            
        except Exception as e:
            logger.error(f"Error in SpecialtyDocsRule evaluation: {str(e)}")
            return RuleResult(
                rule_id=self.rule_id,
                result_type=RuleResultType.FLAG,
                message=f"Error during specialty documentation validation: {str(e)}",
                details={"error": str(e)}
            )