---
id: debugging
title: Déboguer les sources .NET reconstruites
description: Débogage .NET
section: Modifier et reconstruire
order: 10
sourceRevision: 1
---

Le débogueur intégré utilise NetCoreDbg pour les projets .NET compatibles et les copies managées modifiées. Ce n’est pas un débogueur général natif/Java/Python. Il nécessite une sortie exécutable compatible, les sources correspondantes et des symboles utilisables, généralement des PDB portables.

## Démarrer une session {#start-a-session}

1. Installez/configurez le débogueur avec la commande de composant proposée.
2. Ouvrez les sources, enregistrez, compilez la configuration voulue et sélectionnez le projet de démarrage.
3. Ouvrez le fichier concerné et placez un point d’arrêt. Un fichier modifié doit d’abord être enregistré.
4. Lancez le débogage du projet, ou **Déboguer la copie modifiée** pour un patch managé enregistré et vérifié.
5. Consultez l’état du **Débogueur**. Un point d’arrêt demandé peut rester non vérifié jusqu’au chargement des symboles correspondants.

## Mettre en pause et inspecter {#pause-and-inspect}

En pause, utilisez **Pile et variables** pour choisir thread/cadre et examiner les variables disponibles. Ajoutez des surveillances et évaluez les expressions prises en charge dans ce contexte. Continuer/Pause, Pas à pas principal, détaillé et sortant contrôlent l’exécution. F5 reprend une session active en pause ; F9 bascule un point d’arrêt dans l’éditeur focalisé. Utilisez les commandes visibles si le focus se trouve ailleurs.

Valeurs et identifiants de pause appartiennent à la session active. Ne les réutilisez pas après reprise, redémarrage ou arrêt. Une surveillance en échec peut provenir d’une variable absente, expression invalide, optimisation ou cadre périmé plutôt que d’un plantage.

## Maintenir la correspondance source {#keep-source-correspondence}

Les sources deviennent non modifiables pendant le débogage. Si elles changent extérieurement, arrêtez, recompilez et redémarrez avant de vous fier aux lignes. Le débogueur appartient à une tâche : **Arrêter le débogage** termine la session, et l’annulation traite son arborescence de processus. Le code de sortie est enregistré séparément de la réussite des points d’arrêt/inspections.

## Diagnostiquer les échecs courants {#diagnose-common-failures}

| Symptôme | Vérification |
|---|---|
| Aucune cible exécutable | Projet de démarrage, sortie exécutable et runtime .NET |
| Point d’arrêt non lié | Identité PDB, révision source et optimisation |
| Mauvaise ligne source | Recompiler après modification ; vérifier le module |
| Variables indisponibles | Cadre, portée, code optimisé et état de pause |
| Copie refusée | Intégrité du reçu et nouvelle compilation/préparation |

Consultez les [projets](doc:projects), le [remplacement de méthode](doc:patching) et le [dépannage](doc:troubleshooting).
