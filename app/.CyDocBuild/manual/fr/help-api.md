---
id: help-api
title: API des liens d’aide natifs
description: Ouvrir depuis Python un chapitre, une section ou une image annotée de l’aide locale.
section: Références / Intégration
order: 91
kind: api
sourceRevision: 2
---

L’application utilise le module Python `documentation` pour résoudre les liens d’aide
locaux. Il lit le catalogue de routes fourni, accepte les anciens noms de chapitres
reconnus et refuse les destinations inconnues. L’import exige que les modules de
l’application installée soient accessibles.

## Ouvrir un chapitre {#open-a-chapter}

```python
from documentation import Documentation

help = Documentation()
help.open('projects', 'fr', anchor='edit-and-build')
```

`Documentation(root=None, opener=None)` utilise par défaut le dossier `Documentation`
voisin de `documentation.py`. `root` permet de choisir un autre export installé complet.
La fonction `opener` facultative suit le contrat `webbrowser.open(url, new=0)` ; un
retour faux signale une erreur d’ouverture du navigateur.

## Méthodes publiques {#public-methods}

- [`Documentation.url`](doc:help-route-api) retourne une URL locale encodée sans l’ouvrir.
- [`Documentation.open`](doc:open-help-api) valide la même destination et l’ouvre.

Les deux méthodes acceptent les mêmes champs de page, langue, section et vue de média.
L’anglais est la langue par défaut. Une variante comme `fr-CA` sélectionne le français ;
les autres langues de l’interface utilisent l’anglais. Les identifiants de pages et
d’annotations sont communs aux deux éditions.

## Une image annotée {#an-annotated-image}

```python
url = help.url('start', 'en', media='workspace-screenshot',
               note='function-list', zoom=1.25)
```

L’image est déjà fournie avec le manuel. Le lien n’importe aucun nouveau média et
n’exécute pas le code d’une application analysée. Les règles du navigateur peuvent
limiter la persistance des préférences de lecture pour les fichiers locaux.
