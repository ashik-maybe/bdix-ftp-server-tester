"""Derive human-facing accessibility tiers from probe results."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

TIERS = ("opens", "login", "ftp_only", "blocked", "dead")
TIER_LABELS = {
    "opens": "Opens",
    "login": "Needs login",
    "ftp_only": "FTP only",
    "blocked": "Blocked / gone",
    "dead": "Dead",
}
TIER_ORDER = {t: i for i, t in enumerate(TIERS)}


def _get(row: Mapping[str, Any] | Any, key: str, default: Any = None) -> Any:
    if isinstance(row, Mapping):
        return row.get(key, default)
    return getattr(row, key, default)


def tier_for(row: Mapping[str, Any] | Any) -> str:
    bucket = _get(row, "bucket", "UNKNOWN")
    ftp = _get(row, "ftp_status", "FTP_SKIP")
    if bucket in ("OK", "REDIRECT"):
        return "opens"
    if bucket == "AUTH":
        return "login"
    if ftp == "FTP_OK" and bucket not in ("OK", "REDIRECT"):
        return "ftp_only"
    if bucket in ("FORBIDDEN", "NOT_FOUND", "SERVER_ERR"):
        return "blocked"
    return "dead"


def is_accessible(row: Mapping[str, Any] | Any) -> bool:
    return tier_for(row) in ("opens", "login", "ftp_only")


def tier_label(tier: str) -> str:
    return TIER_LABELS.get(tier, tier)


def enrich(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for r in rows:
        rr = dict(r)
        rr["tier"] = tier_for(rr)
        rr["tier_label"] = tier_label(rr["tier"])
        out.append(rr)
    return out
