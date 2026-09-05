"""Refonte de la synchronisation texte -> modèle pivot (2026-09-01) : le mécanisme purement
différé (synchro seulement à la perte de focus/changement de chapitre/sauvegarde) causait des
bugs en cascade (menu contextuel invisible, Ctrl+Z inopérant) et ne marquait jamais le projet
"non enregistré" avant une synchro différée. Remplacé par un débounce court (500ms d'inactivité
clavier) qui garde le modèle pivot toujours quasi à jour, sans jamais dépendre du focus, et par
un dirty flag posé immédiatement à chaque frappe (avant même la synchro)."""
from controller import ProjectController
from model.document import Chapter, Paragraph, Run
from model.styles import CharFormat
from PySide6.QtCore import Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtTest import QTest
from ui.structure_editor import StructureEditor


def _make_editor(qapp) -> tuple[ProjectController, StructureEditor]:
    controller = ProjectController()
    editor = StructureEditor(controller)
    return controller, editor


def _type_character(preview, char: str) -> None:
    """Simule une vraie frappe clavier via keyPressEvent (pas cursor.insertText, qui contourne
    le mécanisme de débounce/dirty branché sur keyPressEvent/inputMethodEvent)."""
    event = QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key.Key_A, Qt.KeyboardModifier.NoModifier, char)
    preview.keyPressEvent(event)


def test_typing_marks_project_dirty_immediately_without_sync(qapp):
    """Régression : le dirty flag ne se levait qu'à la synchro différée — fermer l'app juste
    après avoir tapé (sans perte de focus préalable) ne déclenchait pas l'avertissement
    "modifications non enregistrées". mark_dirty() doit être appelé dès keyPressEvent, avant
    toute synchro vers le modèle pivot."""
    controller, editor = _make_editor(qapp)
    chapter = Chapter.create(title="Chapitre Un")
    chapter.paragraphs = [Paragraph(runs=[Run(text="Original", fmt=CharFormat())])]
    controller.project.document.add_chapter(chapter)
    controller.chapters_changed.emit()

    item = editor.tree.topLevelItem(0)
    editor.tree.setCurrentItem(item)
    preview = editor.preview
    assert controller.has_unsaved_content() is False

    block = preview.document().begin().next()
    cursor = preview.textCursor()
    cursor.setPosition(block.position())
    preview.setTextCursor(cursor)

    _type_character(preview, "X")

    # Le dirty flag doit être vrai IMMÉDIATEMENT, avant que le débounce (500ms) n'ait eu la
    # moindre chance de se déclencher — sync_timer n'a même pas été laissé tourner ici.
    assert controller.has_unsaved_content() is True


def test_debounce_syncs_automatically_after_inactivity(qapp):
    """Le modèle pivot doit refléter la frappe après le délai d'inactivité du débounce, SANS
    appel explicite à sync_pending_edits() — le timer doit se déclencher seul."""
    controller, editor = _make_editor(qapp)
    chapter = Chapter.create(title="Chapitre Un")
    chapter.paragraphs = [Paragraph(runs=[Run(text="Original", fmt=CharFormat())])]
    controller.project.document.add_chapter(chapter)
    controller.chapters_changed.emit()

    item = editor.tree.topLevelItem(0)
    editor.tree.setCurrentItem(item)
    preview = editor.preview

    block = preview.document().begin().next()
    cursor = preview.textCursor()
    cursor.setPosition(block.position())
    cursor.movePosition(cursor.MoveOperation.EndOfBlock, cursor.MoveMode.KeepAnchor)
    preview.setTextCursor(cursor)
    preview.textCursor().insertText(" Modifié")
    # insertText() direct ne passe pas par keyPressEvent -- démarre le timer manuellement, pour
    # isoler ce test du mécanisme de détection de frappe (déjà couvert par le test précédent).
    preview._on_text_possibly_changed()

    assert controller.project.document.chapters[chapter.id].paragraphs[0].plain_text() == "Original"
    assert preview._sync_timer.isActive() is True

    # Réduit l'intervalle pour ne pas ralentir la suite avec un vrai délai de 500ms.
    preview._sync_timer.setInterval(20)
    preview._sync_timer.start()
    QTest.qWait(80)

    assert preview._sync_timer.isActive() is False
    assert "Modifié" in controller.project.document.chapters[chapter.id].paragraphs[0].plain_text()


def test_sync_timer_stopped_by_explicit_sync(qapp):
    """Un appel explicite à sync_pending_edits() (perte de focus, changement de chapitre...)
    doit arrêter le débounce en cours, pas seulement synchroniser en plus de lui."""
    controller, editor = _make_editor(qapp)
    chapter = Chapter.create(title="Chapitre Un")
    chapter.paragraphs = [Paragraph(runs=[Run(text="Original", fmt=CharFormat())])]
    controller.project.document.add_chapter(chapter)
    controller.chapters_changed.emit()

    item = editor.tree.topLevelItem(0)
    editor.tree.setCurrentItem(item)
    preview = editor.preview

    block = preview.document().begin().next()
    cursor = preview.textCursor()
    cursor.setPosition(block.position())
    cursor.movePosition(cursor.MoveOperation.EndOfBlock, cursor.MoveMode.KeepAnchor)
    preview.setTextCursor(cursor)
    preview.textCursor().insertText(" Modifié")
    preview._on_text_possibly_changed()
    assert preview._sync_timer.isActive() is True

    preview.sync_pending_edits()

    assert preview._sync_timer.isActive() is False
    assert "Modifié" in controller.project.document.chapters[chapter.id].paragraphs[0].plain_text()


def test_ctrl_z_via_real_keypress_event_undoes_typed_text(qapp):
    """Régression critique : Qt (QTextBrowser, comme tout widget de texte) intercepte et
    CONSOMME Ctrl+Z/Ctrl+Y dans son propre traitement interne dès que le widget a le focus — même
    avec setUndoRedoEnabled(False) (qui désactive seulement la modification du document, pas la
    consommation de l'événement clavier). L'événement ne remontait donc JAMAIS jusqu'au raccourci
    de menu Edit > Annuler : appuyer sur Ctrl+Z dans le panneau ne déclenchait RIEN, quelle que
    soit la logique de synchro derrière — tous les tests précédents appelaient perform_undo (ou
    l'ancien controller.undo()) directement, sans jamais passer par un vrai keyPressEvent, donc
    aucun ne pouvait détecter ce problème. Ce test envoie un VRAI QKeyEvent à keyPressEvent, sans
    jamais appeler perform_undo/perform_redo directement, pour couvrir le chemin réel."""
    controller, editor = _make_editor(qapp)
    chapter = Chapter.create(title="Chapitre Un")
    chapter.paragraphs = [Paragraph(runs=[Run(text="Original", fmt=CharFormat())])]
    controller.project.document.add_chapter(chapter)
    controller.chapters_changed.emit()

    item = editor.tree.topLevelItem(0)
    editor.tree.setCurrentItem(item)
    preview = editor.preview

    block = preview.document().begin().next()
    cursor = preview.textCursor()
    cursor.setPosition(block.position())
    cursor.movePosition(cursor.MoveOperation.EndOfBlock, cursor.MoveMode.KeepAnchor)
    preview.setTextCursor(cursor)
    _type_character(preview, "X")
    assert controller.project.document.chapters[chapter.id].paragraphs[0].plain_text() == "Original"
    assert preview.toPlainText().strip().endswith("X")

    undo_event = QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier, "z")
    preview.keyPressEvent(undo_event)

    assert controller.project.document.chapters[chapter.id].paragraphs[0].plain_text() == "Original"
    assert preview.toPlainText().strip().endswith("Original")
    # Régression distincte : controller.undo()/redo() émettent QUATRE signaux à la suite
    # (chapters_changed, structure_changed, fonts_changed, assets_changed), chacun connecté à
    # StructureEditor.refresh() -> show_chapter() : show_chapter() était appelée plusieurs fois
    # en cascade pour ce seul undo(), et relâchait _suppress_sync_once dès le PREMIER appel — les
    # suivants retombaient sans protection sur une resynchro qui écrasait le undo qui venait de
    # réussir, vidant silencieusement redo_stack (repoussé par le _snapshot_structure() de cette
    # resynchro non voulue). undo_stack/redo_stack finissaient identiques à leur état d'avant
    # l'opération : Ctrl+Z semblait "avoir marché" (le texte affiché changeait bien une première
    # fois) mais Ctrl+Y n'avait plus rien à rétablir juste après.
    assert len(controller._undo_stack) == 0
    assert len(controller._redo_stack) == 1

    redo_event = QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key.Key_Y, Qt.KeyboardModifier.ControlModifier, "y")
    preview.keyPressEvent(redo_event)

    assert controller.project.document.chapters[chapter.id].paragraphs[0].plain_text() == "X"
    assert preview.toPlainText().strip().endswith("X")
    assert len(controller._undo_stack) == 1
    assert len(controller._redo_stack) == 0
