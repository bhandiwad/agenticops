"""Shared SSRF guard for outbound requests to user-supplied URLs.

Resolves every address the host maps to and blocks the request if ANY of them is
non-public (loopback / private / link-local / reserved / multicast / unspecified) —
this covers cloud metadata (169.254.169.254), localhost, and internal RFC-1918 ranges.
Best-effort (DNS is resolved once, so it does not fully close a TOCTOU rebind window),
but it is the standard mitigation and matches the platform's existing guard.
"""

from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse


def is_safe_public_url(url: str, allowed_schemes: tuple[str, ...] = ("http", "https")) -> tuple[bool, str]:
    """Return (ok, reason). ok=False means the URL should NOT be fetched."""
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
    for info in infos:
        ip_str = info[4][0]
        try:
            ip = ipaddress.ip_address(ip_str)
        except ValueError:
            continue
        if (ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved
                or ip.is_multicast or ip.is_unspecified):
            return False, f"host resolves to non-public address {ip_str}"
    return True, ""


def assert_safe_public_url(url: str, allowed_schemes: tuple[str, ...] = ("http", "https")) -> None:
    ok, reason = is_safe_public_url(url, allowed_schemes)
    if not ok:
        raise ValueError(f"SSRF blocked: {reason}")
