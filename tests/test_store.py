from pathlib import Path

from bdix_check.store import diff_runs, filter_rows, load_run, normalize_rows, save_run


def sample():
    return [
        {
            "provider": "A",
            "page": "media",
            "kind": "server",
            "url": "http://a",
            "host": "a",
            "bucket": "OK",
            "ftp_status": "FTP_REFUSED",
            "latency_ms": 100,
            "vantage": "public",
        },
        {
            "provider": "B",
            "page": "livetv",
            "kind": "server",
            "url": "http://b",
            "host": "b",
            "bucket": "TIMEOUT",
            "ftp_status": "FTP_OK",
            "latency_ms": 5000,
            "vantage": "public",
        },
        {
            "provider": "C",
            "page": "media",
            "kind": "server",
            "url": "http://c",
            "host": "10.0.0.1",
            "bucket": "TIMEOUT",
            "ftp_status": "FTP_TIMEOUT",
            "latency_ms": None,
            "vantage": "private-range",
        },
        {
            "provider": "S",
            "page": "media",
            "kind": "social",
            "url": "http://fb",
            "host": "fb",
            "bucket": "OK",
            "ftp_status": "FTP_SKIP",
            "latency_ms": 200,
            "vantage": "public",
        },
    ]


def test_filter_defaults_to_servers_and_accessible_tiers_can_be_selected():
    rows = normalize_rows(sample())
    servers = filter_rows(rows)
    assert len(servers) == 3
    opens = filter_rows(rows, tiers={"opens", "login", "ftp_only"})
    assert {r["url"] for r in opens} == {"http://a", "http://b"}
    ftp = filter_rows(rows, ftp_only=True)
    assert [r["url"] for r in ftp] == ["http://b"]


def test_filter_query_and_private():
    rows = normalize_rows(sample())
    assert [r["url"] for r in filter_rows(rows, query="10.0.0.1")] == ["http://c"]
    assert [r["url"] for r in filter_rows(rows, include_private=False)] == ["http://a", "http://b"]


def test_save_and_load_run(tmp_path: Path):
    path = save_run(sample(), runs_dir=tmp_path)
    assert path.exists()
    loaded = load_run(path)
    assert loaded["count"] == 4
    assert all("tier" in r for r in loaded["results"])


def test_diff_runs_counts_transitions():
    prev = normalize_rows(
        [
            {"url": "http://a", "bucket": "TIMEOUT", "ftp_status": "FTP_TIMEOUT"},
            {"url": "http://b", "bucket": "OK", "ftp_status": "FTP_SKIP"},
            {"url": "http://c", "bucket": "AUTH", "ftp_status": "FTP_SKIP"},
        ]
    )
    curr = normalize_rows(
        [
            {"url": "http://a", "bucket": "OK", "ftp_status": "FTP_SKIP"},
            {"url": "http://b", "bucket": "TIMEOUT", "ftp_status": "FTP_TIMEOUT"},
            {"url": "http://c", "bucket": "TIMEOUT", "ftp_status": "FTP_TIMEOUT"},
            {"url": "http://d", "bucket": "OK", "ftp_status": "FTP_SKIP"},
        ]
    )
    d = diff_runs(curr, prev)
    assert d["now_open"] == 1
    assert d["now_dead"] == 2
    assert d["added"] == 1
    assert d["removed"] == 0
    assert d["compared"] == 3
