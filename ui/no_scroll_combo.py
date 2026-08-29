from PySide6.QtCore import Qt
from PySide6.QtWidgets import QComboBox


class NoScrollComboBox(QComboBox):
    """QComboBox qui ignore la molette tant qu'il n'a pas le focus (clic préalable), pour éviter
    qu'un simple défilement de la fenêtre au-dessus d'un menu déroulant modifie sa valeur à
    l'insu de l'utilisateur — comportement par défaut de Qt, mais jamais voulu ici."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    def wheelEvent(self, event):
        if self.hasFocus():
            super().wheelEvent(event)
        else:
            event.ignore()
