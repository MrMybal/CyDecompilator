---
id: troubleshooting
title: Dépannage et états des résultats
description: Dépannage
section: Réglages et repères
order: 20
sourceRevision: 1
---

Ouvrez le [journal de l’application](doc:troubleshooting) et la sortie de la tâche concernée. Relevez opération, entrée/projet, moteur, révision source, état final et erreur. Lisez la première erreur exploitable autant que le résumé final ; les messages suivants peuvent découler d’une dépendance manquante initiale.

## Localiser l’échec {#locate-the-failure}

| Symptôme | Vérification suivante |
|---|---|
| Le logiciel ne démarre pas | Interpréteur privé, dépendances natives et journal du lanceur |
| Moteur absent | Page Moteurs, chemin exécutable et version Java/.NET/Node |
| Aucune fonction / code partiel | Format, architecture, empaquetage et instructions incompatibles |
| Compilation échouée | Compilateur, références, entrée, ressources et diagnostics |
| Compilation réussie mais lancement refusé | Identité de sortie neuve, projet de démarrage et runtime |
| Préparation de patch échouée | Signature/ABI, capacité, relocations, méthode donneuse et révision |
| Aucune variable au débogage | Pause/cadre actif, symboles et optimisation |
| Requête IA échouée | Fournisseur/modèle, connexion/clé existante, limites et sortie |
| Scénario incomplet | Pilote, sélecteurs, délais, actions et limites de capture |
| Menu absent | Version installée de l’application/module et parcours applicable |
| Disque saturé | Ressources importées/extraites, sorties répétées, instantanés et tests |

## Interpréter les états, pas seulement les couleurs {#interpret-states-instead-of-only-colors}

Queued, Preparing et Running sont intermédiaires. Completed, Failed et Cancelled sont terminaux pour le Runtime. **Completed** signifie que le gestionnaire a retourné un résultat : examinez l’état métier, qui peut encore indiquer compilation échouée, différences ou exécution non vérifiée. Une annulation peut conserver des diagnostics partiels utiles sans résultat validé.

Pour reconstruire, distinguez compilation, tests et concordance des scénarios. Pour une conversion console, distinguez préparation, converted-unverified, executed-unverified et réussite des assertions. Pour un patch, un plan valide précède la création d’un reçu de copie vérifiée. Ne réutilisez jamais une ancienne réussite après changement des empreintes d’entrée/sortie.

## Reprendre sans perdre le travail {#recover-without-losing-work}

Enregistrez les buffers, arrêtez les processus concernés et examinez le dernier point d’historique source. Recompilez ou recréez le plan après changement pertinent. Corrigez les outils absents avant de relancer ; ne répétez pas un long scénario sans modification significative. Avant suppression, consultez le [stockage](doc:storage). Un petit exemple représentatif permet de distinguer défaut général d’installation et application particulière incompatible.
