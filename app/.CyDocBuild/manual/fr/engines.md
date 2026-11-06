---
id: engines
title: Moteurs et formats pris en charge
description: Choisir un moteur adapté au format et installer ses composants facultatifs.
section: Bien démarrer
parent: start
order: 2
sourceRevision: 2
---

Ouvrez [Moteurs](doc:engines) pour examiner les composants, installer un moteur optionnel ou configurer un exécutable compatible déjà présent. Les téléchargements utilisent les sources officielles et les métadonnées d’intégrité disponibles ; les moteurs restent séparés du Python privé de l’application. Leur installation peut nécessiter Internet, contrairement à ce manuel.

## Choisir un moteur {#pick-an-engine}

| Entrée | Moteur | Vue attendue |
|---|---|---|
| PE/ELF natif x86/x64/ARM64 | CyDecompilator C | C structuré pour les cas pris en charge |
| Binaires natifs et firmware | Ghidra, s’il est installé | Pseudo-code C et analyse native approfondie |
| Code machine natif | Désassembleur intégré | Instructions, appels, imports et chaînes |
| Assemblies .NET managées | ILSpy | C# et export de projet source |
| Classes Java/JAR | Vineflower | Sources Java |
| APK/DEX Android | JADX | Java, ressources et manifeste Android |
| Bytecode Python | Moteur Python | Sources récupérées compatibles ou bytecode |
| Shaders DXBC, DXIL, SPIR-V | Moteur de shaders intégré | HLSL/GLSL et instructions/bytecode |
| Application JS/TS/HTML/ASAR | Analyseur d’investigation | Modules, source maps et preuves fonctionnelles |

La détection examine le contenu, pas seulement l’extension. Renommer un exécutable ne change pas son format. Les moteurs disponibles apparaissent dans le sélecteur de l’espace de travail. Choisir un moteur sans résultat en cache démarre son analyse ; **Réanalyser** rafraîchit ses résultats. Deux moteurs peuvent retrouver des fonctions, noms ou pseudo-codes différents sans que l’un constitue le code source original.

## Installer ou sélectionner un outil existant {#install-or-select-an-existing-tool}

1. Repérez le composant, examinez son état et ses prérequis, puis choisissez Installer si nécessaire.
2. Pour un Java, .NET, Ghidra ou autre outil compatible déjà installé, utilisez le sélecteur de chemin et vérifiez l’exécutable et sa version.
3. Revenez à l’espace de travail et lancez l’analyse. Consultez la sortie de la tâche en cas de dépendance manquante, architecture incompatible ou délai dépassé.

Ghidra/Java, les services managés, TypeScript/Node.js et les convertisseurs console ont des prérequis distincts. Installer l’un n’installe pas tous les autres. La présence d’un compilateur ou d’un débogueur est également indépendante de celle d’un décompilateur.

## Limites selon le format {#format-specific-limits}

Consultez l’[analyse native](doc:native) pour les types inférés et les instructions non prises en charge, puis [.NET, Java, Python et shaders](doc:languages) pour les limites de récupération. Une application empaquetée peut nécessiter une extraction préalable. Le chiffrement, les dépendances originales indisponibles, les protections et le code généré dynamiquement peuvent bloquer l’analyse. Augmentez les limites uniquement si le rapport identifie ce problème ; prolonger un délai ne permet pas de récupérer des octets indisponibles.
