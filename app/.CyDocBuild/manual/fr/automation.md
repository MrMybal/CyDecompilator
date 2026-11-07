---
id: automation
title: MCP, CLI et référence des opérations
description: Connecter un client MCP ou CLI et suivre le protocole des opérations et tâches.
section: IA et automatisation
parent: ai
order: 14
sourceRevision: 3
---

Interface, CLI et MCP exposent les mêmes opérations métier Runtime. Ouvrez les [opérations avancées](doc:automation) pour consulter contrats installés, formulaires de paramètres, permissions et sorties. Ce catalogue actif fait référence pour votre version ; ne figez pas un nombre d’opérations dans un guide ou un prompt IA.

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

Si l’interface ou un autre serveur possède déjà la base des tâches, choisissez un dossier de jobs absolu distinct avec **--data-dir**, placé avant **mcp** dans les arguments. Les projets d’analyse restent partagés : coordonnez les modifications du même projet entre clients. Installez le skill CyDecompilator fourni via **app/scripts/install_skill.py** si votre client le permet ; cela ne configure pas automatiquement MCP.

## Découvrir, soumettre, attendre et examiner {#discover-submit-wait-inspect}

Utilisez **cy_describe_operation** avant de construire les paramètres. Les outils métier **op_...** utilisent une enveloppe **parameters**. Les outils de contrôle comme **cy_get_job** reçoivent leurs propres arguments directement :

```json
{"tool":"op_open_file","arguments":{"parameters":{"path":"C:/samples/App.dll","engine":"ilspy"}}}
```

L’identifiant de job retourné n’est pas le résultat. Interrogez **cy_get_job** jusqu’à Completed, Failed ou Cancelled, puis lisez outputs/error. Un job terminé peut contenir un résultat de compilation/test en échec ou non vérifié. Conservez les identifiants de projet, plan, reçu et capture entre opérations dépendantes. N’inventez pas d’identifiants et ne considérez pas une réponse IA comme une preuve d’exécution.

## CLI et permissions {#cli-and-permissions}

L’interpréteur privé exécute **app/tool.py list-operations** et **invoke** avec un fichier de paramètres et un délai explicite. Le contrat installé indique les besoins en réseau, lancement de processus et fichiers externes. Un client restreint doit disposer explicitement de ces permissions ; ne placez jamais de jeton dans les paramètres métier. Lire le manuel ou suivre ses liens locaux ne donne aucun droit d’exécution et ne lance aucune commande.

Consultez l’[IA](doc:ai), les [projets](doc:projects) et les [observations](doc:observations) pour les parcours correspondants.
