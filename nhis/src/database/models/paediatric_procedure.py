from sqlalchemy import Column, Integer, String, JSON, Numeric, TIMESTAMP
from . import Base


class PaediatricProcedure(Base):
    __tablename__ = "paediatric_procedures"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    paed_code = Column(String(15), unique=True, index=True)
    description = Column(String, nullable=False)
    level_of_care = Column(JSON, nullable=True)
    tariff = Column(Numeric, nullable=True)
    created_at = Column(TIMESTAMP(timezone=True), nullable=False)