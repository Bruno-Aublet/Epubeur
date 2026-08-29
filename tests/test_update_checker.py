from model.update_checker import is_newer, parse_version


def test_parse_version_accepts_plain_semver():
    assert parse_version("1.2.3") == (1, 2, 3)


def test_parse_version_accepts_v_prefix():
    assert parse_version("v1.2.3") == (1, 2, 3)


def test_parse_version_rejects_malformed_string():
    assert parse_version("not-a-version") is None


def test_is_newer_true_when_remote_patch_is_higher():
    assert is_newer("1.0.3", "1.0.2") is True


def test_is_newer_false_when_versions_are_equal():
    assert is_newer("1.0.2", "1.0.2") is False


def test_is_newer_false_when_remote_is_older():
    assert is_newer("0.9.9", "1.0.2") is False


def test_is_newer_true_when_remote_major_is_higher():
    assert is_newer("2.0.0", "1.9.9") is True


def test_is_newer_false_when_either_version_is_malformed():
    assert is_newer("bad", "1.0.2") is False
    assert is_newer("1.0.3", "bad") is False


def test_update_checker_signal_carries_version_and_url(qapp):
    from model.update_checker import UpdateChecker

    checker = UpdateChecker("1.0.0")
    received = []
    checker.update_available.connect(lambda version, url: received.append((version, url)))

    checker.update_available.emit("1.2.0", "https://github.com/Bruno-Aublet/Epubeur/releases/latest")

    assert received == [("1.2.0", "https://github.com/Bruno-Aublet/Epubeur/releases/latest")]
