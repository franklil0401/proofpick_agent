"""Load the committed, redacted V2 portfolio replay bundle."""

from __future__ import annotations

from pathlib import Path

from .models import PortfolioDemoBundle


DEMO_DATA_PATH = (
    Path(__file__).resolve().parents[2]
    / "vendor"
    / "youtu-rag"
    / "frontend"
    / "rag_webui"
    / "assets"
    / "data"
    / "proofpick-demos.json"
)


def load_demo_bundle(path: Path = DEMO_DATA_PATH) -> PortfolioDemoBundle:
    return PortfolioDemoBundle.model_validate_json(path.read_text(encoding="utf-8"))
