---
id: languages
title: .NET, Java, Python et shaders
description: Comprendre les parcours .NET, Java, Android, Python et shaders pris en charge.
section: Analyser le code
parent: workspace
order: 5
sourceRevision: 2
---

## Assemblies .NET {#managed-net}

Utilisez ILSpy pour examiner le C# et récupérer un projet avec ses références et ressources disponibles. Un SDK .NET est nécessaire pour compiler ; les packs de ciblage et dépendances originales peuvent aussi être requis. Les noms et structures retrouvés peuvent différer des sources, particulièrement après obfuscation. Un hôte .NET single-file peut nécessiter une extraction avant de choisir l’assembly managée.

Pour éditer les sources et utiliser diagnostics, complétion et formatage, rattachez le projet récupéré à l’[IDE de projet](doc:projects). Le remplacement de méthode et le débogage ont leurs prérequis ; consultez le [remplacement](doc:patching) et le [débogage](doc:debugging). Les méthodes auxiliaires et machines à états générées doivent être modifiées via leur méthode source propriétaire, plutôt que sélectionnées comme cibles indépendantes.

## Java et Android {#java-and-android}

Vineflower traite les classes/JAR Java ; JADX traite DEX/APK Android et les entrées Java compatibles. Installez leur Java requis dans [Moteurs](doc:engines). Vérifiez avertissements et ressources récupérées. Le Java produit aide à comprendre, mais reconstruire Android peut toujours nécessiter le projet Gradle, SDK, signature, ressources et dépendances d’origine. La reconstruction Android complète en un clic n’est pas garantie.

## Bytecode Python {#python-bytecode}

Le moteur Python utilise des outils adaptés au format du bytecode. La récupération de sources couvre les versions compatibles jusqu’à Python 3.8 ; des versions plus récentes peuvent disposer d’une vue bytecode sans reconstruction des sources originales. La version Python du logiciel ne change pas celle du bytecode d’entrée. L’extraction PyInstaller peut exposer des fichiers embarqués à ouvrir individuellement. Modules absents, extensions natives et ressources d’exécution restent à reconstruire séparément.

## Shaders GPU {#gpu-shaders}

Le moteur intégré traite les entrées DXBC SM4/5, DXIL SM6 et SPIR-V prises en charge. Il produit du HLSL/GLSL ou une vue des instructions selon le format et les informations disponibles. Comparez liaisons registres/ressources, points d’entrée et contrôle avec les preuves du shader original.

```image
{"id": "workspace-screenshot", "src": "assets/workspace.png", "alt": "Exemple DXBC fourni, reconstruit en HLSL dans l’espace de travail.", "title": "Exemple DXBC fourni, reconstruit en HLSL dans l’espace de travail.", "controls": "minimal", "annotations": [{"id": "function-list", "type": "rect", "x": 0.12, "y": 0.1, "toX": 0.33, "toY": 0.97, "label": "Fonctions et recherche"}]}
```


Les contrôles de compilation nécessitent le vérificateur approprié et sont rapportés séparément de la décompilation. Un shader qui compile ne prouve ni images identiques, ni états de pipeline, ressources ou performances équivalents. Utilisez les [comportements observés](doc:observations) et le scénario de rendu réel pour valider une modification graphique. Un décompilateur de shaders n’est pas un convertisseur complet du moteur graphique en sources.
