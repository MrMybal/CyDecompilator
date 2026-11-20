---
id: automation
title: MCP, CLI et référence des opérations
description: Connecter un client MCP ou CLI et suivre le protocole des opérations et tâches.
section: IA et automatisation
parent: ai
order: 14
sourceRevision: 7
---

Interface, CLI et MCP exposent les mêmes opérations métier Runtime. Ouvrez les [opérations avancées](doc:automation) pour consulter contrats installés, formulaires de paramètres, permissions et sorties. Ce catalogue actif fait référence pour votre version ; ne figez pas un nombre d’opérations dans un guide ou un prompt IA.

## IA externe par le CLI du SDK {#external-ai-through-sdk-cli}

Une IA externe ayant accès au terminal peut piloter CyDecompilator sans MCP, sans conversation intégrée et sans compte de modèle dans cette application. **--auto** rejoint la fenêtre ouverte ou travaille sans fenêtre si elle est fermée. Le CLI gère la connexion et le profil d’accès local choisi et conserve son identité entre commandes.

```powershell
CyDecompilatorCLI.exe --auto list-operations
CyDecompilatorCLI.exe --auto describe-operation open_file
CyDecompilatorCLI.exe --auto invoke open_file --params-file input.json
CyDecompilatorCLI.exe --auto sdk describe
CyDecompilatorCLI.exe --auto sdk invoke open_file --params-file input.json
CyDecompilatorCLI.exe --auto jsonl
```

La commande **jsonl** (également **sdk stdio**) utilise le protocole dispatch_app natif du SDK compilé : une requête et une réponse par ligne. Garder stdin ouvert pour les tâches asynchrones et le débogage. **invoke** renvoie une tâche ; **sdk invoke** renvoie le résultat métier et _jobId. Utiliser **jobs**, **job JOB_ID**, **wait JOB_ID --timeout 30**, **result JOB_ID --offset 0 --length 32768** et **cancel JOB_ID** avec --auto pour suivre le travail durable, y compris depuis un autre processus CLI. Un échec reste un échec ; un délai d’attente n’autorise jamais à rejouer une action. Édition des sources, compilation et tests appellent les mêmes vrais handlers métier. La politique d’approbation du client IA externe reste applicable.

## Connecter un client MCP {#connect-an-mcp-client}

Les paquets Windows complets fournissent **CyDecompilatorCLI.exe mcp** comme serveur stdio. Les venv de développement peuvent toujours utiliser leur Python privé avec **app/tool.py mcp**. Remplacez les chemins d’exemple par votre emplacement réel :

```json
{
  "mcpServers": {
    "cydecompilator": {
      "command": "C:/Tools/CyDecompilator/CyDecompilatorCLI.exe",
      "args": ["mcp"]
    }
  }
}
```

Pour piloter la fenêtre déjà ouverte, connectez-vous à cette même instance avec le profil HTTP local choisi comme indiqué plus bas. Un **--data-dir** absolu distinct avant **mcp** crée un ordonnanceur sans interface séparé. Les projets d’analyse restent partagés : coordonnez les modifications du même projet entre clients. Installez le skill CyDecompilator fourni via **app/scripts/install_skill.py** si votre client le permet ; cela ne configure pas automatiquement MCP.

## Découvrir, soumettre, attendre et examiner {#discover-submit-wait-inspect}

Utilisez **cy_describe_operation** avant de construire les paramètres. Les opérations natives acceptent directement leurs arguments métier et renvoient leur résultat. Les outils compatibles **op_...** utilisent une enveloppe **parameters** et renvoient une tâche durable. Les outils de contrôle comme **cy_get_job** reçoivent leurs propres arguments directement :

```json
{"tool":"op_open_file","arguments":{"parameters":{"path":"C:/samples/App.dll","engine":"ilspy"}}}
```

L’identifiant de job retourné n’est pas le résultat. Interrogez **cy_get_job** jusqu’à Completed, Failed ou Cancelled, puis lisez outputs/error. Un job terminé peut contenir un résultat de compilation/test en échec ou non vérifié. Conservez les identifiants de projet, plan, reçu et capture entre opérations dépendantes. N’inventez pas d’identifiants et ne considérez pas une réponse IA comme une preuve d’exécution.

## CLI et permissions {#cli-and-permissions}

L’interpréteur privé exécute **app/tool.py list-operations** et **invoke** avec un fichier de paramètres et un délai explicite. Le contrat installé indique les besoins en réseau, lancement de processus et fichiers externes. Un client restreint doit disposer explicitement de ces permissions ; ne placez jamais de jeton dans les paramètres métier. Lire le manuel ou suivre ses liens locaux ne donne aucun droit d’exécution et ne lance aucune commande.

Consultez l’[IA](doc:ai), les [projets](doc:projects) et les [observations](doc:observations) pour les parcours correspondants.

## Se connecter à la fenêtre ouverte {#connect-to-the-open-window}

**Free est le profil MCP local par défaut.** Lancer **CyDecompilator.exe --mcp-port=8766**, puis connecter le client MCP à **http://127.0.0.1:8766/mcp**. L’adresse seule donne accès à toutes les opérations exposées, modifications comprises, sans jeton ni confirmation supplémentaire. La validation des arguments reste active. Le point d’accès utilise les mêmes tâches, projets et moteur que la fenêtre ouverte. Le port 0 choisit un port local disponible ; copier l’adresse active dans **Réglages de l’assistant IA → Options CyMCPSDK et outils externes**.

Choisir un profil dans ce panneau, enregistrer et redémarrer. Les configurations sans profil migrent vers Free ; les choix explicites sont conservés.

| Profil | Jeton | Accès aux opérations |
| --- | --- | --- |
| Free | Aucun | Toutes les opérations exposées sans confirmation supplémentaire |
| Local contrôlé | Aucun | Permissions et confirmations de l’application |
| Jeton seul | Requis | Toutes les opérations exposées sans confirmation supplémentaire |
| Protégé | Requis | Permissions et confirmations de l’application |

Les appelants Free et Local contrôlé partagent une identité locale. Pour le profil Protégé, créer un client avant de lancer la fenêtre : **CyDecompilatorCLI.exe --data-dir D:/CyDecJobs create-client --name external --permission processSpawn --permission filesystemExternal**. Conserver le jeton renvoyé dans un emplacement privé ; le fournir par **CYMCP_TOKEN** (l’ancien alias **CYTOOLS_TOKEN** est accepté) ou un en-tête HTTP Authorization Bearer. Ne jamais placer les identifiants dans les arguments métier.

Pour le CLI sur la fenêtre ouverte, utiliser **CyDecompilatorCLI.exe --connect http://127.0.0.1:8766/v1 list-operations** ou **invoke**. Free ne demande aucun jeton. Le serveur SDK écoute uniquement sur **127.0.0.1** et conserve les contrôles Host/Origin dans tous les profils.

## Découverte compacte et résultats complets {#compact-discovery-and-complete-results}

**mcp --compact** expose **cy_tools_search**, **cy_tools_describe**, **cy_tools_call**, **cy_resources_read** et **cy_resources_grep**. Rechercher une intention, charger le schéma complet puis appeler avec les arguments validés. **mcp --full** expose les opérations directes et les outils de tâches compatibles ; la découverte complète reste le mode stdio par défaut des anciens clients. Le chat intégré choisit sa découverte compacte indépendamment.

Les gros résultats temporaires utilisent des références privées. Lire leur manifeste et suivre les URI de morceaux pendant leur rétention. Une référence expirée produit une erreur et ne rejoue jamais une modification. Les résultats JSON durables survivent au redémarrage et à la rétention SDK : **cy_read_result** accepte jobId, offset et length (jusqu’à 65536 octets) et renvoie les octets en base64, leur taille totale et nextOffset. Préserver les fichiers d’une tâche arrêtée avec **cy_export_job** avant de terminer une tâche temporaire. **cy_finish_task** retire ses fichiers après l’arrêt des workers ; les enregistrements de résultats restent durables.

La ressource **cydec://operations** expose le catalogue. Le grep natif des ressources recherche les textes enregistrés sans parcourir le disque. Les opérations facultatives **workspace_grep_native** et **workspace_read_native** exigent que l’hôte active ripgrep et choisisse explicitement workspaceRoot. Elles fournissent curseurs/plages bornés et vérification de révision ; aucun dossier n’est déduit d’un prompt.

## Régler les options indépendantes {#configure-independent-options}

Ouvrir **Réglages de l’assistant IA → Options CyMCPSDK et outils externes**. Découverte compacte, cache, TTL, notifications, stockage temporaire sur disque/dossier/quota/rétention, taille des morceaux, taille en ligne, mesures de métadonnées et projection du contexte API sont indépendants. Enregistrer et redémarrer. Les valeurs initiales utilisent des morceaux de 32 Kio, 16 Kio en ligne, 16 Mio de mémoire temporaire, 128 Mio de disque temporaire et 15 minutes de rétention. Renseigner **spoolRoot** avec un dossier absolu pour choisir son disque indépendamment ; vide, il reste sous le stockage des tâches. Ces limites ne suppriment pas les résultats durables des tâches. Les mesures sont désactivées par défaut et excluent messages, résultats d’outils et identifiants. Les API utilisent une projection réglable en conservant l’historique complet ; les agents CLI gardent leur propre gestion du contexte.

## Connecter une autre application {#connect-another-application}

Seuls les serveurs configurés par l’utilisateur et les noms d’outils explicitement autorisés sont accessibles au chat intégré. La configuration contient un exécutable et ses arguments structurés, ou une URL HTTPS (HTTP seulement sur loopback), et une liste **allowedTools**. Les secrets restent dans le coffre sous **mcp:identifiant-serveur**, jamais dans le JSON. **remote_tools** renvoie les schémas approuvés ; **remote_call** appelle le véritable outil distant et conserve ses erreurs métier. **remote_resources** lit les URI explicitement approuvées ou les ressources référencées par un outil autorisé, et peut activer/lire les notifications d’un transport compatible. Le SDK suit la pagination et invalide les lectures compatibles via les notifications. Une ressource absente ou expirée n’autorise jamais à rejouer l’action initiale.

Les profils contrôlés et les identités CLI indépendantes exigent **--confirm** pour les actions destructives et appliquent les permissions déclarées. Les accès HTTP Free et Jeton seul ne demandent pas ces confirmations. L’assistant intégré exclut réglages de compte, mises à jour applicatives et actions destructives. Consulter le schéma installé avant toute opération inconnue.
