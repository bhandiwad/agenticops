"""FinOps routes — cloud cost via the already-connected cloud providers.

Today: AWS Cost Explorer (via the connected read-only assume-role). The Cost Explorer
API is billed per request (~$0.01), so results are cached per (user, period). GCP/Azure
report connection state only for now (ingestion tracked in epic #17).
"""

from __future__ import annotations

import datetime
import logging
import time

from flask import Blueprint, jsonify, request

from utils.auth.rbac_decorators import require_permission
from utils.auth.stateless_auth import get_credentials_from_db

logger = logging.getLogger(__name__)

finops_bp = Blueprint("finops", __name__)

_PERIOD_DAYS = {"7d": 7, "30d": 30, "90d": 90, "180d": 180, "365d": 365}
_CACHE: dict[str, tuple[float, dict]] = {}
_TTL_SECONDS = 3600  # Cost Explorer is billed per request — cache aggressively.


def _aws_creds(user_id: str) -> dict | None:
    try:
        c = get_credentials_from_db(user_id, "aws")
    except Exception:  # noqa: BLE001
        return None
    if c and (c.get("read_only_role_arn") or c.get("role_arn")):
        return c
    return None


@finops_bp.route("/api/finops/sources", methods=["GET"])
@require_permission("connectors", "read")
def finops_sources(user_id):
    """Which cost-capable cloud providers are connected (drives the UI state)."""
    def connected(provider: str) -> bool:
        try:
            return bool(get_credentials_from_db(user_id, provider))
        except Exception:  # noqa: BLE001
            return False

    return jsonify({
        "aws": _aws_creds(user_id) is not None,
        "gcp": connected("gcp"),
        "azure": connected("azure"),
    })


@finops_bp.route("/api/finops/cloud-cost", methods=["GET"])
@require_permission("connectors", "read")
def cloud_cost(user_id):
    """AWS cloud spend from Cost Explorer using the connected read-only role.

    Returns {connected, provider, total, currency, by_service[], over_time[]} or
    {connected, provider, error} when CE access is missing. {connected: false} when
    AWS isn't connected at all."""
    period = request.args.get("period", "30d")
    days = _PERIOD_DAYS.get(period, 30)
    cache_key = f"{user_id}:{period}"
    now = time.time()
    hit = _CACHE.get(cache_key)
    if hit and now - hit[0] < _TTL_SECONDS:
        return jsonify(hit[1])

    creds = _aws_creds(user_id)
    if not creds:
        return jsonify({"connected": False, "provider": "aws"})

    try:
        import boto3

        role_arn = creds.get("read_only_role_arn") or creds.get("role_arn")
        external_id = creds.get("external_id")
        assume_kwargs = {"RoleArn": role_arn, "RoleSessionName": f"aurora-finops-{str(user_id)[:24]}"}
        if external_id:
            assume_kwargs["ExternalId"] = external_id

        tc = boto3.client("sts").assume_role(**assume_kwargs)["Credentials"]
        ce = boto3.client(
            "ce", region_name="us-east-1",
            aws_access_key_id=tc["AccessKeyId"],
            aws_secret_access_key=tc["SecretAccessKey"],
            aws_session_token=tc["SessionToken"],
        )

        end = datetime.date.today()
        start = end - datetime.timedelta(days=days)
        resp = ce.get_cost_and_usage(
            TimePeriod={"Start": start.isoformat(), "End": end.isoformat()},
            Granularity="DAILY",
            Metrics=["UnblendedCost"],
            GroupBy=[{"Type": "DIMENSION", "Key": "SERVICE"}],
        )

        over_time: list[dict] = []
        by_service: dict[str, float] = {}
        total = 0.0
        currency = "USD"
        for day in resp.get("ResultsByTime", []):
            day_total = 0.0
            for g in day.get("Groups", []):
                svc = g["Keys"][0]
                metric = g["Metrics"]["UnblendedCost"]
                amt = float(metric.get("Amount", 0) or 0)
                currency = metric.get("Unit", currency)
                by_service[svc] = by_service.get(svc, 0.0) + amt
                day_total += amt
            over_time.append({"date": day["TimePeriod"]["Start"], "cost": round(day_total, 2)})
            total += day_total

        top = sorted(
            ({"service": k, "cost": round(v, 2)} for k, v in by_service.items()),
            key=lambda x: x["cost"], reverse=True,
        )[:12]

        payload = {
            "connected": True, "provider": "aws", "currency": currency,
            "total": round(total, 2), "by_service": top, "over_time": over_time,
        }
        _CACHE[cache_key] = (now, payload)
        return jsonify(payload)
    except Exception as e:  # noqa: BLE001
        msg = str(e)
        if "AccessDenied" in msg or "not authorized" in msg or "UnauthorizedOperation" in msg:
            hint = "AWS is connected, but the role lacks Cost Explorer access — grant ce:GetCostAndUsage to the read-only role."
        else:
            hint = msg[:180]
        logger.warning("finops cloud-cost failed for user %s: %s", user_id, msg[:200])
        return jsonify({"connected": True, "provider": "aws", "error": hint})
