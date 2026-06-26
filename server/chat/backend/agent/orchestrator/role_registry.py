"""Singleton registry that loads and validates role .md files at startup."""

import logging
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import yaml

logger = logging.getLogger(__name__)

_ROLES_DIR = Path(__file__).parent / "roles"
_REQUIRED_FRONTMATTER_KEYS = frozenset(
    {"name", "description", "tools", "max_turns", "max_seconds", "rca_priority"}
)
def _split_frontmatter(text: str) -> Optional[tuple[str, str]]:
    """Linear-time split of a `---`-fenced YAML frontmatter from a markdown body.

    Replaces a regex (``^---\\s*\\n(.*?)\\n---\\s*\\n``) flagged by SonarQube as
    backtracking-prone (S5852). Returns ``(yaml_text, body_after_fence)`` if the
    text opens with a ``---`` line and contains a closing ``---`` line; else None.
    """
    lines = text.split("\n")
    if not lines or lines[0].rstrip() != "---":
        return None
    for i in range(1, len(lines)):
        if lines[i].rstrip() == "---":
            return "\n".join(lines[1:i]), "\n".join(lines[i + 1:])
    return None


# Default role kind. RCA sub-agent dispatch (triage/dispatcher/synthesis) only
# considers `investigator` roles; other kinds are lifecycle/typed agents
# (summarizer, correlation, notification, postmortem, ...) dispatched by the
# trigger router rather than RCA triage.
INVESTIGATOR_KIND = "investigator"


def apply_agent_override(agent: dict, override: Optional[dict]) -> dict:
    """Overlay a per-org override onto a serialized agent dict. Pure.

    ``override`` may set ``enabled`` and override ``max_turns`` / ``max_seconds``
    / ``model``. ``None`` fields in the override are ignored (keep the default).
    Absence of an override leaves the agent at its markdown defaults, enabled.
    """
    out = dict(agent)
    if not override:
        out.setdefault("enabled", True)
        return out
    out["enabled"] = bool(override.get("enabled", True))
    for key in ("max_turns", "max_seconds", "model"):
        val = override.get(key)
        if val is not None:
            out[key] = val
    return out


@dataclass
class RoleMeta:
    name: str
    description: str
    tools: list[str]  # capability tags
    max_turns: int
    max_seconds: int
    rca_priority: int
    model: Optional[str]  # None → falls back to ModelConfig.RCA_SUBAGENT_MODEL
    body: str             # markdown after frontmatter
    kind: str = INVESTIGATOR_KIND  # "investigator" (RCA) | lifecycle agent kind


class RoleRegistry:
    _instance: Optional["RoleRegistry"] = None
    _lock = threading.Lock()

    def __init__(self) -> None:
        self._roles: dict = {}
        self._load()

    @classmethod
    def get_instance(cls) -> "RoleRegistry":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    def _load(self) -> None:
        if not _ROLES_DIR.is_dir():
            logger.warning("RoleRegistry: roles directory not found at %s", _ROLES_DIR)
            return

        for md_file in sorted(_ROLES_DIR.glob("*.md")):
            try:
                raw = md_file.read_text(encoding="utf-8")
                parts = _split_frontmatter(raw)
                if parts is None:
                    logger.warning("RoleRegistry: %s has no frontmatter — skipping", md_file.name)
                    continue
                yaml_text, body = parts
                meta = yaml.safe_load(yaml_text)
                if not isinstance(meta, dict):
                    logger.warning("RoleRegistry: %s frontmatter is not a mapping — skipping", md_file.name)
                    continue
                missing = _REQUIRED_FRONTMATTER_KEYS - meta.keys()
                if missing:
                    logger.warning(
                        "RoleRegistry: %s missing keys %s — skipping", md_file.name, missing
                    )
                    continue
                role = RoleMeta(
                    name=str(meta["name"]),
                    description=str(meta["description"]),
                    tools=list(meta.get("tools") or []),
                    max_turns=int(meta["max_turns"]),
                    max_seconds=int(meta["max_seconds"]),
                    rca_priority=int(meta["rca_priority"]),
                    model=meta.get("model") or None,
                    body=body.strip(),
                    kind=str(meta.get("kind") or INVESTIGATOR_KIND),
                )
                self._roles[role.name] = role
                logger.info("RoleRegistry: loaded role %r", role.name)
            except Exception:
                logger.exception("RoleRegistry: failed to load %s", md_file.name)

    def list_all(self, kind: Optional[str] = None) -> list[RoleMeta]:
        """Return roles sorted by ``rca_priority``; optionally filter by ``kind``."""
        roles = sorted(self._roles.values(), key=lambda r: r.rca_priority)
        if kind is not None:
            roles = [r for r in roles if r.kind == kind]
        return roles

    def list_investigators(self) -> list[RoleMeta]:
        """Return only RCA investigator roles — the roles eligible for RCA
        sub-agent dispatch. Lifecycle/typed agents (summarizer, correlation,
        notification, ...) are excluded so they never enter RCA triage."""
        return self.list_all(kind=INVESTIGATOR_KIND)

    def get(self, name: str) -> Optional[RoleMeta]:
        return self._roles.get(name)

    def serialize(self) -> list[dict]:
        """Return all roles as JSON-able dicts for the Agents API/UI, ordered by
        (kind, rca_priority). The prompt body is included as ``prompt``."""
        rows = [
            {
                "name": r.name,
                "kind": r.kind,
                "description": r.description,
                "capability_tags": list(r.tools),
                "max_turns": r.max_turns,
                "max_seconds": r.max_seconds,
                "rca_priority": r.rca_priority,
                "model": r.model,
                "prompt": r.body,
            }
            for r in self.list_all()
        ]
        rows.sort(key=lambda r: (r["kind"], r["rca_priority"], r["name"]))
        return rows

    def list_available_roles(self, user_id: str, kind: Optional[str] = INVESTIGATOR_KIND) -> list[RoleMeta]:
        """Return roles whose capability tags intersect the user's reachable tags.

        Per-user filtering: a role is included only if at least one of its
        ``tools`` (capability tags) is contributed by a tool the user can
        actually invoke (built-in, or skill-owned and connected).

        ``kind`` defaults to ``investigator`` so RCA triage/synthesis only ever
        see investigator roles; pass ``kind=None`` to consider every kind.
        """
        from chat.backend.agent.orchestrator.select_skills import get_available_capability_tags
        available_tags = get_available_capability_tags(user_id)
        result = []
        for role in self.list_all(kind=kind):
            if any(tag in available_tags for tag in role.tools):
                result.append(role)

        # Per-org overlay: drop agents the org has explicitly disabled. Lazy
        # import keeps this module light for unit tests; fail-open so a lookup
        # error never removes roles RCA needs.
        try:
            from services.registry.overrides import get_disabled_agents_safe
            disabled = get_disabled_agents_safe(user_id)
            if disabled:
                result = [r for r in result if r.name not in disabled]
        except Exception:
            logger.debug("RoleRegistry: agent-override lookup failed (fail-open)")
        return result
