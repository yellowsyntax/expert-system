from typing import List, Dict, Any, Optional
from ..base_rule import BaseRule, RuleResult, RuleResultType
from ...core.models import ClaimProcessingContext
import json
import logging

logger = logging.getLogger(__name__)


class EndoscopyDocsRule(BaseRule):
    
    def __init__(self, reference_data_path: str = "reference_data/documentation_requirements.json"):
        super().__init__(
            rule_id="DOC_ENDOSCOPY",
            name="Endoscopy Documentation Rule",
            description="Validate endoscopy-specific documentation requirements"
        )
        self.reference_data = self._load_endoscopy_requirements(reference_data_path)
    
    def _load_endoscopy_requirements(self, file_path: str) -> Dict[str, Any]:
        try:
            with open(file_path, 'r') as f:
                data = json.load(f)
                return data.get('endoscopy_documentation', {})
        except Exception as e:
            logger.warning(f"Could not load endoscopy documentation reference data: {str(e)}")
            return self._get_default_endoscopy_data()
    
    def _get_default_endoscopy_data(self) -> Dict[str, Any]:
        return {
            "endoscopy_procedures": {
                "ENDO001": "Upper GI Endoscopy",
                "ENDO002": "Colonoscopy", 
                "ENDO003": "Bronchoscopy",
                "ENDO004": "Cystoscopy",
                "ENDO005": "Arthroscopy",
                "ENDO006": "Laparoscopy",
                "ENDO007": "Hysteroscopy",
                "ENDO008": "ERCP"
            },
            "required_documents": {
                "pre_procedure": [
                    "endoscopy_request_form",
                    "informed_consent",
                    "pre_procedure_assessment",
                    "indication_for_procedure"
                ],
                "procedure": [
                    "procedure_report",
                    "findings_report",
                    "photographic_documentation",
                    "biopsy_report"
                ],
                "post_procedure": [
                    "post_procedure_note",
                    "discharge_instructions",
                    "follow_up_plan"
                ]
            },
            "mandatory_fields": {
                "indication": "Clinical indication for endoscopy",
                "findings": "Endoscopic findings",
                "complications": "Any complications during procedure",
                "sedation": "Sedation/anesthesia used",
                "equipment": "Endoscopic equipment used"
            },
            "biopsy_requirements": {
                "biopsy_taken": ["biopsy_site", "number_of_samples", "histology_request"],
                "no_biopsy": ["reason_no_biopsy"]
            }
        }
    
    def _is_endoscopy_procedure(self, procedure_code: str) -> bool:
        endoscopy_procedures = self.reference_data.get('endoscopy_procedures', {})
        return procedure_code in endoscopy_procedures
    
    def _get_endoscopy_procedures(self, claim) -> List[Dict[str, Any]]:
        endoscopy_procedures = []
        
        if not hasattr(claim, 'procedures') or not claim.procedures:
            return endoscopy_procedures
        
        endoscopy_codes = self.reference_data.get('endoscopy_procedures', {})
        
        for procedure in claim.procedures:
            procedure_code = procedure.get('code', '')
            if self._is_endoscopy_procedure(procedure_code):
                endoscopy_procedures.append({
                    'code': procedure_code,
                    'name': endoscopy_codes.get(procedure_code, 'Unknown Endoscopy'),
                    'procedure_data': procedure
                })
        
        return endoscopy_procedures
    
    def _check_required_documents(self, claim) -> Dict[str, Any]:
        required_docs = self.reference_data.get('required_documents', {})
        document_status = {}
        
        for category, docs in required_docs.items():
            document_status[category] = {
                'required': docs,
                'available': [],
                'missing': []
            }
            
            for doc_name in docs:
                is_available = self._check_document_availability(claim, doc_name)
                if is_available:
                    document_status[category]['available'].append(doc_name)
                else:
                    document_status[category]['missing'].append(doc_name)
        
        return document_status
    
    def _check_document_availability(self, claim, doc_name: str) -> bool:
        # Direct field check
        if hasattr(claim, doc_name) and getattr(claim, doc_name):
            return True
        
        # Check in endoscopy-specific fields
        endoscopy_fields = [
            'endoscopy_report', 'endoscopy_findings', 'endoscopy_images',
            'procedure_report', 'consent_form', 'pre_assessment'
        ]
        
        for field in endoscopy_fields:
            if hasattr(claim, field) and getattr(claim, field):
                field_content = str(getattr(claim, field)).lower()
                if doc_name.replace('_', ' ') in field_content:
                    return True
        
        # Check attachments
        if hasattr(claim, 'attachments') and claim.attachments:
            for attachment in claim.attachments:
                if isinstance(attachment, dict):
                    attachment_name = attachment.get('name', '').lower()
                    attachment_type = attachment.get('type', '').lower()
                    if doc_name in attachment_name or doc_name in attachment_type:
                        return True
        
        return False
    
    def _check_mandatory_fields(self, claim) -> Dict[str, Any]:
        mandatory_fields = self.reference_data.get('mandatory_fields', {})
        field_status = {}
        
        for field_name, description in mandatory_fields.items():
            field_available = False
            field_content = None
            
            # Check direct field
            if hasattr(claim, field_name) and getattr(claim, field_name):
                field_available = True
                field_content = getattr(claim, field_name)
            
            # Check in procedure report or findings
            elif hasattr(claim, 'procedure_report') and claim.procedure_report:
                if field_name in claim.procedure_report.lower():
                    field_available = True
                    field_content = "Found in procedure report"
            
            elif hasattr(claim, 'endoscopy_findings') and claim.endoscopy_findings:
                if field_name in claim.endoscopy_findings.lower():
                    field_available = True
                    field_content = "Found in findings report"
            
            field_status[field_name] = {
                'description': description,
                'available': field_available,
                'content': field_content
            }
        
        return field_status
    
    def _check_biopsy_requirements(self, claim) -> Dict[str, Any]:
        biopsy_requirements = self.reference_data.get('biopsy_requirements', {})
        biopsy_status = {'biopsy_taken': False, 'requirements_met': False, 'missing_info': []}
        
        # Check if biopsy was taken
        biopsy_indicators = ['biopsy_taken', 'tissue_sample', 'histology_sample']
        
        for indicator in biopsy_indicators:
            if hasattr(claim, indicator) and getattr(claim, indicator):
                biopsy_status['biopsy_taken'] = True
                break
        
        # Check biopsy-related content in reports
        if hasattr(claim, 'procedure_report') and claim.procedure_report:
            biopsy_keywords = ['biopsy', 'tissue', 'sample', 'histology']
            report_lower = claim.procedure_report.lower()
            if any(keyword in report_lower for keyword in biopsy_keywords):
                biopsy_status['biopsy_taken'] = True
        
        # Validate requirements based on biopsy status
        if biopsy_status['biopsy_taken']:
            required_fields = biopsy_requirements.get('biopsy_taken', [])
            for field in required_fields:
                if not hasattr(claim, field) or not getattr(claim, field):
                    biopsy_status['missing_info'].append(field)
        else:
            required_fields = biopsy_requirements.get('no_biopsy', [])
            for field in required_fields:
                if not hasattr(claim, field) or not getattr(claim, field):
                    biopsy_status['missing_info'].append(field)
        
        biopsy_status['requirements_met'] = len(biopsy_status['missing_info']) == 0
        
        return biopsy_status
    
    def evaluate(self, context: ClaimProcessingContext) -> RuleResult:
        try:
            claim = context.claim
            
            endoscopy_procedures = self._get_endoscopy_procedures(claim)
            
            if not endoscopy_procedures:
                return RuleResult(
                    rule_id=self.rule_id,
                    result_type=RuleResultType.APPROVE,
                    message="No endoscopy procedures found - rule skipped",
                    details={"reason": "no_endoscopy_procedures"}
                )
            
            document_status = self._check_required_documents(claim)
            mandatory_fields = self._check_mandatory_fields(claim)
            biopsy_status = self._check_biopsy_requirements(claim)
            
            # Collect all missing items
            missing_documents = []
            missing_fields = []
            
            for category, status in document_status.items():
                missing_documents.extend([f"{category}:{doc}" for doc in status['missing']])
            
            for field_name, field_info in mandatory_fields.items():
                if not field_info['available']:
                    missing_fields.append(field_name)
            
            details = {
                "endoscopy_procedures": [proc['code'] for proc in endoscopy_procedures],
                "document_status": document_status,
                "mandatory_fields": mandatory_fields,
                "biopsy_status": biopsy_status,
                "missing_documents": missing_documents,
                "missing_fields": missing_fields
            }
            
            # Determine result based on missing items
            critical_missing = missing_documents + missing_fields
            if not biopsy_status['requirements_met']:
                critical_missing.extend(biopsy_status['missing_info'])
            
            if critical_missing:
                return RuleResult(
                    rule_id=self.rule_id,
                    result_type=RuleResultType.PEND,
                    message=f"Missing endoscopy documentation: {', '.join(critical_missing)}",
                    details=details
                )
            
            context.endoscopy_docs_validated = True
            context.endoscopy_procedures = [proc['code'] for proc in endoscopy_procedures]
            
            return RuleResult(
                rule_id=self.rule_id,
                result_type=RuleResultType.APPROVE,
                message=f"All endoscopy documentation requirements met for {len(endoscopy_procedures)} procedures",
                details=details
            )
            
        except Exception as e:
            logger.error(f"Error in EndoscopyDocsRule evaluation: {str(e)}")
            return RuleResult(
                rule_id=self.rule_id,
                result_type=RuleResultType.FLAG,
                message=f"Error during endoscopy documentation validation: {str(e)}",
                details={"error": str(e)}
            )