---
id: ai
title: Assistance IA et parcours autonomes
description: Configurer un assistant et donner un objectif précis et vérifiable à un parcours autonome.
section: IA et automatisation
order: 13
sourceRevision: 3
---

Ouvrez les [réglages de l’assistant IA](doc:ai) pour configurer un CLI connecté ou un fournisseur HTTP pris en charge, le modèle et les limites. Un CLI utilise son compte existant ; un fournisseur HTTP peut nécessiter sa clé et sa facturation. Les clés appartiennent au mécanisme d’identifiants du logiciel, jamais aux sources, scénarios JSON, captures ou paramètres métier. Un fournisseur local nécessite aussi son service et son modèle actifs.

## Choisir un mode {#choose-an-interaction-mode}

| Mode | Usage |
|---|---|
| Assistant de l’application | Conversation générale avec le SDK natif, même sans projet sélectionné |
| Parcours autonome | Investigation, reconstruction, modification ou portage/test via les opérations |
| Conversation | Questions sur le programme ; examiner appels d’outils et réponse |
| Fonction | Expliquer, proposer des noms ou convertir la fonction choisie |

Le panneau de l’espace de travail et la [page IA](doc:ai) proposent ces modes. Sélectionnez projet/fonction avant une action ciblée. Une conversion produit des sources modifiables avec un état de compilation séparé ; elle ne modifie pas à elle seule l’exécutable.

```diagram
{"type": "flow", "title": "Une tâche autonome exige des preuves", "nodes": [{"id": "step-0", "label": "1. Définir la tâche", "x": 20, "y": 20, "width": 320}, {"id": "step-1", "label": "2. Examiner les preuves", "x": 370, "y": 20, "width": 320}, {"id": "step-2", "label": "3. Borner le travail", "x": 720, "y": 20, "width": 320}, {"id": "step-3", "label": "4. Sauvegarder et modifier", "x": 720, "y": 135, "width": 320}, {"id": "step-4", "label": "5. Compiler et vérifier", "x": 370, "y": 135, "width": 320}, {"id": "step-5", "label": "6. Rapporter ou reprendre", "x": 20, "y": 135, "width": 320}], "edges": [{"from": "step-0", "to": "step-1"}, {"from": "step-1", "to": "step-2"}, {"from": "step-2", "to": "step-3"}, {"from": "step-3", "to": "step-4"}, {"from": "step-4", "to": "step-5"}]}
```

1. **Définir la tâche** — Préciser périmètre et résultat.
2. **Examiner les preuves** — Découvrir outils et prérequis.
3. **Borner le travail** — Limiter étapes et tentatives.
4. **Sauvegarder et modifier** — Vérifier révisions et historique.
5. **Compiler et vérifier** — Exiger des résultats enregistrés.
6. **Rapporter ou reprendre** — Conserver reprise et inconnues.


## Donner une tâche vérifiable {#give-a-testable-task}

Précisez cible, changement voulu, périmètre source autorisé, résultat demandé et scénario concret d’acceptation. Par exemple : expliquer une routine d’export, reconstruire son projet, changer le format de sortie, compiler et comparer un cas d’entrée/sortie défini. Configurez limites d’étapes, de corrections et de jetons plutôt que des essais sans fin.

L’agent découvre les opérations Runtime, conserve des points de reprise, sauvegarde les sources et examine les erreurs. Les buffers enregistrés sont protégés pendant ses modifications. Progression et reprise sont exposées par l’opération d’état de l’agent. Erreur du fournisseur, annulation, outils absents ou sources périmées peuvent interrompre le parcours ; examinez le dernier point de reprise avant de relancer.

## Vérifier le résultat {#verify-the-result}

Lisez modifications, sorties de compilation, commits, reçus des copies et scénarios enregistrés. La fin d’un parcours exige ses preuves de validation, pas seulement une réponse affirmative. Une requête au modèle réussie ne signifie ni compilation réussie, ni tests passés, ni équivalence. Aucun fournisseur ne récupère des octets chiffrés absents ou ne garantit la reconstruction de toute application ou de tout jeu.

Pour un client externe, consultez [MCP / CLI](doc:automation). Les réparations sont détaillées dans la [reconstruction](doc:reconstruction), et les changements ciblés dans le [remplacement](doc:patching).

## Sessions et pièces jointes {#sessions-and-attachments}

L’**assistant de l’application** utilise CyMCPSDK Conversation et le même registre métier que CLI/MCP. Le texte arrive progressivement ; Annuler interrompt un tour actif. **Actualiser les conversations** et **Restaurer la conversation** rouvrent une session précise appartenant à votre identité applicative. Les historiques conservent les échanges d’outils et survivent au redémarrage. Les anciennes conversations de projet restent accessibles ; une continuation explicite crée un checkpoint SDK sans supprimer l’ancien fichier.

**Joindre des fichiers** sélectionne des fichiers locaux de 8 Mio maximum chacun. Les types image/audio/fichier acceptés dépendent du fournisseur et du transport réel ; un contenu non pris en charge produit une erreur. Pour les API, la fenêtre de contexte configurable réduit la requête tout en conservant l’historique local complet, les instructions système, le tour actif et les échanges d’outils entiers. Les agents CLI gardent leur propre gestion du contexte. Le résumé reste facultatif, sans requête cachée.

Codex reçoit les outils dynamiques natifs. Les transports HTTP/Ollama compatibles utilisent les échanges d’outils du SDK. Claude Code reçoit une délégation MCP locale authentifiée limitée à cette conversation ; ses propres actions shell/fichiers restent désactivées. Les autres profils CLI/ACP permettent l’assistance de fonction mais demandent un chemin MCP explicite pour agir dans le chat métier. La détection d’un CLI ne prouve ni la connexion du compte ni la réussite d’une génération.

## Permissions et outils externes {#permissions-and-external-tools}

**Autoriser les modifications de l’application** permet les modifications métier dans les droits du client. Identifiants, mises à jour applicatives et actions destructives restent exclus du chat ; les révisions source, la préservation des binaires originaux et les sauvegardes Git existantes s’appliquent. Une conversation limitée à un projet ne peut pas utiliser un autre identifiant de projet.

Dans **Réglages de l’assistant IA → Options CyMCPSDK et outils externes**, choisir les optimisations indépendantes et les serveurs MCP externes. Seuls les outils explicitement nommés dans `allowedTools` sont accessibles. Les secrets restent dans le coffre. `remote_tools`, `remote_call` et `remote_resources` découvrent/appellent les outils autorisés, lisent leurs ressources référencées et exposent les métadonnées des notifications compatibles. Une erreur métier distante reste une erreur. L’expiration d’une référence ne rejoue jamais une modification. Les transports et exemples sont détaillés dans [MCP et CLI](doc:automation).
