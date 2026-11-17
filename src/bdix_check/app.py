from __future__ import annotations

import asyncio
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx
import pandas as pd
import streamlit as st

from .fetch import fetch_targets
from .probe import ProbeResult, probe_target
from .store import diff_runs, filter_rows, list_runs, load_run, save_run
from .tiers import TIER_LABELS, TIER_ORDER, TIERS, is_accessible

RUNS_DIR = Path("data/runs")
CACHE_DIR = Path(".cache")
ACCESSIBLE_TIERS = {"opens", "login", "ftp_only"}
TIER_COLOR = {
    "opens": "#3fb950",
    "login": "#d29922",
    "ftp_only": "#58a6ff",
    "blocked": "#f0883e",
    "dead": "#f85149",
}


def _fmt_ms(ms: Any) -> str:
    if ms is None or ms == "" or pd.isna(ms):
        return "—"
    ms = int(ms)
    return f"{ms} ms" if ms < 1000 else f"{ms / 1000:.1f} s"


def _load_all_runs() -> list[dict[str, Any]]:
    runs = []
    for p in list_runs(RUNS_DIR):
        try:
            runs.append(load_run(p))
        except Exception:
            continue
    return runs


def _run_label(run: dict[str, Any]) -> str:
    ts = run.get("checked_at") or run.get("path", "unknown")
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        ts = dt.strftime("%Y-%m-%d %H:%M UTC")
    except Exception:
        pass
    n = run.get("count") or len(run.get("results", []))
    meta = run.get("meta") or {}
    vantage = meta.get("vantage", "local")
    return f"{ts} · {n} links · {vantage}"


def _kpis(rows: list[dict[str, Any]]) -> dict[str, Any]:
    servers = [r for r in rows if r.get("kind") == "server"]
    c = Counter(r.get("tier") for r in servers)
    lats = [
        r["latency_ms"]
        for r in servers
        if r.get("latency_ms") is not None and r.get("tier") == "opens"
    ]
    median = int(sorted(lats)[len(lats) // 2]) if lats else None
    return {
        "opens": c.get("opens", 0),
        "login": c.get("login", 0),
        "ftp_only": c.get("ftp_only", 0),
        "dead": c.get("dead", 0),
        "blocked": c.get("blocked", 0),
        "isps": len({r.get("provider") for r in servers if r.get("provider")}),
        "total": len(servers),
        "median": median,
    }


def _styled_table(rows: list[dict[str, Any]]) -> str:
    def esc(s: Any) -> str:
        import html

        return html.escape(str(s or ""), quote=True)

    css = """
    <style>
    .board{width:100%;border-collapse:collapse;font:14px/1.45 -apple-system,BlinkMacSystemFont,Segoe UI,Inter,Roboto,sans-serif}
    .board th{text-align:left;font:600 11px/1 ui-monospace,SFMono-Regular,Menlo,monospace;letter-spacing:.1em;text-transform:uppercase;color:#8b98a5;padding:8px;border-bottom:1px solid #222a33}
    .board td{padding:9px 8px;border-bottom:1px solid #161d24;vertical-align:middle;color:#e6edf3}
    .board a{color:#e6edf3;text-decoration:none;font-weight:600}
    .board a:hover{color:#58a6ff;text-decoration:underline}
    .pill{display:inline-block;border-radius:999px;padding:3px 9px;font:600 11px/1.4 ui-monospace,Menlo,monospace}
    .muted{color:#8b98a5;font-size:12px}
    .mono{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;color:#8b98a5}
    </style><table class='board'><thead><tr>
    <th>ISP</th><th>Host</th><th>Status</th><th>Latency</th><th>FTP</th><th>Page</th>
    </tr></thead><tbody>
    """
    out = [css]
    for r in rows:
        tier = r.get("tier", "dead")
        color = TIER_COLOR.get(tier, "#8b98a5")
        label = esc(r.get("tier_label") or tier)
        pill = f"<span class='pill' style='color:{color};border:1px solid {color}33;background:{color}18'>{label}</span>"
        ftp = r.get("ftp_status")
        ftp_cell = (
            "<span class='pill' style='color:#3fb950;border:1px solid #3fb95033;background:#3fb95018'>open</span>"
            if ftp == "FTP_OK"
            else "<span class='muted'>—</span>"
        )
        host = esc(r.get("host"))
        url = esc(r.get("url"))
        prov = esc(r.get("provider"))
        note = ""
        if r.get("vantage") == "private-range":
            note = "<div class='muted'>private IP — ISP-internal</div>"
        elif ftp == "FTP_OK" and tier == "ftp_only":
            note = "<div class='muted'>HTTP failed, FTP answered</div>"
        out.append(
            f"<tr><td>{prov}</td>"
            f"<td><a href='{url}' target='_blank' rel='noopener noreferrer'>{host}</a>{note}</td>"
            f"<td>{pill}</td><td class='mono'>{esc(_fmt_ms(r.get('latency_ms')))}</td>"
            f"<td>{ftp_cell}</td><td class='muted'>{esc(r.get('page'))}</td></tr>"
        )
    out.append("</tbody></table>")
    return "".join(out)


async def _run_check(
    pages: list[str], do_ftp: bool, workers: int, timeout: float, progress, status
) -> list[ProbeResult]:
    targets = await fetch_targets(pages, cache_dir=CACHE_DIR, refresh=False)
    status.write(f"Discovered {len(targets)} targets. Probing…")
    sem = asyncio.Semaphore(workers)
    results: list[ProbeResult] = []
    done = 0
    limits = httpx.Limits(max_connections=workers, max_keepalive_connections=max(1, workers // 2))
    headers = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) bdix-check/0.1"}
    timeout_cfg = httpx.Timeout(timeout, connect=min(5.0, timeout))

    async with httpx.AsyncClient(
        limits=limits, headers=headers, timeout=timeout_cfg, follow_redirects=True, verify=False
    ) as client:

        async def one(t):
            nonlocal done
            r = await probe_target(t, client, sem, timeout, do_ftp)
            done += 1
            progress.progress(done / len(targets), text=f"Probed {done}/{len(targets)}")
            return r

        results = await asyncio.gather(*[one(t) for t in targets])
    return list(results)


def main() -> None:
    st.set_page_config(page_title="BDIX Sites — working servers", page_icon="🛰️", layout="wide")
    st.title("Working BDIX sites")
    st.caption(
        "FTP, media and live TV servers from the community list — showing what actually opens from your connection."
    )

    runs = _load_all_runs()
    if not runs:
        st.warning(
            "No saved runs yet. Use the **Run a check** panel below to create one, or place a run JSON in `data/runs/`."
        )
        current = None
        previous = None
    else:
        labels = [_run_label(r) for r in runs]
        idx = st.sidebar.selectbox(
            "Snapshot", options=list(range(len(runs))), format_func=lambda i: labels[i], index=0
        )
        current = runs[idx]
        previous = runs[idx + 1] if idx + 1 < len(runs) else None

    with st.sidebar:
        st.header("Filters")
        default_tiers = list(ACCESSIBLE_TIERS)
        tiers_sel = st.multiselect(
            "Show tiers",
            options=list(TIERS),
            default=default_tiers,
            format_func=lambda t: TIER_LABELS[t],
        )
        pages_sel = st.multiselect(
            "Page",
            options=["media", "livetv"],
            default=["media", "livetv"],
            format_func=lambda p: "Media & FTP" if p == "media" else "Live TV",
        )
        query = st.text_input("Search ISP, host or IP", placeholder="circle, 103.58, live tv…")
        ftp_only = st.checkbox("FTP:21 open only", value=False)
        include_private = st.checkbox("Include private-range IPs", value=True)
        max_lat = st.slider(
            "Max latency (ms)", min_value=200, max_value=15000, value=15000, step=200
        )
        table_mode = st.radio("Table", options=["Styled board", "Sortable table"], horizontal=True)

    rows = (current or {}).get("results", [])
    servers = [r for r in rows if r.get("kind") == "server"]
    filtered = filter_rows(
        rows,
        pages=set(pages_sel) if pages_sel else None,
        tiers=set(tiers_sel) if tiers_sel else None,
        query=query,
        ftp_only=ftp_only,
        include_private=include_private,
        max_latency_ms=None if max_lat >= 15000 else max_lat,
        kind="server",
    )
    # sort: tier order then latency
    filtered = sorted(
        filtered,
        key=lambda r: (
            TIER_ORDER.get(r.get("tier"), 9),
            r.get("latency_ms") if r.get("latency_ms") is not None else 10**9,
            r.get("host", ""),
        ),
    )

    k = _kpis(rows)
    if current:
        ts = current.get("checked_at", "unknown time")
        st.markdown(
            f"**Snapshot:** `{ts}` · vantage: `{(current.get('meta') or {}).get('vantage', 'local')}` · {k['total']} servers"
        )
    c1, c2, c3, c4, c5, c6 = st.columns(6)
    c1.metric("Opens", k["opens"])
    c2.metric("Needs login", k["login"])
    c3.metric("FTP only", k["ftp_only"])
    c4.metric("Dead", k["dead"])
    c5.metric("ISPs", k["isps"])
    c6.metric("Median latency", _fmt_ms(k["median"]))

    if previous and current:
        d = diff_runs(current.get("results", []), previous.get("results", []))
        st.info(
            f"**What changed** vs previous snapshot (compared {d['compared']}): "
            f"+{d['now_open']} now accessible · −{d['now_dead']} went dead · {d['changed']} changed tier · "
            f"{d['added']} added · {d['removed']} removed"
        )

    st.subheader(f"Sites ({len(filtered)} shown)")
    if not filtered:
        st.write("No sites match the current filters.")
    elif table_mode == "Sortable table":
        df = pd.DataFrame(
            [
                {
                    "ISP": r.get("provider"),
                    "Host": r.get("host"),
                    "URL": r.get("url"),
                    "Status": r.get("tier_label"),
                    "Tier": r.get("tier"),
                    "Latency": r.get("latency_ms"),
                    "FTP": "open" if r.get("ftp_status") == "FTP_OK" else "—",
                    "Page": r.get("page"),
                    "HTTP": r.get("http_status"),
                    "Private": r.get("vantage") == "private-range",
                }
                for r in filtered
            ]
        )
        st.dataframe(
            df,
            use_container_width=True,
            hide_index=True,
            column_config={
                "URL": st.column_config.LinkColumn("Open", display_text="open"),
                "Latency": st.column_config.NumberColumn("Latency (ms)", format="%d ms"),
            },
        )
    else:
        st.markdown(_styled_table(filtered), unsafe_allow_html=True)

    # working links / exports
    working = [r for r in filtered if is_accessible(r)]
    st.subheader("Working links")
    col_a, col_b = st.columns(2)
    with col_a:
        urls = "\n".join(r["url"] for r in working)
        st.text_area("Copy working URLs", urls, height=160)
    with col_b:
        tv_urls = "\n".join(r["url"] for r in working if r.get("page") == "livetv")
        st.text_area("Copy working Live TV URLs", tv_urls or "(none in current filter)", height=160)
    if filtered:
        csv_df = pd.DataFrame(filtered)
        st.download_button(
            "Download filtered CSV",
            csv_df.to_csv(index=False),
            file_name="bdix-filtered.csv",
            mime="text/csv",
        )
        st.download_button(
            "Download filtered JSON",
            csv_df.to_json(orient="records", indent=2),
            file_name="bdix-filtered.json",
            mime="application/json",
        )

    # failures summary
    with st.expander("Failures and unreachable hosts"):
        deadish = [r for r in servers if r.get("tier") in ("dead", "blocked")]
        if not deadish:
            st.write("No failing servers in this snapshot.")
        else:
            bc = Counter(r.get("bucket") for r in deadish)
            st.write({k: v for k, v in bc.most_common()})
            prov = Counter(r.get("provider") for r in deadish)
            st.write("Top failing ISPs:", dict(prov.most_common(15)))

    st.divider()
    st.subheader("Run a check (local)")
    st.caption(
        "Runs from this machine's network. Results reflect your vantage point — BDIX-only hosts may differ elsewhere."
    )
    with st.form("run"):
        rc1, rc2, rc3, rc4 = st.columns(4)
        pages = rc1.multiselect("Pages", ["media", "livetv"], default=["media", "livetv"])
        workers = rc2.number_input("Workers", min_value=8, max_value=128, value=48)
        timeout = rc3.number_input("Timeout (s)", min_value=3.0, max_value=30.0, value=12.0)
        do_ftp = rc4.checkbox("Probe FTP:21", value=True)
        go = st.form_submit_button("Run check and save snapshot")
    if go:
        if not pages:
            st.error("Pick at least one page.")
        else:
            progress = st.progress(0.0, text="Starting…")
            status = st.empty()
            try:
                results = asyncio.run(
                    _run_check(pages, do_ftp, int(workers), float(timeout), progress, status)
                )
                path = save_run(
                    results, runs_dir=RUNS_DIR, meta={"vantage": "local", "pages": pages}
                )
                st.success(f"Saved snapshot: {path} ({len(results)} results)")
                st.rerun()
            except Exception as e:
                st.error(f"Check failed: {e}")

    st.divider()
    st.markdown(
        "**Source:** [BDIX FTP Server List](https://sites.google.com/view/bdixftpserverlist/) (community, Google Sites). "
        "Unofficial mirror/checker — not affiliated with the source site or any ISP. "
        "A timeout from your connection does not prove a server is dead on BDIX; "
        "private-range IPs are ISP-internal."
    )
