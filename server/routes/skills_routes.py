"""Skills catalog — the domain-knowledge skill packs (SKILL.md) the agent loads.

Read-only listing for the UI. Skills are code-defined (SKILL.md files), not per-org,
so this is org-agnostic but gated behind a read permission.
"""

import logging
from flask import Blueprint, jsonify
from utils.auth.rbac_decorators import require_permission

logger = logging.getLogger(__name__)
skills_bp = Blueprint("skills", __name__)


@skills_bp.route("/api/skills", methods=["GET"])
@require_permission("connectors", "read")
def list_skills(user_id):
    try:
        from chat.backend.agent.skills.registry import SkillRegistry
        reg = SkillRegistry.get_instance()
        out = []
        for sid in reg.get_all_skill_ids():
            m = reg.get_skill_metadata(sid)
            if not m:
                continue
            out.append({
                "id": m.id,
                "name": m.name,
                "category": m.category,
                "tools": list(m.tools or []),
                "summary": (m.index or "").strip()[:400],
                "requires_connection": bool(m.connection_check),
            })
        out.sort(key=lambda x: (x["category"], x["name"]))
        return jsonify({"skills": out, "count": len(out)})
    except Exception:
        logger.exception("skills: failed to list")
        return jsonify({"error": "Failed to load skills"}), 500
