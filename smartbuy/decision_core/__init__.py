"""Domain-neutral query understanding and deterministic decision primitives.

Submodules are intentionally imported explicitly by consumers.  Keeping this
package initializer side-effect free prevents the Domain Pack loader and the
canonical-value layer from forming an import cycle.
"""
