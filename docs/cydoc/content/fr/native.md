---
id: native
title: Code natif et détails des exécutables
description: Code natif
section: Analyser le code
order: 4
sourceRevision: 1
---

## Ce que récupère l’analyse native {#what-native-analysis-recovers}

Le moteur C intégré couvre les chemins x86, x64 et ARM64 pris en charge dans les fichiers PE/ELF. Il peut retrouver des structures de contrôle, opérations arithmétiques, certaines opérations flottantes/SIMD et des prototypes d’appel inférés. Le désassembleur expose les instructions même lorsqu’une fonction ne peut pas être reconstruite en C. Ghidra offre une investigation optionnelle plus approfondie avec types, instructions et preuves high-pcode.

Les types, limites de fonctions, conventions d’appel et cibles indirectes inférés restent des interprétations de travail. Une instruction non prise en charge ou un flot de contrôle incomplet impose d’examiner le désassemblage et le rapport, plutôt que de considérer le pseudo-code comme complet.

## Examiner une fonctionnalité {#inspect-one-feature}

1. Ouvrez l’exécutable et confirmez architecture, organisation mémoire et points d’entrée.
2. Repérez une chaîne, un import, un export ou un symbole lié à la fonctionnalité dans l’[espace de travail](doc:workspace).
3. Suivez les appels et comparez le C récupéré aux instructions correspondantes.
4. Utilisez l’[investigation](doc:investigation) pour obtenir un dossier d’instructions, types et valeurs lorsque Ghidra est disponible.
5. Consignez fonction/adresse, identité de l’entrée, preuves et inconnues avant toute modification.

## Exporter du C et reconstruire {#export-c-and-reconstruct}

La vue Programme peut exporter les fonctions natives sélectionnées, les fonctions exportées ou une fonction et ses appels pris en charge. Les globales, constantes et imports récupérables sont inclus. L’[IDE de projet](doc:projects) peut préparer des cibles exécutables, DLL ou bibliothèques statiques avec CMake et des projets Visual Studio Windows. Des entrées, imports, exports de données, initialisations TLS ou ressources manquants peuvent toujours empêcher une reconstruction exécutable.

Un C qui compile n’est pas automatiquement équivalent. Vérifiez les tailles de pointeurs, structures, durées de vie, conventions des callbacks et initialisations. Le remplacement d’une fonction isolée impose des contraintes plus strictes qu’un projet reconstruit complet ; consultez les [plans de remplacement](doc:patching).

## Conteneurs, empaquetage et symboles {#containers-packing-and-symbols}

Les détails disponibles incluent entropie des sections, surcouche, ressources embarquées, protections, manifestes et indices de chaîne d’outils. L’extraction traite les cas PyInstaller, .NET single-file, UPX et ZIP ajouté reconnus. Le résultat doit être analysé séparément ; une détection ne prouve ni désencapsulation ni déchiffrement réussi.

Les symboles améliorent les noms, sans retrouver tous les types et fichiers sources originaux. Un ELF sans sections peut être chargé depuis ses segments validés ; l’absence de symboles ou de relocations limite toujours le résultat. L’identité des modules console et certaines dépendances de valeurs natives indirectes peuvent rester inconnues. Conservez ces limites dans le rapport d’investigation.
