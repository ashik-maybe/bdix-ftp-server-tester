from bdix_check.tiers import enrich, is_accessible, tier_for


def test_tier_opens():
    assert tier_for({"bucket": "OK", "ftp_status": "FTP_REFUSED"}) == "opens"
    assert tier_for({"bucket": "REDIRECT", "ftp_status": "FTP_SKIP"}) == "opens"


def test_tier_login():
    assert tier_for({"bucket": "AUTH", "ftp_status": "FTP_TIMEOUT"}) == "login"


def test_tier_ftp_only():
    assert tier_for({"bucket": "TIMEOUT", "ftp_status": "FTP_OK"}) == "ftp_only"
    assert is_accessible({"bucket": "DNS_FAIL", "ftp_status": "FTP_OK"}) is True


def test_tier_blocked_and_dead():
    assert tier_for({"bucket": "FORBIDDEN", "ftp_status": "FTP_REFUSED"}) == "blocked"
    assert tier_for({"bucket": "NOT_FOUND", "ftp_status": "FTP_SKIP"}) == "blocked"
    assert tier_for({"bucket": "TIMEOUT", "ftp_status": "FTP_TIMEOUT"}) == "dead"
    assert is_accessible({"bucket": "TIMEOUT", "ftp_status": "FTP_TIMEOUT"}) is False


def test_enrich_adds_labels():
    rows = enrich([{"bucket": "OK", "ftp_status": "FTP_SKIP"}])
    assert rows[0]["tier"] == "opens"
    assert rows[0]["tier_label"] == "Opens"
