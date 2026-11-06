---
id: unreal
title: Connaissances de reconstruction Unreal
description: Consulter les règles et profils de campagne avant d’implémenter un sous-système.
section: Consoles et Unreal
parent: consoles
order: 17
sourceRevision: 2
---

Ouvrez [Reconstruction Unreal](doc:unreal) pour consulter méthodologie et catalogue de profils fournis. Cette page expose des connaissances et identités sources. Elle ne convertit pas automatiquement un jeu console en projet Unreal fonctionnel et n’intègre pas Unreal Editor dans CyDecompilator.

## Utiliser le catalogue {#use-the-catalogue}

1. Choisissez la méthodologie générale ou un profil spécifique disponible.
2. Filtrez les règles par catégorie et examinez prérequis, preuves et comportements inconnus.
3. Copiez le guide affiché si nécessaire ; il conserve les identités/empreintes pertinentes.
4. Utilisez les opérations Runtime/MCP de règles et de guide pour une investigation pilotée par agent.

Le catalogue traite notamment géométrie/UV, matériaux, animation, navigation, armes, IA, véhicules, effets et audio. Chaque profil spécifique conserve son identité d’exécutable et ses hypothèses de modèles. Le seul titre d’un jeu ne prouve pas qu’un profil correspond à vos fichiers.

## Passer à un sous-système validé {#from-knowledge-to-a-validated-subsystem}

Définissez une fonctionnalité observable, identifiez ressources et fonctions, enregistrez le comportement original pertinent, puis implémentez et testez le remplacement dans un projet adapté. Comparez rendu représentatif, commandes, temps et sorties. Conservez les comportements non pris en charge comme inconnus, plutôt que de considérer des règles comme preuve d’implémentation.

```diagram
{"type": "flow", "title": "Reconstruire avec des preuves", "nodes": [{"id": "step-0", "label": "1. Comportement original", "x": 20, "y": 20, "width": 320}, {"id": "step-1", "label": "2. Projet modifiable", "x": 370, "y": 20, "width": 320}, {"id": "step-2", "label": "3. Résoudre les blocages", "x": 720, "y": 20, "width": 320}, {"id": "step-3", "label": "4. Compiler et corriger", "x": 720, "y": 135, "width": 320}, {"id": "step-4", "label": "5. Rejouer les tests", "x": 370, "y": 135, "width": 320}, {"id": "step-5", "label": "6. Examiner le résultat", "x": 20, "y": 135, "width": 320}], "edges": [{"from": "step-0", "to": "step-1"}, {"from": "step-1", "to": "step-2"}, {"from": "step-2", "to": "step-3"}, {"from": "step-3", "to": "step-4"}, {"from": "step-4", "to": "step-5"}]}
```

1. **Comportement original** — Définir un scénario reproductible.
2. **Projet modifiable** — Récupérer sources et ressources.
3. **Résoudre les blocages** — Vérifier ABI, entrées et dépendances.
4. **Compiler et corriger** — Borner les essais ; sauvegarder.
5. **Rejouer les tests** — Exécuter les assertions prévues.
6. **Examiner le résultat** — Distinguer compilation et comportement.


## Ce qui reste séparé {#what-remains-separate}

Import des ressources, génération du projet, implémentation, installation Unreal et compilations/exécutions restent des travaux distincts. Le catalogue est consultable sans jeu ; une conversion réelle nécessite sources/ressources adaptées et environnement de développement. Consulter des règles ne garantit ni conversion générique PS3/PS4/PS5/Xbox vers Unreal, ni performances.

Utilisez l’[analyse native](doc:native) et l’[investigation](doc:investigation) pour les preuves, les [projets](doc:projects) pour les sources et les [observations](doc:observations) pour les comportements testables. Les instantanés de référence du catalogue sont distincts de l’historique propre à votre sortie reconstruite.
