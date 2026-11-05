---
id: reconstruction
title: Reconstruire, compiler et valider
description: Reconstruire et valider
section: Modifier et reconstruire
order: 7
sourceRevision: 1
---

Dans **IDE de projet → Reconstruction**, **Reconstruire et valider** enchaîne création des sources, compilations, corrections optionnelles et comparaisons enregistrées. Définissez le comportement attendu avant d’autoriser des tentatives automatiques. Un point d’entrée absent, une dépendance incompatible ou un original indisponible ne se résout pas uniquement en augmentant le nombre d’essais.

```diagram
{"type": "flow", "title": "Reconstruire avec des preuves", "nodes": [{"id": "step-0", "label": "1. Comportement original", "x": 20, "y": 20, "width": 320}, {"id": "step-1", "label": "2. Projet modifiable", "x": 370, "y": 20, "width": 320}, {"id": "step-2", "label": "3. Résoudre les blocages", "x": 720, "y": 20, "width": 320}, {"id": "step-3", "label": "4. Compiler et corriger", "x": 720, "y": 135, "width": 320}, {"id": "step-4", "label": "5. Rejouer les tests", "x": 370, "y": 135, "width": 320}, {"id": "step-5", "label": "6. Examiner le résultat", "x": 20, "y": 135, "width": 320}], "edges": [{"from": "step-0", "to": "step-1"}, {"from": "step-1", "to": "step-2"}, {"from": "step-2", "to": "step-3"}, {"from": "step-3", "to": "step-4"}, {"from": "step-4", "to": "step-5"}]}
```

1. **Comportement original** — Définir un scénario reproductible.
2. **Projet modifiable** — Récupérer sources et ressources.
3. **Résoudre les blocages** — Vérifier ABI, entrées et dépendances.
4. **Compiler et corriger** — Borner les essais ; sauvegarder.
5. **Rejouer les tests** — Exécuter les assertions prévues.
6. **Examiner le résultat** — Distinguer compilation et comportement.


## Préparer le parcours {#prepare-the-run}

1. Ouvrez/analysez l’entrée et vérifiez la [cible du projet](doc:projects).
2. Configurez compilateur/runtime, références et projet de démarrage. Enregistrez les fichiers ouverts.
3. Définissez des scénarios avec comportement attendu et commandes de lancement original/reconstruction. **Utiliser le scénario d’investigation** reprend la configuration d’observation courante.
4. Choisissez un nombre borné de compilations. Les corrections IA nécessitent un fournisseur configuré et Git ; la première compilation compte dans la limite.
5. Lancez la reconstruction. Les sources sont protégées contre l’édition concurrente pendant les modifications automatiques. Annulez via les commandes de tâche si nécessaire.

Les corrections sont des modifications de sources avec contrôle des révisions et sauvegardes Git. Une réponse périmée ou une modification externe interrompt l’application de la correction. Le texte de l’IA n’est pas exécuté comme commande de terminal arbitraire.

## Interpréter l’état final {#interpret-the-final-state}

| Résultat | Signification |
|---|---|
| Échec de compilation / reconstruction bloquée | Examiner diagnostics et prérequis non résolus |
| Compilé ; comportement non vérifié | Une sortie neuve existe ; les preuves d’exécution suffisantes manquent |
| Échec des tests du projet | Les tests demandés ont échoué |
| Le comportement diffère | Au moins un critère de comparaison activé diffère |
| Les scénarios enregistrés concordent | Les assertions activées concordent uniquement pour ces scénarios |

Utilisez **Examiner la comparaison enregistrée** pour consulter les preuves dans Investigation. Les rapports conservent tentatives, modifications, commits, diagnostics et identités des captures. Une bibliothèque nécessite un exécutable de test adapté. Un scénario graphique doit couvrir l’interaction pertinente ; le seul démarrage ne valide pas une fonctionnalité.

## Projets web et Electron {#web-and-electron-projects}

La configuration conserve type, entrée, script de compilation et dossier de sortie. Un script npm build/test configuré s’exécute lorsqu’il est demandé ; l’installation verrouillée des dépendances dispose d’une action explicite séparée. Les modules natifs nécessitent encore le runtime et l’ABI compatibles. Un ASAR produit n’est pas un installeur signé. Recompilez après changement de sources ou d’artefact. Serveurs, API distantes, identifiants et ressources absentes ne sont pas recréés automatiquement.

Consultez ensuite les [comportements observés](doc:observations), les [parcours IA](doc:ai) et le [dépannage](doc:troubleshooting).
