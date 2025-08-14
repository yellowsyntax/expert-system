from .episode_tracking_queries import EpisodeTrackingQueries
from .provider_capability_queries import ProviderCapabilityQueries
from .readmission_queries import ReadmissionQueries


class QueryManager:
    def __init__(self, db_session):
        self.db_session = db_session
        self.episode_queries = EpisodeTrackingQueries(db_session)
        self.provider_queries = ProviderCapabilityQueries(db_session)
        self.readmission_queries = ReadmissionQueries(db_session)
    
    def get_episode_queries(self) -> EpisodeTrackingQueries:
        return self.episode_queries
    
    def get_provider_queries(self) -> ProviderCapabilityQueries:
        return self.provider_queries
    
    def get_readmission_queries(self) -> ReadmissionQueries:
        return self.readmission_queries


__all__ = [
    "EpisodeTrackingQueries",
    "ProviderCapabilityQueries", 
    "ReadmissionQueries",
    "QueryManager"
]