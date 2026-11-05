# Prototype autonome et intégration native

Le parcours utilisateur est désormais intégré dans **Portage Xbox** de CyDecompilator.
Le code livré est sous `app/cydec/xbox.py`, `app/xbox_ui.py` et `app/xbox_support/`.
Les opérations `xbox_*` utilisent le Runtime commun, ses permissions, son annulation
et ses journaux. Voir `app/Docs/XboxPorting.fr.md` pour les méthodes et problèmes
rencontrés. Le présent dossier conserve le prototype et ses anciens projets de jeu ;
ils peuvent être rattachés depuis l'application sans les déplacer.

Le package `xbox_native` du prototype reste indépendant, Python 3.11+, sans import
depuis `app`, sans manifeste MCP et sans modification de CyDecompilator.
Les fonctions exposées dans `formats.py`, `disc.py` et `backend.py` peuvent être
appelées directement ou via `python -m xbox_native`.

| Opération | Entrée | Résultat |
|---|---|---|
| `inspect` | XBE ou XEX2 | Identité, architecture, adresses, imports, blocages |
| `prepare` | Fichier, dossier, ISO, ZIP contenant une ISO | Nouveau workspace et exécutable préservé |
| `extract-assets` | ISO XDVDFS | Nouveau dossier de données et SHA-256 de chaque fichier |
| `export-xbe` | Workspace Xbox | Sections binaires et adresses d'origine |
| `decompile-xbe` | Workspace Xbox + Ghidra | Fonctions en pseudocode C |
| `analyse` | Workspace Xbox 360 + XenonAnalyse | Tables de sauts candidates |
| `probe` | Workspace Xbox 360 + pont natif | Image, imports, helpers vérifiés |
| `configure` | Workspace Xbox 360, profil optionnel | TOML de traduction, sans écrasement |
| `translate` | Workspace Xbox 360 + moteur + contexte PPC | C++ statique, diagnostics et blocages |
| `audit` | Workspace Xbox 360 + image analysée | Sites non résolus avec adresses et `.pdata` |

Les scripts `check_translation.py` et `verify_halo_leaf.py` sont des vérifications
de développement séparées ; le second exécute un harnais natif particulier.
`verify_control_flow.py` utilise uniquement un XEX synthétique créé localement.
`package_cpu.py` conserve une archive native et les preuves d'un essai de lien,
y compris lorsque le linker refuse les imports console non implémentés.

`setup_rexglue.py` installe séparément le SDK officiel 0.10.0, après vérification
du téléchargement. `rex_project.py` prépare, compile et lance un projet natif
indépendant, avec données utilisateur persistantes sous son dossier `data/` et
journaux par tentative sous `runs/`. Il vérifie l'identité du XEX lors du build et
du lancement. Le profil Halo est limité au SHA-256 testé. `rex_guard_branches.py`
conserve comme fatals deux branchements de cette image vers une instruction
illégale, au lieu des retours silencieux émis par cette version du SDK.

Les sorties structurées portent `schema_version: 1`. L'identité stable d'un jeu
analysé est le SHA-256 de l'exécutable, associé au Title ID lorsqu'il existe. Un
profil ne s'applique jamais au seul nom du jeu. Chaque tentative externe conserve
son répertoire, ses arguments, sa durée, son journal et son code de sortie.

`native_game_ready` reste faux dans cette version, y compris après une traduction,
une compilation d'objets ou le test d'une fonction réussi. Une UI future doit afficher
séparément préparation, analyse, traduction, compilation, lien et scénarios validés.
Un champ d'état positif d'une étape ne doit pas être réinterprété comme une
compatibilité du jeu.

Pour intégrer le module, adapter les sous-processus au gestionnaire de jobs et à
l'annulation de CyDecompilator, déclarer les capacités réseau/processus nécessaires,
versionner les moteurs séparément et faire passer les textes UI par la localisation
de l'application. Ces raccordements sont fournis par la version sous `app/` ; les
anciens scripts du prototype ne deviennent pas eux-mêmes des handlers du Runtime.
