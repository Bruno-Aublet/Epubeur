from main import epbz_argument


def test_returns_none_with_no_arguments():
    assert epbz_argument([]) is None


def test_returns_none_when_no_epbz_argument():
    assert epbz_argument(["--debug", "foo.txt"]) is None


def test_finds_existing_epbz_path(tmp_path):
    epbz_path = tmp_path / "MonRoman.epbz"
    epbz_path.write_bytes(b"fake zip content")

    assert epbz_argument([str(epbz_path)]) == epbz_path


def test_ignores_epbz_path_that_does_not_exist(tmp_path):
    nonexistent = tmp_path / "nexistepas.epbz"
    assert epbz_argument([str(nonexistent)]) is None


def test_case_insensitive_extension_match(tmp_path):
    epbz_path = tmp_path / "MonRoman.EPBZ"
    epbz_path.write_bytes(b"fake zip content")

    assert epbz_argument([str(epbz_path)]) == epbz_path


def test_ignores_non_epbz_arguments_and_finds_the_epbz_one(tmp_path):
    epbz_path = tmp_path / "MonRoman.epbz"
    epbz_path.write_bytes(b"fake zip content")

    assert epbz_argument(["--flag", str(epbz_path), "autre_argument"]) == epbz_path
