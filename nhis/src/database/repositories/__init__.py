from .base_repository import BaseRepository
from .claim_v2_repository import ClaimV2Repository
from .provider_repository import ProviderRepository
from .episode_repository import EpisodeRepository
from .audit_repository import AuditRepository
from .batch_repository import BatchRepository
from .tariff_repository import TariffRepository

class RepositoryFactory:
    def __init__(self, db_session):
        self.db_session = db_session
        self._repositories = {}
    
    def get_claim_repository(self) -> ClaimV2Repository:
        if 'claim' not in self._repositories:
            self._repositories['claim'] = ClaimV2Repository(self.db_session)
        return self._repositories['claim']
    
    def get_provider_repository(self) -> ProviderRepository:
        if 'provider' not in self._repositories:
            self._repositories['provider'] = ProviderRepository(self.db_session)
        return self._repositories['provider']
    
    def get_episode_repository(self) -> EpisodeRepository:
        if 'episode' not in self._repositories:
            self._repositories['episode'] = EpisodeRepository(self.db_session)
        return self._repositories['episode']
    
    def get_audit_repository(self) -> AuditRepository:
        if 'audit' not in self._repositories:
            self._repositories['audit'] = AuditRepository(self.db_session)
        return self._repositories['audit']
    
    def get_batch_repository(self) -> BatchRepository:
        if 'batch' not in self._repositories:
            self._repositories['batch'] = BatchRepository(self.db_session)
        return self._repositories['batch']
    
    def get_tariff_repository(self) -> TariffRepository:
        if 'tariff' not in self._repositories:
            self._repositories['tariff'] = TariffRepository(self.db_session)
        return self._repositories['tariff']
    
    def close_all(self):
        for repo in self._repositories.values():
            if hasattr(repo, 'close'):
                repo.close()
        self._repositories.clear()

__all__ = [
    "BaseRepository",
    "ClaimV2Repository", 
    "ProviderRepository",
    "EpisodeRepository",
    "AuditRepository", 
    "BatchRepository",
    "TariffRepository",
    "RepositoryFactory"
]