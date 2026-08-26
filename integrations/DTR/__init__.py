"""
DTR - Deep Tabular Research Framework

A modular framework for answering complex tabular queries through:
- Action decomposition (ADO)
- Path planning (MCTS) 
- Step-by-step execution with rewards (SMG)

Version: 1.0.0
"""

from .src import DTRFramework, Operator, ExecutionPath
from .utils import logger, LLMClient, Config, load_config

__all__ = [
    'DTRFramework',
    'Operator',
    'ExecutionPath',
    'logger',
    'LLMClient',
    'Config',
    'load_config'
]

__version__ = '1.0.0'
__author__ = 'DTR Team'

