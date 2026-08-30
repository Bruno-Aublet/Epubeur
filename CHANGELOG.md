# Changelog

## v1.0.3 - 2026-08-30 - Cadre de sélection, badge police figée, onglet aperçu EPUB, nom de police figée, fermeture de projet et confirmation de sortie

- Ajout d'un cadre pointillé autour du saut de page manuel ou de l'image visés par un clic gauche ou droit, pour voir clairement sur quoi on agit avant de le supprimer.
- Le badge "[figée]" de l'onglet Police de caractères s'affiche désormais en vert pour mieux le repérer.
- Agrandissement du texte d'invitation et du bouton "Générer l'EPUB" dans l'onglet Aperçu EPUB, trop petits jusqu'ici.
- Le bouton "Générer l'EPUB" est désormais désactivé tant qu'aucun chapitre n'a été importé.
- Correction : les fichiers de police figée étaient enregistrés dans le projet .epbz sous un nom technique illisible (leur empreinte de contenu) au lieu de leur vrai nom de fichier.
- Correction : fermer un projet laissait des résidus de l'ancien projet (formulaire Métadonnées, langue verrouillée, liste d'import EPUB, statut de génération, aperçu de police), ce qui pouvait notamment faire apparaître un faux conflit de métadonnées lors d'un import ODT dans le projet suivant.
- Correction : un avertissement "modifications non enregistrées" s'affichait à tort en fermant un projet tout juste ouvert et jamais modifié.
- Ajout : quitter l'application (croix de la fenêtre, Alt+F4, menu) demande désormais confirmation en présence de modifications non enregistrées, comme "Ouvrir un projet".

## v1.0.2 - 2026-08-29 - Vérification des mises à jour et corrections diverses

- Correction : renommer une image dans l'onglet Images ne renommait que son libellé affiché, jamais le fichier physique correspondant dans le projet .epbz (les projets déjà concernés sont corrigés automatiquement à la prochaine ouverture).
- Ajout d'une vérification automatique des mises à jour au démarrage (et manuelle depuis le menu Aide), avec un lien direct vers la dernière version sur GitHub.
- Ajout d'une entrée "Historique des versions" dans le menu Aide, affichant le contenu de ce changelog.
- Ajout d'un avertissement si des chapitres semblent avoir changé d'ordre lors du remplacement d'un fichier Writer déjà importé (les titres pouvaient auparavant être réattribués au mauvais chapitre sans prévenir).
- Correction : l'icône Epubeur des fichiers .epbz ne s'affichait toujours pas dans l'explorateur Windows après compilation (le chemin enregistré dans le registre pointait à côté de l'exécutable au lieu du dossier interne où PyInstaller place réellement l'icône).
- Correction : les polices figées disparaissaient toujours après réimport d'un EPUB dès qu'un ISBN était renseigné dans les métadonnées.
- Correction : les dossiers temporaires créés à l'ouverture d'un projet ou à la génération d'un aperçu EPUB n'étaient jamais nettoyés, accumulant des fichiers orphelins au fil d'une session.
- Correction : scinder un chapitre à partir de son tout premier paragraphe créait un chapitre vide sans avertissement (le paragraphe 0 n'est plus proposé comme point de scission).
- Correction : un cas limite imprévu dans l'analyse d'un fichier Writer pouvait faire planter l'application au lieu d'afficher un message d'erreur, même quand l'ouverture initiale du fichier avait réussi.
- Correction : un ISBN copié depuis un site utilisant un tiret typographique (au lieu du tiret standard) était rejeté à tort comme invalide, bloquant la génération de l'EPUB.
- Correction : une police dont le nom de fichier contient "ExtraBold" ou "UltraBold" pouvait être détectée avec un poids trop faible (Bold au lieu d'ExtraBold) quand ses métadonnées internes n'étaient pas lisibles.
- Correction : un paragraphe contenant deux images côte à côte (ancrées au caractère) ne conservait que la première ; la seconde disparaissait silencieusement à l'import.
- Correction : une sous-liste imbriquée dans une note de bas de page pouvait afficher le mauvais style (puces au lieu de numéros, ou l'inverse).
- Correction : une liste placée directement dans une cellule de tableau (sans texte avant) perdait tout son contenu à l'import.
- Correction : un flash furtif de fenêtre Windows pouvait apparaître en actualisant l'onglet Images en présence d'images orphelines.
- Correction : deux polices figées au contenu identique produisaient un doublon inutile dans le fichier de projet .epbz.
- Correction : rouvrir un même fichier via un chemin de casse différente créait une entrée en double dans les listes "Projets récents"/"Fichiers récents".
- Correction : le rôle d'un contributeur venant d'un EPUB externe ou d'une édition manuelle du projet pouvait être silencieusement réinitialisé à "non précisé" en rouvrant le formulaire Métadonnées.
- Correction : l'import d'un EPUB externe (non généré par Epubeur) pouvait fusionner à tort deux chapitres distincts si leur texte contenait un exemple technique ressemblant à un marqueur interne de l'application.
- Correction : coller une image dont le fichier a été déplacé ou supprimé entre le copier et le coller pouvait planter l'application au lieu d'afficher un message d'erreur.
- Correction : cliquer plusieurs fois rapidement sur "Vérifier les mises à jour" avant la fin de la première vérification pouvait produire un avertissement "QSslSocket: device not open" dans la console (le menu est désormais désactivé pendant la vérification).
- Renforcement : la fusion d'un chapitre avec lui-même est désormais explicitement rejetée plutôt que de risquer une perte de contenu.
- Nettoyage : suppression d'une fonction interne jamais utilisée (détection de numéro de chapitre dans le titre), sans effet sur le comportement de l'application.

## v1.0.1 - 2026-08-29 - Améliorations et corrections

- Ajout d'un lien vers le dépôt GitHub dans le menu Aide.
- Suppression des points de suspension dans les libellés de boutons, menus et messages de statut.
- Ajout d'une icône pour l'application (fenêtres et exécutable compilé).
- Ajout d'un écran de démarrage (splash screen).
- Correction : la molette de la souris ne modifie plus un menu déroulant sur lequel elle passe pendant un défilement, sans clic préalable dessus.
- Correction : les polices non figées détectées à l'import restent désormais visibles et figeables après un rechargement de projet (elles disparaissaient de l'onglet Polices).
- Ajout de l'illustration Epubeur dans la fenêtre "À propos d'Epubeur".
- Les fichiers .epbz affichent désormais l'icône Epubeur dans l'explorateur Windows.
- Les boîtes de dialogue Enregistrer/Ouvrir un projet se souviennent désormais du dernier dossier utilisé.

## v1.0.0 - 2026-08-26

- Version initiale.
