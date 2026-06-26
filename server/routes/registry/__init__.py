"""Read-only API for the tool and agent registries (AgenticOps Phase 1)."""

from flask import Blueprint

registry_bp = Blueprint("registry", __name__, url_prefix="/api/registry")

from . import registry_routes  # noqa: E402,F401  (registers routes on import)

__all__ = ["registry_bp"]
