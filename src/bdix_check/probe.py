from __future__ import annotations

import asyncio
import ipaddress
import socket
import time
from dataclasses import asdict, dataclass
from typing import Any

import httpx

from .fetch import Target


@dataclass(slots=True)
class ProbeResult:
    provider: str
    page: str
    kind: str
    url: str
    host: str
    scheme: str
    http_status: int | None
    bucket: str
    latency_ms: int | None
    final_url: str | None
    redirects: int
    ftp_status: str
    ftp_banner: str | None
    note: str
    vantage: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _vantage(host: str) -> str:
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return "public"
    if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
        return "private-range"
    return "public"


def _bucket_for_status(status: int) -> str:
    if 200 <= status < 300:
        return "OK"
    if 300 <= status < 400:
        return "REDIRECT"
    if status in (401, 407):
        return "AUTH"
    if status == 403:
        return "FORBIDDEN"
    if status == 404:
        return "NOT_FOUND"
    if 400 <= status < 500:
        return f"CLIENT_{status}"
    if 500 <= status < 600:
        return "SERVER_ERR"
    return "UNKNOWN"


def _bucket_for_exc(exc: Exception) -> str:
    msg = str(exc).lower()
    name = type(exc).__name__.lower()
    if isinstance(exc, (httpx.ConnectTimeout, httpx.ReadTimeout, httpx.PoolTimeout, asyncio.TimeoutError)):
        return "TIMEOUT"
    if isinstance(exc, httpx.ConnectError):
        if "name or service not known" in msg or "nodename nor servname" in msg or "getaddrinfo" in msg:
            return "DNS_FAIL"
        if "refused" in msg:
            return "REFUSED"
        if "ssl" in msg or "certificate" in msg or "tls" in msg:
            return "TLS_ERR"
        return "CONNECT_ERR"
    if "ssl" in name or "certificate" in msg or "tls" in msg:
        return "TLS_ERR"
    if "timeout" in name or "timed out" in msg:
        return "TIMEOUT"
    if "dns" in msg or "getaddrinfo" in msg:
        return "DNS_FAIL"
    return "UNKNOWN"


async def probe_ftp(host: str, port: int = 21, timeout: float = 3.0) -> tuple[str, str | None]:
    try:
        # quick DNS resolve to distinguish
        loop = asyncio.get_running_loop()
        try:
            await asyncio.wait_for(loop.getaddrinfo(host, port, type=socket.SOCK_STREAM), timeout=timeout)
        except socket.gaierror:
            return "FTP_NO_DNS", None
        reader, writer = await asyncio.wait_for(asyncio.open_connection(host, port), timeout=timeout)
        try:
            data = await asyncio.wait_for(reader.read(256), timeout=timeout)
            banner = data.decode("utf-8", errors="replace").strip() if data else ""
            banner = "".join(ch for ch in banner if ch.isprintable() or ch in " \t")[:120] or None
            return "FTP_OK", banner
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass
    except TimeoutError:
        return "FTP_TIMEOUT", None
    except ConnectionRefusedError:
        return "FTP_REFUSED", None
    except OSError as e:
        msg = str(e).lower()
        if "refused" in msg:
            return "FTP_REFUSED", None
        if "name or service not known" in msg or "nodename" in msg:
            return "FTP_NO_DNS", None
        if "timed out" in msg:
            return "FTP_TIMEOUT", None
        return "FTP_ERR", str(e)[:80]
    except Exception as e:
        return "FTP_ERR", str(e)[:80]


async def _http_once(client: httpx.AsyncClient, url: str, method: str) -> httpx.Response:
    if method == "HEAD":
        return await client.head(url)
    # streamed GET with range to be light
    headers = {"Range": "bytes=0-0"}
    req = client.build_request("GET", url, headers=headers)
    resp = await client.send(req, stream=True)
    await resp.aread()
    await resp.aclose()
    return resp


async def probe_http(client: httpx.AsyncClient, url: str, timeout: float) -> tuple[int | None, str, int | None, str | None, int, str]:
    t0 = time.perf_counter()
    redirects = 0
    try:
        # first try HEAD
        try:
            r = await _http_once(client, url, "HEAD")
        except Exception:
            r = None
        if r is None or r.status_code in (403, 405, 501):
            r = await _http_once(client, url, "GET")
        # httpx with follow_redirects=True tracks history
        redirects = len(r.history)
        ms = int((time.perf_counter() - t0) * 1000)
        bucket = _bucket_for_status(r.status_code)
        return r.status_code, bucket, ms, str(r.url), redirects, ""
    except Exception as e:
        ms = int((time.perf_counter() - t0) * 1000)
        bucket = _bucket_for_exc(e)
        note = type(e).__name__
        return None, bucket, ms, None, redirects, note


async def probe_target(
    target: Target,
    client: httpx.AsyncClient,
    sem: asyncio.Semaphore,
    timeout: float,
    do_ftp: bool,
) -> ProbeResult:
    async with sem:
        http_status, bucket, latency_ms, final_url, redirects, note = await probe_http(client, target.url, timeout)
        ftp_status, ftp_banner = ("FTP_SKIP", None)
        if do_ftp:
            ftp_status, ftp_banner = await probe_ftp(target.host)
        return ProbeResult(
            provider=target.provider,
            page=target.page,
            kind=target.kind,
            url=target.url,
            host=target.host,
            scheme=target.scheme,
            http_status=http_status,
            bucket=bucket,
            latency_ms=latency_ms,
            final_url=final_url,
            redirects=redirects,
            ftp_status=ftp_status,
            ftp_banner=ftp_banner,
            note=note,
            vantage=_vantage(target.host),
        )
