from sqlalchemy import Column, Integer, String, Float, TIMESTAMP
from . import Base

class Investigation(Base):
    __tablename__ = "investigations"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    inv_code = Column(String(15), unique=True, index=True)
    name = Column(String, nullable=False)
    tariff = Column(Float, nullable=True)
    created_at = Column(TIMESTAMP(timezone=True), nullable=False)
