from sqlalchemy import Column, Integer, String, JSON, Numeric, TIMESTAMP
from . import Base

class ICD10Code(Base):
    __tablename__ = "icd10_codes"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    icd_code = Column(String(10), nullable=False, index=True)
    diagnosis_description = Column(String, nullable=False)
    gdrg_code = Column(String(20), nullable=True)
    gdrg_name = Column(String, nullable=True)
    level_of_care = Column(JSON, nullable=True)  
    created_at = Column(TIMESTAMP(timezone=True), nullable=False)
    tariff = Column(Numeric, nullable=True)