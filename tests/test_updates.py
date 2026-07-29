from fleech.ui.updates import check_for_updates, is_newer


def test_version_comparison():
    assert is_newer("1.1.0", "1.0.0")
    assert is_newer("1.0.1", "1.0.0")
    assert is_newer("2.0.0", "1.9.9")
    assert not is_newer("1.0.0", "1.0.0")
    assert not is_newer("0.9.0", "1.0.0")


def test_no_feed_returns_not_configured():
    result = check_for_updates(None)
    assert result["status"] == "not_configured"
    assert "current" in result


def test_bad_feed_url_returns_error_not_crash():
    result = check_for_updates("http://127.0.0.1:9/nope.json", timeout=0.5)
    assert result["status"] == "error"
    assert result["current"]
