---
id: workspace
title: Espace de travail : inspection et navigation
description: Espace de travail
section: Analyser le code
order: 3
sourceRevision: 1
---

Ouvrez l’[espace de travail](doc:workspace) pour inspecter un binaire. Un projet d’analyse conserve l’identité de l’entrée, les résultats des moteurs, les annotations et les caches de sources séparément de l’application originale.

## Ouvrir et analyser {#open-and-analyze}

1. Appuyez sur **Ctrl+O**, choisissez un fichier, ou collez son chemin dans la barre d’outils et validez avec Entrée. Les projets récents permettent de reprendre une analyse.
2. Vérifiez le format et l’architecture détectés. Choisissez un moteur disponible ; installez les composants manquants dans [Moteurs](doc:engines).
3. Attendez la tâche d’analyse. La barre d’état et le journal indiquent sa progression et ses erreurs. Annulez une tâche si nécessaire ; une sortie partielle n’est pas une analyse terminée.
4. Sélectionnez une fonction pour la décompiler. Filtrez la liste par nom ou adresse.

```image
{"id": "workspace-screenshot", "src": "assets/workspace.png", "alt": "Analyse réelle du shader DXBC fourni, avec HLSL, liste des fonctions et commandes du parcours IA.", "title": "Analyse réelle du shader DXBC fourni, avec HLSL, liste des fonctions et commandes du parcours IA.", "controls": "minimal", "annotations": [{"id": "function-list", "type": "rect", "x": 0.12, "y": 0.1, "toX": 0.33, "toY": 0.97, "label": "Fonctions et recherche"}]}
```


## Suivre le code {#follow-the-code}

Double-cliquez sur un nom de fonction reconnu pour l’ouvrir. Les boutons précédent/suivant parcourent l’historique de navigation. Le clic droit propose les actions de renommage et recherche disponibles. Les onglets distinguent décompilation, désassemblage/bytecode et sources converties par IA. Un extrait converti possède son propre état de vérification ; il ne remplace pas le binaire original.

Utilisez les **chaînes** et les recherches pour retrouver des messages visibles ou des constantes. Les références et appels relient une fonction à ses appelants et aux fonctions qu’elle appelle. La vue **Programme** présente les informations disponibles : imports/exports, sections, protections, version/manifeste et indices de contenus embarqués. **Détails** contient les propriétés et notes de la fonction ; dans une fenêtre étroite, cette vue rejoint les onglets du code au lieu d’occuper un panneau droit permanent.

## Noms, notes et symboles {#names-notes-and-symbols}

Les noms retrouvés peuvent provenir des exports, des symboles PDB, des inférences du moteur ou de vos annotations. Vérifiez l’identité des symboles avant de vous y fier. La recherche PDB locale et le serveur configuré utilisent les identifiants correspondants ; un nom de fichier similaire ne suffit pas. Renommer ou commenter modifie les annotations d’analyse, pas le code machine de l’entrée. Exportez les notes ou les sources produites si vous en avez besoin hors du projet.

## Poursuivre le travail {#continue-the-workflow}

Utilisez les [projets](doc:projects) pour modifier des fichiers et compiler, le [remplacement de fonction](doc:patching) pour produire une copie modifiée, ou l’[investigation](doc:investigation) pour conserver des preuves fonctionnelles. Les explications IA sont des hypothèses à confronter au code et aux observations. Pour une entrée empaquetée, examinez l’extraction et ouvrez l’exécutable pertinent dans son propre projet.
