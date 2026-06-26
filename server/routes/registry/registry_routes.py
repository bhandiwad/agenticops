"""Tool catalog + agent registry API (read + per-org overlay management).

Reads (connectors:read):
  * GET /api/registry/tools  — native tool catalog with risk + capabilities,
    annotated with per-org enable/disable (org_tool_availability).
  * GET /api/registry/agents — typed agent registry with per-org overrides
    (agent_overrides: enabled + max_turns/max_seconds/model).

Writes (admin:access — org governance, mirrors tool-permissions):
  * PUT /api/registry/tools/<tool_name>   {enabled}
  * PUT /api/registry/agents/<agent_name> {enabled, max_turns?, max_seconds?, model?}

Tool risk/capabilities and agent prompts remain code/markdown-defined; only the
per-org overlay fields are editable here.
"""

import logging

from flask import jsonify, request

from utils.auth.rbac_decorators import require_permission
from utils.auth.stateless_auth import get_org_id_from_request

logger = logging.getLogger(__name__)

from . import registry_bp

_ERR_NO_ORG = "No org context"


@registry_bp.route("/tools", methods=["GET"])
@require_permission("connectors", "read")
def list_tools(user_id):
    """Return the native tool catalog with risk/capability + per-org enabled state."""
    try:
        from chat.backend.agent.tools.tool_registry import (
            KNOWN_CAPABILITIES,
            merge_availability,
            serialize_catalog,
        )
        from services.registry.overrides import get_tool_availability

        rows = serialize_catalog()
        org_id = get_org_id_from_request()
        availability = {}
        if org_id:
            try:
                availability = get_tool_availability(user_id, org_id)
            except Exception:
                logger.exception("registry: failed to load tool availability; defaulting to enabled")
        rows = merge_availability(rows, availability)
        return jsonify({
            "tools": rows,
            "count": len(rows),
            "capabilities": sorted(KNOWN_CAPABILITIES),
        })
    except Exception:
        logger.exception("registry: failed to serialize tool catalog")
        return jsonify({"error": "Failed to load tool catalog"}), 500


@registry_bp.route("/tools/<tool_name>", methods=["PUT"])
@require_permission("admin", "access")
def set_tool(user_id, tool_name):
    """Enable/disable a catalog tool for the org."""
    from chat.backend.agent.tools.tool_registry import get_tool_spec
    from services.registry.overrides import set_tool_availability

    if get_tool_spec(tool_name) is None:
        return jsonify({"error": f"Unknown tool: {tool_name}"}), 400
    org_id = get_org_id_from_request()
    if not org_id:
        return jsonify({"error": _ERR_NO_ORG}), 400
    body = request.get_json(silent=True) or {}
    if not isinstance(body.get("enabled"), bool):
        return jsonify({"error": "`enabled` must be a boolean"}), 400

    try:
        set_tool_availability(user_id, org_id, tool_name, body["enabled"])
    except Exception:
        logger.exception("registry: failed to set tool availability")
        return jsonify({"error": "Failed to update tool"}), 500
    return jsonify({"tool_name": tool_name, "enabled": body["enabled"]})


@registry_bp.route("/agents", methods=["GET"])
@require_permission("connectors", "read")
def list_agents(user_id):
    """Return the typed agent registry with per-org overrides applied."""
    try:
        from chat.backend.agent.orchestrator.role_registry import (
            RoleRegistry,
            apply_agent_override,
        )
        from services.registry.overrides import get_agent_overrides

        agents = RoleRegistry.get_instance().serialize()
        for a in agents:
            a["custom"] = False
        org_id = get_org_id_from_request()
        overrides = {}
        if org_id:
            try:
                overrides = get_agent_overrides(user_id, org_id)
            except Exception:
                logger.exception("registry: failed to load agent overrides; using defaults")
            try:
                from services.registry.custom_agents import list_custom_agents
                for c in list_custom_agents(user_id, org_id):
                    agents.append({
                        "name": c["name"], "kind": c["kind"], "description": c["description"],
                        "capability_tags": c["capability_tags"], "max_turns": c["max_turns"],
                        "max_seconds": c["max_seconds"], "rca_priority": 200,
                        "model": c["model"], "prompt": c["prompt"], "custom": True,
                    })
            except Exception:
                logger.exception("registry: failed to load custom agents")
        agents = [apply_agent_override(a, overrides.get(a["name"])) for a in agents]
        kinds = sorted({a["kind"] for a in agents})
        return jsonify({"agents": agents, "count": len(agents), "kinds": kinds})
    except Exception:
        logger.exception("registry: failed to serialize agent registry")
        return jsonify({"error": "Failed to load agent registry"}), 500


@registry_bp.route("/agents", methods=["POST"])
@require_permission("admin", "access")
def create_agent(user_id):
    """Create (or upsert) a custom org agent."""
    org_id = get_org_id_from_request()
    if not org_id:
        return jsonify({"error": _ERR_NO_ORG}), 400
    body = request.get_json(silent=True) or {}
    try:
        from services.registry.custom_agents import create_custom_agent
        create_custom_agent(
            user_id, org_id,
            name=(body.get("name") or "").strip(),
            kind=(body.get("kind") or "investigator").strip(),
            description=body.get("description") or "",
            capability_tags=body.get("capability_tags") or [],
            prompt=body.get("prompt") or "",
            max_turns=int(body.get("max_turns") or 16),
            max_seconds=int(body.get("max_seconds") or 360),
            model=body.get("model") or None,
        )
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception:
        logger.exception("registry: failed to create custom agent")
        return jsonify({"error": "Failed to create agent"}), 500
    return jsonify({"name": body.get("name")}), 201


@registry_bp.route("/agents/<agent_name>", methods=["DELETE"])
@require_permission("admin", "access")
def delete_agent(user_id, agent_name):
    from chat.backend.agent.orchestrator.role_registry import RoleRegistry
    if RoleRegistry.get_instance().get(agent_name) is not None:
        return jsonify({"error": "Cannot delete a built-in agent"}), 400
    org_id = get_org_id_from_request()
    if not org_id:
        return jsonify({"error": _ERR_NO_ORG}), 400
    try:
        from services.registry.custom_agents import delete_custom_agent
        if not delete_custom_agent(user_id, org_id, agent_name):
            return jsonify({"error": "Agent not found"}), 404
    except Exception:
        logger.exception("registry: failed to delete custom agent")
        return jsonify({"error": "Failed to delete agent"}), 500
    return jsonify({"name": agent_name, "deleted": True})


@registry_bp.route("/agents/<agent_name>", methods=["PUT"])
@require_permission("admin", "access")
def set_agent(user_id, agent_name):
    """Set the per-org override for an agent (enabled + limits + model)."""
    from chat.backend.agent.orchestrator.role_registry import RoleRegistry
    from services.registry.overrides import set_agent_override

    if RoleRegistry.get_instance().get(agent_name) is None:
        return jsonify({"error": f"Unknown agent: {agent_name}"}), 400
    org_id = get_org_id_from_request()
    if not org_id:
        return jsonify({"error": _ERR_NO_ORG}), 400
    body = request.get_json(silent=True) or {}
    if not isinstance(body.get("enabled"), bool):
        return jsonify({"error": "`enabled` must be a boolean"}), 400

    def _opt_int(key):
        v = body.get(key)
        if v is None or v == "":
            return None
        try:
            return int(v)
        except (TypeError, ValueError):
            return None

    model = body.get("model") or None
    try:
        set_agent_override(
            user_id, org_id, agent_name,
            enabled=body["enabled"],
            max_turns=_opt_int("max_turns"),
            max_seconds=_opt_int("max_seconds"),
            model=model,
        )
    except Exception:
        logger.exception("registry: failed to set agent override")
        return jsonify({"error": "Failed to update agent"}), 500
    return jsonify({"agent_name": agent_name, "enabled": body["enabled"]})


@registry_bp.route("/triggers", methods=["GET"])
@require_permission("connectors", "read")
def list_triggers(user_id):
    """Return the lifecycle-event routing table with per-org enabled state."""
    try:
        from services.routing.events import EVENT_TYPES
        from services.routing.trigger_router import default_routing_table
        from services.routing.rules import get_trigger_rules

        table = default_routing_table()
        org_id = get_org_id_from_request()
        rules = {}
        custom_by_event = {}
        if org_id:
            try:
                rules = get_trigger_rules(user_id, org_id)
            except Exception:
                logger.exception("registry: failed to load trigger rules; defaulting to enabled")
            try:
                from services.routing.custom_routes import list_custom_routes
                for r in list_custom_routes(user_id, org_id):
                    custom_by_event.setdefault(r["event_type"], []).append(r)
            except Exception:
                logger.exception("registry: failed to load custom routes")

        routes = []
        for et in EVENT_TYPES:
            builtin = [
                {"target_type": s["target_type"], "ref": s["ref"], "match": s.get("match"), "custom": False}
                for s in table.get(et, [])
            ]
            custom = [
                {"target_type": c["target_type"], "ref": c["target_ref"], "match": c.get("match"),
                 "custom": True, "id": c["id"], "enabled": c["enabled"]}
                for c in custom_by_event.get(et, [])
            ]
            routes.append({
                "event_type": et,
                "steps": builtin + custom,
                "enabled": rules.get(et, True),
            })
        return jsonify({"routes": routes, "event_types": list(EVENT_TYPES)})
    except Exception:
        logger.exception("registry: failed to build trigger routing table")
        return jsonify({"error": "Failed to load triggers"}), 500


@registry_bp.route("/trigger-routes", methods=["POST"])
@require_permission("admin", "access")
def create_trigger_route(user_id):
    """Add a custom route step (agent/workflow) to a lifecycle event."""
    org_id = get_org_id_from_request()
    if not org_id:
        return jsonify({"error": _ERR_NO_ORG}), 400
    body = request.get_json(silent=True) or {}
    try:
        from services.routing.custom_routes import create_custom_route
        route_id = create_custom_route(
            user_id, org_id,
            event_type=(body.get("event_type") or "").strip(),
            target_type=(body.get("target_type") or "agent").strip(),
            target_ref=(body.get("target_ref") or "").strip(),
            match=body.get("match") or None,
        )
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception:
        logger.exception("registry: failed to create custom route")
        return jsonify({"error": "Failed to create route"}), 500
    return jsonify({"id": route_id}), 201


@registry_bp.route("/trigger-routes/<route_id>", methods=["DELETE"])
@require_permission("admin", "access")
def delete_trigger_route(user_id, route_id):
    org_id = get_org_id_from_request()
    if not org_id:
        return jsonify({"error": _ERR_NO_ORG}), 400
    try:
        from services.routing.custom_routes import delete_custom_route
        if not delete_custom_route(user_id, org_id, route_id):
            return jsonify({"error": "Route not found"}), 404
    except Exception:
        logger.exception("registry: failed to delete custom route")
        return jsonify({"error": "Failed to delete route"}), 500
    return jsonify({"id": route_id, "deleted": True})


@registry_bp.route("/triggers/<event_type>", methods=["PUT"])
@require_permission("admin", "access")
def set_trigger(user_id, event_type):
    """Enable/disable a lifecycle route for the org."""
    from services.routing.events import EVENT_TYPES
    from services.routing.rules import set_trigger_rule

    if event_type not in EVENT_TYPES:
        return jsonify({"error": f"Unknown event_type: {event_type}"}), 400
    org_id = get_org_id_from_request()
    if not org_id:
        return jsonify({"error": _ERR_NO_ORG}), 400
    body = request.get_json(silent=True) or {}
    if not isinstance(body.get("enabled"), bool):
        return jsonify({"error": "`enabled` must be a boolean"}), 400

    try:
        set_trigger_rule(user_id, org_id, event_type, body["enabled"])
    except Exception:
        logger.exception("registry: failed to set trigger rule")
        return jsonify({"error": "Failed to update trigger"}), 500
    return jsonify({"event_type": event_type, "enabled": body["enabled"]})


# --------------------------------------------------------------------------- #
# MCP server registry
# --------------------------------------------------------------------------- #
@registry_bp.route("/mcp-servers", methods=["GET"])
@require_permission("connectors", "read")
def list_mcp(user_id):
    org_id = get_org_id_from_request()
    if not org_id:
        return jsonify({"error": _ERR_NO_ORG}), 400
    try:
        from services.registry.mcp_servers import list_mcp_servers
        servers = list_mcp_servers(user_id, org_id)
        return jsonify({"servers": servers, "count": len(servers)})
    except Exception:
        logger.exception("registry: failed to list mcp servers")
        return jsonify({"error": "Failed to load MCP servers"}), 500


@registry_bp.route("/mcp-servers", methods=["POST"])
@require_permission("admin", "access")
def create_mcp(user_id):
    org_id = get_org_id_from_request()
    if not org_id:
        return jsonify({"error": _ERR_NO_ORG}), 400
    body = request.get_json(silent=True) or {}
    name = (body.get("name") or "").strip()
    if not name:
        return jsonify({"error": "`name` is required"}), 400
    try:
        from services.registry.mcp_servers import create_mcp_server
        server_id = create_mcp_server(
            user_id, org_id,
            name=name,
            transport=(body.get("transport") or "http"),
            url=body.get("url"),
            read_only=bool(body.get("read_only", True)),
            auth_token=body.get("auth_token") or None,
        )
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception:
        logger.exception("registry: failed to create mcp server")
        return jsonify({"error": "Failed to create MCP server"}), 500
    return jsonify({"id": server_id, "name": name}), 201


@registry_bp.route("/mcp-servers/<server_id>", methods=["PUT"])
@require_permission("admin", "access")
def update_mcp(user_id, server_id):
    org_id = get_org_id_from_request()
    if not org_id:
        return jsonify({"error": _ERR_NO_ORG}), 400
    body = request.get_json(silent=True) or {}
    try:
        from services.registry.mcp_servers import update_mcp_server
        ok = update_mcp_server(
            user_id, org_id, server_id,
            enabled=body.get("enabled"),
            read_only=body.get("read_only"),
        )
    except Exception:
        logger.exception("registry: failed to update mcp server")
        return jsonify({"error": "Failed to update MCP server"}), 500
    if not ok:
        return jsonify({"error": "MCP server not found or nothing to update"}), 404
    return jsonify({"id": server_id})


@registry_bp.route("/mcp-servers/<server_id>", methods=["DELETE"])
@require_permission("admin", "access")
def delete_mcp(user_id, server_id):
    org_id = get_org_id_from_request()
    if not org_id:
        return jsonify({"error": _ERR_NO_ORG}), 400
    try:
        from services.registry.mcp_servers import delete_mcp_server
        ok = delete_mcp_server(user_id, org_id, server_id)
    except Exception:
        logger.exception("registry: failed to delete mcp server")
        return jsonify({"error": "Failed to delete MCP server"}), 500
    if not ok:
        return jsonify({"error": "MCP server not found"}), 404
    return jsonify({"id": server_id, "deleted": True})


# --------------------------------------------------------------------------- #
# Workflow registry (compose agents + actions + approval gates)
# --------------------------------------------------------------------------- #
@registry_bp.route("/workflows", methods=["GET"])
@require_permission("connectors", "read")
def list_workflows(user_id):
    try:
        from services.workflows.workflow_registry import DEFAULT_WORKFLOWS, serialize_workflow
        from services.workflows.rules import get_workflow_rules

        org_id = get_org_id_from_request()
        rules = {}
        custom = []
        if org_id:
            try:
                rules = get_workflow_rules(user_id, org_id)
            except Exception:
                logger.exception("registry: failed to load workflow rules; defaulting to enabled")
            try:
                from services.workflows.custom import list_custom_workflows
                custom = list_custom_workflows(user_id, org_id)
            except Exception:
                logger.exception("registry: failed to load custom workflows")
        workflows = [
            {**serialize_workflow(wf, enabled=rules.get(key, True)), "custom": False}
            for key, wf in DEFAULT_WORKFLOWS.items()
        ]
        workflows.extend(custom)
        return jsonify({"workflows": workflows, "count": len(workflows)})
    except Exception:
        logger.exception("registry: failed to build workflow list")
        return jsonify({"error": "Failed to load workflows"}), 500


@registry_bp.route("/workflows", methods=["POST"])
@require_permission("admin", "access")
def create_workflow(user_id):
    org_id = get_org_id_from_request()
    if not org_id:
        return jsonify({"error": _ERR_NO_ORG}), 400
    body = request.get_json(silent=True) or {}
    try:
        from services.workflows.custom import create_custom_workflow
        create_custom_workflow(
            user_id, org_id,
            key=(body.get("key") or "").strip(),
            name=(body.get("name") or "").strip() or (body.get("key") or ""),
            kind=body.get("kind") or "llm",
            description=body.get("description") or "",
            steps=body.get("steps") or [],
        )
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception:
        logger.exception("registry: failed to create custom workflow")
        return jsonify({"error": "Failed to create workflow"}), 500
    return jsonify({"key": body.get("key")}), 201


@registry_bp.route("/workflows/<workflow_key>", methods=["PUT"])
@require_permission("admin", "access")
def set_workflow(user_id, workflow_key):
    from services.workflows.workflow_registry import DEFAULT_WORKFLOWS
    from services.workflows.rules import set_workflow_rule
    from services.workflows.custom import set_custom_workflow_enabled

    org_id = get_org_id_from_request()
    if not org_id:
        return jsonify({"error": _ERR_NO_ORG}), 400
    body = request.get_json(silent=True) or {}
    if not isinstance(body.get("enabled"), bool):
        return jsonify({"error": "`enabled` must be a boolean"}), 400
    try:
        if workflow_key in DEFAULT_WORKFLOWS:
            set_workflow_rule(user_id, org_id, workflow_key, body["enabled"])
        elif not set_custom_workflow_enabled(user_id, org_id, workflow_key, body["enabled"]):
            return jsonify({"error": f"Unknown workflow: {workflow_key}"}), 404
    except Exception:
        logger.exception("registry: failed to set workflow rule")
        return jsonify({"error": "Failed to update workflow"}), 500
    return jsonify({"workflow_key": workflow_key, "enabled": body["enabled"]})


@registry_bp.route("/workflows/<workflow_key>", methods=["DELETE"])
@require_permission("admin", "access")
def delete_workflow(user_id, workflow_key):
    from services.workflows.workflow_registry import DEFAULT_WORKFLOWS
    if workflow_key in DEFAULT_WORKFLOWS:
        return jsonify({"error": "Cannot delete a built-in workflow"}), 400
    org_id = get_org_id_from_request()
    if not org_id:
        return jsonify({"error": _ERR_NO_ORG}), 400
    try:
        from services.workflows.custom import delete_custom_workflow
        if not delete_custom_workflow(user_id, org_id, workflow_key):
            return jsonify({"error": "Workflow not found"}), 404
    except Exception:
        logger.exception("registry: failed to delete custom workflow")
        return jsonify({"error": "Failed to delete workflow"}), 500
    return jsonify({"workflow_key": workflow_key, "deleted": True})


# --------------------------------------------------------------------------- #
# Prompt versioning
# --------------------------------------------------------------------------- #
@registry_bp.route("/prompts/<prompt_key>", methods=["GET"])
@require_permission("connectors", "read")
def list_prompts(user_id, prompt_key):
    org_id = get_org_id_from_request()
    if not org_id:
        return jsonify({"error": _ERR_NO_ORG}), 400
    try:
        from services.prompts.versions import list_prompt_versions
        return jsonify({"prompt_key": prompt_key, "versions": list_prompt_versions(user_id, org_id, prompt_key)})
    except Exception:
        logger.exception("registry: failed to list prompt versions")
        return jsonify({"error": "Failed to load prompt versions"}), 500


@registry_bp.route("/prompts/<prompt_key>", methods=["POST"])
@require_permission("admin", "access")
def create_prompt(user_id, prompt_key):
    org_id = get_org_id_from_request()
    if not org_id:
        return jsonify({"error": _ERR_NO_ORG}), 400
    body = request.get_json(silent=True) or {}
    content = body.get("content")
    if not content or not isinstance(content, str):
        return jsonify({"error": "`content` is required"}), 400
    try:
        from services.prompts.versions import create_prompt_version
        version = create_prompt_version(user_id, org_id, prompt_key, content, activate=bool(body.get("activate", True)))
    except Exception:
        logger.exception("registry: failed to create prompt version")
        return jsonify({"error": "Failed to create prompt version"}), 500
    return jsonify({"prompt_key": prompt_key, "version": version}), 201


@registry_bp.route("/prompts/<prompt_key>/activate/<int:version>", methods=["PUT"])
@require_permission("admin", "access")
def activate_prompt(user_id, prompt_key, version):
    org_id = get_org_id_from_request()
    if not org_id:
        return jsonify({"error": _ERR_NO_ORG}), 400
    try:
        from services.prompts.versions import activate_prompt_version
        ok = activate_prompt_version(user_id, org_id, prompt_key, version)
    except Exception:
        logger.exception("registry: failed to activate prompt version")
        return jsonify({"error": "Failed to activate prompt version"}), 500
    if not ok:
        return jsonify({"error": "Prompt version not found"}), 404
    return jsonify({"prompt_key": prompt_key, "version": version, "active": True})


# --------------------------------------------------------------------------- #
# Evidence store + run replay (incident-scoped, read-only)
# --------------------------------------------------------------------------- #
@registry_bp.route("/evidence", methods=["GET"])
@require_permission("incidents", "read")
def list_run_evidence(user_id):
    org_id = get_org_id_from_request()
    incident_id = request.args.get("incident_id")
    if not org_id or not incident_id:
        return jsonify({"error": "org context and incident_id required"}), 400
    try:
        from services.observability.evidence import list_evidence
        items = list_evidence(user_id, org_id, incident_id)
        return jsonify({"evidence": items, "count": len(items)})
    except Exception:
        logger.exception("registry: failed to list evidence")
        return jsonify({"error": "Failed to load evidence"}), 500


@registry_bp.route("/replay", methods=["GET"])
@require_permission("incidents", "read")
def replay_run(user_id):
    org_id = get_org_id_from_request()
    incident_id = request.args.get("incident_id")
    if not org_id or not incident_id:
        return jsonify({"error": "org context and incident_id required"}), 400
    try:
        from services.observability.replay import replay_incident
        steps = replay_incident(user_id, org_id, incident_id)
        return jsonify({"steps": steps, "count": len(steps)})
    except Exception:
        logger.exception("registry: failed to build replay")
        return jsonify({"error": "Failed to load replay"}), 500
