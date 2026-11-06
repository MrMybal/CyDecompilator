---
id: shortcuts
title: Raccourcis, glossaire et repères
description: Retrouver les raccourcis, les termes des parcours et la page d’aide adaptée.
section: Réglages et repères
parent: settings
order: 21
sourceRevision: 2
---

## Clavier et souris {#keyboard-and-mouse}

| Commande | Contexte | Action |
|---|---|---|
| F1 | Page de l’application | Ouvrir son chapitre d’aide |
| Ctrl+K | Lecteur CyDoc | Rechercher dans la documentation locale |
| Ctrl+Maj+P | Application | Ouvrir/fermer la palette de commandes |
| Ctrl+O | Application | Choisir un fichier d’entrée |
| Double-clic sur une fonction | Symbole source reconnu | Ouvrir cette fonction |
| Clic droit sur un nom | Espace de travail | Actions disponibles de nom/recherche |
| F5 | Débogueur .NET actif en pause | Continuer |
| F9 | Éditeur source focalisé avec débogage .NET | Basculer un point d’arrêt |
| Molette | Image du manuel/capture agrandie | Zoom autour du pointeur |
| Glisser | Image agrandie | Déplacer |
| Double-clic | Image agrandie | Ajuster à la zone |
| Échap | Image du manuel agrandie | Fermer l’image |

Les raccourcis d’édition s’appliquent à l’éditeur focalisé ; les commandes disponibles dépendent du composant et du parcours. Utilisez les boutons si le focus se trouve ailleurs. Précédent/Suivant du manuel est distinct de la navigation entre fonctions et d’Undo/Redo dans les sources.

## Termes des rapports {#terms-used-in-reports}

| Terme | Signification |
|---|---|
| Projet d’analyse | Identité/résultats/annotations persistants d’une entrée importée |
| Espace source | Fichiers modifiables rattachés ou générés pour ce projet |
| Moteur | Décompilateur, analyseur, convertisseur ou backend choisi séparément |
| Tâche Runtime | Opération planifiée avec progression, annulation, sorties/erreur |
| Plan | Remplacement proposé et contrôlé avant écriture d’une copie |
| Reçu | Enregistrement lié à l’identité d’une conversion/copie créée |
| Scénario | Entrées, actions, contrôles et délais définis |
| Preuve | Sortie enregistrée liée aux cibles et étapes observées |
| Non vérifié | Les preuves requises du comportement ne sont pas établies |
| Blocage | Prérequis manquant ou cas incompatible empêchant le résultat |

## Trouver la référence adaptée {#reference-map}

Les [opérations avancées](doc:automation) donnent les contrats/paramètres installés ; les [moteurs](doc:engines) aident à choisir un format, le [stockage](doc:storage) décrit les données et le [dépannage](doc:troubleshooting) les erreurs. [Reconstruction](doc:reconstruction), [remplacement](doc:patching) et [observations](doc:observations) expliquent leurs états de validation. Consulter l’[API des opérations](doc:operation-api) pour les paramètres et résultats publics, et l’[API des liens d’aide natifs](doc:help-api) pour ouvrir un chapitre précis depuis Python.
