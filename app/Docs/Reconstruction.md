# Reconstruire, compiler et comparer

Dans **Project IDE → Reconstruction**, **Reconstruire et valider** crée un projet si
nécessaire, compile, exécute éventuellement ses tests, puis compare l’original et la
version reconstruite. Activer **Corrections IA automatiques avec historique Git**
pour utiliser le fournisseur configuré dans les réglages IA. La limite de 1 à 10
compilations comprend la première tentative. Chaque correction est enregistrée
dans le dépôt Git privé ; les réponses du modèle sont traitées uniquement comme
des modifications de sources, jamais comme des commandes de terminal.

Les fichiers ouverts sont enregistrés avant le lancement, puis bloqués en écriture
pendant la tâche. Les révisions sont vérifiées avant de corriger les fichiers. Une
réponse obsolète ou une modification extérieure interrompt la tâche ; un échec
d’écriture restaure les octets précédents. L’original reste séparé du projet produit.
Les corrections reçoivent aussi les sources JavaScript originales vérifiées par
SHA256, ou un extrait limité du désassemblage natif, pour appuyer les réparations.

| Famille | Projet reconstruit | Préparation et limites |
|---|---|---|
| .NET | Sources C# ILSpy, ressources, références disponibles et solution Visual Studio | SDK .NET requis. Choisir le projet de démarrage dans les solutions multiples. Les dépendances manquantes, protections, frameworks propriétaires et initialisations peuvent nécessiter une correction. |
| PE natif | Application EXE, DLL avec exports/ordinaux ou bibliothèque statique ; VC++ et CMake | Outils C++ Visual Studio sous Windows. Les entrées `main` récupérées reçoivent un adaptateur ; entrées inconnues, WinMain, TLS, exports de données et fonctions absentes restent des blocages explicites. Les imports nommés disponibles sont liés au démarrage ; les ressources PE sont extraites exactement et réintégrées par RC. |
| ELF natif | Code C et cible CMake | Environnement et chaîne de compilation ELF requis. Les types, conventions d’appel, imports et initialisations doivent être vérifiés. L’exécution ELF n’a pas été testée sous Linux ici. |
| Node / JavaScript / TypeScript | Sources et ressources récupérées, `package.json`, configuration et espace de travail éditables | Node.js et analyseur TypeScript privé requis. Le mode intégré vérifie la syntaxe, formate le JS et transpile TS/JSX avec source maps ; il ne fait pas une vérification complète des types. |
| Web | Projet éditable et sortie séparée, aperçu HTTP local | Les versions sont servies successivement à la même origine locale pour rejouer un scénario Chromium. Les API distantes, serveurs et secrets absents ne sont pas recréés. |
| Electron | Sources main/preload/renderer, ressources, sortie exécutable avec runtime Electron et archive ASAR | Installer Electron dans **Engines** ou choisir un runtime existant. Version et architecture doivent correspondre aux modules natifs. L’ASAR peut être distribué avec un runtime adapté ; ce parcours ne produit pas un installeur signé. |

Pour JS/Electron, `cydec.project.json` définit `kind`, `entry`, `buildScript` et
`outputDirectory`. Un script npm existant est utilisé s’il est configuré ; sa sortie
doit être un sous-dossier de `build`. L’ancienne sortie est conservée sous un autre
nom avant le lancement pour empêcher une réussite basée sur un artefact périmé.
Sans script, une nouvelle sortie est créée à chaque compilation. Un changement des
sources ou de l’artefact impose une nouvelle compilation avant **Run**. Pour
Electron, le lancement utilise l’ASAR produit ; son hash et les fichiers du dossier
`.unpacked` sont également vérifiés avant l’exécution et les comparaisons.

**Installer les dépendances npm verrouillées** lance explicitement `npm ci` avec
les scripts de cycle de vie désactivés, à partir de `package-lock.json`. Les scripts
`build` et `test` du projet sont exécutés lorsqu’ils sont demandés. Les modules
natifs peuvent encore nécessiter une reconstruction ABI. L’ASAR conserve les modules
installés et place les fichiers `.node`, `.dll` et `.exe` dans son dossier `.unpacked`.
Les limites du projet reconstruit restent 10 000 fichiers, 128 Mio et 16 Mio par fichier ;
l’historique Git a ses propres limites documentées dans le guide principal.

## Scénarios et preuves

**Utiliser le scénario d’investigation** reprend les étapes visuelles, le réseau,
l’entrée standard et les fichiers de départ configurés dans Investigation. Le
champ JSON permet plusieurs scénarios, jusqu’à dix, et des commandes de lancement
spécifiques. Un exécutable reconstruit doit rester relatif au projet ; le runtime
Electron ou Chromium et l’exécutable original sont des chemins absolus.

```json
[
  {
    "name": "Exporter le rapport",
    "timeout": 40,
    "checks": {"stderr": false},
    "observation": {
      "driver": "electron",
      "network": true,
      "settleMs": 200,
      "steps": [
        {"action": "click", "selector": "#export"},
        {"action": "assertText", "selector": "#result", "text": "Terminé"},
        {"action": "snapshot"}
      ]
    }
  }
]
```

Par défaut, tous les critères sont comparés : `stdout`, `stderr`, `exitCode`,
`files`, `network`, `graphics`. Dans cet exemple, `stderr` est explicitement exclu
pour les journaux internes du runtime. Le rapport conserve ces différences et
indique les critères réellement validés. Les chemins `file://` appartenant aux deux
versions Electron sont rapprochés uniquement dans les URL d’application ; les
captures brutes, textes visibles et autres origines restent inchangés. Désactiver
ce rapprochement avec `normalizeApplicationPaths: false`.

Les états principaux sont **Compilé ; comportement non vérifié**, **Le comportement
diffère**, **Les scénarios enregistrés concordent**, **Échec de la compilation** et
**Reconstruction bloquée**, ou **Échec des tests du projet**. Une bibliothèque exige un exécutable de test ; le projet
TypeScript original exige un lanceur approprié. Sans ce scénario, une compilation
réussie reste non vérifiée. L’accord des scénarios concerne seulement les
interactions et critères enregistrés, et ne prouve pas une équivalence générale.

Les sorties, diagnostics, corrections motivées, commits Git et identifiants des
captures sont conservés dans `reconstruction/latest.json` et
`reconstruction/runs/<id>.json` du projet d’analyse. **Examiner la comparaison
enregistrée** ouvre les preuves dans Investigation. Une annulation conserve le
rapport et arrête les processus détenus par la tâche.

Les opérations partagées entre GUI, CLI et MCP sont `reconstruction_run`,
`reconstruction_status`, `workspace_create`, `workspace_dependencies` et
`workspace_execute`. Les tests reproductibles sont dans
`tests/test_reconstruction.py` : .NET, EXE et ressources, DLL et ordinaux,
JS/TS, ASAR, Electron avec preload/IPC, Chromium, corrections et conflits.
