from .base_rule import BaseRule, RuleResult, RuleDecision

from .opd import (
    EpisodeLimitsRule,
    MultiSpecialtyRule,
    ZoomProceduresRule,
    PhysiotherapyRule
)

from .inpatient import (
    BillingTimingRule,
    MultipleProceduresRule,
    ReadmissionRule
)

from .emergency import (
    ClassificationRule,
    DetentionRule,
    EmergencyImagingRule
)

from .gdrg import (
    ICD10MappingRule,
    ProcedureVsDiagnosisRule,
    AgeSplitRule,
    FacilityTariffRule
)

from .modifiers import (
    BilateralSurgeryRule,
    DentalMultiToothRule,
    EmergencyModifiersRule
)

from .documentation import (
    ICD10CoherenceRule,
    PreauthRule,
    SpecialtyDocsRule,
    EndoscopyDocsRule
)

class RuleEngine:
    def __init__(self, db_session, reference_data_manager):
        self.db_session = db_session
        self.reference_data = reference_data_manager
        
        self.opd_rules = {
            'episode_limits': EpisodeLimitsRule(db_session, reference_data_manager),
            'multi_specialty': MultiSpecialtyRule(db_session, reference_data_manager),
            'zoom_procedures': ZoomProceduresRule(db_session, reference_data_manager),
            'physiotherapy': PhysiotherapyRule(db_session, reference_data_manager)
        }
        
        self.inpatient_rules = {
            'billing_timing': BillingTimingRule(db_session, reference_data_manager),
            'multiple_procedures': MultipleProceduresRule(db_session, reference_data_manager),
            'readmission': ReadmissionRule(db_session, reference_data_manager)
        }
        
        self.emergency_rules = {
            'classification': ClassificationRule(db_session, reference_data_manager),
            'detention': DetentionRule(db_session, reference_data_manager),
            'emergency_imaging': EmergencyImagingRule(db_session, reference_data_manager)
        }
        
        self.gdrg_rules = {
            'icd10_mapping': ICD10MappingRule(db_session, reference_data_manager),
            'procedure_vs_diagnosis': ProcedureVsDiagnosisRule(db_session, reference_data_manager),
            'age_split': AgeSplitRule(db_session, reference_data_manager),
            'facility_tariff': FacilityTariffRule(db_session, reference_data_manager)
        }
        
        self.modifier_rules = {
            'bilateral_surgery': BilateralSurgeryRule(db_session, reference_data_manager),
            'dental_multi_tooth': DentalMultiToothRule(db_session, reference_data_manager),
            'emergency_modifiers': EmergencyModifiersRule(db_session, reference_data_manager)
        }
        
        self.documentation_rules = {
            'icd10_coherence': ICD10CoherenceRule(db_session, reference_data_manager),
            'preauth': PreauthRule(db_session, reference_data_manager),
            'specialty_docs': SpecialtyDocsRule(db_session, reference_data_manager),
            'endoscopy_docs': EndoscopyDocsRule(db_session, reference_data_manager)
        }
    
    def get_opd_rules(self):
        return self.opd_rules
    
    def get_inpatient_rules(self):
        return self.inpatient_rules
    
    def get_emergency_rules(self):
        return self.emergency_rules
    
    def get_gdrg_rules(self):
        return self.gdrg_rules
    
    def get_modifier_rules(self):
        return self.modifier_rules
    
    def get_documentation_rules(self):
        return self.documentation_rules
    
    def get_rule_by_name(self, rule_name: str):
        all_rules = {
            **self.opd_rules,
            **self.inpatient_rules,
            **self.emergency_rules,
            **self.gdrg_rules,
            **self.modifier_rules,
            **self.documentation_rules
        }
        return all_rules.get(rule_name)
    
    def get_rules_by_category(self, category: str):
        category_map = {
            'opd': self.opd_rules,
            'inpatient': self.inpatient_rules,
            'emergency': self.emergency_rules,
            'gdrg': self.gdrg_rules,
            'modifiers': self.modifier_rules,
            'documentation': self.documentation_rules
        }
        return category_map.get(category, {})

__all__ = [
    "BaseRule",
    "RuleResult", 
    "RuleDecision",
    "RuleEngine",
    "EpisodeLimitsRule",
    "MultiSpecialtyRule",
    "ZoomProceduresRule",
    "PhysiotherapyRule",
    "BillingTimingRule",
    "MultipleProceduresRule",
    "ReadmissionRule",
    "ClassificationRule",
    "DetentionRule",
    "EmergencyImagingRule",
    "ICD10MappingRule",
    "ProcedureVsDiagnosisRule",
    "AgeSplitRule",
    "FacilityTariffRule",
    "BilateralSurgeryRule",
    "DentalMultiToothRule",
    "EmergencyModifiersRule",
    "ICD10CoherenceRule",
    "PreauthRule",
    "SpecialtyDocsRule",
    "EndoscopyDocsRule"
]