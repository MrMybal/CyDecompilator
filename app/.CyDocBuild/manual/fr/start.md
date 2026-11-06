---
id: start
title: Bienvenue dans CyDecompilator
description: Choisir un parcours, examiner une première entrée et parcourir ce manuel.
section: Bien démarrer
order: 0
sourceRevision: 2
---

CyDecompilator inspecte des applications compilées, récupère du code et aide à créer, modifier et tester les projets sources pris en charge. Ce manuel est inclus dans l’application : sa consultation ne nécessite ni Internet, ni moteur d’analyse installé, ni compte IA, ni projet ouvert.

## Se repérer {#find-your-way}

Appuyez sur **F1** depuis une page pour ouvrir son guide. Sélectionnez **Documentation** dans la barre latérale ou la palette Ctrl+Maj+P pour ouvrir le lecteur CyDoc installé dans le navigateur, avec une URL de fichier local. Le champ de recherche globale en haut ou **Ctrl+K** parcourt le texte de tous les chapitres ; le sommaire permet de rejoindre une section, et les commandes **Précédent** / **Suivant** du navigateur de revenir sur les pages consultées. Utilisez la commande d’agrandissement de l’image pour l’étendre dans la fenêtre du lecteur : molette pour zoomer, glisser pour déplacer et double-clic pour réinitialiser. Échap réduit la vue agrandie. Les blocs de code disposent d’un bouton Copier. Les liens documentaires ouvrent un autre chapitre ; les liens web externes s’ouvrent séparément et ne sont pas nécessaires à la consultation locale.

L’anglais est la langue par défaut. Le manuel suit le choix anglais/français de l’interface jusqu’à la sélection de sa propre langue. Les autres langues d’interface utilisent le manuel anglais. Les deux traductions couvrent les mêmes chapitres, illustrations et parcours.

## Obtenir un premier résultat {#first-useful-result}

1. Consultez l’[installation](doc:installation), puis ouvrez [Moteurs](doc:engines) pour vérifier l’outil nécessaire.
2. Ouvrez l’[espace de travail](doc:workspace). Sélectionnez un fichier avec **Ctrl+O**, ou collez son chemin et validez avec Entrée.
3. Choisissez un moteur, attendez l’analyse, puis sélectionnez une fonction. Examinez ensemble les sources récupérées et le désassemblage.
4. Utilisez l’[IDE de projet](doc:projects) pour modifier les sources, l’[investigation](doc:investigation) pour les preuves, ou l’[IA](doc:ai) pour un parcours assisté.
5. Enregistrez les notes utiles et les modifications des sources. Conservez l’entrée originale et examinez les erreurs et les inconnues signalées.

```diagram
{"type": "flow", "title": "De l’entrée à la compréhension", "nodes": [{"id": "step-0", "label": "1. Conserver l’entrée", "x": 20, "y": 20, "width": 320}, {"id": "step-1", "label": "2. Examiner le format", "x": 370, "y": 20, "width": 320}, {"id": "step-2", "label": "3. Choisir un moteur", "x": 720, "y": 20, "width": 320}, {"id": "step-3", "label": "4. Analyser", "x": 720, "y": 135, "width": 320}, {"id": "step-4", "label": "5. Examiner le code", "x": 370, "y": 135, "width": 320}, {"id": "step-5", "label": "6. Conserver les conclusions", "x": 20, "y": 135, "width": 320}], "edges": [{"from": "step-0", "to": "step-1"}, {"from": "step-1", "to": "step-2"}, {"from": "step-2", "to": "step-3"}, {"from": "step-3", "to": "step-4"}, {"from": "step-4", "to": "step-5"}]}
```

1. **Conserver l’entrée** — Séparer les octets originaux.
2. **Examiner le format** — Confirmer architecture et contenu.
3. **Choisir un moteur** — Vérifier ses prérequis.
4. **Analyser** — Lire progression et diagnostics.
5. **Examiner le code** — Comparer fonctions et instructions.
6. **Conserver les conclusions** — Garder preuves et inconnues.


```image
{"id": "workspace-screenshot", "src": "assets/workspace.png", "alt": "Espace de travail affichant le shader de sommets DXBC fourni, décompilé en HLSL, avec navigation dans les fonctions et panneau IA.", "title": "Espace de travail affichant le shader de sommets DXBC fourni, décompilé en HLSL, avec navigation dans les fonctions et panneau IA.", "controls": "minimal", "annotations": [{"id": "function-list", "type": "rect", "x": 0.12, "y": 0.1, "toX": 0.33, "toY": 0.97, "label": "Fonctions et recherche"}]}
```


## Choisir un objectif {#choose-a-goal}

| Objectif | Guide |
|---|---|
| Comprendre une fonction ou retrouver des noms | [Espace de travail](doc:workspace) et [analyse native](doc:native) |
| Reconstruire une application modifiable | [Projets](doc:projects) et [reconstruction et validation](doc:reconstruction) |
| Changer une fonction dans une copie de l’application | [Remplacement de fonction](doc:patching) |
| Examiner une fonctionnalité Electron | [Investigation JavaScript et native](doc:investigation) |
| Comparer deux versions, leur réseau et leur interface | [Comportements observés](doc:observations) |
| Piloter le logiciel depuis un client IA | [IA](doc:ai) et [MCP / CLI](doc:automation) |
| Préparer une entrée console ou consulter les règles Unreal | [PS5](doc:ps5), [Xbox](doc:xbox), [Unreal](doc:unreal) |

## Interpréter les résultats {#read-results-accurately}

Le code récupéré n’est pas le projet source original. Une compilation prouve que la chaîne d’outils a accepté le projet produit ; elle ne prouve pas son comportement original. Des scénarios concordants ne couvrent que leurs interactions et assertions enregistrées. Les instructions non prises en charge, dépendances manquantes, ressources indisponibles et plateformes non testées restent des limites explicites. Une page absente de votre version n’y est pas disponible ; mettre à jour le code de l’application n’installe pas ses moteurs optionnels.
