from bdix_check.fetch import (
    classify_kind,
    clean_provider_name,
    parse_targets,
    unwrap_google_url,
)

SAMPLE_HTML = """
<html><body>
<h3>⭐1. PROVIDER A FTP SERVER</h3>
<a href="https://www.google.com/url?q=http%3A%2F%2Fexample.com&sa=D">http://example.com</a>
<a href="https://www.google.com/url?q=https%3A%2F%2Fwww.facebook.com%2Fgroup&sa=D">fb</a>
<h3>2. PROVIDER B</h3>
<a href="http://10.0.0.5/media">local</a>
<a href="http://example.com/">dup</a>
</body></html>
"""


def test_unwrap_google_url():
    href = "https://www.google.com/url?q=http%3A%2F%2Fftpbd.net&sa=D&sntz=1"
    assert unwrap_google_url(href) == "http://ftpbd.net"
    assert unwrap_google_url("http://direct.test/path") == "http://direct.test/path"
    assert unwrap_google_url("/relative") is None


def test_parse_targets_provider_and_dedupe():
    targets = parse_targets(SAMPLE_HTML, "media")
    urls = [t.url for t in targets]
    assert "http://example.com" in urls
    assert "http://10.0.0.5/media" in urls
    # duplicate example.com/ should be removed
    assert sum(1 for u in urls if "example.com" in u) == 1
    # provider mapping: emoji/number/suffix stripped, original index preserved
    by_url = {t.url: t for t in targets}
    assert by_url["http://example.com"].provider == "PROVIDER A"
    assert by_url["http://example.com"].provider_index == 1
    assert by_url["http://10.0.0.5/media"].provider == "PROVIDER B"
    assert by_url["http://10.0.0.5/media"].provider_index == 2


def test_clean_provider_name():
    assert clean_provider_name("⭐1. BUSINESS NETWORK (FTPBD) FTP SERVER🔝") == (
        1,
        "BUSINESS NETWORK (FTPBD)",
    )
    assert clean_provider_name("18. MOJALOSS FTP SERVER") == (18, "MOJALOSS")
    assert clean_provider_name("TOP 50 ACTIVE SERVERS") == (None, "Unknown")
    assert clean_provider_name("A-Z") == (None, "Unknown")
    assert clean_provider_name(None) == (None, "Unknown")
    assert clean_provider_name("   ") == (None, "Unknown")


def test_classify_kind():
    assert classify_kind("www.facebook.com") == "social"
    assert classify_kind("pastebin.com") == "social"
    assert classify_kind("103.58.73.6") == "server"
    assert classify_kind("ftp.example.net") == "server"
