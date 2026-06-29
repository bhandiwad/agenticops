"""Configuration loader for the CFX enrichment pipeline.

Reads the same Aurora .env so credentials stay in one place. No secrets are
written to logs or output documents.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_ENV_PATH = os.environ.get("AURORA_ENV_PATH", "/home/ubuntu/aurora/.env")
DEFAULT_OUTPUT_DIR = os.environ.get(
    "CFX_RCA_OUTPUT_DIR", "/home/ubuntu/aurora/data/cfx_rca"
)


def load_env(path: str | Path = DEFAULT_ENV_PATH) -> dict[str, str]:
    env: dict[str, str] = {}
    p = Path(path)
    if not p.exists():
        return env
    for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[7:].strip()
        key, value = line.split("=", 1)
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        env[key.strip()] = value
    return env


@dataclass
class CfxConfig:
    api_base: str
    api_token: str
    refresh_token: str = ""
    refresh_url: str = ""
    project_id: str = ""
    customer_id: str = ""
    verify_ssl: bool = False
    timeout_sec: int = 60
    # Topology graph (discovered defaults; override via env if needed)
    topology_graph: str = "cfx_rdaf_topology_graph"
    topology_db: str = "cfx_rdaf_topology"
    relationship_map: str = "rdaf_topology_relationships"
    env_path: str = DEFAULT_ENV_PATH
    output_dir: str = DEFAULT_OUTPUT_DIR
    raw: dict[str, str] = field(default_factory=dict)

    @classmethod
    def from_env(cls, path: str | Path = DEFAULT_ENV_PATH) -> "CfxConfig":
        env = load_env(path)
        # Docker containers receive CFX_* via environment; overlay file values.
        for key, value in os.environ.items():
            if key.startswith("CFX_") or key in ("CFX_RCA_OUTPUT_DIR", "AURORA_ENV_PATH"):
                if value:
                    env[key] = value
        verify = (env.get("CFX_VERIFY_SSL", "false") or "false").strip().lower() not in (
            "0",
            "false",
            "no",
            "off",
        )
        return cls(
            api_base=(env.get("CFX_API_BASE", "") or "").rstrip("/"),
            api_token=env.get("CFX_API_TOKEN", "") or "",
            refresh_token=env.get("CFX_REFRESH_TOKEN", "") or "",
            refresh_url=env.get("CFX_REFRESH_API_URL", "") or "",
            project_id=env.get("CFX_PROJECT_ID", "") or env.get("CFX_POLL_PROJECT_ID", "") or "",
            customer_id=env.get("CFX_CUSTOMER_ID", "") or "",
            verify_ssl=verify,
            timeout_sec=int(env.get("CFX_POLL_TIMEOUT_SEC", "60") or "60"),
            topology_graph=env.get("CFX_TOPOLOGY_GRAPH", "cfx_rdaf_topology_graph"),
            topology_db=env.get("CFX_TOPOLOGY_DB", "cfx_rdaf_topology"),
            relationship_map=env.get("CFX_RELATIONSHIP_MAP", "rdaf_topology_relationships"),
            env_path=str(path),
            output_dir=env.get("CFX_RCA_OUTPUT_DIR", DEFAULT_OUTPUT_DIR),
            raw=env,
        )
