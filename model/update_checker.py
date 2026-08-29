import json
import re

from PySide6.QtCore import QObject, QUrl, Signal
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest

GITHUB_LATEST_RELEASE_API = "https://api.github.com/repos/Bruno-Aublet/Epubeur/releases/latest"
GITHUB_LATEST_RELEASE_PAGE = "https://github.com/Bruno-Aublet/Epubeur/releases/latest"


def parse_version(version: str) -> tuple[int, ...] | None:
    """Convertit "1.2.3" (ou "v1.2.3") en tuple comparable (1, 2, 3). None si le format ne
    correspond pas à un simple x.y.z — on préfère ignorer une release mal formée plutôt que de
    planter ou de la comparer au hasard."""
    match = re.fullmatch(r"v?(\d+)\.(\d+)\.(\d+)", version.strip())
    if match is None:
        return None
    return tuple(int(part) for part in match.groups())


def is_newer(remote_version: str, current_version: str) -> bool:
    remote = parse_version(remote_version)
    current = parse_version(current_version)
    if remote is None or current is None:
        return False
    return remote > current


class UpdateChecker(QObject):
    """Interroge l'API GitHub releases/latest de manière asynchrone (ne bloque jamais le
    démarrage de l'appli) et signale si une version plus récente que __version__ est disponible.
    update_available est le seul signal utilisé par la vérification automatique au démarrage —
    silencieuse en cas d'échec réseau ou si l'appli est déjà à jour. up_to_date et check_failed
    existent pour la vérification manuelle (menu Aide), qui doit donner un retour dans tous les
    cas puisque l'utilisateur l'a explicitement demandée."""

    update_available = Signal(str, str)  # (version_distante, url_release)
    up_to_date = Signal()
    check_failed = Signal()

    def __init__(self, current_version: str, parent=None):
        super().__init__(parent)
        self._current_version = current_version
        self._manager = QNetworkAccessManager(self)
        self._reply: QNetworkReply | None = None

    def check(self) -> None:
        request = QNetworkRequest(QUrl(GITHUB_LATEST_RELEASE_API))
        request.setHeader(QNetworkRequest.KnownHeaders.UserAgentHeader, "Epubeur-UpdateChecker")
        self._reply = self._manager.get(request)
        self._reply.finished.connect(self._on_finished)

    def _on_finished(self) -> None:
        reply = self._reply
        self._reply = None
        if reply is None:
            return
        reply.deleteLater()
        if reply.error() != QNetworkReply.NetworkError.NoError:
            self.check_failed.emit()
            return
        try:
            data = json.loads(bytes(reply.readAll()).decode("utf-8"))
            remote_version = str(data["tag_name"])
            release_url = str(data.get("html_url") or GITHUB_LATEST_RELEASE_PAGE)
        except (ValueError, KeyError, TypeError):
            self.check_failed.emit()
            return
        if is_newer(remote_version, self._current_version):
            self.update_available.emit(remote_version, release_url)
        else:
            self.up_to_date.emit()
