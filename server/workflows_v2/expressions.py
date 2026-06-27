"""Pure, deterministic expression resolver for node configs.

Supports ``{{ $node.<id>.output.<path> }}`` and ``{{ $context.<path> }}``.
A config value that is exactly one expression returns the raw referenced value;
otherwise expressions are interpolated into the surrounding string.

Pure (only ``re``) so it is safe to call inside the Temporal workflow sandbox.
"""

from __future__ import annotations

import re
from typing import Any

_EXPR = re.compile(r"\{\{\s*(.*?)\s*\}\}")


def _eval_path(expr: str, scope: dict) -> Any:
    expr = expr.strip()
    if not expr.startswith("$"):
        return expr
    cur: Any = scope
    for part in expr.split("."):
        if isinstance(cur, dict):
            cur = cur.get(part)
        elif isinstance(cur, list):
            try:
                cur = cur[int(part)]
            except (ValueError, IndexError):
                return None
        else:
            return None
        if cur is None:
            return None
    return cur


def resolve(value: Any, scope: dict) -> Any:
    """Recursively resolve expressions in ``value`` against ``scope``.

    ``scope`` looks like ``{"$node": {nid: {"output": ...}}, "$context": {...}}``.
    """
    if isinstance(value, str):
        m = _EXPR.fullmatch(value.strip())
        if m:  # single, whole-string expression -> return raw referenced value
            return _eval_path(m.group(1), scope)
        return _EXPR.sub(lambda mo: str(_eval_path(mo.group(1), scope) if _eval_path(mo.group(1), scope) is not None else ""), value)
    if isinstance(value, dict):
        return {k: resolve(v, scope) for k, v in value.items()}
    if isinstance(value, list):
        return [resolve(v, scope) for v in value]
    return value


def truthy(value: Any) -> bool:
    """Deterministic truthiness, treating common string falsies as False."""
    if isinstance(value, str):
        return value.strip().lower() not in ("", "false", "0", "none", "null", "no")
    return bool(value)


def eval_condition(cfg: dict) -> bool:
    """Evaluate an if/switch condition from a *resolved* config dict.

    Either a comparison ``{left, op, right}`` (op in ==, !=, contains, >, <, >=, <=)
    or a single ``{condition: <value>}`` truthiness check. Pure + deterministic.
    """
    op = cfg.get("op")
    if op:
        left, right = cfg.get("left"), cfg.get("right")
        if op == "==":
            return str(left) == str(right)
        if op == "!=":
            return str(left) != str(right)
        if op == "contains":
            return str(right) in str(left or "")
        if op in (">", "<", ">=", "<="):
            try:
                l, r = float(left), float(right)
            except (TypeError, ValueError):
                return False
            return {">": l > r, "<": l < r, ">=": l >= r, "<=": l <= r}[op]
        return False
    return truthy(cfg.get("condition"))


def topo_order(nodes: dict, edges: list) -> list:
    """Kahn topological sort over node ids. Deterministic (sorted frontier).

    ``edges`` are dicts ``{"source": id, "target": id}``. Nodes not connected by
    any edge are appended in declaration order after the sorted component.
    """
    indeg = {nid: 0 for nid in nodes}
    adj: dict = {nid: [] for nid in nodes}
    for e in edges:
        s, t = e.get("source"), e.get("target")
        if s in nodes and t in nodes:
            adj[s].append(t)
            indeg[t] += 1
    frontier = sorted([nid for nid, d in indeg.items() if d == 0])
    order: list = []
    while frontier:
        nid = frontier.pop(0)
        order.append(nid)
        for nxt in sorted(adj[nid]):
            indeg[nxt] -= 1
            if indeg[nxt] == 0:
                frontier.append(nxt)
        frontier.sort()
    # Any remaining (cycle) appended deterministically so the run still completes.
    for nid in nodes:
        if nid not in order:
            order.append(nid)
    return order
