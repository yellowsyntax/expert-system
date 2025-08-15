from typing import Dict, Any, Optional, List
from datetime import datetime, timedelta
from dataclasses import dataclass
from ..database.repositories import (
    EpisodeRepository, ClaimV2Repository, ClaimDecisionRepository
)
from ..database.queries.episode_tracking_queries import EpisodeTrackingQueries
import logging

logger = logging.getLogger(__name__)


@dataclass
class EpisodeInfo:
    episode_type: str
    visit_count: int
    first_visit_date: datetime
    last_visit_date: datetime
    days_span: int
    facilities: List[str]
    diagnoses: List[str]
    within_limits: bool
    limit_threshold: int
    remaining_visits: int


class EpisodeTrackingService:
    
    def __init__(self,
                 episode_repo: EpisodeRepository,
                 claim_repo: ClaimV2Repository,
                 decision_repo: ClaimDecisionRepository):
        
        self.episode_repo = episode_repo
        self.claim_repo = claim_repo
        self.decision_repo = decision_repo
        self.episode_queries = EpisodeTrackingQueries()
        
        # Episode limits configuration
        self.episode_limits = {
            'acute': {'visits': 3, 'days': 14},
            'chronic': {'visits': 6, 'days': 365},
            'antenatal': {'visits': 6, 'days': 280},
            'postnatal': {'visits': 3, 'days': 42}
        }
    
    def get_patient_episode_history(self, patient_id: str, 
                                   episode_type: str = None,
                                   lookback_days: int = 365) -> Dict[str, Any]:
        try:
            cutoff_date = datetime.utcnow() - timedelta(days=lookback_days)
            
            # Get episode history from database
            episodes = self.episode_repo.get_patient_episodes(
                patient_id=patient_id,
                episode_type=episode_type,
                start_date=cutoff_date
            )
            
            if not episodes:
                return {
                    'patient_id': patient_id,
                    'episode_type': episode_type,
                    'total_episodes': 0,
                    'episodes': [],
                    'current_status': 'no_episodes'
                }
            
            # Process episodes
            processed_episodes = []
            for episode in episodes:
                episode_info = self._process_episode(episode)
                processed_episodes.append(episode_info)
            
            # Calculate summary statistics
            summary = self._calculate_episode_summary(processed_episodes, episode_type)
            
            return {
                'patient_id': patient_id,
                'episode_type': episode_type or 'all',
                'lookback_days': lookback_days,
                'total_episodes': len(processed_episodes),
                'episodes': processed_episodes,
                'summary': summary,
                'last_updated': datetime.utcnow().isoformat()
            }
            
        except Exception as e:
            logger.error(f"Error getting episode history for patient {patient_id}: {str(e)}")
            return {
                'patient_id': patient_id,
                'error': str(e),
                'status': 'error'
            }
    
    def check_episode_limits(self, patient_id: str, new_visit_date: datetime,
                            episode_type: str, primary_diagnosis: str = None) -> Dict[str, Any]:
        try:
            if episode_type not in self.episode_limits:
                return {
                    'status': 'unknown_episode_type',
                    'episode_type': episode_type,
                    'valid_types': list(self.episode_limits.keys())
                }
            
            limits = self.episode_limits[episode_type]
            lookback_date = new_visit_date - timedelta(days=limits['days'])
            
            # Get recent visits of the same episode type
            recent_visits = self.episode_queries.get_recent_visits_by_type(
                patient_id=patient_id,
                episode_type=episode_type,
                start_date=lookback_date,
                end_date=new_visit_date
            )
            
            current_visit_count = len(recent_visits)
            limit_threshold = limits['visits']
            
            # Check if adding this visit would exceed limits
            would_exceed = (current_visit_count + 1) > limit_threshold
            remaining_visits = max(0, limit_threshold - current_visit_count - 1)
            
            # Additional checks for specific episode types
            additional_info = {}
            if episode_type == 'chronic':
                additional_info = self._check_chronic_episode_validity(
                    patient_id, primary_diagnosis, recent_visits
                )
            elif episode_type in ['antenatal', 'postnatal']:
                additional_info = self._check_pregnancy_episode_validity(
                    patient_id, episode_type, new_visit_date, recent_visits
                )
            
            return {
                'status': 'within_limits' if not would_exceed else 'exceeds_limits',
                'patient_id': patient_id,
                'episode_type': episode_type,
                'new_visit_date': new_visit_date.isoformat(),
                'current_visit_count': current_visit_count,
                'limit_threshold': limit_threshold,
                'remaining_visits': remaining_visits,
                'would_exceed': would_exceed,
                'lookback_period_days': limits['days'],
                'recent_visits': [
                    {
                        'visit_date': visit.service_date.isoformat(),
                        'facility_id': visit.facility_id,
                        'claim_id': visit.id
                    }
                    for visit in recent_visits
                ],
                'additional_info': additional_info
            }
            
        except Exception as e:
            logger.error(f"Error checking episode limits: {str(e)}")
            return {
                'status': 'error',
                'error': str(e)
            }
    
    def track_new_episode_visit(self, claim_id: str, patient_id: str,
                               episode_type: str, visit_date: datetime) -> Dict[str, Any]:
        try:
            # Create or update episode record
            episode_record = self.episode_repo.create_or_update_episode(
                patient_id=patient_id,
                episode_type=episode_type,
                visit_date=visit_date,
                claim_id=claim_id
            )
            
            # Update episode statistics
            self._update_episode_statistics(episode_record)
            
            return {
                'status': 'success',
                'episode_id': episode_record.id,
                'patient_id': patient_id,
                'episode_type': episode_type,
                'visit_date': visit_date.isoformat(),
                'total_visits': episode_record.visit_count,
                'episode_start_date': episode_record.start_date.isoformat(),
                'last_visit_date': episode_record.end_date.isoformat()
            }
            
        except Exception as e:
            logger.error(f"Error tracking episode visit: {str(e)}")
            return {
                'status': 'error',
                'error': str(e)
            }
    
    def get_episode_analytics(self, facility_id: str = None,
                             start_date: datetime = None,
                             end_date: datetime = None) -> Dict[str, Any]:
        try:
            if not start_date:
                start_date = datetime.utcnow() - timedelta(days=30)
            if not end_date:
                end_date = datetime.utcnow()
            
            # Get episode statistics
            episode_stats = self.episode_queries.get_episode_statistics(
                facility_id=facility_id,
                start_date=start_date,
                end_date=end_date
            )
            
            # Get violation statistics
            violation_stats = self.episode_queries.get_violation_statistics(
                facility_id=facility_id,
                start_date=start_date,
                end_date=end_date
            )
            
            # Calculate analytics
            analytics = {
                'analysis_period': {
                    'start_date': start_date.isoformat(),
                    'end_date': end_date.isoformat(),
                    'facility_id': facility_id
                },
                'episode_statistics': episode_stats,
                'violation_statistics': violation_stats,
                'trends': self._calculate_episode_trends(episode_stats),
                'recommendations': self._generate_episode_recommendations(violation_stats)
            }
            
            return analytics
            
        except Exception as e:
            logger.error(f"Error generating episode analytics: {str(e)}")
            return {
                'status': 'error',
                'error': str(e)
            }
    
    def _process_episode(self, episode) -> Dict[str, Any]:
        episode_info = {
            'episode_id': episode.id,
            'episode_type': episode.episode_type,
            'patient_id': episode.patient_id,
            'start_date': episode.start_date.isoformat(),
            'end_date': episode.end_date.isoformat(),
            'visit_count': episode.visit_count,
            'days_span': (episode.end_date - episode.start_date).days,
            'status': episode.status
        }
        
        # Add limit checking
        if episode.episode_type in self.episode_limits:
            limits = self.episode_limits[episode.episode_type]
            episode_info['within_limits'] = episode.visit_count <= limits['visits']
            episode_info['limit_threshold'] = limits['visits']
            episode_info['remaining_visits'] = max(0, limits['visits'] - episode.visit_count)
        
        return episode_info
    
    def _calculate_episode_summary(self, episodes: List[Dict[str, Any]], 
                                  episode_type: str = None) -> Dict[str, Any]:
        if not episodes:
            return {}
        
        total_episodes = len(episodes)
        total_visits = sum(ep['visit_count'] for ep in episodes)
        
        # Group by episode type
        by_type = {}
        for episode in episodes:
            ep_type = episode['episode_type']
            if ep_type not in by_type:
                by_type[ep_type] = {'count': 0, 'visits': 0, 'violations': 0}
            
            by_type[ep_type]['count'] += 1
            by_type[ep_type]['visits'] += episode['visit_count']
            
            if not episode.get('within_limits', True):
                by_type[ep_type]['violations'] += 1
        
        return {
            'total_episodes': total_episodes,
            'total_visits': total_visits,
            'by_episode_type': by_type,
            'most_recent_episode': max(episodes, key=lambda x: x['end_date']),
            'average_visits_per_episode': total_visits / total_episodes if total_episodes > 0 else 0
        }
    
    def _check_chronic_episode_validity(self, patient_id: str, primary_diagnosis: str,
                                       recent_visits: List) -> Dict[str, Any]:
        # Check if patient has verified chronic condition
        chronic_conditions = self.episode_queries.get_patient_chronic_conditions(patient_id)
        
        is_verified_chronic = False
        if primary_diagnosis:
            is_verified_chronic = any(
                primary_diagnosis.startswith(condition['icd10_prefix'])
                for condition in chronic_conditions
            )
        
        return {
            'verified_chronic_patient': is_verified_chronic,
            'chronic_conditions_count': len(chronic_conditions),
            'primary_diagnosis': primary_diagnosis
        }
    
    def _check_pregnancy_episode_validity(self, patient_id: str, episode_type: str,
                                         visit_date: datetime, recent_visits: List) -> Dict[str, Any]:
        # For pregnancy episodes, check for valid pregnancy period
        pregnancy_episodes = self.episode_queries.get_patient_pregnancy_episodes(
            patient_id=patient_id,
            reference_date=visit_date
        )
        
        active_pregnancy = None
        for pregnancy in pregnancy_episodes:
            # Check if visit falls within pregnancy period
            pregnancy_start = pregnancy.get('estimated_start_date')
            pregnancy_end = pregnancy.get('estimated_end_date')
            
            if pregnancy_start and pregnancy_end:
                if pregnancy_start <= visit_date <= pregnancy_end:
                    active_pregnancy = pregnancy
                    break
        
        return {
            'active_pregnancy_found': active_pregnancy is not None,
            'pregnancy_info': active_pregnancy,
            'episode_type': episode_type
        }
    
    def _update_episode_statistics(self, episode_record):
        # Update any cached statistics or derived fields
        try:
            # Calculate episode duration
            if episode_record.start_date and episode_record.end_date:
                duration_days = (episode_record.end_date - episode_record.start_date).days
                episode_record.duration_days = duration_days
            
            # Update status based on visit count and limits
            if episode_record.episode_type in self.episode_limits:
                limits = self.episode_limits[episode_record.episode_type]
                if episode_record.visit_count > limits['visits']:
                    episode_record.status = 'exceeds_limits'
                else:
                    episode_record.status = 'active'
            
            self.episode_repo.update(episode_record)
            
        except Exception as e:
            logger.error(f"Error updating episode statistics: {str(e)}")
    
    def _calculate_episode_trends(self, episode_stats: Dict[str, Any]) -> Dict[str, Any]:
        # Calculate trends from episode statistics
        trends = {}
        
        for episode_type, stats in episode_stats.items():
            if isinstance(stats, dict) and 'count' in stats:
                trends[episode_type] = {
                    'total_episodes': stats['count'],
                    'average_visits': stats.get('visits', 0) / max(1, stats['count']),
                    'violation_rate': stats.get('violations', 0) / max(1, stats['count']) * 100
                }
        
        return trends
    
    def _generate_episode_recommendations(self, violation_stats: Dict[str, Any]) -> List[str]:
        recommendations = []
        
        for episode_type, violations in violation_stats.items():
            if violations > 0:
                recommendations.append(
                    f"High episode limit violations detected for {episode_type} episodes ({violations} cases). "
                    f"Consider reviewing clinical protocols and patient education."
                )
        
        if not recommendations:
            recommendations.append("Episode patterns are within normal limits.")
        
        return recommendations