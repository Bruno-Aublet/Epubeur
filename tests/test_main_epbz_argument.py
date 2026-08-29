from PySide6.QtGui import QIcon, QPixmap

from main import _splash_image_path, _window_icon_path, epbz_argument


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


def test_window_icon_path_points_to_an_existing_file():
    assert _window_icon_path().is_file()


def test_window_icon_path_loads_as_a_valid_icon(qapp):
    icon = QIcon(str(_window_icon_path()))
    assert not icon.isNull()


def test_splash_image_path_points_to_an_existing_file():
    assert _splash_image_path().is_file()


def test_splash_image_path_loads_as_a_valid_pixmap(qapp):
    pixmap = QPixmap(str(_splash_image_path()))
    assert not pixmap.isNull()
