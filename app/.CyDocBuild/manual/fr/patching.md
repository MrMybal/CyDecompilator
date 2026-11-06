---
id: patching
title: Remplacer une fonction dans une copie
description: Préparer le remplacement d’une fonction native ou .NET et écrire une copie distincte.
section: Modifier et reconstruire
parent: projects
order: 9
sourceRevision: 2
---

La page **Modification de fonction** produit une copie modifiée après compilation et contrôle du remplacement. Elle ne modifie pas arbitrairement une fonction en mémoire pendant l’exécution. Conservez original, version des sources et reçu de modification pour garder un résultat traçable.

```diagram
{"type": "flow", "title": "Changer une fonction", "nodes": [{"id": "step-0", "label": "1. Choisir la cible", "x": 20, "y": 20, "width": 320}, {"id": "step-1", "label": "2. Modifier les sources", "x": 370, "y": 20, "width": 320}, {"id": "step-2", "label": "3. Compiler un plan", "x": 720, "y": 20, "width": 320}, {"id": "step-3", "label": "4. Lire les avertissements", "x": 720, "y": 135, "width": 320}, {"id": "step-4", "label": "5. Créer une copie", "x": 370, "y": 135, "width": 320}, {"id": "step-5", "label": "6. Valider le comportement", "x": 20, "y": 135, "width": 320}], "edges": [{"from": "step-0", "to": "step-1"}, {"from": "step-1", "to": "step-2"}, {"from": "step-2", "to": "step-3"}, {"from": "step-3", "to": "step-4"}, {"from": "step-4", "to": "step-5"}]}
```

1. **Choisir la cible** — Confirmer méthode et identité.
2. **Modifier les sources** — Préserver le contrat externe.
3. **Compiler un plan** — Vérifier code et liaisons.
4. **Lire les avertissements** — Examiner taille, IL ou relocations.
5. **Créer une copie** — Conserver original et reçu.
6. **Valider le comportement** — Tester le changement demandé.


## PE Windows natif x86/x64 {#native-x86-x64-windows-pe}

1. Sélectionnez la fonction dans l’espace de travail, puis **IDE de projet → Modification de fonction → Modifier la fonction sélectionnée**.
2. Préservez signature, convention d’appel, tailles de pointeurs et contrat observable. Commencez par une fonction C autonome prise en charge.
3. Choisissez le symbole de remplacement puis **Compiler et vérifier le patch**. Examinez instructions, capacité disponible, avertissements et liaisons.
4. Pour les fonctions plus grandes prises en charge, la liaison étendue peut ajouter une section native et rediriger l’entrée. Appels, données, relocations et informations de déroulement nécessitent des liaisons valides ; ce n’est pas un éditeur de liens natif sans restriction.
5. Choisissez **Écrire une copie modifiée** uniquement pour un plan valide et actuel. Analysez/exécutez ensuite cette copie et comparez le comportement voulu.

Architecture/format incompatibles, entrée trop courte, symboles non résolus et relocations dangereuses peuvent bloquer un plan. Un pseudo-code C qui compile seul ne prouve pas un remplacement compatible.

## Méthode .NET managée {#managed-net-method}

1. Créez/rattachez les sources C# puis **Charger les méthodes .NET**.
2. Sélectionnez une méthode source modifiable puis **Modifier le type déclarant**. Modifiez et enregistrez ses sources.
3. Utilisez **Compiler et vérifier le patch de méthode**. L’assembly donneuse doit correspondre au projet et à la méthode sélectionnés.
4. Examinez changements IL, dépendances générées et contrôle des autres méthodes avant d’écrire la copie.
5. Exécutez ou déboguez la copie avec symboles correspondants et scénario défini.

Les dépendances générées prises en charge sont importées avec leur méthode propriétaire ; ce ne sont pas des cibles libres indépendantes. Retirer une signature strong-name est une option explicite pouvant casser des dépendances. Les contraintes de signature ne sont pas réparées automatiquement.

## Après création {#after-creation}

Les **copies modifiées enregistrées** conservent reçus et commits sources lorsqu’ils existent. **Analyser la copie modifiée** la rouvre pour inspection. **Exécuter la copie modifiée** nécessite arguments et délai valides ; une bibliothèque nécessite un banc de test. Une modification des sources impose sauvegarde et nouveau plan. Ne réutilisez pas un reçu après changement du binaire ou de ses dépendances. Consultez le [débogage](doc:debugging), l’[historique](doc:history) et la [validation](doc:observations).
