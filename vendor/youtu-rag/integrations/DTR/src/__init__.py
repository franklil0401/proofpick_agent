"""
DTR Framework - Source Package

Deep Tabular Research framework for complex query answering.
"""

from .core.dtr_framework import DTRFramework
from .core.dtr_structures import (
    Operator, OperatorType, ExecutionPath, TableState,
    MCTSNode, SMGNode, RewardVector, ADOResult
)

__all__ = [
    'DTRFramework',
    'Operator',
    'OperatorType',
    'ExecutionPath',
    'TableState',
    'MCTSNode',
    'SMGNode',
    'RewardVector',
    'ADOResult'
]

__version__ = '1.0.0'

