from PySide6.QtCore import QLocale, QObject, Qt, Signal
from PySide6.QtGui import QAbstractTextDocumentLayout, QColor, QCursor, QPainter, QTextDocument
from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QTextEdit,
    QToolTip,
    QVBoxLayout,
    QWidget,
)

from controller import ProjectController
from model.book_metadata import BookMetadata, Contributor
from model.contributor_roles import CONTRIBUTOR_ROLE_LABELS
from model.language import LANGUAGE_NAMES_FR
from model.thema import thema_children, thema_parent_chain
from ui.metadata_conflict_dialog import MetadataConflictDialog
from ui.no_scroll_combo import NoScrollComboBox


def _derive_file_as(author_name: str) -> str:
    """Dérive un nom de tri "Nom, Prénom(s)" depuis un nom affiché "Prénom(s) Nom" — règle
    simple (dernier mot = nom de famille) qui couvre le cas courant, mais se trompera sur un nom
    composé ou une particule (ex. "Charles de Gaulle") : c'est pourquoi le champ résultant reste
    toujours éditable à la main plutôt que verrouillé sur cette heuristique."""
    parts = author_name.strip().split()
    if len(parts) < 2:
        return author_name.strip()
    return f"{parts[-1]}, {' '.join(parts[:-1])}"


def _set_immediate_yellow_tooltip(widget: QWidget, text: str) -> None:
    """Tooltip jaune classique (fond clair, distinct du thème de la fenêtre) qui s'affiche dès
    l'entrée de la souris, sans attendre le délai par défaut de Qt (~700ms) — même traitement que
    les menus Thema (_ThemaRow), factorisé ici pour être réutilisé sur d'autres widgets."""
    widget.setToolTip(text)
    widget.setStyleSheet(
        (widget.styleSheet() or "")
        + " QToolTip { background-color: #FFFFCC; color: #000000; border: 1px solid #808080; }"
    )
    base_enter_event = type(widget).enterEvent

    def _enter_event(event: object, w: QWidget = widget) -> None:
        if w.toolTip():
            QToolTip.showText(QCursor.pos(), w.toolTip(), w)
        base_enter_event(w, event)

    widget.enterEvent = _enter_event


class _WrappingPlaceholderTextEdit(QTextEdit):
    """QTextEdit dont le placeholder fait un vrai retour à la ligne — QTextEdit.setPlaceholderText
    ne wrap JAMAIS (limite de Qt, vérifiée par rendu comparé : le même texte affiché comme
    contenu réel wrap correctement, affiché comme placeholder natif il reste sur une seule ligne
    tronquée par la largeur du widget, quelle que soit la hauteur disponible). Le placeholder est
    donc peint manuellement via un QTextDocument séparé dans paintEvent, seulement quand le champ
    est vide."""

    def __init__(self, placeholder_text: str, parent=None):
        super().__init__(parent)
        self._placeholder_text = placeholder_text

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        if self.toPlainText():
            return
        painter = QPainter(self.viewport())
        doc = QTextDocument()
        doc.setDefaultFont(self.font())
        doc.setTextWidth(self.viewport().width())
        doc.setPlainText(self._placeholder_text)
        painter.translate(2, 2)
        ctx = QAbstractTextDocumentLayout.PaintContext()
        ctx.palette.setColor(ctx.palette.ColorRole.Text, QColor("#8a8a8a"))
        doc.documentLayout().draw(painter, ctx)
        painter.end()


class _ContributorRow(QObject):
    """Deux VRAIES lignes du QFormLayout principal par contributeur, miroir exact du bloc
    Auteur/Nom de tri de l'auteur (mêmes placeholders, même alignement de label dans la colonne
    de gauche — pas de sous-formulaire ni de widget composite imbriqué qui décalerait les labels).
    QObject (pas QWidget) : cette classe ne porte aucun layout/apparence propre, elle expose juste
    les deux widgets de ligne (name_row_widget, file_as_edit) que GeneratePanel insère/retire
    directement dans son propre form via insertRow/removeRow, en renumérotant à chaque
    ajout/retrait les labels "Contributeur N :"/"Nom de tri du contributeur N :" qu'il possède
    (cf. GeneratePanel._renumber_contributor_labels)."""

    removed = Signal(object)  # émet self, pour que GeneratePanel retire la paire de lignes

    def __init__(self, parent=None):
        super().__init__(parent)

        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("ex : Jean-Paul Sartre (prénom puis nom, pas de virgule)")

        self.role_combo = NoScrollComboBox()
        for code, label in CONTRIBUTOR_ROLE_LABELS.items():
            self.role_combo.addItem(label, code)
        # Code de rôle non reconnu par CONTRIBUTOR_ROLE_LABELS (import EPUB externe, édition
        # manuelle du JSON .epbz) : le combo ne peut pas l'afficher (aucune entrée ne correspond),
        # mais il ne doit pas pour autant être remplacé silencieusement par "non précisé" dès la
        # réouverture du formulaire — conservé ici tant que l'utilisateur n'a pas lui-même changé
        # la sélection, cf. set_role_code/to_contributor ci-dessous.
        self._unrecognized_role_code: str | None = None
        self.role_combo.currentIndexChanged.connect(self._on_role_combo_changed)

        self.remove_btn = QPushButton("Retirer")
        self.remove_btn.clicked.connect(lambda: self.removed.emit(self))

        # Emplacement réservé pour le bouton "+" global (jamais rempli qu'au plus une seule fois,
        # sur la dernière ligne) — cf. GeneratePanel._reposition_add_contributor_button.
        self.trailing_slot = QHBoxLayout()

        name_row = QHBoxLayout()
        name_row.setContentsMargins(0, 0, 0, 0)
        name_row.addWidget(self.name_edit, 1)
        name_row.addWidget(self.role_combo)
        name_row.addWidget(self.remove_btn)
        name_row.addLayout(self.trailing_slot)
        # QFormLayout::addRow(label, widget) exige un QWidget — un QHBoxLayout ne peut pas être
        # passé directement (ni réinséré après removeRow sans porteur stable).
        self.name_row_widget = QWidget()
        self.name_row_widget.setLayout(name_row)

        self.file_as_edit = QLineEdit()
        self.file_as_edit.setPlaceholderText(
            "ex : Sartre, Jean-Paul (nom puis prénom avec une virgule : ce champ est utilisé pour le tri alphabétique)")
        self._file_as_manually_set = False
        self.name_edit.textEdited.connect(self._on_name_edited)
        self.file_as_edit.textEdited.connect(self._mark_file_as_manually_set)

    def _on_name_edited(self, text: str) -> None:
        if not self._file_as_manually_set:
            self.file_as_edit.setText(_derive_file_as(text))

    def _mark_file_as_manually_set(self) -> None:
        self._file_as_manually_set = True

    def set_file_as(self, file_as: str) -> None:
        """Fixe le nom de tri programmatiquement (import EPUB) sans le marquer comme modifié à
        la main — symétrique de apply_metadata pour l'auteur."""
        self.file_as_edit.setText(file_as or _derive_file_as(self.name_edit.text()))
        self._file_as_manually_set = bool(file_as)

    def set_role_code(self, role_code: str) -> None:
        """Fixe le rôle programmatiquement (import EPUB/rechargement de projet) — si role_code
        n'est reconnu par aucune entrée du combo, il est conservé tel quel dans
        _unrecognized_role_code plutôt que silencieusement perdu au profit de la valeur par
        défaut affichée (index 0, "non précisé")."""
        index = self.role_combo.findData(role_code)
        if index != -1:
            self._unrecognized_role_code = None
            self.role_combo.setCurrentIndex(index)
        else:
            self._unrecognized_role_code = role_code or None

    def _on_role_combo_changed(self) -> None:
        # Un choix explicite de l'utilisateur dans le combo prime toujours sur un code non
        # reconnu conservé précédemment — sans ça, le code d'origine reviendrait malgré un
        # changement manuel ultérieur.
        self._unrecognized_role_code = None

    def to_contributor(self) -> Contributor:
        return Contributor(
            name=self.name_edit.text(),
            role_code=self._unrecognized_role_code or self.role_combo.currentData(),
            file_as=self.file_as_edit.text(),
        )


class _ThemaRow(QWidget):
    """Classification Thema : une suite de menus déroulants en cascade, profondeur DYNAMIQUE —
    un nouveau menu apparaît sur la même ligne tant que le code sélectionné a des sous-catégories
    (thema_children non vide), et les menus devenus obsolètes disparaissent dès qu'une sélection
    en amont change. Le premier menu (les catégories racines, réglé sur "(aucun)" par défaut) est
    toujours présent. Une seule instance fixe dans GeneratePanel (pas de liste de lignes
    ajoutables/supprimables — un livre n'a besoin que d'une seule classification Thema finale,
    obtenue en affinant la sélection de menu en menu)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._row_layout = QHBoxLayout(self)
        self._row_layout.setContentsMargins(0, 0, 0, 0)
        self.combos: list[QComboBox] = []
        # Ancre tous les menus à gauche : sans ce stretch final, le QHBoxLayout n'a rien pour
        # absorber l'espace restant et le QFormLayout parent centre la ligne entière.
        self._row_layout.addStretch(1)
        # Fond jaune classique pour ne pas se confondre avec le fond de la fenêtre — la feuille
        # de style Qt par défaut (thème sombre/clair du système) ne garantit pas un tooltip
        # visuellement distinct.
        self.setStyleSheet("QToolTip { background-color: #FFFFCC; color: #000000; border: 1px solid #808080; }")

        self._add_level("")  # premier menu : les catégories racines

    def _add_level(self, parent_code: str) -> None:
        combo = NoScrollComboBox()
        combo.addItem("(aucun)", "")
        for code, label in thema_children(parent_code):
            combo.addItem(label, code)
            combo.setItemData(combo.count() - 1, label, Qt.ItemDataRole.ToolTipRole)
        combo.currentIndexChanged.connect(self._on_combo_changed)
        # Largeur plafonnée mais confortable : certains libellés Thema sont très longs (ex.
        # "Architectes et cabinets d'architecture") — sans plafond, QComboBox réclame sa largeur
        # préférée (le texte le plus long de sa liste) et chaque menu ajouté élargit la fenêtre
        # un peu plus, sans jamais se stabiliser. Le texte tronqué reste lisible via l'ellipse
        # (au lieu d'une coupe brutale) et le tooltip affiche le libellé complet au survol.
        combo.setMaximumWidth(260)
        combo.setMinimumWidth(160)
        combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        combo.setMinimumContentsLength(20)
        combo.setToolTip(combo.currentText())
        combo.currentTextChanged.connect(combo.setToolTip)
        # Le délai par défaut de Qt avant affichage d'un tooltip (~700ms) est trop long ici —
        # affichage immédiat en interceptant l'entrée de la souris plutôt que de compter sur le
        # mécanisme automatique.
        combo.enterEvent = lambda event, c=combo: self._show_tooltip_immediately(c, event)
        self._row_layout.insertWidget(self._row_layout.count() - 1, combo)
        self.combos.append(combo)

    def _show_tooltip_immediately(self, combo: QComboBox, event) -> None:
        if combo.toolTip():
            QToolTip.showText(QCursor.pos(), combo.toolTip(), combo)
        QComboBox.enterEvent(combo, event)

    def _truncate_after(self, level: int) -> None:
        """Retire tous les menus au-delà de `level` — appelé quand une sélection en amont
        change, pour ne jamais laisser un menu enfant obsolète (sous-catégories d'un code qui
        n'est plus sélectionné)."""
        while len(self.combos) > level + 1:
            combo = self.combos.pop()
            self._row_layout.removeWidget(combo)
            combo.deleteLater()

    def _on_combo_changed(self, _index: int) -> None:
        sender = self.sender()
        level = self.combos.index(sender)
        self._truncate_after(level)
        code = sender.currentData() or ""
        if code and thema_children(code):
            self._add_level(code)

    def to_code(self) -> str:
        for combo in reversed(self.combos):
            if combo.currentData():
                return combo.currentData()
        return ""

    def set_code(self, code: str) -> None:
        """Reconstruit la bonne profondeur de menus et pré-sélectionne chaque niveau pour un
        code déjà connu (utilisé par apply_metadata)."""
        self._truncate_after(0)
        self.combos[0].blockSignals(True)
        self.combos[0].setCurrentIndex(0)
        self.combos[0].blockSignals(False)
        chain = thema_parent_chain(code)
        for level, ancestor in enumerate(chain):
            if level >= len(self.combos):
                parent_code = chain[level - 1] if level > 0 else ""
                self._add_level(parent_code)
            idx = self.combos[level].findData(ancestor)
            if idx != -1:
                self.combos[level].blockSignals(True)
                self.combos[level].setCurrentIndex(idx)
                self.combos[level].blockSignals(False)


class GeneratePanel(QWidget):
    """Formulaire des métadonnées du livre (titre, auteur, ISBN, description…) — la génération de
    l'EPUB (bouton "Générer l'EPUB...") vit uniquement dans l'onglet Aperçu EPUB (GenerateControls),
    pas ici : ce panneau ne fait que collecter/pré-remplir les métadonnées."""

    def __init__(self, controller: ProjectController, parent=None):
        super().__init__(parent)
        self.controller = controller

        outer_layout = QVBoxLayout(self)
        outer_layout.setContentsMargins(0, 0, 0, 0)

        # Le formulaire (Titre... Résumé d'accessibilité) est long — il défile dans un ascenseur
        # plutôt que d'agrandir la fenêtre indéfiniment à chaque nouveau champ de métadonnées.
        scroll_content = QWidget()
        layout = QVBoxLayout(scroll_content)

        form = QFormLayout()
        self.title_edit = QLineEdit()
        form.addRow("Titre :", self.title_edit)
        self.author_edit = QLineEdit()
        self.author_edit.setPlaceholderText("ex : Jean-Paul Sartre (prénom puis nom, pas de virgule)")
        form.addRow("Auteur :", self.author_edit)
        self.author_file_as_edit = QLineEdit()
        self.author_file_as_edit.setPlaceholderText(
            "ex : Sartre, Jean-Paul (nom puis prénom avec une virgule : ce champ est utilisé pour le tri alphabétique)")
        self._author_file_as_manually_set = False
        self.author_edit.textEdited.connect(self._on_author_edited)
        self.author_file_as_edit.textEdited.connect(self._mark_author_file_as_manually_set)
        form.addRow("Nom de tri de l'auteur :", self.author_file_as_edit)
        self._form = form
        # Index d'insertion FIXE des lignes de contributeurs (juste après le nom de tri de
        # l'auteur) — chaque _ContributorRow ajoute/retire 2 lignes ici via insertRow/removeRow ;
        # tous les champs ajoutés APRÈS ce point (langue, ISBN...) restent donc toujours en
        # dessous du bloc contributeurs, quel que soit son nombre de lignes courant.
        self._contributors_row_index = form.rowCount()
        self._contributor_rows: list[_ContributorRow] = []
        self.language_combo = NoScrollComboBox()
        for code, name in sorted(LANGUAGE_NAMES_FR.items(), key=lambda item: item[1]):
            self.language_combo.addItem(name, code)
        self._language_manually_set = False
        self._preselect_default_language()
        self.language_combo.currentIndexChanged.connect(self._mark_language_manually_set)
        form.addRow("Langue :", self.language_combo)
        self.reading_direction_combo = NoScrollComboBox()
        self.reading_direction_combo.addItem("Gauche à droite (standard)", "ltr")
        self.reading_direction_combo.addItem("Droite à gauche (manga, arabe, hébreu…)", "rtl")
        form.addRow("Sens de lecture :", self.reading_direction_combo)
        self.isbn_edit = QLineEdit()
        self.isbn_edit.setPlaceholderText("ISBN-10 ou ISBN-13, facultatif")
        form.addRow("ISBN :", self.isbn_edit)
        self.publisher_edit = QLineEdit()
        form.addRow("Éditeur :", self.publisher_edit)
        self.date_edit = QLineEdit()
        self.date_edit.setPlaceholderText("ex: 2026-08-25 ou 2026")
        form.addRow("Date de publication :", self.date_edit)
        self.subjects_edit = QLineEdit()
        self.subjects_edit.setPlaceholderText("mots-clés séparés par des virgules")
        form.addRow("Genre / mots-clés :", self.subjects_edit)
        bisac_row = QHBoxLayout()
        self.bisac_edit = QLineEdit()
        self.bisac_edit.setPlaceholderText("ex : FIC009000 — cherchez le code sur le site officiel BISG")
        bisac_row.addWidget(self.bisac_edit, 1)
        bisac_link = QLabel('<a href="https://www.bisg.org/complete-bisac-subject-headings-list">Trouver un code BISAC</a>')
        bisac_link.setOpenExternalLinks(True)
        bisac_row.addWidget(bisac_link)
        form.addRow("Code BISAC :", bisac_row)
        self.thema_row = _ThemaRow()
        form.addRow("Classification Thema :", self.thema_row)
        self.rights_edit = QLineEdit()
        self.rights_edit.setPlaceholderText("ex: © 2026 Auteur, tous droits réservés")
        form.addRow("Droits :", self.rights_edit)
        self.source_edit = QLineEdit()
        self.source_edit.setPlaceholderText("ex : Volo's Guide to Waterdeep, par Volothamp Geddarm")
        form.addRow("Source :", self.source_edit)
        self.relation_edit = QLineEdit()
        self.relation_edit.setPlaceholderText("ex : La Trilogie Complète (titre, ISBN ou lien vers l'ouvrage associé)")
        form.addRow("Ouvrage associé :", self.relation_edit)
        self.coverage_edit = QLineEdit()
        self.coverage_edit.setPlaceholderText("ex : Paris, 1920-1940 (portée géographique/temporelle de l'œuvre)")
        form.addRow("Portée géo./temporelle :", self.coverage_edit)
        self.collection_title_edit = QLineEdit()
        self.collection_title_edit.setPlaceholderText("nom de la série/collection")
        form.addRow("Série / collection :", self.collection_title_edit)
        self.collection_position_edit = QLineEdit()
        self.collection_position_edit.setPlaceholderText("ex: 2")
        form.addRow("Numéro dans la série :", self.collection_position_edit)
        self.description_edit = QTextEdit()
        self.description_edit.setFixedHeight(80)
        form.addRow("Description / résumé :", self.description_edit)
        self.accessibility_summary_edit = _WrappingPlaceholderTextEdit(
            "Par exemple : \"Ce livre contient uniquement du texte structuré, compatible avec "
            "les lecteurs d'écran. Les quelques images sont accompagnées de descriptions.\"")
        self.accessibility_summary_edit.setFixedHeight(80)
        form.addRow("Résumé d'accessibilité :", self.accessibility_summary_edit)
        layout.addLayout(form)

        self.add_contributor_btn = QPushButton("+")
        self.add_contributor_btn.setFixedWidth(28)
        self.add_contributor_btn.clicked.connect(lambda: self._add_contributor_row())
        _set_immediate_yellow_tooltip(self.add_contributor_btn, "Ajouter un contributeur")
        self._add_contributor_row()  # au moins une paire de lignes visible dès l'ouverture

        layout.addStretch()

        scroll_area = QScrollArea()
        scroll_area.setWidget(scroll_content)
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShape(QScrollArea.Shape.NoFrame)
        outer_layout.addWidget(scroll_area)

        controller.metadata_imported.connect(self.apply_metadata)
        controller.odt_metadata_found.connect(self.apply_metadata_if_empty)
        controller.project_loaded.connect(self._on_project_loaded)

    def _preselect_default_language(self) -> None:
        """Présélectionne la langue système (l'utilisateur écrit très probablement dans sa propre
        langue) — repli sur le français si la langue système n'est pas dans la table ISO 639-1
        (ex. code régional sans correspondance directe). Ne compte jamais comme une saisie
        manuelle (cf. _language_manually_set) : un import ODT ultérieur peut la remplacer sans
        déclencher de conflit."""
        system_code = QLocale.system().bcp47Name().split("-")[0].lower()
        target_code = system_code if system_code in LANGUAGE_NAMES_FR else "fr"
        self._set_language_code(target_code)

    def _set_language_code(self, code: str) -> None:
        """Changement PROGRAMMATIQUE de la langue (présélection initiale, ou résolution d'un
        import/conflit) — ne doit jamais faire passer _language_manually_set à True, contrairement
        à une sélection faite par l'utilisateur dans la liste déroulante."""
        index = self.language_combo.findData((code or "").split("-")[0].lower())
        if index == -1:
            return
        was_manually_set = self._language_manually_set
        self.language_combo.setCurrentIndex(index)
        self._language_manually_set = was_manually_set

    def _mark_language_manually_set(self) -> None:
        self._language_manually_set = True

    def _on_author_edited(self, text: str) -> None:
        """Re-dérive le nom de tri à chaque frappe dans le champ Auteur, TANT QUE l'utilisateur
        n'a jamais modifié le champ de tri lui-même à la main — sinon une correction manuelle
        (nom composé mal détecté par _derive_file_as) serait écrasée à la prochaine frappe."""
        if not self._author_file_as_manually_set:
            self.author_file_as_edit.setText(_derive_file_as(text))

    def _mark_author_file_as_manually_set(self) -> None:
        self._author_file_as_manually_set = True

    def _language_code(self) -> str:
        return self.language_combo.currentData() or "fr"

    def _add_contributor_row(self) -> None:
        row = _ContributorRow(self)
        row.removed.connect(self._remove_contributor_row)
        insert_at = self._contributors_row_index + 2 * len(self._contributor_rows)
        self._form.insertRow(insert_at, "Contributeur :", row.name_row_widget)
        self._form.insertRow(insert_at + 1, "Nom de tri du contributeur :", row.file_as_edit)
        self._contributor_rows.append(row)
        self._renumber_contributor_labels()
        self._update_remove_buttons_enabled()
        self._reposition_add_contributor_button()

    def _remove_contributor_row(self, row: _ContributorRow) -> None:
        # Si le bouton "+" vit sur CETTE ligne (c'est la dernière), le détacher AVANT
        # deleteLater() : sinon Qt le détruit en cascade avec la ligne (il est enfant du
        # trailing_slot de la ligne), et le prochain _add_contributor_row()/
        # _reposition_add_contributor_button() plante sur un objet C++ déjà supprimé.
        self.add_contributor_btn.setParent(None)

        index = self._contributor_rows.index(row)
        row_start = self._contributors_row_index + 2 * index
        # removeRow(row_start) deux fois : après la première suppression, la ligne "nom de tri"
        # de cette paire est redescendue à row_start.
        self._form.removeRow(row_start)
        self._form.removeRow(row_start)
        self._contributor_rows.pop(index)
        row.deleteLater()
        if not self._contributor_rows:
            self._add_contributor_row()  # toujours au moins une paire de lignes visible
        else:
            self._renumber_contributor_labels()
            self._update_remove_buttons_enabled()
            self._reposition_add_contributor_button()

    def _update_remove_buttons_enabled(self) -> None:
        """Le bouton "Retirer" n'a de sens que s'il reste plus d'une paire de lignes — avec une
        seule ligne, il resterait toujours au moins celle-ci (cf. _remove_contributor_row), donc
        cliquer ne ferait rien d'utile : mieux vaut le désactiver plutôt que de laisser un clic
        sans effet visible."""
        enabled = len(self._contributor_rows) > 1
        for row in self._contributor_rows:
            row.remove_btn.setEnabled(enabled)

    def _renumber_contributor_labels(self) -> None:
        """Les labels "Contributeur N :"/"Nom de tri du contributeur N :" sont renumérotés à
        chaque ajout/retrait plutôt que fixés une fois pour toutes, puisqu'un retrait au milieu
        de la liste doit décaler la numérotation des lignes suivantes."""
        for i, row in enumerate(self._contributor_rows, start=1):
            suffix = "" if len(self._contributor_rows) == 1 else f" {i}"
            name_label_item = self._form.labelForField(row.name_row_widget)
            file_as_label_item = self._form.labelForField(row.file_as_edit)
            if name_label_item is not None:
                name_label_item.setText(f"Contributeur{suffix} :")
            if file_as_label_item is not None:
                file_as_label_item.setText(f"Nom de tri du contributeur{suffix} :")

    def _reposition_add_contributor_button(self) -> None:
        """Le bouton "+" (ajout d'un nouveau contributeur) vit sur la ligne "nom" de la DERNIÈRE
        _ContributorRow — le déplacer là à chaque ajout/retrait plutôt que d'avoir une instance
        par ligne."""
        if not self._contributor_rows:
            return
        self.add_contributor_btn.setParent(None)
        last_row = self._contributor_rows[-1]
        last_row.trailing_slot.addWidget(self.add_contributor_btn)

    def apply_metadata(self, metadata: BookMetadata) -> None:
        """Pré-remplit le formulaire avec les métadonnées lues dans un EPUB importé (symétrique
        de collect_metadata) — écrase les champs existants plutôt que de les fusionner, pour
        refléter fidèlement le fichier importé."""
        self.title_edit.setText(metadata.title if metadata.title != "Sans titre" else "")
        self.author_edit.setText(metadata.author)
        self.author_file_as_edit.setText(metadata.author_file_as or _derive_file_as(metadata.author))
        self._author_file_as_manually_set = bool(metadata.author_file_as)
        self._set_language_code(metadata.language)
        direction_index = self.reading_direction_combo.findData(metadata.reading_direction)
        if direction_index != -1:
            self.reading_direction_combo.setCurrentIndex(direction_index)
        self.isbn_edit.setText(metadata.isbn)
        self.publisher_edit.setText(metadata.publisher)
        self.date_edit.setText(metadata.publication_date)
        self.subjects_edit.setText(", ".join(metadata.subjects))
        self.bisac_edit.setText(metadata.bisac_code)
        self.rights_edit.setText(metadata.rights)
        self.source_edit.setText(metadata.source)
        self.relation_edit.setText(metadata.relation)
        self.coverage_edit.setText(metadata.coverage)
        self.collection_title_edit.setText(metadata.collection_title)
        self.collection_position_edit.setText(metadata.collection_position)
        self.description_edit.setPlainText(metadata.description)
        self.accessibility_summary_edit.setPlainText(metadata.accessibility_summary)

        self.add_contributor_btn.setParent(None)
        while self._contributor_rows:
            row = self._contributor_rows[-1]
            row_start = self._contributors_row_index + 2 * (len(self._contributor_rows) - 1)
            self._form.removeRow(row_start)
            self._form.removeRow(row_start)
            self._contributor_rows.pop()
            row.deleteLater()
        for contributor in metadata.contributors:
            self._add_contributor_row()
            row = self._contributor_rows[-1]
            row.name_edit.setText(contributor.name)
            row.set_file_as(contributor.file_as)
            row.set_role_code(contributor.role_code)
        if not metadata.contributors:
            self._add_contributor_row()  # toujours au moins une paire de lignes visible

        self.thema_row.set_code(metadata.thema_codes[0] if metadata.thema_codes else "")

    def _on_project_loaded(self) -> None:
        """Repeuple le formulaire depuis les métadonnées du projet fraîchement chargé
        (controller.project_loaded, émis par ProjectController.load_project_from) — réutilise
        apply_metadata (mêmes sémantiques d'écrasement complet que pour un import EPUB, correctes
        ici puisqu'un chargement de projet remplace tout l'état affiché)."""
        self.apply_metadata(self.controller.project.book_metadata)

    def apply_metadata_if_empty(self, metadata: BookMetadata, source_file_name: str = "") -> None:
        """Complète le formulaire avec les propriétés de document lues dans un .odt importé —
        contrairement à apply_metadata (import EPUB), ne remplit que les champs encore VIDES,
        pour ne jamais écraser silencieusement une valeur déjà saisie ou déjà déduite d'un fichier
        ODT précédent (un projet agrège souvent plusieurs .odt). Seuls titre/auteur/langue/
        description/date/sujets peuvent venir d'un .odt (office:meta n'a pas d'équivalent ISBN/
        éditeur/droits/série — ces champs restent donc toujours à la seule main de l'utilisateur).

        Si un champ est DÉJÀ rempli avec une valeur DIFFÉRENTE de celle du nouveau fichier, ce
        n'est ni ignoré ni écrasé automatiquement : MetadataConflictDialog demande à l'utilisateur
        de choisir, champ par champ. Exception : les mots-clés/sujets sont une liste, fusionnée
        automatiquement sans conflit (un livre agrégeant plusieurs fichiers peut légitimement
        accumuler des mots-clés complémentaires, contrairement à un titre ou un auteur)."""
        simple_fields = {
            "title": (self.title_edit, metadata.title if metadata.title != "Sans titre" else ""),
            "author": (self.author_edit, metadata.author),
            "description": (self.description_edit, metadata.description),
            "publication_date": (self.date_edit, metadata.publication_date),
        }

        conflicts: dict[str, tuple[str, str]] = {}
        for field_name, (widget, new_value) in simple_fields.items():
            if not new_value:
                continue
            current_value = (widget.toPlainText() if isinstance(widget, QTextEdit) else widget.text()).strip()
            if not current_value:
                self._set_field_text(widget, new_value)
                # setText() n'émet pas textEdited : _on_author_edited ne se déclenche pas tout
                # seul ici — dériver explicitement le nom de tri quand l'auteur vient d'être
                # complété par cet import (office:meta ODT n'a pas d'équivalent file-as).
                if field_name == "author" and not self._author_file_as_manually_set:
                    self.author_file_as_edit.setText(_derive_file_as(new_value))
            elif current_value != new_value.strip():
                conflicts[field_name] = (current_value, new_value)

        # La langue est présélectionnée automatiquement à la création du formulaire (langue
        # système, cf. _preselect_default_language) : cette présélection n'est jamais une vraie
        # saisie utilisateur ni une valeur déduite d'un import précédent, donc jamais un conflit —
        # seule une langue déjà changée MANUELLEMENT ou déjà remplie par un import ODT précédent
        # peut entrer en conflit avec un nouveau fichier.
        new_language_code = metadata.language.strip().lower()
        language_conflict_code: str | None = None
        if new_language_code and new_language_code in LANGUAGE_NAMES_FR:
            if self._language_manually_set:
                current_code = self._language_code()
                if current_code != new_language_code:
                    conflicts["language"] = (LANGUAGE_NAMES_FR[current_code], LANGUAGE_NAMES_FR[new_language_code])
                    language_conflict_code = new_language_code
            else:
                self._set_language_code(new_language_code)

        if conflicts:
            dialog = MetadataConflictDialog(conflicts, source_file_name or "fichier importé", self)
            dialog.exec()
            resolved = dialog.resolved_choices()
            for field_name, take_new in resolved.items():
                if not take_new:
                    continue
                if field_name == "language" and language_conflict_code is not None:
                    self._set_language_code(language_conflict_code)
                elif field_name in simple_fields:
                    self._set_field_text(simple_fields[field_name][0], simple_fields[field_name][1])
                    if field_name == "author" and not self._author_file_as_manually_set:
                        self.author_file_as_edit.setText(_derive_file_as(simple_fields[field_name][1]))

        if metadata.subjects:
            existing = [s.strip() for s in self.subjects_edit.text().split(",") if s.strip()]
            for subject in metadata.subjects:
                if subject not in existing:
                    existing.append(subject)
            self.subjects_edit.setText(", ".join(existing))

        # Une seule classification Thema (self.thema_row, ligne fixe) : complétée seulement si
        # vide, comme les champs texte simples — plus de sémantique "fusion de liste" possible
        # depuis qu'il n'y a plus qu'une seule ligne. bisac_code n'est volontairement pas
        # concerné : office:meta ODT n'a pas d'équivalent, comme isbn/publisher/rights déjà
        # exclus de simple_fields.
        if metadata.thema_codes and not self.thema_row.to_code():
            self.thema_row.set_code(metadata.thema_codes[0])

    @staticmethod
    def _set_field_text(widget, value: str) -> None:
        if isinstance(widget, QTextEdit):
            widget.setPlainText(value)
        else:
            widget.setText(value)

    def collect_metadata(self) -> BookMetadata:
        subjects = [s.strip() for s in self.subjects_edit.text().split(",") if s.strip()]
        contributors = [row.to_contributor() for row in self._contributor_rows if row.name_edit.text().strip()]
        thema_codes = [self.thema_row.to_code()] if self.thema_row.to_code() else []
        return BookMetadata(
            title=self.title_edit.text() or "Sans titre",
            author=self.author_edit.text(),
            author_file_as=self.author_file_as_edit.text(),
            language=self._language_code(),
            reading_direction=self.reading_direction_combo.currentData(),
            isbn=self.isbn_edit.text(),
            description=self.description_edit.toPlainText(),
            publication_date=self.date_edit.text(),
            publisher=self.publisher_edit.text(),
            subjects=subjects,
            thema_codes=thema_codes,
            bisac_code=self.bisac_edit.text(),
            rights=self.rights_edit.text(),
            contributors=contributors,
            source=self.source_edit.text(),
            relation=self.relation_edit.text(),
            coverage=self.coverage_edit.text(),
            collection_title=self.collection_title_edit.text(),
            collection_position=self.collection_position_edit.text(),
            accessibility_summary=self.accessibility_summary_edit.toPlainText(),
        )
