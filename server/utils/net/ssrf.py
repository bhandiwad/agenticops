"""Shared SSRF guard for outbound requests to user-supplied URLs.

Resolves every address the host maps to and blocks the request if ANY of them is
non-public (loopback / private / link-local / reserved / multicast / unspecified) —
this covers cloud metadata (169.254.169.254), localhost, and internal RFC-1918 ranges.
Best-effort (DNS is resolved once, so it does not fully close a TOCTOU rebind window),
but it is the standard mitigation and matches the platform's existing guard.

On-prem infrastructure connectors (FortiGate, Zabbix, VM management, etc.) legitimately
target private/management networks. Operators opt those ranges in explicitly via
``AURORA_SSRF_ALLOWED_CIDRS`` (comma-separated CIDRs, e.g. ``10.0.0.0/8,192.168.0.0/16``).
Callers may also pass ``allow_cidrs`` per-invocation. Default (env unset, no arg) keeps the
strict public-only behavior unchanged — a resolved IP is only permitted into a private range
when the operator has deliberately declared it trusted.
"""

from __future__ import annotations

import ipaddress
import os
import socket
from urllib.parse import urlparse


def _parse_cidrs(raw: str) -> list:
    nets = []
    for part in (raw or "").split(","):
        part = part.strip()
        if not part:
            continue
        try:
            nets.append(ipaddress.ip_network(part, strict=False))
        except ValueError:
            continue
    return nets


def _allowed_networks(extra: tuple[str, ...]) -> list:
    """Operator-declared trusted CIDRs: env allowlist plus any per-call additions."""
    return _parse_cidrs(os.getenv("AURORA_SSRF_ALLOWED_CIDRS", "")) + _parse_cidrs(",".join(extra))


def is_safe_public_url(
    url: str,
    allowed_schemes: tuple[str, ...] = ("http", "https"),
    allow_cidrs: tuple[str, ...] = (),
) -> tuple[bool, str]:
    """Return (ok, reason). ok=False means the URL should NOT be fetched.

    ``allow_cidrs`` (plus the ``AURORA_SSRF_ALLOWED_CIDRS`` env allowlist) permits resolved
    IPs that fall inside operator-trusted ranges even if they are private — for on-prem
    infrastructure connectors. Everything else stays blocked.
    """
    try:
        parsed = urlparse(url or "")
    except Exception:  # noqa: BLE001
        return False, "invalid URL"
    if parsed.scheme not in allowed_schemes:
        return False, f"scheme not allowed: {parsed.scheme or '(none)'}"
    host = parsed.hostname
    if not host:
        return False, "no host in URL"
    try:
        infos = socket.getaddrinfo(host, None)
    except Exception as e:  # noqa: BLE001
        return False, f"DNS resolution failed: {e}"
    allowed_nets = _allowed_networks(allow_cidrs)
    for info in infos:
        ip_str = info[4][0]
        try:
            ip = ipaddress.ip_address(ip_str)
        except ValueError:
            continue
        if any(ip in net for net in allowed_nets):
            continue  # operator-declared trusted infrastructure range
        if (ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved
                or ip.is_multicast or ip.is_unspecified):
            return False, f"host resolves to non-public address {ip_str}"
    return True, ""


def assert_safe_public_url(
    url: str,
    allowed_schemes: tuple[str, ...] = ("http", "https"),
    allow_cidrs: tuple[str, ...] = (),
) -> None:
    ok, reason = is_safe_public_url(url, allowed_schemes, allow_cidrs)
    if not ok:
        raise ValueError(f"SSRF blocked: {reason}")
