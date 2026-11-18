from __future__ import annotations

import asyncio
from pathlib import Path

import httpx
import typer
from rich.console import Console

from .fetch import fetch_targets
from .probe import ProbeResult, probe_target
from .report import LiveReporter, append_jsonl, print_summary, write_csv, write_json

app = typer.Typer(
    add_completion=False,
    context_settings={"allow_interspersed_args": True},
    help="Check BDIX FTP/media/live-TV server links from the public Google Sites list.",
)


@app.callback(invoke_without_command=True)
def main(
    ctx: typer.Context,
    pages: str = typer.Argument("all", help="Which page to check: media, livetv, or all"),
    filter: str = typer.Option("server", "--filter", help="Show/filter: server, social, or all"),
    ftp: bool = typer.Option(True, "--ftp/--no-ftp", help="Probe TCP port 21 for FTP banner"),
    workers: int = typer.Option(64, "--workers", min=1, max=256, help="Max concurrent probes"),
    timeout: float = typer.Option(12.0, "--timeout", help="HTTP timeout seconds"),
    only_failing: bool = typer.Option(
        False, "--only-failing", help="Show only failing rows in live table"
    ),
    export: Path | None = typer.Option(
        None, "--export", help="Directory to write results.csv, results.json, partial.jsonl"
    ),
    refresh: bool = typer.Option(
        False, "--refresh", help="Ignore cached page HTML and re-download"
    ),
    cache_dir: Path = typer.Option(
        Path(".cache"), "--cache-dir", help="Cache directory for downloaded pages"
    ),
) -> None:
    if ctx.invoked_subcommand is not None:
        return
    if pages not in {"media", "livetv", "all"}:
        raise typer.BadParameter("pages must be one of: media, livetv, all")
    if filter not in {"server", "social", "all"}:
        raise typer.BadParameter("filter must be one of: server, social, all")
    page_list = ["media", "livetv"] if pages == "all" else [pages]
    asyncio.run(
        run(
            page_list=page_list,
            filter_kind=filter,
            do_ftp=ftp,
            workers=workers,
            timeout=timeout,
            only_failing=only_failing,
            export=export,
            refresh=refresh,
            cache_dir=cache_dir,
        )
    )


async def run(
    page_list: list[str],
    filter_kind: str,
    do_ftp: bool,
    workers: int,
    timeout: float,
    only_failing: bool,
    export: Path | None,
    refresh: bool,
    cache_dir: Path,
) -> None:
    console = Console()
    console.print(f"[bold]Fetching pages:[/bold] {', '.join(page_list)}")
    targets = await fetch_targets(page_list, cache_dir=cache_dir, refresh=refresh)
    console.print(
        f"Discovered [bold]{len(targets)}[/bold] unique targets (server={sum(1 for t in targets if t.kind == 'server')}, social={sum(1 for t in targets if t.kind == 'social')})"
    )

    if export:
        export.mkdir(parents=True, exist_ok=True)
        partial = export / "partial.jsonl"
        if partial.exists():
            partial.unlink()

    sem = asyncio.Semaphore(workers)
    reporter = LiveReporter(console=console, filter_kind=filter_kind, only_failing=only_failing)
    results: list[ProbeResult] = []

    limits = httpx.Limits(max_connections=workers, max_keepalive_connections=workers // 2)
    headers = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) bdix-check/0.1"}
    timeout_cfg = httpx.Timeout(timeout, connect=min(5.0, timeout))

    async with httpx.AsyncClient(
        limits=limits,
        headers=headers,
        timeout=timeout_cfg,
        follow_redirects=True,
        verify=False,  # many BDIX servers have broken certs; record as reachable, not TLS-perfect
    ) as client:
        reporter.start()

        async def one(t):
            try:
                r = await probe_target(t, client, sem, timeout, do_ftp)
            except Exception as e:
                r = ProbeResult(
                    provider=t.provider,
                    provider_index=t.provider_index,
                    page=t.page,
                    kind=t.kind,
                    url=t.url,
                    host=t.host,
                    scheme=t.scheme,
                    http_status=None,
                    bucket="UNKNOWN",
                    latency_ms=None,
                    final_url=None,
                    redirects=0,
                    ftp_status="FTP_SKIP",
                    ftp_banner=None,
                    note=f"probe-error:{type(e).__name__}",
                    vantage="public",
                )
            results.append(r)
            reporter.add(r)
            if export:
                append_jsonl(export / "partial.jsonl", r)
            return r

        tasks = [asyncio.create_task(one(t)) for t in targets]
        try:
            await asyncio.gather(*tasks)
        except KeyboardInterrupt:
            for task in tasks:
                task.cancel()
        finally:
            reporter.stop()

    if export:
        write_csv(export / "results.csv", results)
        write_json(export / "results.json", results)
        console.print(
            f"Exported: {export / 'results.csv'}, {export / 'results.json'}, {export / 'partial.jsonl'}"
        )

    print_summary(console, results, filter_kind=filter_kind)


if __name__ == "__main__":
    app()
