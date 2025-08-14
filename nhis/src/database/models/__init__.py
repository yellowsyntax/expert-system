from sqlalchemy.ext.declarative import declarative_base

Base = declarative_base()

from .claim_v2 import ClaimV2
from .provider_profile import ProviderProfile
from .claim_batch import ClaimBatch
from .claim_decision import ClaimDecision
from .audit_log import AuditLog

try:
    from .icd10_code import ICD10Code
    from .investigation import Investigation
    from .zoom_code import ZoomCode
    from .opd_procedure import OPDProcedure
    from .dent_procedure import DentProcedure
    from .ent_procedure import ENTProcedure
    from .medicine_procedure import MedicineProcedure
    from .paediatric_procedure import PaediatricProcedure
    from .surgery_procedure import SurgeryProcedure
    from .medicines import Medicines
except ImportError:
    ICD10Code = None
    Investigation = None
    ZoomCode = None
    OPDProcedure = None
    DentProcedure = None
    ENTProcedure = None
    MedicineProcedure = None
    PaediatricProcedure = None
    SurgeryProcedure = None
    Medicines = None


def get_all_models():
    models = [ClaimV2, ProviderProfile, ClaimBatch, ClaimDecision, AuditLog]

    optional_models = [
        ICD10Code,
        Investigation,
        ZoomCode,
        OPDProcedure,
        DentProcedure,
        ENTProcedure,
        MedicineProcedure,
        PaediatricProcedure,
        SurgeryProcedure,
        Medicines,
    ]

    for model in optional_models:
        if model is not None:
            models.append(model)

    return models


def get_core_models():
    return [ClaimV2, ProviderProfile, ClaimBatch, ClaimDecision, AuditLog]


def get_reference_models():
    reference_models = []
    optional_models = [
        ICD10Code,
        Investigation,
        ZoomCode,
        OPDProcedure,
        DentProcedure,
        ENTProcedure,
        MedicineProcedure,
        PaediatricProcedure,
        SurgeryProcedure,
        Medicines,
    ]

    for model in optional_models:
        if model is not None:
            reference_models.append(model)

    return reference_models


def get_model_by_name(model_name: str):
    model_map = {
        "ClaimV2": ClaimV2,
        "ProviderProfile": ProviderProfile,
        "ClaimBatch": ClaimBatch,
        "ClaimDecision": ClaimDecision,
        "AuditLog": AuditLog,
    }

    optional_model_map = {
        "ICD10Code": ICD10Code,
        "Investigation": Investigation,
        "ZoomCode": ZoomCode,
        "OPDProcedure": OPDProcedure,
        "DentProcedure": DentProcedure,
        "ENTProcedure": ENTProcedure,
        "MedicineProcedure": MedicineProcedure,
        "PaediatricProcedure": PaediatricProcedure,
        "SurgeryProcedure": SurgeryProcedure,
        "Medicines": Medicines,
    }

    if model_name in model_map:
        return model_map[model_name]

    if model_name in optional_model_map and optional_model_map[model_name] is not None:
        return optional_model_map[model_name]

    return None


def get_table_names():
    tables = []
    for model in get_all_models():
        if hasattr(model, "__tablename__"):
            tables.append(model.__tablename__)
    return tables


__all__ = [
    "Base",
    "ClaimV2",
    "ProviderProfile",
    "ClaimBatch",
    "ClaimDecision",
    "AuditLog",
    "ICD10Code",
    "Investigation",
    "ZoomCode",
    "OPDProcedure",
    "DentProcedure",
    "ENTProcedure",
    "MedicineProcedure",
    "PaediatricProcedure",
    "SurgeryProcedure",
    "Medicines",
    "get_all_models",
    "get_core_models",
    "get_reference_models",
    "get_model_by_name",
    "get_table_names",
]
