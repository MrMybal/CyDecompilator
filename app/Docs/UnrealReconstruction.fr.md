# Reconstruction Unreal — règles intégrées

Dans CyDecompilator, ouvrir **Reconstruction Unreal** dans la navigation. Choisir le profil général ou **Halo CEA Xbox 360 / UE 5.8**, puis une catégorie. Le bouton **Copier le guide de reconstruction** copie les règles affichées avec leurs références et empreintes.

Le catalogue livré dans `app/unreal_support/reconstruction-rules.json` contient 26 règles, dont 24 de méthode générale et deux propres au format/profil Halo. Les 11 catégories couvrent sources, géométrie/UV, matériaux/éclairage, animations, collisions/navigation, joueur/armes, IA, véhicules, effets/audio, campagne et validation. Les dix profils de mission conservent identités XEX et correspondances de modèles du prototype.

## Accès commun à l’interface, au CLI et à MCP

- `unreal_rules` : règles structurées, catégories, profils, limites et empreinte du catalogue.
- `unreal_guide` : mêmes données avec un guide Markdown copiable.
- Paramètres : `profile` (`generic` ou `halo-cea-x360`), `category` (vide ou identifiant renvoyé), `language` (`en` ou `fr`).
- Les opérations sont en lecture seule, sans permission réseau ni lancement de processus, et ne demandent pas de projet ouvert.
- L’agent intégré peut découvrir ces deux opérations et les consulter avant de reconstruire un jeu ; cette consultation ne satisfait pas ses conditions de validation d’une reconstruction.

Exemple CLI depuis la racine, avec un dossier de jobs distinct de l’application ouverte :

```powershell
runtime/python/Scripts/python.exe app/tool.py --data-dir data/unreal-guide-jobs invoke unreal_rules --params '{"profile":"halo-cea-x360","category":"vehicles","language":"fr"}'
```

Pour MCP, décrire `unreal_rules` avec `cy_describe_operation`, puis appeler `op_unreal_rules` avec l’enveloppe `parameters` habituelle.

## Portée

Il s’agit d’une intégration des connaissances et des profils. Les règles sont des consignes et contrôles à appliquer, sans moteur d’application automatique. Le module `modules/unreal-reconstruction` conserve extraction, imports, sources C++ et projet Unreal ; sa présence est indiquée sans exécuter son code. Le catalogue et le guide restent consultables même si ce module ou les fichiers du jeu sont absents.

Aucun jeu, asset, binaire compilé, outil d’extraction tiers ou moteur Unreal n’est copié dans le catalogue. L’intégration ne modifie pas les cartes ni les sauvegardes. Elle ne rend pas la conversion universelle : les parseurs Halo demandent une édition et un XEX adaptés. Les empreintes des références identifient l’instantané utilisé pour les règles, pas la validité du gameplay actuel. Les différences restantes d’IA, de physique et de contrôleurs Saber restent explicites.

## Tests

`app/tests/test_unreal.py` contrôle profils et filtres, traçabilité, autonomie du catalogue, erreurs d’entrée, jobs Runtime sans permissions, découverte par l’agent et transport MCP réel. Le rendu EN/FR et le rapport d’intégration sont conservés sous `data/reports/unreal-integration`.
