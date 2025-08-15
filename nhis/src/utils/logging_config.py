import logging
import logging.config
import os
from datetime import datetime
from pathlib import Path


def setup_logging(log_level: str = "INFO", log_dir: str = "logs"):
    log_path = Path(log_dir)
    log_path.mkdir(exist_ok=True)
    
    today = datetime.now().strftime("%Y-%m-%d")
    
    config = {
        'version': 1,
        'disable_existing_loggers': False,
        'formatters': {
            'detailed': {
                'format': '%(asctime)s - %(name)s - %(levelname)s - %(funcName)s:%(lineno)d - %(message)s'
            },
            'simple': {
                'format': '%(asctime)s - %(levelname)s - %(message)s'
            },
            'json': {
                'format': '{"timestamp": "%(asctime)s", "logger": "%(name)s", "level": "%(levelname)s", "function": "%(funcName)s", "line": %(lineno)d, "message": "%(message)s"}'
            }
        },
        'handlers': {
            'console': {
                'class': 'logging.StreamHandler',
                'level': log_level,
                'formatter': 'simple',
                'stream': 'ext://sys.stdout'
            },
            'file': {
                'class': 'logging.handlers.RotatingFileHandler',
                'level': log_level,
                'formatter': 'detailed',
                'filename': log_path / f'nhis_expert_system_{today}.log',
                'maxBytes': 10485760,
                'backupCount': 5,
                'encoding': 'utf8'
            },
            'error_file': {
                'class': 'logging.handlers.RotatingFileHandler',
                'level': 'ERROR',
                'formatter': 'detailed',
                'filename': log_path / f'nhis_errors_{today}.log',
                'maxBytes': 10485760,
                'backupCount': 5,
                'encoding': 'utf8'
            },
            'audit_file': {
                'class': 'logging.handlers.RotatingFileHandler',
                'level': 'INFO',
                'formatter': 'json',
                'filename': log_path / f'nhis_audit_{today}.log',
                'maxBytes': 10485760,
                'backupCount': 30,
                'encoding': 'utf8'
            }
        },
        'loggers': {
            'nhis_expert_system': {
                'level': log_level,
                'handlers': ['console', 'file'],
                'propagate': False
            },
            'nhis_expert_system.audit': {
                'level': 'INFO',
                'handlers': ['audit_file'],
                'propagate': False
            },
            'nhis_expert_system.performance': {
                'level': 'INFO',
                'handlers': ['file'],
                'propagate': False
            },
            'nhis_expert_system.database': {
                'level': log_level,
                'handlers': ['console', 'file'],
                'propagate': False
            },
            'nhis_expert_system.rules': {
                'level': log_level,
                'handlers': ['console', 'file'],
                'propagate': False
            },
            'nhis_expert_system.calculators': {
                'level': log_level,
                'handlers': ['console', 'file'],
                'propagate': False
            },
            'nhis_expert_system.services': {
                'level': log_level,
                'handlers': ['console', 'file'],
                'propagate': False
            }
        },
        'root': {
            'level': 'WARNING',
            'handlers': ['console', 'error_file']
        }
    }
    
    logging.config.dictConfig(config)


def get_logger(name: str) -> logging.Logger:
    if not name.startswith('nhis_expert_system'):
        name = f'nhis_expert_system.{name}'
    return logging.getLogger(name)


def get_audit_logger() -> logging.Logger:
    return logging.getLogger('nhis_expert_system.audit')


def get_performance_logger() -> logging.Logger:
    return logging.getLogger('nhis_expert_system.performance')