---
id: storage
title: Stockage, sauvegardes et originaux
description: Distinguer originaux, projets générés, caches et sauvegardes récupérables.
section: Réglages et repères
parent: settings
order: 19
sourceRevision: 2
---

Applications volumineuses et entrées console peuvent occuper beaucoup plus que le code de CyDecompilator. Vérifiez l’espace disponible avant extraction, conversion ou copies répétées de test. Annuler une tâche ne signifie pas que toutes les sorties persistantes ou tous les téléchargements partiels ont été supprimés.

## Comprendre les dossiers {#understand-directory-ownership}

| Emplacement | Contenu | Conservation |
|---|---|---|
| Emplacement de l’entrée originale | Application, ressources ou archive | Garder comme original indépendant |
| data/projects/ | Instantanés importés, analyses, sources, historique et reçus | Données persistantes à sauvegarder volontairement |
| data/settings/ | Réglages de l’interface et du logiciel | Préserver pendant les mises à jour |
| data/jobs/ et rapports | État des tâches, sorties et preuves | Vérifier les références avant suppression |
| runtime/python/ | Interpréteur privé et dépendances | Nécessaire au lancement, pas un cache jetable |
| runtime/engines/ | Outils optionnels installés | Distincts de la compilation d’un projet |
| runtime/build/, téléchargements, préparation/sauvegardes | Travaux générés et mises à jour | Examiner le sous-dossier exact et son utilisation |
| dist/ | Archives de distribution préparées | Distinctes des projets actifs |

```diagram
{"type": "flow", "title": "Préserver chaque étape utile", "nodes": [{"id": "step-0", "label": "1. Entrée originale", "x": 20, "y": 20, "width": 320}, {"id": "step-1", "label": "2. Projet d’analyse", "x": 370, "y": 20, "width": 320}, {"id": "step-2", "label": "3. Sources modifiables", "x": 720, "y": 20, "width": 320}, {"id": "step-3", "label": "4. Instantané Git", "x": 720, "y": 135, "width": 320}, {"id": "step-4", "label": "5. Sortie testée", "x": 370, "y": 135, "width": 320}, {"id": "step-5", "label": "6. Examiner le nettoyage", "x": 20, "y": 135, "width": 320}], "edges": [{"from": "step-0", "to": "step-1"}, {"from": "step-1", "to": "step-2"}, {"from": "step-2", "to": "step-3"}, {"from": "step-3", "to": "step-4"}, {"from": "step-4", "to": "step-5"}]}
```

1. **Entrée originale** — Conserver l’original indépendant.
2. **Projet d’analyse** — Garder identité et preuves récupérées.
3. **Sources modifiables** — Identifier le dossier propriétaire.
4. **Instantané Git** — Sauvegarder les changements utiles.
5. **Sortie testée** — Garder artefact utile et reçu.
6. **Examiner le nettoyage** — Retirer seulement le travail inutilisé.


## Éviter les duplications inutiles {#avoid-unnecessary-duplication}

Réutilisez les moteurs compatibles plutôt que de copier une chaîne complète à chaque test. Un projet natif enregistré peut dépendre de son dossier actuel ; identifiez le propriétaire des ressources. Dossier d’application, extraction, conversion et copie neuve de test peuvent chacun prendre beaucoup de place. Les limites de l’historique source ne bornent pas toutes ces copies.

## Nettoyer volontairement {#clean-deliberately}

Arrêtez les tâches concernées et examinez le dossier exact avant de retirer compilations générées, captures obsolètes ou anciens téléchargements. Préservez dernière sortie utile, rapports nécessaires, dépôts d’historique, originaux et composants actifs. Supprimer les données d’un projet peut aussi effacer sources et historique ; ce n’est pas nettoyer des fichiers objets.

Sauvegardez ensemble sources, données persistantes et dépendances externes nécessaires. Un instantané Git est utile mais ne contient pas tous les fichiers de jeu, runtimes ou réglages des fournisseurs. Aucun bouton de documentation ne supprime automatiquement des fichiers ni ne lance un nettoyage.
