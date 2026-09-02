"""Fail-closed registry for data-only Domain Packs."""

from __future__ import annotations

from pathlib import Path

from smartbuy.domain_packs.loader import (
    DomainPackLoader,
    DomainPackValidationError,
    LoadedDomainPack,
)


class DomainPackRegistry:
    """Discovers packs by manifest identity without importing pack code."""

    def __init__(self, root: Path | str | None = None) -> None:
        self.root = (
            Path(root).resolve()
            if root is not None
            else Path(__file__).resolve().parent
        )

    def list(self) -> dict[str, Path]:
        found: dict[str, Path] = {}
        if not self.root.is_dir():
            return found
        for candidate in sorted(item for item in self.root.iterdir() if item.is_dir()):
            if not (candidate / "manifest.json").is_file():
                continue
            loaded = DomainPackLoader().load(candidate)
            if loaded.domain_id in found:
                raise DomainPackValidationError("duplicate domain id in registry")
            found[loaded.domain_id] = candidate
        return found

    def load(self, domain_id: str) -> LoadedDomainPack:
        path = self.list().get(domain_id)
        if path is None:
            raise DomainPackValidationError("requested domain pack is unavailable")
        return DomainPackLoader().load(path)
