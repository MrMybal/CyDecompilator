---
id: investigation
title: Relier une fonctionnalité au code et aux preuves
description: Relier une fonctionnalité visible aux sources, appels et observations.
section: Examiner les comportements
order: 11
sourceRevision: 2
---

Ouvrez [Investigation](doc:investigation) pour relier une fonctionnalité visible à des fichiers, fonctions, ressources, routes ou appels candidats. Une correspondance statique reste un candidat ; une observation d’exécution est une preuve distincte. Le dossier conserve empreintes de la cible et positions source/adresses pour permettre la vérification des conclusions.

## JavaScript, Electron et web {#javascript-electron-and-web}

1. Sélectionnez un dossier d’application, une archive ASAR, un fichier JS/TS/JSX/TSX ou une entrée HTML.
2. Installez l’analyseur TypeScript s’il est demandé et fournissez Node.js. Lancez l’analyse ; elle n’exécute pas les modules inspectés.
3. Recherchez une chaîne visible, un identifiant HTML, une route, un symbole, un pont preload ou un canal IPC.
4. Examinez modules main/preload/renderer et source maps locales liés. Vérifiez positions et identité du contenu réel.
5. Importez des observations HAR compatibles ou configurez un scénario d’exécution pour compléter l’investigation.

Une source map peut être incomplète, périmée ou absente. Le nom d’un canal IPC ne prouve pas quel gestionnaire s’est exécuté. Appels indirects, routes dynamiques et chemins calculés peuvent rester inconnus. Services externes, identifiants et code serveur absent ne sont pas récupérables depuis le seul frontend.

## Investigation native {#native-investigation}

Choisissez un projet natif analysé et la fonction concernée. Les dossiers Ghidra compatibles exposent types, instructions et preuves high-pcode/utilisation des valeurs. Rattachez chaque instruction au bon module et conservez les bases d’adresse. Une même adresse numérique dans un autre module ne suffit pas à attribuer un appel. Consultez l’[analyse native](doc:native) pour exports, chaînes et conventions d’appel.

```diagram
{"type": "flow", "title": "Du scénario à la conclusion", "nodes": [{"id": "step-0", "label": "1. Choisir les versions", "x": 20, "y": 20, "width": 320}, {"id": "step-1", "label": "2. Définir les actions", "x": 370, "y": 20, "width": 320}, {"id": "step-2", "label": "3. Exécuter séparément", "x": 720, "y": 20, "width": 320}, {"id": "step-3", "label": "4. Capturer les preuves", "x": 720, "y": 135, "width": 320}, {"id": "step-4", "label": "5. Comparer", "x": 370, "y": 135, "width": 320}, {"id": "step-5", "label": "6. Préciser la conclusion", "x": 20, "y": 135, "width": 320}], "edges": [{"from": "step-0", "to": "step-1"}, {"from": "step-1", "to": "step-2"}, {"from": "step-2", "to": "step-3"}, {"from": "step-3", "to": "step-4"}, {"from": "step-4", "to": "step-5"}]}
```

1. **Choisir les versions** — Consigner identités et prérequis.
2. **Définir les actions** — Utiliser mêmes entrées et contrôles.
3. **Exécuter séparément** — Borner durée et processus.
4. **Capturer les preuves** — Sorties, fichiers, écrans, réseau.
5. **Comparer** — Examiner écarts et données absentes.
6. **Préciser la conclusion** — Seuls les contrôles observés sont établis.


## Construire une conclusion vérifiable {#build-a-defensible-conclusion}

Pour chaque fonctionnalité, conservez identité de l’entrée, recherche, relation candidate, position, interaction observée et inconnues. Utilisez les [observations réseau et graphiques](doc:observations) pour rejouer un scénario sur deux versions. Le rapport doit préciser ce qui a été vu, en quoi cela soutient la relation proposée et ce qui n’a pas été observé. Proximité temporelle, chaînes ou captures identiques ne prouvent pas seules une chaîne d’appels complète ni une équivalence générale.
