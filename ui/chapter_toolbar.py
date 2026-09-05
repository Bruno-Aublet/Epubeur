from PySide6.QtCore import QSignalBlocker, Qt
from PySide6.QtGui import QAction, QActionGroup, QFont, QTextCharFormat, QTextCursor
from PySide6.QtWidgets import QHBoxLayout, QInputDialog, QLineEdit, QToolButton, QWidget

from controller import ProjectController
from model.styles import ParagraphKind
from ui.chapter_editor_sync import EPUBEUR_PARAGRAPH_KIND_PROPERTY, KIND_TO_INT
from ui.chapter_preview import ChapterPreview
from ui.no_scroll_combo import NoScrollComboBox

_PARAGRAPH_STYLE_LABELS: dict[ParagraphKind, str] = {
    ParagraphKind.BODY: "Normal",
    ParagraphKind.QUOTE: "Citation",
    ParagraphKind.HEADING: "Titre",
}


class ChapterFormatToolbar(QWidget):
    """Barre d'outils de mise en forme pour le texte édité dans ChapterPreview — lit et écrit
    exclusivement via target.textCursor() (QTextCursor/QTextCharFormat/QTextBlockFormat),
    jamais directement le modèle pivot (la synchro vers celui-ci reste entièrement gérée par
    ChapterPreview._sync_to_model, cf. plan)."""

    def __init__(self, controller: ProjectController, target: ChapterPreview, parent=None):
        super().__init__(parent)
        self.controller = controller
        self.target = target

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.bold_btn = self._make_toggle_action("G", "Gras", self._toggle_bold, layout)
        self.bold_btn.setStyleSheet("font-weight: bold;")
        self.italic_btn = self._make_toggle_action("I", "Italique", self._toggle_italic, layout)
        self.italic_btn.setStyleSheet("font-style: italic;")
        self.underline_btn = self._make_toggle_action("S", "Souligné", self._toggle_underline, layout)
        self.underline_btn.setStyleSheet("text-decoration: underline;")
        self.strike_btn = self._make_toggle_action("B", "Barré", self._toggle_strikethrough, layout)
        self.strike_btn.setStyleSheet("text-decoration: line-through;")

        self.superscript_btn = self._make_toggle_action("x²", "Exposant", self._toggle_superscript, layout)
        self.subscript_btn = self._make_toggle_action("x₂", "Indice", self._toggle_subscript, layout)

        self.align_left_btn = self._make_toggle_action("⟵", "Aligner à gauche",
                                                         lambda: self._set_alignment(Qt.AlignmentFlag.AlignLeft),
                                                         layout)
        self.align_center_btn = self._make_toggle_action("↔", "Centrer",
                                                           lambda: self._set_alignment(Qt.AlignmentFlag.AlignHCenter),
                                                           layout)
        self.align_right_btn = self._make_toggle_action("⟶", "Aligner à droite",
                                                          lambda: self._set_alignment(Qt.AlignmentFlag.AlignRight),
                                                          layout)
        self.align_justify_btn = self._make_toggle_action("≡", "Justifier",
                                                            lambda: self._set_alignment(Qt.AlignmentFlag.AlignJustify),
                                                            layout)
        align_group = QActionGroup(self)
        align_group.setExclusive(True)
        for btn in (self.align_left_btn, self.align_center_btn, self.align_right_btn, self.align_justify_btn):
            align_group.addAction(btn.defaultAction())

        self.paragraph_style_combo = NoScrollComboBox()
        for kind, label in _PARAGRAPH_STYLE_LABELS.items():
            self.paragraph_style_combo.addItem(label, kind)
        self.paragraph_style_combo.activated.connect(self._apply_paragraph_style)
        layout.addWidget(self.paragraph_style_combo)

        self.font_combo = NoScrollComboBox()
        self.font_combo.addItem("Police du document", None)
        self.font_combo.activated.connect(self._apply_font)
        layout.addWidget(self.font_combo)

        self.link_btn = QToolButton()
        self.link_btn.setText("Lien")
        self.link_btn.setToolTip("Ajouter/modifier un lien hypertexte")
        self.link_btn.clicked.connect(self._edit_link)
        layout.addWidget(self.link_btn)

        self.page_break_btn = QToolButton()
        self.page_break_btn.setText("Saut de page")
        self.page_break_btn.setToolTip("Insérer un saut de page manuel après ce paragraphe")
        self.page_break_btn.clicked.connect(self._insert_page_break)
        layout.addWidget(self.page_break_btn)

        layout.addStretch()

        self._all_controls = [
            self.bold_btn, self.italic_btn, self.underline_btn, self.strike_btn,
            self.superscript_btn, self.subscript_btn,
            self.align_left_btn, self.align_center_btn, self.align_right_btn, self.align_justify_btn,
            self.paragraph_style_combo, self.font_combo, self.link_btn, self.page_break_btn,
        ]

        self.target.cursorPositionChanged.connect(self._sync_from_cursor)
        self.target.selectionChanged.connect(self._sync_from_cursor)
        self.controller.fonts_changed.connect(self._refresh_locked_fonts)
        self._refresh_locked_fonts()
        self._sync_from_cursor()

    def _make_toggle_action(self, text: str, tooltip: str, handler, layout: QHBoxLayout) -> QToolButton:
        action = QAction(text, self)
        action.setToolTip(tooltip)
        action.setCheckable(True)
        action.triggered.connect(handler)
        btn = QToolButton()
        btn.setDefaultAction(action)
        layout.addWidget(btn)
        return btn

    def _refresh_locked_fonts(self) -> None:
        current = self.font_combo.currentData()
        with QSignalBlocker(self.font_combo):
            self.font_combo.clear()
            self.font_combo.addItem("Police du document", None)
            for locked_font in self.controller.project.document.locked_fonts:
                self.font_combo.addItem(locked_font.family, locked_font.family)
            index = self.font_combo.findData(current)
            self.font_combo.setCurrentIndex(index if index >= 0 else 0)

    # -- Application des formats sur la sélection courante -----------------------------------

    def _toggle_bold(self, checked: bool) -> None:
        fmt = QTextCharFormat()
        fmt.setFontWeight(QFont.Weight.Bold if checked else QFont.Weight.Normal)
        self._merge_char_format(fmt)

    def _toggle_italic(self, checked: bool) -> None:
        fmt = QTextCharFormat()
        fmt.setFontItalic(checked)
        self._merge_char_format(fmt)

    def _toggle_underline(self, checked: bool) -> None:
        fmt = QTextCharFormat()
        fmt.setFontUnderline(checked)
        self._merge_char_format(fmt)

    def _toggle_strikethrough(self, checked: bool) -> None:
        fmt = QTextCharFormat()
        fmt.setFontStrikeOut(checked)
        self._merge_char_format(fmt)

    def _toggle_superscript(self, checked: bool) -> None:
        fmt = QTextCharFormat()
        fmt.setVerticalAlignment(
            QTextCharFormat.VerticalAlignment.AlignSuperScript if checked else QTextCharFormat.VerticalAlignment.AlignNormal
        )
        self._merge_char_format(fmt)
        with QSignalBlocker(self.subscript_btn.defaultAction()):
            self.subscript_btn.defaultAction().setChecked(False)

    def _toggle_subscript(self, checked: bool) -> None:
        fmt = QTextCharFormat()
        fmt.setVerticalAlignment(
            QTextCharFormat.VerticalAlignment.AlignSubScript if checked else QTextCharFormat.VerticalAlignment.AlignNormal
        )
        self._merge_char_format(fmt)
        with QSignalBlocker(self.superscript_btn.defaultAction()):
            self.superscript_btn.defaultAction().setChecked(False)

    def _apply_font(self, index: int) -> None:
        family = self.font_combo.itemData(index)
        cursor = self.target.textCursor()
        fmt = QTextCharFormat()
        if family:
            fmt.setFontFamilies([family])
        else:
            fmt.clearProperty(QTextCharFormat.Property.FontFamilies)
            fmt.clearProperty(QTextCharFormat.Property.FontFamily)
        cursor.mergeCharFormat(fmt)
        self.target.setFocus()

    def _set_alignment(self, alignment: Qt.AlignmentFlag) -> None:
        cursor = self.target.textCursor()
        block_format = cursor.blockFormat()
        block_format.setAlignment(alignment)
        cursor.mergeBlockFormat(block_format)
        self.target.setFocus()

    def _apply_paragraph_style(self, index: int) -> None:
        kind = self.paragraph_style_combo.itemData(index)
        cursor = self.target.textCursor()
        block_format = cursor.blockFormat()
        block_format.setProperty(EPUBEUR_PARAGRAPH_KIND_PROPERTY, KIND_TO_INT[kind])
        cursor.mergeBlockFormat(block_format)
        self.target.setFocus()

    def _edit_link(self) -> None:
        cursor = self.target.textCursor()
        if not cursor.hasSelection():
            cursor.select(QTextCursor.SelectionType.WordUnderCursor)
            self.target.setTextCursor(cursor)  # rend la sélection visible avant le dialogue
        current_url = cursor.charFormat().anchorHref()
        url, ok = QInputDialog.getText(self, "Lien hypertexte", "URL :", QLineEdit.EchoMode.Normal, current_url)
        if not ok or not cursor.hasSelection():
            return
        fmt = QTextCharFormat()
        if url:
            fmt.setAnchor(True)
            fmt.setAnchorHref(url)
        else:
            fmt.setAnchor(False)
            fmt.setAnchorHref("")
        cursor.mergeCharFormat(fmt)
        self.target.setFocus()

    def _insert_page_break(self) -> None:
        chapter_id = self.target._chapter_id
        if chapter_id is None:
            return
        cursor = self.target.textCursor()
        paragraph_index = self.target._eligible_paragraph_index_for_block(cursor.block())
        if paragraph_index is None:
            return
        # Synchronise d'abord tout texte édité non encore écrit dans le modèle : insert_page_break
        # a besoin d'un paragraph_index valide sur un chapter.paragraphs à jour.
        self.target.sync_pending_edits()
        # insert_page_break() modifie chapter.paragraphs DIRECTEMENT (pas via le buffer Qt) et
        # émet chapters_changed de façon synchrone, qui rappelle StructureEditor.refresh() ->
        # show_chapter() SANS force=True pour le chapitre déjà affiché — celui-ci retomberait
        # alors sur une simple resynchro (_sync_to_model), qui écraserait le saut de page tout
        # juste inséré avec le contenu du buffer Qt (qui, lui, ne le reflète pas encore).
        # Suspendu jusqu'à la reconstruction forcée explicite ci-dessous, seule à même de
        # refléter correctement le nouveau modèle. show_chapter() ne relâche plus ce flag
        # elle-même (cf. son commentaire — nécessaire pour undo/redo, qui émettent plusieurs
        # signaux en cascade) : relâché ici explicitement une fois la séquence terminée.
        self.target.suppress_sync_until_next_reconstruction()
        try:
            self.controller.insert_page_break(chapter_id, paragraph_index)
            self.target.show_chapter(chapter_id, force=True)
        finally:
            self.target._suppress_sync_once = False

    # -- Lecture de l'état courant du curseur -------------------------------------------------

    def _merge_char_format(self, fmt: QTextCharFormat) -> None:
        cursor = self.target.textCursor()
        cursor.mergeCharFormat(fmt)
        self.target.mergeCurrentCharFormat(fmt)
        self.target.setFocus()

    def _sync_from_cursor(self) -> None:
        cursor = self.target.textCursor()
        editable = self.target._is_selection_editable(cursor)
        for control in self._all_controls:
            control.setEnabled(editable)
        if not editable:
            return

        char_format = cursor.charFormat()
        with QSignalBlocker(self.bold_btn.defaultAction()):
            self.bold_btn.defaultAction().setChecked(char_format.fontWeight() >= QFont.Weight.Bold)
        with QSignalBlocker(self.italic_btn.defaultAction()):
            self.italic_btn.defaultAction().setChecked(char_format.fontItalic())
        with QSignalBlocker(self.underline_btn.defaultAction()):
            self.underline_btn.defaultAction().setChecked(char_format.fontUnderline())
        with QSignalBlocker(self.strike_btn.defaultAction()):
            self.strike_btn.defaultAction().setChecked(char_format.fontStrikeOut())
        with QSignalBlocker(self.superscript_btn.defaultAction()):
            self.superscript_btn.defaultAction().setChecked(
                char_format.verticalAlignment() == QTextCharFormat.VerticalAlignment.AlignSuperScript
            )
        with QSignalBlocker(self.subscript_btn.defaultAction()):
            self.subscript_btn.defaultAction().setChecked(
                char_format.verticalAlignment() == QTextCharFormat.VerticalAlignment.AlignSubScript
            )

        block_format = cursor.blockFormat()
        alignment = block_format.alignment()
        with QSignalBlocker(self.align_left_btn.defaultAction()):
            self.align_left_btn.defaultAction().setChecked(bool(alignment & Qt.AlignmentFlag.AlignLeft))
        with QSignalBlocker(self.align_center_btn.defaultAction()):
            self.align_center_btn.defaultAction().setChecked(bool(alignment & Qt.AlignmentFlag.AlignHCenter))
        with QSignalBlocker(self.align_right_btn.defaultAction()):
            self.align_right_btn.defaultAction().setChecked(bool(alignment & Qt.AlignmentFlag.AlignRight))
        with QSignalBlocker(self.align_justify_btn.defaultAction()):
            self.align_justify_btn.defaultAction().setChecked(bool(alignment & Qt.AlignmentFlag.AlignJustify))

        kind_value = block_format.property(EPUBEUR_PARAGRAPH_KIND_PROPERTY)
        kind = ParagraphKind.BODY
        if kind_value is not None:
            for candidate, value in KIND_TO_INT.items():
                if value == int(kind_value):
                    kind = candidate
                    break
        with QSignalBlocker(self.paragraph_style_combo):
            style_index = self.paragraph_style_combo.findData(kind)
            self.paragraph_style_combo.setCurrentIndex(style_index if style_index >= 0 else 0)

        with QSignalBlocker(self.font_combo):
            font_name = char_format.fontFamilies()[0] if char_format.hasProperty(
                QTextCharFormat.Property.FontFamilies) and char_format.fontFamilies() else None
            font_index = self.font_combo.findData(font_name)
            self.font_combo.setCurrentIndex(font_index if font_index >= 0 else 0)
