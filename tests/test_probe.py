
from bdix_check.probe import _bucket_for_exc, _bucket_for_status, _vantage


def test_bucket_for_status():
    assert _bucket_for_status(200) == "OK"
    assert _bucket_for_status(301) == "REDIRECT"
    assert _bucket_for_status(401) == "AUTH"
    assert _bucket_for_status(403) == "FORBIDDEN"
    assert _bucket_for_status(404) == "NOT_FOUND"
    assert _bucket_for_status(502) == "SERVER_ERR"


def test_vantage_private():
    assert _vantage("10.1.1.1") == "private-range"
    assert _vantage("172.16.50.4") == "private-range"
    assert _vantage("192.168.0.2") == "private-range"
    assert _vantage("103.58.73.6") == "public"
    assert _vantage("example.com") == "public"


def test_bucket_for_timeout_exc():
    assert _bucket_for_exc(TimeoutError("timed out")) == "TIMEOUT"
