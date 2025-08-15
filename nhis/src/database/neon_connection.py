import os
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.pool import QueuePool
from contextlib import contextmanager
from typing import Generator, Optional
import logging
from urllib.parse import quote_plus
from dotenv import load_dotenv

logger = logging.getLogger(__name__)

load_dotenv()

class NeonConnection:
    _instance = None
    _engine = None
    _session_factory = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self):
        if not hasattr(self, 'initialized'):
            self.initialized = True
            self._setup_connection()
    
    def _setup_connection(self):
        database_url = self._build_database_url()
        
        self._engine = create_engine(
            database_url,
            poolclass=QueuePool,
            pool_size=5,
            max_overflow=10,
            pool_pre_ping=True,
            pool_recycle=3600,
            echo=os.getenv("DATABASE_ECHO", "false").lower() == "true"
        )
        
        self._session_factory = sessionmaker(
            bind=self._engine,
            autocommit=False,
            autoflush=False
        )
    
    def _build_database_url(self) -> str:
        host = os.getenv("NEON_HOST")
        port = os.getenv("NEON_PORT", "5432")
        database = os.getenv("NEON_DATABASE")
        username = os.getenv("NEON_USERNAME")
        password = os.getenv("NEON_PASSWORD")
        
        if not all([host, database, username, password]):
            raise ValueError("Missing required Neon database environment variables")
        
        encoded_password = quote_plus(password)
        
        return f"postgresql://{username}:{encoded_password}@{host}:{port}/{database}?sslmode=require"
    
    def get_engine(self):
        if self._engine is None:
            self._setup_connection()
        return self._engine
    
    def get_session(self) -> Session:
        if self._session_factory is None:
            self._setup_connection()
        return self._session_factory()
    
    @contextmanager
    def get_session_context(self) -> Generator[Session, None, None]:
        session = self.get_session()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()
    
    def test_connection(self) -> bool:
        try:
            with self.get_session_context() as session:
                session.execute(text("SELECT 1"))
            return True
        except Exception as e:
            logger.error(f"Database connection test failed: {e}")
            return False
    
    def close_connections(self):
        if self._engine:
            self._engine.dispose()
            self._engine = None
            self._session_factory = None

_neon_connection = NeonConnection()

def get_database_engine():
    return _neon_connection.get_engine()

def get_database_session() -> Session:
    return _neon_connection.get_session()

@contextmanager
def get_database_session_context() -> Generator[Session, None, None]:
    with _neon_connection.get_session_context() as session:
        yield session

def test_database_connection() -> bool:
    return _neon_connection.test_connection()

def close_database_connections():
    _neon_connection.close_connections()

def create_all_tables():
    from .models import Base
    engine = get_database_engine()
    Base.metadata.create_all(bind=engine)

def drop_all_tables():
    from .models import Base
    engine = get_database_engine()
    Base.metadata.drop_all(bind=engine)

class DatabaseSessionManager:
    def __init__(self):
        self._session: Optional[Session] = None
    
    @property
    def session(self) -> Session:
        if self._session is None:
            self._session = get_database_session()
        return self._session
    
    def commit(self):
        if self._session:
            self._session.commit()
    
    def rollback(self):
        if self._session:
            self._session.rollback()
    
    def close(self):
        if self._session:
            self._session.close()
            self._session = None
    
    def __enter__(self):
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type:
            self.rollback()
        else:
            self.commit()
        self.close()