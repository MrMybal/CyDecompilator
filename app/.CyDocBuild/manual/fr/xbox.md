---
id: xbox
title: Préparation Xbox et projets natifs
description: Préparer les entrées Xbox et créer, compiler, rattacher ou lancer des projets natifs Xbox 360.
section: Consoles et Unreal
parent: consoles
order: 16
sourceRevision: 2
---

Ouvrez **Portage Xbox** dans la barre latérale pour préparer une entrée ou réutiliser un projet natif. Il traite XBE/XEX, dossiers extraits et images XDVDFS ISO/ZIP compatibles. La Xbox originale dispose actuellement de l’inspection/préparation, pas d’un recompileur natif général. La Xbox 360 utilise le SDK **ReXGlue** installé séparément pour les reconstructions PowerPC vers C++ compatibles.

## Créer un projet {#create-a-project}

1. Ouvrez [Portage Xbox](doc:xbox). Préparez un dossier complet ou une image compatible ; importer un exécutable isolé n’importe pas toutes ses ressources voisines.
2. Choisissez l’entrée et inspectez les métadonnées.
3. Installez/configurez ReXGlue. La compilation Windows x64 nécessite CMake, Ninja, outils C++ Visual Studio, Clang et SDK Windows.
4. Créez/compilez le projet natif puis examinez génération et compilation. **Modifier les sources natives** rattache les sources à l’IDE.
5. Lancez explicitement la sortie et consultez le journal de tâche. Le lanceur vérifie les identités d’exécutables pertinentes ; compiler ne valide pas la compatibilité du jeu.

```diagram
{"type": "flow", "title": "De l’entrée console à une sortie testée", "nodes": [{"id": "step-0", "label": "1. Préserver les ressources", "x": 20, "y": 20, "width": 320}, {"id": "step-1", "label": "2. Choisir le backend", "x": 370, "y": 20, "width": 320}, {"id": "step-2", "label": "3. Convertir ou générer", "x": 720, "y": 20, "width": 320}, {"id": "step-3", "label": "4. Consigner les identités", "x": 720, "y": 135, "width": 320}, {"id": "step-4", "label": "5. Exécuter avec assertions", "x": 370, "y": 135, "width": 320}, {"id": "step-5", "label": "6. Évaluer la compatibilité", "x": 20, "y": 135, "width": 320}], "edges": [{"from": "step-0", "to": "step-1"}, {"from": "step-1", "to": "step-2"}, {"from": "step-2", "to": "step-3"}, {"from": "step-3", "to": "step-4"}, {"from": "step-4", "to": "step-5"}]}
```

1. **Préserver les ressources** — Examiner une entrée complète lisible.
2. **Choisir le backend** — Installer l’outil optionnel compatible.
3. **Convertir ou générer** — Lire code et imports incompatibles.
4. **Consigner les identités** — Garder reçu et journaux de sortie.
5. **Exécuter avec assertions** — Tester explicitement le comportement.
6. **Évaluer la compatibilité** — Compiler ne valide pas tout le jeu.


## Projets natifs existants {#existing-native-projects}

Enregistrez un projet existant sans supposer que ses ressources ont été copiées dans CyDecompilator. Il dépend toujours de son dossier d’origine. Le lancement crée un processus appartenant à une tâche ; son annulation arrête l’arborescence correspondante. Sauvegardes et caches appartiennent aux données du projet natif. Les réglages d’affichage enregistrés peuvent remplacer le mode fenêtré/plein écran demandé.

## Compatibilité et profils expérimentaux {#compatibility-and-experimental-profiles}

Les adaptations propres à un jeu exigent l’identité exacte de l’exécutable pris en charge. Temps de simulation, fréquence d’images, interpolation, interface/clavier, occlusion et rendu nécessitent des contrôles distincts. Un profil compatible avec une révision ne doit pas être appliqué à une autre sur le seul nom de fichier. Backends graphiques et runtimes de compatibilité fournissent encore le comportement console ; un projet C++ généré n’est pas le moteur source original retrouvé.

Ray tracing, réseau de campagne ou écran partagé expérimentaux n’établissent pas une compatibilité générale. IP directe et réseau compétitif ne sont pas interchangeables ; les modes non pris en charge restent indisponibles. Consultez le guide [rendu, commandes et cadence](doc:xbox-methods). Si la page manque, votre version n’inclut pas ce module ; le manuel ne l’installe pas.
