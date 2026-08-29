from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QWheelEvent

from ui.no_scroll_combo import NoScrollComboBox


def _make_wheel_event() -> QWheelEvent:
    return QWheelEvent(
        QPointF(0, 0), QPointF(0, 0), QPoint(0, 120), QPoint(0, 120),
        Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier,
        Qt.ScrollPhase.NoScrollPhase, False,
    )


def test_wheel_event_ignored_without_focus(qapp):
    combo = NoScrollComboBox()
    combo.addItem("Un")
    combo.addItem("Deux")

    event = _make_wheel_event()
    combo.wheelEvent(event)

    assert combo.currentIndex() == 0
    assert not event.isAccepted()


def test_wheel_event_accepted_when_focused(qapp, monkeypatch):
    combo = NoScrollComboBox()
    combo.addItem("Un")
    combo.addItem("Deux")
    # setFocus() ne prend effet de façon synchrone que sur une fenêtre visible avec le focus
    # système, absent en offscreen (QT_QPA_PLATFORM) — on force directement l'état interne testé
    # par wheelEvent (hasFocus()) plutôt que de dépendre d'un vrai gestionnaire de fenêtres.
    monkeypatch.setattr(NoScrollComboBox, "hasFocus", lambda self: True)

    event = _make_wheel_event()
    combo.wheelEvent(event)

    assert event.isAccepted()
