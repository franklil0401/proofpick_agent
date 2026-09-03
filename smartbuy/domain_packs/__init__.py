"""Validated Domain Pack loading and V1 compatibility adapters."""

from smartbuy.domain_packs.loader import (
    DEFAULT_MONITOR_PACK,
    DomainPackLoader,
    DomainPackValidationError,
    LoadedDomainPack,
)
from smartbuy.domain_packs.evaluator import ConstraintDecision, DomainConstraintEvaluator
from smartbuy.domain_packs.registry import DomainPackRegistry
from smartbuy.domain_packs.settings import DomainPackSettings
from smartbuy.domain_packs.category_router import (
    CategoryRoute,
    CategoryRouteStatus,
    CategoryRouter,
    DEFAULT_CATEGORY_REGISTRY,
)

__all__ = [
    "DEFAULT_MONITOR_PACK",
    "DomainPackLoader",
    "DomainPackSettings",
    "DomainPackValidationError",
    "LoadedDomainPack",
    "ConstraintDecision",
    "DomainConstraintEvaluator",
    "DomainPackRegistry",
    "CategoryRoute",
    "CategoryRouteStatus",
    "CategoryRouter",
    "DEFAULT_CATEGORY_REGISTRY",
]
