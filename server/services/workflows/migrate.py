"""Non-destructive migration of V1 linear custom workflows -> V2 node-graph defs.

Each V1 workflow (ordered agent/action/approval steps) becomes a V2 def with the
same steps chained into a graph (key suffixed ``_v2``). The V1 workflows are left
untouched, so this is safe to run repeatedly; full V1 retirement is a later step
once V2 is battle-tested.
"""

from __future__ import annotations

import logging
from typing import List

logger = logging.getLogger("workflows.migrate")


def migrate_v1_to_v2(user_id: str, org_id: str) -> dict:
    from services.workflows.custom import list_custom_workflows
    from services.workflows.defs import upsert_def

    migrated: List[str] = []
    skipped: List[str] = []
    for wf in list_custom_workflows(user_id, org_id):
        steps = wf.get("steps") or []
        if not steps:
            skipped.append(wf.get("key", "?"))
            continue
        nodes, edges, prev = [], [], None
        for i, s in enumerate(steps):
            node_id = f"n{i}"
            nodes.append({
                "id": node_id,
                "type": s.get("type", "set"),
                "ref": s.get("ref", "") or "",
                "config": ({"summary": s.get("label")} if s.get("type") == "approval" else {}),
                "label": s.get("label") or s.get("ref") or s.get("type"),
                "position": {"x": 140, "y": 80 + i * 110},
            })
            if prev:
                edges.append({"source": prev, "target": node_id})
            prev = node_id
        new_key = f"{wf['key']}_v2"
        name = f"{wf.get('name', wf['key'])} (migrated)"
        try:
            upsert_def(user_id, org_id, key=new_key, name=name,
                       graph={"key": new_key, "name": name, "nodes": nodes, "edges": edges})
            migrated.append(new_key)
        except Exception:
            logger.exception("migrate: failed for %s", wf.get("key"))
            skipped.append(wf.get("key", "?"))
    return {"migrated": migrated, "skipped": skipped, "count": len(migrated)}
