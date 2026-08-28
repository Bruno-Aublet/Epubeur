# Epubeur

Epubeur est une application de bureau qui transforme des manuscrits écrits dans LibreOffice
Writer (fichiers `.odt`) en livres numériques au format EPUB, prêts à être lus sur une liseuse ou
une application de lecture.

## Pourquoi ce projet

J'écris mes romans dans LibreOffice Writer, chapitre par chapitre, et je voulais pouvoir les
transformer facilement en EPUB propres, sans passer par une conversion générique qui abîme la
mise en forme, les images ou la structure du texte. Je n'ai trouvé aucun outil qui faisait
exactement ce que je voulais, alors j'ai fait le mien.

## Ce que fait l'application

- Elle importe un ou plusieurs fichiers `.odt` et en reconstitue automatiquement les chapitres, en
  respectant la mise en forme (gras, italique, alignement, listes, tableaux, notes de bas de
  page...).
- Elle permet d'organiser le livre : regrouper les chapitres en parties, les réordonner, leur
  donner un titre.
- Elle gère les images : taille d'affichage, habillage du texte autour, description pour
  l'accessibilité, image de couverture et de 4e de couverture.
- Elle permet de figer une police d'écriture précise pour que le texte s'affiche exactement comme
  voulu, quelle que soit la liseuse utilisée.
- Elle renseigne les métadonnées du livre (titre, auteur, langue, résumé, série, etc.).
- Elle génère un fichier EPUB final, valide et prêt à être lu ou publié.
- Elle peut aussi réimporter un EPUB déjà existant (le sien ou celui d'un autre logiciel) pour
  continuer à le modifier.

Toute l'interface est en français.

## Le format de projet `.epbz`

Un projet Epubeur (le travail en cours sur un livre : chapitres, structure, réglages) se
sauvegarde dans un seul fichier, avec l'extension `.epbz`. C'est un fichier unique, facile à
déplacer, sauvegarder ou envoyer, qui contient tout ce dont l'application a besoin pour reprendre
le travail exactement là où il a été laissé.

## Statut

Ce projet est développé pour mon usage personnel, mais il est ouvert si son fonctionnement vous
intéresse. L'application fonctionne sous Windows.

## Licence

Ce projet est distribué sous licence [GNU GPL v3](LICENSE).
