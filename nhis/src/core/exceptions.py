from typing import Dict, Any,  List


class NHISExpertSystemError(Exception):

    def __init__(
        self, message: str, error_code: str = None, details: Dict[str, Any] = None
    ):

        super().__init__(message)
        self.message = message
        self.error_code = error_code or self.__class__.__name__.upper()
        self.details = details or {}

    def to_dict(self) -> Dict[str, Any]:

        return {
            "error_type": self.__class__.__name__,
            "error_code": self.error_code,
            "message": self.message,
            "details": self.details,
        }


class ClaimProcessingError(NHISExpertSystemError):

    def __init__(
        self,
        message: str,
        claim_id: str = None,
        processing_step: str = None,
        validation_errors: List[str] = None,
        **kwargs,
    ):

        details = {
            "claim_id": claim_id,
            "processing_step": processing_step,
            "validation_errors": validation_errors or [],
        }
        details.update(kwargs)

        super().__init__(message, "CLAIM_PROCESSING_ERROR", details)
        self.claim_id = claim_id
        self.processing_step = processing_step
        self.validation_errors = validation_errors or []


class ReferenceDataError(NHISExpertSystemError):

    def __init__(
        self, message: str, file_path: str = None, data_type: str = None, **kwargs
    ):

        details = {"file_path": file_path, "data_type": data_type}
        details.update(kwargs)

        super().__init__(message, "REFERENCE_DATA_ERROR", details)
        self.file_path = file_path
        self.data_type = data_type


class DatabaseConnectionError(NHISExpertSystemError):

    def __init__(
        self,
        message: str,
        operation: str = None,
        table_name: str = None,
        connection_string: str = None,
        **kwargs,
    ):

        # Mask sensitive connection info
        masked_connection = None
        if connection_string:
            # Hide password/sensitive parts
            masked_connection = (
                connection_string.split("@")[-1] if "@" in connection_string else "***"
            )

        details = {
            "operation": operation,
            "table_name": table_name,
            "connection": masked_connection,
        }
        details.update(kwargs)

        super().__init__(message, "DATABASE_CONNECTION_ERROR", details)
        self.operation = operation
        self.table_name = table_name


class ValidationError(NHISExpertSystemError):

    def __init__(
        self,
        message: str,
        field_name: str = None,
        field_value: Any = None,
        validation_rule: str = None,
        **kwargs,
    ):

        details = {
            "field_name": field_name,
            "field_value": str(field_value) if field_value is not None else None,
            "validation_rule": validation_rule,
        }
        details.update(kwargs)

        super().__init__(message, "VALIDATION_ERROR", details)
        self.field_name = field_name
        self.field_value = field_value
        self.validation_rule = validation_rule


class ConfigurationError(NHISExpertSystemError):

    def __init__(
        self, message: str, config_key: str = None, config_file: str = None, **kwargs
    ):

        details = {"config_key": config_key, "config_file": config_file}
        details.update(kwargs)

        super().__init__(message, "CONFIGURATION_ERROR", details)
        self.config_key = config_key
        self.config_file = config_file


class GDRGMappingError(ReferenceDataError):

    def __init__(
        self, message: str, icd10_code: str = None, encounter_type: str = None, **kwargs
    ):

        details = {"icd10_code": icd10_code, "encounter_type": encounter_type}
        details.update(kwargs)

        super().__init__(message, data_type="gdrg_mapping", **details)
        self.icd10_code = icd10_code
        self.encounter_type = encounter_type


class TariffCalculationError(ClaimProcessingError):

    def __init__(
        self,
        message: str,
        gdrg_code: str = None,
        facility_level: str = None,
        calculation_step: str = None,
        **kwargs,
    ):

        details = {
            "gdrg_code": gdrg_code,
            "facility_level": facility_level,
            "calculation_step": calculation_step,
        }
        details.update(kwargs)

        super().__init__(message, processing_step="calculation", **details)
        self.gdrg_code = gdrg_code
        self.facility_level = facility_level
        self.calculation_step = calculation_step


class EpisodeTrackingError(DatabaseConnectionError):

    def __init__(
        self, message: str, patient_id: str = None, episode_type: str = None, **kwargs
    ):

        details = {"patient_id": patient_id, "episode_type": episode_type}
        details.update(kwargs)

        super().__init__(message, operation="episode_tracking", **details)
        self.patient_id = patient_id
        self.episode_type = episode_type


class DocumentationError(ValidationError):

    def __init__(
        self,
        message: str,
        document_type: str = None,
        required_documents: List[str] = None,
        provided_documents: List[str] = None,
        **kwargs,
    ):

        details = {
            "document_type": document_type,
            "required_documents": required_documents or [],
            "provided_documents": provided_documents or [],
        }
        details.update(kwargs)

        super().__init__(
            message, validation_rule="documentation_requirements", **details
        )
        self.document_type = document_type
        self.required_documents = required_documents or []
        self.provided_documents = provided_documents or []


def handle_exception_gracefully(func):

    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except NHISExpertSystemError:

            raise
        except FileNotFoundError as e:
            raise ReferenceDataError(f"Reference data file not found: {e}")
        except ConnectionError as e:
            raise DatabaseConnectionError(f"Database connection failed: {e}")
        except ValueError as e:
            raise ValidationError(f"Data validation failed: {e}")
        except Exception as e:

            raise NHISExpertSystemError(f"Unexpected system error: {e}")

    return wrapper


def create_claim_rejection_error(
    reason: str, claim_id: str, details: Dict[str, Any] = None
) -> ClaimProcessingError:

    return ClaimProcessingError(
        message=f"Claim rejected: {reason}",
        claim_id=claim_id,
        error_code=f"CLAIM_REJECTED_{reason}",
        details=details or {},
    )
