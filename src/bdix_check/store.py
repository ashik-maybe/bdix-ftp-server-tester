"""Load, save, filter, and diff probe runs."""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import asdict, is_dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .tiers import enrich, tier_for

RUNS_DIR = Path("data/runs")


def _row_dict(row: Any) -> dict[str, Any]:
    if is_dataclass(row) and not isinstance(row, type):
        return asdict(row)
    if isinstance(row, dict):
        return dict(row)
    return {k: getattr(row, k) for k in dir(row) if not k.startswith("_")}


def normalize_rows(rows: Iterable[Any]) -> list[dict[str, Any]]:
    return enrich([_row_dict(r) for r in rows])


def save_run(
    rows: Iterable[Any],
    runs_dir: Path = RUNS_DIR,
    checked_at: datetime | None = None,
    meta: dict[str, Any] | None = None,
) -> Path:
    runs_dir.mkdir(parents=True, exist_ok=True)
    checked_at = checked_at or datetime.now(UTC)
    data_rows = normalize_rows(rows)
    payload = {
        "checked_at": checked_at.isoformat(),
        "count": len(data_rows),
        "meta": meta or {},
        "results": data_rows,
    }
    name = checked_at.strftime("%Y-%m-%dT%H-%M-%SZ")
    path = runs_dir / f"{name}.json"
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def load_run(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, list):
        # legacy/raw results.json form
        return {
            "checked_at": None,
            "count": len(data),
            "meta": {},
            "results": normalize_rows(data),
            "path": str(path),
        }
    data = dict(data)
    data["results"] = normalize_rows(data.get("results", []))
    data["path"] = str(path)
    return data


def list_runs(runs_dir: Path = RUNS_DIR) -> list[Path]:
    if not runs_dir.exists():
        return []
    return sorted(runs_dir.glob("*.json"), reverse=True)


def latest_run(runs_dir: Path = RUNS_DIR) -> dict[str, Any] | None:
    paths = list_runs(runs_dir)
    if not paths:
        return None
    return load_run(paths[0])


def filter_rows(
    rows: list[dict[str, Any]],
    *,
    pages: set[str] | None = None,
    tiers: set[str] | None = None,
    providers: set[str] | None = None,
    query: str = "",
    ftp_only: bool = False,
    include_private: bool = True,
    max_latency_ms: int | None = None,
    kind: str = "server",
) -> list[dict[str, Any]]:
    q = query.strip().lower()
    out = []
    for r in rows:
        if kind != "all" and r.get("kind") != kind:
            continue
        if pages and r.get("page") not in pages:
            continue
        if tiers and r.get("tier") not in tiers:
            continue
        if providers and r.get("provider") not in providers:
            continue
        if ftp_only and r.get("ftp_status") != "FTP_OK":
            continue
        if not include_private and r.get("vantage") == "private-range":
            continue
        lat = r.get("latency_ms")
        if max_latency_ms is not None and lat is not None and lat > max_latency_ms:
            continue
        if q:
            hay = " ".join(
                str(r.get(k, "") or "")
                for k in ("provider", "host", "url", "page", "tier", "bucket", "http_status")
            ).lower()
            if q not in hay:
                continue
        out.append(r)
    return out


def diff_runs(current: list[dict[str, Any]], previous: list[dict[str, Any]]) -> dict[str, Any]:
    prev_by = {r.get("url"): r for r in previous}
    curr_by = {r.get("url"): r for r in current}
    common = set(prev_by) & set(curr_by)
    now_open = 0
    now_dead = 0
    changed = 0
    for url in common:
        ct = tier_for(curr_by[url])
        pt = tier_for(prev_by[url])
        if ct in ("opens", "login", "ftp_only") and pt == "dead":
            now_open += 1
        elif ct == "dead" and pt in ("opens", "login", "ftp_only"):
            now_dead += 1
        elif ct != pt:
            changed += 1
    return {
        "now_open": now_open,
        "now_dead": now_dead,
        "changed": changed,
        "added": len(set(curr_by) - set(prev_by)),
        "removed": len(set(prev_by) - set(curr_by)),
        "compared": len(common),
    }
