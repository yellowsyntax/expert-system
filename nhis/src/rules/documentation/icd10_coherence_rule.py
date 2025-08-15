from typing import List, Dict, Any, Optional, Set
from ..base_rule import BaseRule, RuleResult, RuleResultType
from ...core.models import ClaimProcessingContext
import json
import re
import logging

logger = logging.getLogger(__name__)


class ICD10CoherenceRule(BaseRule):
    
    def __init__(self, reference_data_path: str = "reference_data/documentation_requirements.json"):
        super().__init__(
            rule_id="DOC_ICD10_COHERENCE",
            name="ICD-10 Coherence Rule",
            description="Validate ICD-10 diagnosis coherence with clinical narrative"
        )
        self.reference_data = self._load_icd10_mappings(reference_data_path)
    
    def _load_icd10_mappings(self, file_path: str) -> Dict[str, Any]:
        try:
            with open(file_path, 'r') as f:
                data = json.load(f)
                return data.get('icd10_coherence', {})
        except Exception as e:
            logger.warning(f"Could not load ICD-10 coherence reference data: {str(e)}")
            return self._get_default_icd10_data()
    
    def _get_default_icd10_data(self) -> Dict[str, Any]:
        return {
            "keyword_mappings": {
                "A00-A09": ["diarrhea", "gastroenteritis", "cholera", "dysentery", "food poisoning"],
                "B00-B09": ["herpes", "chickenpox", "varicella", "shingles", "viral infection"],
                "C00-C97": ["cancer", "carcinoma", "tumor", "malignancy", "neoplasm", "oncology"],
                "E10-E14": ["diabetes", "diabetic", "hyperglycemia", "insulin", "glucose"],
                "F00-F99": ["depression", "anxiety", "psychiatric", "mental", "psychosis", "bipolar"],
                "G00-G99": ["seizure", "epilepsy", "stroke", "headache", "migraine", "neurological"],
                "H00-H59": ["eye", "vision", "blindness", "cataract", "glaucoma", "ophthalmology"],
                "H60-H95": ["ear", "hearing", "deafness", "otitis", "tinnitus"],
                "I00-I99": ["heart", "cardiac", "hypertension", "blood pressure", "cardiovascular"],
                "J00-J99": ["cough", "pneumonia", "asthma", "respiratory", "lung", "breathing"],
                "K00-K95": ["abdominal", "stomach", "liver", "intestine", "digestive", "gastric"],
                "L00-L99": ["skin", "rash", "dermatitis", "eczema", "dermatology", "wound"],
                "M00-M99": ["joint", "arthritis", "bone", "muscle", "orthopedic", "fracture"],
                "N00-N99": ["kidney", "urinary", "bladder", "renal", "urology", "nephrology"],
                "O00-O9A": ["pregnancy", "pregnant", "delivery", "obstetric", "fetal", "maternal"],
                "P00-P96": ["newborn", "neonatal", "infant", "pediatric", "birth"],
                "Q00-Q99": ["congenital", "birth defect", "malformation", "genetic"],
                "R00-R99": ["fever", "pain", "symptom", "abnormal", "finding"],
                "S00-T88": ["injury", "trauma", "accident", "fracture", "wound", "burn"],
                "Z00-Z99": ["screening", "examination", "follow-up", "vaccination", "prevention"]
            },
            "exclusion_keywords": [
                "not", "no", "negative", "absent", "denies", "rule out", "r/o"
            ],
            "coherence_threshold": 0.6,
            "minimum_narrative_length": 10
        }
    
    def _extract_icd10_category(self, icd10_code: str) -> str:
        if not icd10_code or len(icd10_code) < 3:
            return ""
        
        category_mappings = self.reference_data.get('keyword_mappings', {})
        icd10_prefix = icd10_code[:3].upper()
        
        for category_range, keywords in category_mappings.items():
            if '-' in category_range:
                start_code, end_code = category_range.split('-')
                if start_code <= icd10_prefix <= end_code:
                    return category_range
        
        return icd10_prefix
    
    def _get_expected_keywords(self, icd10_code: str) -> List[str]:
        category = self._extract_icd10_category(icd10_code)
        keyword_mappings = self.reference_data.get('keyword_mappings', {})
        return keyword_mappings.get(category, [])
    
    def _clean_narrative(self, narrative: str) -> str:
        if not narrative:
            return ""
        
        narrative = narrative.lower()
        narrative = re.sub(r'[^\w\s]', ' ', narrative)
        narrative = ' '.join(narrative.split())
        
        return narrative
    
    def _has_exclusion_keywords(self, narrative: str) -> bool:
        exclusion_keywords = self.reference_data.get('exclusion_keywords', [])
        return any(keyword in narrative for keyword in exclusion_keywords)
    
    def _calculate_coherence_score(self, expected_keywords: List[str], narrative: str) -> float:
        if not expected_keywords or not narrative:
            return 0.0
        
        narrative_words = set(narrative.split())
        matching_keywords = []
        
        for keyword in expected_keywords:
            if keyword in narrative:
                matching_keywords.append(keyword)
        
        return len(matching_keywords) / len(expected_keywords)
    
    def _validate_narrative_length(self, narrative: str) -> bool:
        minimum_length = self.reference_data.get('minimum_narrative_length', 10)
        return len(narrative.strip()) >= minimum_length
    
    def evaluate(self, context: ClaimProcessingContext) -> RuleResult:
        try:
            claim = context.claim
            
            if not claim.primary_diagnosis:
                return RuleResult(
                    rule_id=self.rule_id,
                    result_type=RuleResultType.PEND,
                    message="Missing primary diagnosis for coherence validation",
                    details={"reason": "missing_primary_diagnosis"}
                )
            
            clinical_narrative = ""
            narrative_sources = []
            
            if hasattr(claim, 'clinical_notes') and claim.clinical_notes:
                clinical_narrative += " " + claim.clinical_notes
                narrative_sources.append("clinical_notes")
            
            if hasattr(claim, 'diagnosis_narrative') and claim.diagnosis_narrative:
                clinical_narrative += " " + claim.diagnosis_narrative
                narrative_sources.append("diagnosis_narrative")
            
            if hasattr(claim, 'presenting_complaint') and claim.presenting_complaint:
                clinical_narrative += " " + claim.presenting_complaint
                narrative_sources.append("presenting_complaint")
            
            if hasattr(claim, 'history_present_illness') and claim.history_present_illness:
                clinical_narrative += " " + claim.history_present_illness
                narrative_sources.append("history_present_illness")
            
            cleaned_narrative = self._clean_narrative(clinical_narrative)
            
            if not self._validate_narrative_length(cleaned_narrative):
                return RuleResult(
                    rule_id=self.rule_id,
                    result_type=RuleResultType.PEND,
                    message="Clinical narrative too short for coherence validation",
                    details={
                        "reason": "insufficient_narrative",
                        "narrative_length": len(cleaned_narrative),
                        "minimum_required": self.reference_data.get('minimum_narrative_length', 10)
                    }
                )
            
            expected_keywords = self._get_expected_keywords(claim.primary_diagnosis)
            
            if not expected_keywords:
                return RuleResult(
                    rule_id=self.rule_id,
                    result_type=RuleResultType.FLAG,
                    message=f"No keyword mappings found for ICD-10 code: {claim.primary_diagnosis}",
                    details={
                        "reason": "no_keyword_mapping",
                        "icd10_code": claim.primary_diagnosis
                    }
                )
            
            has_exclusions = self._has_exclusion_keywords(cleaned_narrative)
            coherence_score = self._calculate_coherence_score(expected_keywords, cleaned_narrative)
            coherence_threshold = self.reference_data.get('coherence_threshold', 0.6)
            
            matching_keywords = [kw for kw in expected_keywords if kw in cleaned_narrative]
            
            details = {
                "icd10_code": claim.primary_diagnosis,
                "expected_keywords": expected_keywords,
                "matching_keywords": matching_keywords,
                "coherence_score": coherence_score,
                "coherence_threshold": coherence_threshold,
                "has_exclusion_keywords": has_exclusions,
                "narrative_sources": narrative_sources,
                "narrative_length": len(cleaned_narrative)
            }
            
            if has_exclusions:
                return RuleResult(
                    rule_id=self.rule_id,
                    result_type=RuleResultType.PEND,
                    message="Clinical narrative contains exclusion keywords - manual review required",
                    details=details
                )
            
            if coherence_score < coherence_threshold:
                return RuleResult(
                    rule_id=self.rule_id,
                    result_type=RuleResultType.PEND,
                    message=f"ICD-10 diagnosis not coherent with clinical narrative (score: {coherence_score:.2f}, threshold: {coherence_threshold})",
                    details=details
                )
            
            context.icd10_coherence_validated = True
            context.coherence_score = coherence_score
            
            return RuleResult(
                rule_id=self.rule_id,
                result_type=RuleResultType.APPROVE,
                message=f"ICD-10 diagnosis coherent with clinical narrative (score: {coherence_score:.2f})",
                details=details
            )
            
        except Exception as e:
            logger.error(f"Error in ICD10CoherenceRule evaluation: {str(e)}")
            return RuleResult(
                rule_id=self.rule_id,
                result_type=RuleResultType.FLAG,
                message=f"Error during ICD-10 coherence validation: {str(e)}",
                details={"error": str(e)}
            )