---
id: projects
title: Projets sources modifiables
description: Créer ou rattacher un projet source, modifier les fichiers et compiler.
section: Modifier et reconstruire
order: 6
sourceRevision: 2
---

Ouvrez l’[IDE de projet](doc:projects) après avoir sélectionné un projet d’analyse. **Créer un projet source** génère un espace modifiable pris en charge ; ouvrir/rattacher un dossier source existant est une action distincte. Un dossier rattaché reste une source utilisateur persistante : ce n’est pas un répertoire temporaire de tâche.

## Cibles de reconstruction {#supported-reconstruction-targets}

| Famille | Projet produit | Prérequis restants |
|---|---|---|
| .NET | C# ILSpy, ressources, solution et projets | SDK, références, projet de démarrage et framework |
| PE natif Windows | C, CMake, solution VC++ ; cible EXE, DLL ou statique | Outils C++, entrée/imports/ressources récupérables |
| ELF natif | Sources C et cible CMake | Hôte/outils compatibles, ABI et initialisations manquantes |
| Node/TS/web | Sources/ressources récupérées et configuration | Node.js, dépendances et points d’entrée |
| Electron | Sources main/preload/renderer et sortie ASAR | Runtime Electron compatible et ABI des modules natifs |

Ce sont des parcours de reconstruction, pas la garantie de recréer toute application. Examinez les blocages avant de supposer que la sortie pourra fonctionner.

## Modifier et compiler {#edit-and-build}

1. Créez ou rattachez les sources et examinez l’arborescence de solution/fichiers.
2. Sélectionnez un fichier pour l’ouvrir. L’édition utilise l’éditeur natif conservé, Undo/Redo et les services disponibles pour le langage.
3. Enregistrez avant compilation. Dans une solution multiple, choisissez configuration et projet de démarrage.
4. Utilisez Compiler/Recompiler/Nettoyer selon disponibilité. Examinez **Sortie de compilation** et **Problèmes**. Un diagnostic navigable ouvre sa position source.
5. Exécutez ou déboguez une sortie nouvellement validée ; des artefacts périmés ou modifiés peuvent imposer une nouvelle compilation.

```image
{"id": "project-ide-screenshot", "src": "assets/project-ide.png", "alt": "IDE affichant un exemple CMake et des sources C++ modifiables. Cette illustration n’affirme pas qu’une compilation a réussi.", "title": "IDE affichant un exemple CMake et des sources C++ modifiables. Cette illustration n’affirme pas qu’une compilation a réussi.", "controls": "minimal"}
```


## Services et limites de l’éditeur {#source-services-and-limits}

Le panneau d’assistance C# fournit diagnostics et opérations de symboles prises en charge via les outils SDK locaux. Complétion et aperçus de refactorisation dépendent des références et de l’état du projet. Examinez l’aperçu avant d’appliquer renommage ou formatage. Une modification externe ou une révision périmée peut entraîner un refus plutôt que l’écrasement d’un texte plus récent.

Utilisez l’[historique Git](doc:history) avant des modifications larges et la [reconstruction avec validation](doc:reconstruction) pour les tentatives bornées de compilation/correction. L’éditeur est un environnement intégré de reconstruction ; il ne fournit ni toutes les fonctions de Rider/Visual Studio, ni les SDK propriétaires absents.
