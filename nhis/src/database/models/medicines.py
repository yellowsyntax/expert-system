from sqlalchemy import Column, String, Float, DateTime
import datetime
from . import Base


class Medicines(Base):
    __tablename__ = "medicines"

    code = Column(String(50), primary_key=True, index=True) 
    generic_name = Column(String, nullable=False)
    unit_of_pricing = Column(String(100), nullable=False)
    price = Column(Float, nullable=True)
    level_of_prescribing = Column(String(10), nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow, nullable=False)