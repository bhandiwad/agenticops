"""Every Flask route must be authenticated or explicitly allowlisted as public.

Extends the connector-only RBAC test to ALL blueprints under server/routes/. A route
function must carry an RBAC decorator (`@require_permission` / `@require_auth_only`) OR be
allowlisted below with a reason. New unprotected routes fail CI.

Public routes remain safe because the global internal-secret `before_request` gate fronts
the whole API and Flask is never internet-exposed — but each exemption must be deliberate.
"""

import ast
from pathlib import Path
from typing import List, Tuple

ROUTES_DIR = Path(__file__).resolve().parent.parent.parent / "routes"
RBAC_DECORATORS = {"require_permission", "require_auth_only"}

# Public by *function-name* pattern: OAuth callbacks (state-param authed), inbound webhooks
# (HMAC/signing-secret or URL-token authed), health checks, and static setup scripts.
PUBLIC_NAME_SUFFIXES = ("callback", "webhook", "_script", "_script_ps1")
PUBLIC_NAMES = {
    "health", "healthz", "health_check", "readiness", "readiness_check",
    "deep_readiness_check", "liveness", "liveness_check", "home", "index",
    "login", "register", "logout", "refresh", "verify_email", "reset_password",
}

# Public by explicit "<relpath>::<func>" — reviewed exemptions that don't match a pattern.
PUBLIC_ROUTES = {
    # Inbound event webhooks authenticated by signing secret / HMAC (not RBAC):
    "slack/slack_events.py::slack_events",            # verify_slack_signature
    "slack/slack_events.py::slack_interactions",      # verify_slack_signature
    "google_chat/google_chat_events.py::google_chat_events",  # verify_google_chat_request
    # Public workflow webhook — authenticated by a per-trigger secret token in the URL:
    "registry/registry_routes.py::wf2_hook",
    # Dev-only debug endpoint — returns 404 in non-dev (see debug_routes.py):
    "debug/debug_routes.py::test_endpoint",
    # Prometheus scrape endpoint — aggregate-only, no tenant data; protected by the
    # global INTERNAL_API_SECRET before_request gate (not RBAC), scraped internally:
    "platform_metrics_routes.py::metrics_prometheus",
}


def _decorator_name(node: ast.expr) -> str:
    if isinstance(node, ast.Call):
        return _decorator_name(node.func)
    if isinstance(node, ast.Attribute):
        return node.attr
    if isinstance(node, ast.Name):
        return node.id
    return ""


def _find_route_functions(filepath: Path) -> List[Tuple[str, int, bool]]:
    try:
        tree = ast.parse(filepath.read_text(), filename=str(filepath))
    except SyntaxError:
        return []
    results: List[Tuple[str, int, bool]] = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        has_route = has_rbac = False
        for dec in node.decorator_list:
            name = _decorator_name(dec)
            if name and "route" in name:
                has_route = True
            if name and name in RBAC_DECORATORS:
                has_rbac = True
        if has_route:
            results.append((node.name, node.lineno, has_rbac))
    return results


def _is_public(func_name: str, key: str) -> bool:
    if key in PUBLIC_ROUTES or func_name in PUBLIC_NAMES:
        return True
    return any(func_name.endswith(s) for s in PUBLIC_NAME_SUFFIXES)


def _uncovered() -> List[str]:
    uncovered: List[str] = []
    for f in sorted(ROUTES_DIR.rglob("*.py")):
        if f.name == "__init__.py":
            continue
        rel = f.relative_to(ROUTES_DIR).as_posix()
        for func_name, lineno, has_rbac in _find_route_functions(f):
            if has_rbac:
                continue
            if not _is_public(func_name, f"{rel}::{func_name}"):
                uncovered.append(f"{rel}:{lineno} {func_name}")
    return sorted(uncovered)


def test_all_routes_authenticated_or_allowlisted():
    uncovered = _uncovered()
    assert not uncovered, (
        "Routes without an RBAC decorator and not allowlisted:\n  "
        + "\n  ".join(uncovered)
        + "\n\nAdd @require_permission/@require_auth_only, or allowlist in PUBLIC_ROUTES/"
        "PUBLIC_NAMES with a reason (health / pre-login / OAuth callback / signed webhook)."
    )
