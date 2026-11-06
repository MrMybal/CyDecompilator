---
id: consoles
title: Entrées consoles et projets natifs
description: Choisir un parcours console et comprendre ses prérequis et ses limites.
section: Parcours consoles
order: 15
sourceRevision: 2
---

Partir de fichiers complets et lisibles que vous pouvez analyser. Conserver l’original
séparément des projets générés et des exécutables convertis.

## Choisir un parcours {#choose-a-workflow}

| Entrée ou objectif | Ouvrir | Fonction |
|---|---|---|
| ELF PS5, SELF en clair, application extraite ou conteneur pris en charge | [Portage PS5](doc:ps5) | Préparer l’entrée, configurer AnyPS5/UltraPack, convertir et exécuter des scénarios explicites |
| XBE Xbox, XEX Xbox 360, jeu extrait ou image XDVDFS | [Portage Xbox](doc:xbox) | Préparer l’entrée ; générer, compiler ou rattacher des projets natifs Xbox 360 pris en charge |
| Reconstruire un sous-système compris dans Unreal | [Reconstruction Unreal](doc:unreal) | Consulter règles et profils, puis implémenter et comparer une fonctionnalité précise |

Ces parcours ne fournissent pas de portage universel console vers PC ou vers Unreal.
La recompilation native de la première Xbox et la conversion générale PS3/PS4 ne sont
pas proposées par ces commandes. Un moteur natif peut examiner un exécutable lisible
sans rendre ses interfaces système ou graphiques compatibles avec le PC.

## Maîtriser le volume de travail {#keep-work-manageable}

Vérifier l’espace libre avant d’importer un jeu complet. Entrée conservée, sortie
convertie, sources natives et cache du compilateur occupent des espaces distincts.
Rattacher un projet natif existant lorsqu’une compilation adaptée est déjà disponible ;
éviter de réimporter uniquement pour le rouvrir. Voir le [stockage](doc:storage) et les
[méthodes Xbox](doc:xbox-methods).
