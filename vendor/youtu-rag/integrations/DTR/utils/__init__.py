"""
DTR Framework - Utilities Package

Independent utilities for the Deep Tabular Research framework.
No external dependencies on ExcelAgent or other projects.
"""

from .logger import logger, setup_logger, progress
from .llm_client import LLMClient
from .config import Config, load_config

__all__ = [
    'logger',
    'setup_logger', 
    'progress',
    'LLMClient',
    'Config',
    'load_config'
]

__version__ = '1.0.0'

