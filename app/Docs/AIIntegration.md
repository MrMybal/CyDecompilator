# CyDecompilator : intégration MCP et skill IA

Le serveur MCP expose les opérations métier de l'application : analyse, sources,
reconstruction, compilation, Git, réinjection, débogage et observations de processus,
réseau et interface. Le skill `cydecompilator` explique à l'agent comment enchaîner
ces opérations et interpréter leurs preuves et limites. Les outils disponibles et
leurs schémas se découvrent sur le serveur ; ne pas figer leur nombre côté client.

## Installer le skill

Depuis la racine de l'installation Windows :

```powershell
runtime/python/Scripts/python.exe app/scripts/install_skill.py
```

Le dossier livré [`app/skills/cydecompilator`](../skills/cydecompilator/SKILL.md)
est copié dans `CODEX_HOME/skills/cydecompilator` (par défaut
`~/.codex/skills/cydecompilator`). Le script ne remplace pas une version différente
déjà présente. Pour un autre client compatible avec les skills, sélectionner son
dossier de skills :

```powershell
runtime/python/Scripts/python.exe app/scripts/install_skill.py --destination C:/MesSkills
```

Actualiser la découverte des skills dans le client. Le paquet est autonome : ses
références restent accessibles après copie. Il n'installe ni moteur ni connexion MCP.
Pour invoquer explicitement le skill : « Utilise $cydecompilator pour reconstruire
ce projet, compiler et comparer ces scénarios avec l'original. »

## Connecter le serveur

Exemple de déclaration stdio ; remplacer le dossier d'installation et adapter
l'enveloppe de configuration au client MCP utilisé :

```json
{
  "mcpServers": {
    "cydecompilator": {
      "command": "C:/Tools/CyDecompilator/runtime/python/Scripts/python.exe",
      "args": ["C:/Tools/CyDecompilator/app/tool.py", "mcp"]
    }
  }
}
```

Si l'interface ou un serveur utilise déjà la base des jobs, démarrer cette connexion
avec une base distincte : arguments `app/tool.py`, `--data-dir`, un chemin absolu
comme `C:/Tools/CyDecompilator/data/mcp-jobs`, puis `mcp`.
Les projets d'analyse restent communs à l'installation. Les opérations exécutant
le même projet doivent être coordonnées entre clients.

Le serveur local crée son identité autonome avec les permissions déclarées.
`CYTOOLS_TOKEN` permet une identité restreinte explicitement configurée. Aucun
jeton ni clé IA ne doit apparaître dans les paramètres métier ou dans ce guide.

## Contrat d'appel

Toutes les opérations métier utilisent `parameters`. Les contrôles `cy_*` ont
leurs arguments directement :

```json
{"tool":"cy_describe_operation","arguments":{"operationId":"workspace_create"}}
{"tool":"op_open_file","arguments":{"parameters":{"path":"C:/samples/App.dll","engine":"ilspy"}}}
{"tool":"cy_get_job","arguments":{"jobId":"<jobId retourné>"}}
```

Un appel métier crée un job asynchrone. Attendre `Completed`, `Failed` ou
`Cancelled`, puis lire `outputs` ou `error`. Une réponse MCP réussie ne signifie
pas que le job a réussi. Un job `Completed` peut retourner une compilation
`status=failed`, un scénario incomplet ou une reconstruction non validée.

## Parcours principaux

### Une consigne, puis un parcours autonome

Dans le panneau **AI**, saisir l'objectif, choisir **Investiguer**,
**Reconstruire et valider** ou **Modifier et tester**, puis **Lancer la tâche
autonome**. L'assistant utilise le fournisseur IA déjà configuré et enchaîne les
opérations lui-même. Les sources ouvertes sont enregistrées puis figées pendant
les modifications ; l'éditeur recharge ensuite les révisions produites.

Via MCP, l'opération correspondante est `ai_agent` :

```json
{"tool":"op_ai_agent","arguments":{"parameters":{"projectId":"<projectId>","objective":"Reconstruis, corrige les erreurs de compilation et compare le scénario d'export fourni avec l'original.","workflow":"reconstruct","maxSteps":60,"allowInstall":true,"language":"fr"}}}
```

L'agent découvre les schémas, analyse, installe si nécessaire les composants
officiels, lit les diagnostics, corrige avec révisions et sauvegardes Git
automatiques, compile, exécute et compare. Il passe par les jobs authentifiés du
Runtime, avec les permissions du client ; une réponse du modèle n'est jamais
exécutée comme une commande shell. Il reste sur le projet sélectionné et ne
modifie pas les comptes, la configuration IA ou l'application en cours.

`ai_agent_status` conserve l'avancement, les décisions et les résultats des jobs.
Après interruption ou limite de travail, reprendre avec le `runId`, le même
objectif et le même parcours. **Reprendre la tâche autonome** est aussi disponible
dans l'interface. Annuler le job propriétaire arrête ses jobs enfants, y compris
les processus et sessions de débogage.

L'état `completed` exige une preuve serveur : scénarios reconstruits complets et
correspondants, ou copie modifiée exécutée/testée avec empreinte vérifiée. Un
simple « terminé » du modèle est refusé. Les états `blocked`, `budget-exhausted`,
`cancelled` et `failed` conservent les travaux et expliquent ce qui manque. Un
vrai compte IA, une licence, une dépendance indisponible ou un comportement attendu
inconnu peuvent nécessiter une information de l'utilisateur.

Une IA externe peut également conduire directement les mêmes outils MCP sans
déléguer à un second fournisseur. Le skill lui demande de poursuivre jusqu'au
résultat testé et de résoudre les étapes intermédiaires. Si l'installation locale
est accessible, la CLI fournit une solution de repli en l'absence de connexion MCP.

| Besoin | Enchaînement d'opérations |
|---|---|
| Binaire | `open_file`, `project_info`, `list_functions`, `decompile`, `xrefs`, `strings`, `search` |
| Investigation native | analyse Ghidra, `investigation_native`, `investigation_query` |
| JS/web/Electron | `application_open`, `investigation_query`, `investigation_source` |
| Projet éditable | `workspace_create` ou `workspace_open`, `workspace_info`, `workspace_read/save` |
| IDE C# | `workspace_csharp`, `workspace_refactor_check`, `workspace_evaluate` |
| Compiler/tester | `workspace_execute`, éventuellement `workspace_dependencies` |
| Historique Git | `workspace_history` : `snapshot`, `compare`, `restore` avec révision du diff |
| Reconstruction bornée | `reconstruction_run`, `reconstruction_status` |
| Modifier une fonction native | `patch_prepare`, revue du plan, `patch_apply`, test avec programme appelant pour une DLL |
| Modifier une méthode .NET | `managed_methods`, modification C#, `managed_patch_prepare`, `patch_apply`, `patch_run` |
| Copies sauvegardées | `patch_outputs` et reçus avec empreintes |
| Débogueur .NET | `debug_breakpoints`, lancement `debug_start`, `debug_status`, `debug_control` |
| Réseau et graphique | `behavior_capture`, `behavior_compare`, `behavior_evidence`, `investigation_query` |
| Autres fonctions et administration | découverte MCP puis `cy_describe_operation` ; moteurs, symboles, extractions, exports, IA et mises à jour |
| Travail autonome complet | `ai_agent`, `ai_agent_status`, reprise avec `runId` |

Les noms sont des identifiants métier : les outils correspondants portent le
préfixe `op_`. Chaque appel prend les champs du schéma courant. Par exemple :

```json
{"tool":"op_workspace_create","arguments":{"parameters":{"projectId":"<projectId>"}}}
{"tool":"op_workspace_execute","arguments":{"parameters":{"projectId":"<projectId>","action":"build"}}}
{"tool":"op_reconstruction_run","arguments":{"parameters":{"projectId":"<projectId>","maxRounds":3,"repair":false,"verifyBehavior":true}}}
```

Lire avant d'éditer et passer la `revision` obtenue à `workspace_save`. En cas
de conflit, relire et réconcilier. `repair=true` délègue les corrections au fournisseur
IA configuré et conserve les changements dans Git ; un agent MCP peut aussi
effectuer ses propres modifications via les opérations de sources.

`debug_start` reste actif pendant la session : conserver son job, puis envoyer
les contrôles sans attendre sa fin. Après chaque pause, utiliser les nouveaux
`sessionId` et `stopId`. Annuler le job propriétaire arrête le débogueur et ses
processus. Une copie .NET se débogue avec son `receiptId`, préparé avec `symbols=true`.

## Preuves, conservation et limites

`open_file` copie l'entrée avant l'analyse et conserve son véritable chemin pour
résoudre les dépendances voisines. `application_open` crée un instantané immuable.
Pour importer explicitement un bundle avec `cy_import_file`, inclure ses fichiers
compagnons et le consommer avant la fin de la tâche.

Les copies d'entrée et résultats de job sont temporaires : exporter les résultats
utiles avec `cy_export_job`, puis `cy_finish_task` lorsque tous les consommateurs
ont terminé. Les projets, sources reconstruites et reçus sont des données
persistantes distinctes ; `cy_finish_task` ne les supprime pas.

Une compilation réussie ne prouve pas l'équivalence. `scenarios-matched` signifie
que les scénarios enregistrés ont correspondu aux vérifications activées ;
`compiled-unverified` conserve l'absence de preuve d'exécution. Les modifications
portent sur des copies séparées de l'application. Les observations HTTP/TCP sont
bornées ; elles ne sont pas une capture universelle des paquets. Les captures
graphiques dépendent du pilote Windows/Chromium/Electron et des contrôles exposés.

## Vérification

```powershell
runtime/python/Scripts/python.exe -m pytest app/tests/test_autonomous_agent.py app/tests/test_mcp_workflows.py app/tests/test_skill_delivery.py -q
runtime/python/Scripts/python.exe app/tests/acceptance_mcp.py
runtime/python/Scripts/cytools.exe validate app/CyTool.json
```

Les tests MCP lancent le vrai serveur stdio, avec des magasins isolés : catalogue
et schémas de toutes les opérations déclarées, reconstruction Node, Git et conflits,
reconstruction/patch natif, reconstruction .NET avec dépendance locale, réinjection
et exécution de copie, débogage et annulation, scénario Chromium avec HTTP,
captures, graphe de preuves et refus d'une image altérée. Ils utilisent de vrais
compilateurs/runtimes ; les composants nécessaires doivent être installés.
L'acceptance shader reste disponible sans appel à un fournisseur IA ; `--ai`
déclenche explicitement ce test externe. Voir aussi [CapabilityCoverage.md](CapabilityCoverage.md)
pour les limites de chaque moteur et les tests métier spécialisés.

Les tests de l'agent couvrent la réparation d'une vraie compilation, le refus
d'une conclusion prématurée, la reprise, les conflits de sources, les permissions,
le gel de l'éditeur, l'annulation des processus et une DLL modifiée avec programme
appelant. Les décisions du modèle y sont contrôlées pour rendre la suite stable.
Un essai séparé sur cette machine a aussi utilisé le vrai fournisseur **Claude
Code** configuré : diagnostic, récupération de la source, sauvegardes Git,
correction et comparaison réussie de trois scénarios Node. Ce résultat ne
certifie pas tous les modèles ni toutes les applications.

[MCP.md](MCP.md) décrit le contrat générique CyToolsCore ; les noms de Tool de ses
exemples de scaffold ne sont pas ceux de CyDecompilator.
