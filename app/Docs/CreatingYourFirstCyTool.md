# Ajouter une opération à CyDecompilator

L’hôte Python conserve les contrats applicatifs de jobs, sessions et configurations.
Le registre natif, le chat et MCP sont fournis par [CyMCPSDK](CyMCPSDK.md).
Aucun générateur ou paquet Python de l’ancien SDK n’est nécessaire.

## Préparer le runtime

Depuis la racine, avec Python 3.11 et les outils C++20/CMake :

```powershell
runtime/python/Scripts/python.exe -m pip install -r app/requirements.txt
runtime/python/Scripts/python.exe app/scripts/build_mcp_sdk.py
runtime/python/Scripts/python.exe app/tool.py describe
runtime/python/Scripts/python.exe app/tool.py list-operations
runtime/python/Scripts/python.exe app/tool.py describe-operation list_projects
runtime/python/Scripts/python.exe app/tool.py invoke list_projects --params-file params.json
```

`params.json` contient `{}`. La dernière commande retourne un job terminé et ses
résultats JSON. Les diagnostics restent sur stderr. Utiliser des fichiers JSON
évite les différences d’échappement entre shells.

## Ajouter une opération

Déclarer son identifiant stable, sa description, ses schémas et ses permissions
dans `app/operations.py`, puis générer `app/CyTool.json` avec `app/build_manifest.py`.
Employer `additionalProperties: false` pour détecter les fautes de frappe.
Enregistrer le vrai handler métier dans `app/tool.py`; tout handler manquant
empêche le démarrage. Consulter `app/AGENTS.md` pour les effets, la progression,
l’annulation, les confirmations et les traductions.

Le chat, le CLI et le serveur MCP utilisent ce même registre. Le contrat durable
`op_<operation>` retourne un job consultable avec `cy_get_job`; les noms directs
exécutent les mêmes handlers. `debug_start` démarre un job contrôlable en parallèle.

## Lancer et distribuer

```powershell
runtime/python/Scripts/python.exe app/tool.py mcp --compact
runtime/python/Scripts/python.exe app/tool.py mcp --full
```

Voir [CyMCPSDK.md](CyMCPSDK.md) pour la configuration absolue du client MCP,
l’authentification, les appels sur une instance ouverte et les options indépendantes.
Les scripts de packaging compilent le SDK et livrent la DLL, sa provenance et les
sources nécessaires à sa reconstruction. Aucun chemin privé de développement ni
ancien wheel ne doit être requis sur la machine destinataire.
