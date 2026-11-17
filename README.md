# BDIX FTP server tester

**Check which BDIX FTP, media and live TV servers actually work — from your own connection.**

Async Python CLI that probes the community [BDIX FTP Server List](https://sites.google.com/view/bdixftpserverlist/) (886 links across 443 Bangladeshi ISPs) with HTTP checks and FTP port-21 banner reads, then reports results in a live `rich` table plus CSV/JSON.

[![Python 3.12+](https://img.shields.io/badge/python-3.12%2B-blue)](pyproject.toml)
[![uv](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/uv/main/assets/badge/v0.json)](https://github.com/astral-sh/uv)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)

> **Unofficial.** This project is not affiliated with the source list or with any ISP listed. Provider names and links belong to their owners.

## Why

BDIX (Bangladesh Internet Exchange) ISPs run their own FTP, media and live TV servers. The community list tracks who runs what, but it is static — servers go up and down constantly, and many links are stale. This tool tells you which entries still answer **from the network you run it on**.

## Quick start

Requires [uv](https://docs.astral.sh/uv/) and Python 3.12+.

```bash
git clone https://github.com/ashik-maybe/bdix-ftp-server-tester
cd bdix-ftp-server-tester

uv sync
uv run bdix-check --export out all
```

No `uv` yet: `curl -LsSf https://astral.sh/uv/install.sh | sh`

## Example output

From a sample run (886 unique targets, both pages):

```text
Fetching pages: media, livetv
Discovered 886 unique targets (server=812, social=74)

Summary
  Total (server): 812  |  reachable: 444  |  failing: 368
  Buckets: OK=431, TIMEOUT=219, DNS_FAIL=128, NOT_FOUND=73, REFUSED=9,
           FORBIDDEN=8, AUTH=2, UNKNOWN=2, SERVER_ERR=1 (+13 redirects)
  FTP alive despite HTTP not OK: 11
  Private-range hosts (likely ISP-local only): 52
  Social links probed: 74 total, 74 reachable, 0 failing
```

Exports: `out/results.csv`, `out/results.json`, `out/partial.jsonl`.

## What "working" means

| Bucket | Meaning |
|---|---|
| `OK` / `REDIRECT` | HTTP 2xx, or a redirect that lands on one (counted as reachable) |
| `AUTH` | Server answered but wants credentials (401/407) |
| `FORBIDDEN` | Server refused the request (403) |
| `NOT_FOUND` | Host is up, path is gone (404) |
| `SERVER_ERR` | 5xx response |
| `TIMEOUT` | No answer within the timeout |
| `REFUSED` | Connection refused |
| `DNS_FAIL` | Hostname does not resolve |
| `TLS_ERR` | TLS/certificate/protocol failure |
| `CONNECT_ERR` / `UNKNOWN` | Other connection or probe errors |

`ftp_status` is probed separately on TCP port 21 (default on): `FTP_OK` (banner read), `FTP_REFUSED`, `FTP_TIMEOUT`, `FTP_NO_DNS`, `FTP_ERR`, `FTP_SKIP`. A host can fail HTTP but still answer on FTP — the summary calls these out explicitly.

## Commands

```bash
# Check both pages (default)
uv run bdix-check all --export out

# One page only
uv run bdix-check media --export out/media
uv run bdix-check livetv --export out/livetv

# Options
uv run bdix-check --export out all            # write results.csv, results.json, partial.jsonl
uv run bdix-check --filter all all            # include social links in the live table/summary
uv run bdix-check --no-ftp all                # skip port-21 probe (faster)
uv run bdix-check --only-failing all          # show only failures in the live table
uv run bdix-check --workers 32 --timeout 10 all
uv run bdix-check --refresh all               # ignore cached source pages
uv run bdix-check --cache-dir .cache all
```

## Streamlit app (local)

An interactive local UI that leads with **sites that actually open** (OK/redirect, needs login, or FTP-only) and lets you drill into failures and diffs.

```bash
uv sync
uv run streamlit run streamlit_app.py
```

- **Working board:** accessible sites by default, grouped/filterable by ISP, page, tier, FTP status, latency and search. Switch between a styled board and a sortable table. Copy/download working URLs (and Live TV URLs) or export the filtered view.
- **Snapshots & diff:** each run is saved to `data/runs/<timestamp>.json`; pick a snapshot and see what changed vs the previous one.
- **Run a check:** probes from *this machine's network* and refreshes the board. Run it from a BDIX-connected connection for meaningful results (cloud hosts will over-report failures).

```text
streamlit_app.py
src/bdix_check/app.py      # Streamlit UI
src/bdix_check/store.py    # run load/save/filter/diff
src/bdix_check/tiers.py    # bucket → accessibility tier
.streamlit/config.toml     # dark theme
data/runs/                 # committed snapshots
```

| Option | Default | Description |
|---|---|---|
| `pages` | `all` | `media`, `livetv`, or `all` |
| `--filter` | `server` | `server`, `social`, or `all` (table/summary view; exports always include all rows) |
| `--ftp / --no-ftp` | `--ftp` | Probe TCP port 21 for an FTP banner |
| `--workers` | `64` | Max concurrent probes |
| `--timeout` | `12.0` | HTTP timeout (seconds) |
| `--only-failing` | off | Hide reachable rows in the live table |
| `--export DIR` | none | Write `results.csv`, `results.json`, `partial.jsonl` to DIR |
| `--refresh` | off | Re-download source pages instead of using cache |
| `--cache-dir DIR` | `.cache` | Cache directory for downloaded pages |

## How it works

1. **Fetch** the two Google Sites pages and cache them locally (`.cache/media.html`, `.cache/livetv.html`).
2. **Parse** links by unwrapping Google redirect URLs (`https://www.google.com/url?q=…`) and normalising direct links. A naive `href` scrape would miss the real targets.
3. **Group** each link under the nearest heading so results are attributed per ISP/provider, then dedupe normalized URLs.
4. **Probe HTTP** concurrently: `HEAD` first, falling back to a streamed `GET` with `Range: bytes=0-0` when `HEAD` is rejected (common on these servers). Redirects followed (max 3), status/latency/final URL recorded.
5. **Probe FTP** (optional): raw TCP connect to port 21, read up to 256 bytes for a banner.
6. **Report** with a live `rich` table, a summary (buckets, worst providers, slowest reachable, social footnote), and optional CSV/JSON exports. `partial.jsonl` is appended per probe so Ctrl-C keeps data.

## Output schema

Each row (CSV and JSON) contains:

| Field | Meaning |
|---|---|
| `provider` | ISP/provider heading from the source page |
| `page` | `media` or `livetv` |
| `kind` | `server` or `social` (Facebook/pastebin/sites.google.com links) |
| `url` | Probed URL |
| `host`, `scheme` | Parsed host and scheme |
| `http_status` | HTTP status code, or null on connection failure |
| `bucket` | Classified result (see table above) |
| `latency_ms` | End-to-end HTTP probe time in ms |
| `final_url` | URL after redirects |
| `redirects` | Redirect hop count |
| `ftp_status`, `ftp_banner` | Port-21 probe result and banner snippet |
| `note` | Error class or short note |
| `vantage` | `public` or `private-range` (RFC1918/loopback/link-local) |

## Caveats

- **Vantage point matters.** Results reflect reachability from *the machine/network that runs the check*. Many BDIX hosts answer only from BDIX-peered ISPs in Bangladesh, so `TIMEOUT`/`DNS_FAIL` elsewhere does not prove a server is dead everywhere.
- **Private ranges.** ~50 listed URLs are RFC1918/private (`10.x`, `172.16–31.x`, `192.168.x`, etc.). They are ISP-internal and usually unreachable from outside; rows are tagged `vantage=private-range`.
- **HTTP vs FTP.** The list is labeled "FTP servers" but most links are HTTP URLs. `--ftp` adds a port-21 banner check so HTTP-down/FTP-up hosts are still visible.
- **Snapshot, not monitoring.** Availability changes; rerun with `--refresh` for a fresh snapshot. `partial.jsonl` lets you keep partial progress.
- **Unofficial.** This is a reachability checker over a community-maintained list. It is not affiliated with the source site or any ISP, and it does not mirror or redistribute their content beyond the public links it checks.

## Development

```bash
uv sync
uv run pytest
uv run ruff check src tests
uv run ruff format src tests
```

Tests cover URL unwrapping, provider/heading grouping, deduping, kind classification, and status bucketing (no network).

## Credits

- Server list and provider/link data: [BDIX FTP Server List](https://sites.google.com/view/bdixftpserverlist/) (Google Sites), maintained by its own authors.
- Built with [httpx](https://www.python-httpx.org/), [rich](https://rich.readthedocs.io/), and [typer](https://typer.tiangolo.com/).

## License

[MIT](LICENSE)
