from sqlalchemy import Column, Integer, String, JSON, Float, TIMESTAMP
from . import Base


class ZoomCode(Base):
    __tablename__ = "zoom_codes"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    zoom_code = Column(String(15), unique=True, index=True)
    description = Column(String, nullable=False)
    level_of_care = Column(JSON, nullable=True)
    tariff = Column(Float, nullable=True)
    created_at = Column(TIMESTAMP(timezone=True), nullable=False)