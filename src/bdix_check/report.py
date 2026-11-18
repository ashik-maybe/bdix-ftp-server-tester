from __future__ import annotations

import csv
import json
from collections import Counter, defaultdict
from collections.abc import Iterable
from pathlib import Path

from rich.console import Console
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from .probe import ProbeResult

COLUMNS = [
    "provider",
    "provider_index",
    "page",
    "kind",
    "url",
    "host",
    "scheme",
    "http_status",
    "bucket",
    "latency_ms",
    "final_url",
    "redirects",
    "ftp_status",
    "ftp_banner",
    "note",
    "vantage",
]

BUCKET_STYLE = {
    "OK": "green",
    "REDIRECT": "cyan",
    "AUTH": "yellow",
    "FORBIDDEN": "yellow",
    "NOT_FOUND": "magenta",
    "SERVER_ERR": "red",
    "TLS_ERR": "red",
    "DNS_FAIL": "red",
    "TIMEOUT": "red",
    "REFUSED": "red",
    "CONNECT_ERR": "red",
    "UNKNOWN": "red",
}


class LiveReporter:
    def __init__(
        self, console: Console, filter_kind: str = "server", only_failing: bool = False
    ) -> None:
        self.console = console
        self.filter_kind = filter_kind
        self.only_failing = only_failing
        self.results: list[ProbeResult] = []
        self._live: Live | None = None

    def _visible(self, r: ProbeResult) -> bool:
        if self.filter_kind != "all" and r.kind != self.filter_kind:
            return False
        if self.only_failing and r.bucket == "OK":
            # but FTP_OK might be interesting; keep if http bad but ftp ok? no, bucket is http bucket
            return True
        return True

    def _build_table(self) -> Table:
        table = Table(title="BDIX server check (live)", expand=True, show_lines=False)
        table.add_column("Provider", style="dim", no_wrap=True, max_width=28)
        table.add_column("Kind", no_wrap=True)
        table.add_column("Host", no_wrap=True, max_width=34)
        table.add_column("HTTP", no_wrap=True)
        table.add_column("Bucket", no_wrap=True)
        table.add_column("ms", justify="right", no_wrap=True)
        table.add_column("FTP", no_wrap=True)
        table.add_column("Note", max_width=30)
        # show last 40 visible
        visible = [r for r in self.results if self._visible(r)]
        for r in visible[-40:]:
            bstyle = BUCKET_STYLE.get(r.bucket, "white")
            ftp = r.ftp_status.replace("FTP_", "") if r.ftp_status else "-"
            note = (
                r.note
                or (r.ftp_banner or "")
                or ("private" if r.vantage == "private-range" else "")
            )
            table.add_row(
                r.provider[:28],
                r.kind,
                r.host[:34],
                str(r.http_status or "-"),
                Text(r.bucket, style=bstyle),
                str(r.latency_ms if r.latency_ms is not None else "-"),
                ftp,
                note[:30],
            )
        table.caption = f"{len(self.results)} probed, {len(visible)} shown"
        return table

    def start(self) -> None:
        self._live = Live(self._build_table(), console=self.console, refresh_per_second=8)
        self._live.start()

    def add(self, result: ProbeResult) -> None:
        self.results.append(result)
        if self._live:
            self._live.update(self._build_table())

    def stop(self) -> None:
        if self._live:
            self._live.stop()
            self._live = None


def write_csv(path: Path, results: Iterable[ProbeResult]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS)
        w.writeheader()
        for r in results:
            w.writerow(r.to_dict())


def write_json(path: Path, results: list[ProbeResult]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps([r.to_dict() for r in results], indent=2), encoding="utf-8")


def append_jsonl(path: Path, result: ProbeResult) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(result.to_dict()) + "\n")


def print_summary(
    console: Console, results: list[ProbeResult], filter_kind: str = "server"
) -> None:
    if filter_kind == "all":
        shown = results
    else:
        shown = [r for r in results if r.kind == filter_kind]
    total = len(shown)
    buckets = Counter(r.bucket for r in shown)
    ok = buckets.get("OK", 0) + buckets.get("REDIRECT", 0)
    fail = total - ok

    lines = [f"Total ({filter_kind}): {total}  |  reachable: {ok}  |  failing: {fail}"]
    lines.append(
        "Buckets: " + ", ".join(f"{k}={v}" for k, v in sorted(buckets.items(), key=lambda x: -x[1]))
    )

    # FTP alive but http not ok
    ftp_alive = [r for r in shown if r.ftp_status == "FTP_OK" and r.bucket != "OK"]
    if ftp_alive:
        lines.append(f"FTP alive despite HTTP not OK: {len(ftp_alive)}")

    private = [r for r in shown if r.vantage == "private-range"]
    if private:
        lines.append(f"Private-range hosts (likely ISP-local only): {len(private)}")

    console.print(Panel("\n".join(lines), title="Summary", border_style="blue"))

    # per-provider failing
    prov_fail: dict[str, int] = defaultdict(int)
    prov_total: dict[str, int] = defaultdict(int)
    for r in shown:
        prov_total[r.provider] += 1
        if r.bucket not in ("OK", "REDIRECT"):
            prov_fail[r.provider] += 1
    worst = sorted(
        ((p, prov_fail[p], prov_total[p]) for p in prov_total), key=lambda x: (-x[1], -x[2])
    )[:10]
    if worst and any(w[1] for w in worst):
        t = Table(title="Top providers by failures (shown set)")
        t.add_column("Provider")
        t.add_column("Fail/Total", justify="right")
        for p, f, tot in worst:
            if f:
                t.add_row(p[:50], f"{f}/{tot}")
        console.print(t)

    # slowest ok
    slow = sorted(
        [r for r in shown if r.latency_ms and r.bucket == "OK"],
        key=lambda r: r.latency_ms or 0,
        reverse=True,
    )[:10]
    if slow:
        t = Table(title="Slowest reachable (HTTP OK)")
        t.add_column("Host")
        t.add_column("ms", justify="right")
        for r in slow:
            t.add_row(r.host, str(r.latency_ms))
        console.print(t)

    # social footnote when filtered
    if filter_kind == "server":
        social = [r for r in results if r.kind == "social"]
        if social:
            sok = sum(1 for r in social if r.bucket in ("OK", "REDIRECT"))
            console.print(
                f"[dim]Social links probed: {len(social)} total, {sok} reachable, {len(social) - sok} failing (use --filter all to show)[/dim]"
            )
