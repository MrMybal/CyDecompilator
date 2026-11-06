---
id: history
title: Historique Git et comparaison des sources
description: Enregistrer des versions, comparer les changements et restaurer avec l’historique Git local privé.
section: Modifier et reconstruire
parent: projects
order: 8
sourceRevision: 2
---

**IDE de projet → Historique Git** conserve des versions locales privées des sources. Git doit être installé et accessible dans PATH. Cet historique est distinct du dépôt Git éventuel du dossier source, ainsi que du dépôt de développement de CyDecompilator.

## Enregistrer et comparer {#save-and-compare}

1. Enregistrez les fichiers ouverts pour que le disque corresponde à la version souhaitée.
2. Saisissez une description utile et choisissez **Enregistrer une version Git**.
3. Modifiez les sources ou ressources, puis sélectionnez une version sauvegardée.
4. Choisissez **Comparer avec les sources sauvegardées**, puis un fichier modifié. La vue partagée présente les différences côte à côte, le changement suivant et la recherche. Le texte brut reste disponible pour copier.

```image
{"id": "git-history-screenshot", "src": "assets/git-history.png", "alt": "Comparaison réelle entre un instantané Git privé et des sources C++ modifiées dans la vue intégrée.", "title": "Comparaison réelle entre un instantané Git privé et des sources C++ modifiées dans la vue intégrée.", "controls": "minimal"}
```


## Restaurer volontairement {#restore-deliberately}

Examinez la comparaison et enregistrez les buffers ouverts avant **Restaurer cette version**. La restauration sauvegarde d’abord l’état courant dans un commit récupérable, puis enregistre l’état restauré dans un autre commit. Les fichiers ouverts sont rechargés. Les contrôles de révision refusent une restauration dont l’aperçu ne correspond plus aux fichiers. Cette action ne réinitialise pas silencieusement le dépôt propre au dossier source.

## Contenu sauvegardé {#what-is-included}

Sources, ressources et dépendances locales sont versionnées selon les règles d’historique. Dossiers de compilation, caches et métadonnées Git sont exclus. Les fichiers binaires sont sauvegardables, mais leurs différences ne sont pas affichées comme texte. Les limites sont de 4 000 fichiers, 128 Mio au total et 32 Mio par fichier ; les dépasser impose de réduire le périmètre source, pas de copier automatiquement sans limite.

Les corrections de reconstruction enregistrent aussi des sauvegardes Git. Une copie managée modifiée peut afficher son commit source si un instantané correspondant existait avant sa création. Un instantané ne sauvegarde pas tous les moteurs, ressources originales de jeu ou runtimes externes.

## Sauvegarde et récupération {#backup-and-recovery}

Conservez ensemble données/historique du projet et sources lors d’un déplacement ou d’une sauvegarde. Ne supprimez pas un projet pour vider un cache de compilation : vous risquez de perdre historique privé et preuves. Consultez le [stockage](doc:storage) pour les rôles des dossiers et la [reconstruction](doc:reconstruction) pour les corrections de sources.
