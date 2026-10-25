<p align="center"><img src="app/assets/logo-256.png" width="160" alt="CyDecompilator"></p>

<h1 align="center">CyDecompilator</h1>

<p align="center">
Décompilateur multi-moteurs assisté par IA — Windows, Linux · x86, x64, ARM64 · .NET, Java, Android, Python, shaders
<br>
<img src="https://img.shields.io/badge/version-1.4.0-1f4e8c" alt="version 1.4.0">
<img src="https://img.shields.io/badge/licence-GPL--3.0-1f4e8c" alt="GPL-3.0">
</p>

[English](README.md) · **Français**

CyDecompilator ouvre presque n'importe quel binaire, montre son code reconstruit, et une IA aide à
le comprendre, à le renommer et à le réécrire en vrai code source. Il fonctionne aussi comme
serveur MCP, pour qu'une IA (Claude Code, Codex…) l'utilise directement.

## Lancer

- **Windows** : double-cliquer sur `CyDecompilator.exe`.
- **Linux** : `./CyDecompilator.sh` (nécessite un `runtime/python` créé sous Linux, voir
  [`app/README.md`](app/README.md)).

L'interface est en anglais par défaut. Menu latéral **Options** → *Language* : English, Français,
Deutsch, Español, Italiano, Português, Русский, 简体中文, 日本語, 한국어 (changement immédiat,
sans redémarrage). L'assistant IA répond dans la langue choisie.

L’interface utilise **CyUI** : navigation permanente à gauche, barres d’outils avec infobulles,
explorateur et code redimensionnables, état des tâches en bas. **Options** propose cinq thèmes
(gris moyen, gris clair, nuit ambrée, violet, bleu nuit), une densité compacte ou confortable
et la taille du texte. Les anciennes préférences de thème sont reprises automatiquement.
Sur une petite fenêtre, l’IA reste accessible depuis son entrée dédiée du menu et
les détails de la fonction depuis un onglet près du code.

## Ce qu'il sait ouvrir

| Fichier | Moteur | Résultat |
|---|---|---|
| `.exe`, `.dll`, ELF / `.so` Android (x86, x64, ARM64) | **CyDecompilator C** (intégré) | C structuré et recompilable, sans dépendance |
| `.exe`, `.dll`, `.so`, ELF, Mach-O, firmware brut | **Ghidra** | pseudo-code C (prioritaire s'il est installé) |
| `.exe`, `.dll`, ELF (x86, x64, ARM64) | **Désassembleur intégré** (Capstone) | assembleur annoté, appels, chaînes, imports |
| Assembly .NET (`.dll`, `.exe` managés) | **ILSpy** | C# |
| `.class`, `.jar` | **Vineflower** | Java |
| `.apk`, `.dex` (et `.jar`) | **JADX** | Java + AndroidManifest |
| `.pyc` | **Python** (xdis, uncompyle6, decompyle3) | source jusqu'à Python 3.8, bytecode pour toutes les versions |
| Shaders DXBC (`.cso`, `.fxc`), DXIL SM6, SPIR-V (`.spv`) | **Moteur shader de CyDecompilator** | HLSL (SM4/5 et SM6), GLSL |

Le format est reconnu à partir du contenu du fichier, pas de son extension.

## Le décompilateur C intégré

- x86 (cdecl, stdcall, thiscall, helpers MSVC), x64 (Win64, System V) et ARM64 (AAPCS64,
  Windows ARM64), fichiers PE et ELF.
- `if` / `else`, boucles, `switch` (tables de saut), flottants (SSE, x87, VFP), SIMD (SSE et
  NEON exprimés en intrinsèques SSE), prototypes des fonctions appelées déduits de leur code.
- Onglet *Program* : *Exported functions* / *This function and its callees* écrivent un fichier
  `.c` unique fait pour être recompilé (MSVC, clang) : variables globales initialisées depuis
  le binaire, constantes intégrées, imports reliés.
- Vérifié en recompilant le C produit et en comparant son exécution avec l'original (x86/x64 :
  120/120 ; ARM64 en émulation : 120/120) ; le C de vrais binaires Windows (cmd.exe, msvcrt,
  python311, vcruntime ARM64…) recompile sans erreur.

## Applications Windows (x86, x64, ARM64, DLL)

- **Symboles PDB** : le PDB d'un EXE/DLL est cherché dans les dossiers locaux puis téléchargé
  depuis le serveur de symboles Microsoft (vérifié GUID + âge, mis en cache dans
  `data/symbols`). Les vrais noms de fonctions et de classes apparaissent partout.
- **Détails de l'exécutable** (onglet *Program*) : protections (ASLR, DEP, CFG…), version,
  manifeste, outils de compilation (Rich header), exports, callbacks TLS, entropie des sections,
  overlay, signature, et ce qui a servi à le construire (Go, Rust, Delphi, Electron, Nuitka…).
- **Contenu embarqué** : bouton *Extract* pour les bundles **PyInstaller**, les applications
  **.NET single-file**, les fichiers **UPX** et les archives zip ajoutées. Chaque fichier extrait
  s'ouvre comme un nouveau projet.

## Premiers pas

1. Menu **Engines** : installer les moteurs voulus (*Install*). Ils sont téléchargés depuis
   leurs sources officielles et vérifiés. Un Java 21+, un .NET ou un Ghidra déjà présents
   peuvent être utilisés via *Browse* / *Use*.
2. Menu **Workspace** : *Open file...*, **Ctrl+O** ou coller un chemin et Entrée.
3. Cliquer sur une fonction à gauche : son code s'affiche au centre. Double-clic sur un nom pour
   y aller, clic droit pour renommer ou chercher, boutons `<` `>` pour revenir.
4. Panneau **AI** à droite ou menu **AI** : choisir **Autonomous workflow** pour une tâche
   complète, **Conversation** pour poser une question, ou **Function** pour les actions ciblées :
   - **Explain** : explication de la fonction ;
   - **Suggest names** (+ *Apply*) : noms parlants pour la fonction et ses variables ;
   - **Convert to source** : réécriture en vrai code (C, C++, C#, Java, Python, Rust, Go, HLSL,
     GLSL…), vérification par compilation et réparation automatique des erreurs ;
   - **Conversation → Send** : questions libres ; l'assistant parcourt lui-même le programme avant de répondre ;
   - **Name functions** : nomme en lot les fonctions générées (`FUN_*`, `sub_*`).

## Éditer, reconstruire et tester un projet

L’onglet **Historique Git** du Project IDE conserve les versions locales du projet reconstruit.
Git doit être installé et accessible dans le PATH. Saisir une description, puis **Enregistrer une
version Git** sauvegarde les sources, ressources et dépendances locales. **Comparer avec les
sources enregistrées** affiche les modifications avant de choisir **Restaurer cette version**.
La restauration sauvegarde d’abord l’état actuel dans un commit récupérable, puis crée un nouveau
commit de restauration. Les fichiers ouverts sont rechargés ; enregistrer leurs modifications avant
la comparaison. Les copies .NET affichent le commit des sources lorsqu’une version correspondante
a été enregistrée avant leur création.

Le dépôt Git local est conservé dans les données d’analyse, séparément d’un éventuel dépôt déjà
présent dans les sources. Les dossiers de compilation, caches et métadonnées Git sont exclus ;
les fichiers binaires sont versionnés mais leurs différences ne sont pas affichées comme du texte.
Les versions sont limitées à 4 000 fichiers, 128 Mio au total et 32 Mio par fichier. La restauration
vérifie que les sources n’ont pas changé depuis l’aperçu et protège l’application originale.

Après avoir ouvert une application, l’onglet **Project IDE** propose **Create source project** :

- **.NET** : projet C# ILSpy, ressources récupérées et solution `.sln` ouvrable dans Visual Studio.
- **PE/ELF natif** : code C des fonctions exportées ou d’une fonction sélectionnée et de ses appels,
  cible EXE, DLL ou bibliothèque statique, projet `.vcxproj`, solution `.sln` et configuration CMake.
  Les entrées récupérées, imports, exports et ressources sont reconstruits ; les éléments inconnus
  restent des blocages explicites. ELF demande une chaîne de compilation et un environnement adaptés.
- **JavaScript, TypeScript, web et Electron** : sources et ressources éditables, configuration de
  compilation, sorties séparées et archive ASAR pour Electron. Les dépendances et le runtime doivent
  être disponibles ; les modules natifs exigent une version et une architecture compatibles.

**Project IDE → Reconstruction → Reconstruire et valider** enchaîne la création du projet,
la compilation, les tests optionnels et les comparaisons avec l’original. Activer les corrections IA
pour effectuer plusieurs tentatives, conservées dans Git, jusqu’à la limite choisie. Les scénarios
d’investigation peuvent être repris pour comparer interfaces, fichiers, sorties et réseau.
Le rapport distingue une compilation réussie d’un comportement validé sur les scénarios enregistrés.
Voir le [guide de reconstruction](app/Docs/Reconstruction.md) pour la configuration et les limites.

L’explorateur de solution permet d’ouvrir plusieurs fichiers dans des onglets éditables avec coloration
syntaxique. **Save all**, **Build**, **Rebuild**, **Test** et **Run** utilisent des tâches annulables.
Les erreurs de compilation figurent dans **Problems** ; cliquer dessus ouvre le fichier à la ligne indiquée.
**Open source project** rattache aussi un dossier C#, VC++ ou CMake existant. Une modification externe
du fichier empêche son écrasement ; les onglets modifiés sont protégés à la fermeture.
Les solutions `.sln`/`.slnx` contenant plusieurs projets sont prises en charge : **Build / startup project**
choisit le projet à compiler ou démarrer. **Entire solution** compile ou teste la solution entière ;
sélectionner un projet C# exécutable pour **Run**.
**Search source project** recherche dans les fichiers enregistrés, avec options de casse et de mot entier ;
un clic sur un résultat ouvre sa ligne. **Filter files** filtre l’explorateur et **Go to line** navigue dans
le fichier actif. **Reload file** recharge un fichier modifié sur disque, après confirmation si des
modifications non enregistrées doivent être abandonnées.

La compilation C# nécessite un **SDK .NET**, distinct du runtime installé pour ILSpy. Le C natif utilise
les outils C++ de Visual Studio sous Windows, ou CMake et un compilateur ailleurs. **Test** nécessite
des tests réellement définis ; **Run** d’une bibliothèque native nécessite un exécutable de test.
L’éditeur C# utilise **Roslyn**, fourni par un **SDK .NET 8 ou plus récent** avec ses composants
dotnet-format. **Compléter (Ctrl+Espace)** propose les membres accessibles du type et leurs signatures ;
cliquer sur une suggestion l’insère avec possibilité d’annuler. **Aller à la définition (F12)** retrouve
les déclarations, y compris dans un autre fichier ou un projet C# référencé. **Symboles C#** liste les
types et les membres du projet. **Assistance C#** affiche les diagnostics pendant l’édition et permet
de lancer l’analyse manuellement. Les modifications C# non enregistrées sont prises en compte sans
modifier les fichiers sur disque ; une suggestion périmée est rejetée si le code ou le curseur a changé.
**Aperçu du renommage sémantique** renomme le symbole choisi et ses références dans les fichiers/projets
concernés, sans toucher les homonymes. **Rechercher les références du symbole** affiche ses usages.
**Aperçu du formatage C#** propose le formatage Roslyn. Examiner les différences puis **Appliquer l’aperçu
aux fichiers ouverts** : les modifications restent dans l’éditeur, sont annulables et doivent être enregistrées.
Une modification des sources ou des buffers invalide l’aperçu avant toute application.

Les références restaurées des packages et les assemblies référencés sont utilisés lorsqu’ils sont
disponibles. Les étapes de compilation personnalisées, les propriétés conditionnelles, les analyseurs
et les sources générées peuvent demander une compilation pour un diagnostic complet ; le panneau
signale les références manquantes. Le helper d’édition est compilé localement sans téléchargement de
package. **Évaluer le projet avec MSBuild** exécute explicitement la résolution des références et prend en
compte les imports, propriétés conditionnelles et éléments Compile du projet. Les requêtes d’édition
suivantes lisent ce modèle sans relancer les targets ; une modification de la configuration ou des fichiers
du projet nécessite une nouvelle évaluation. Les projets multi-cibles utilisent leur première cible.
Les services sémantiques des autres langages restent à développer.

Pour modifier directement une fonction, choisir **Edit function / patch** dans Workspace, ou
**Function patch** dans Project IDE :

- **.NET** : **Load .NET methods**, sélectionner la méthode, puis **Edit declaring type** pour ouvrir
  son C# dans l’éditeur. **Build and verify method patch** recompile le projet et remplace uniquement
  le corps IL choisi dans l’assembly original. La nouvelle méthode peut être plus grande ; variables
  locales, branches, chaînes, appels internes et blocs try/catch sont pris en charge. Les lambdas, closures,
  fonctions locales, méthodes async et itérateurs sont pris en charge : leurs dépendances générées sont
  ajoutées sous des noms isolés, puis affichées dans l’aperçu. Choisir la méthode source plutôt qu’une
  fonction générée. Les corps des autres méthodes et les tokens existants sont vérifiés inchangés,
  même après plusieurs remplacements. Si plusieurs sorties existent, préciser l’assembly recompilé relatif au
  projet. Le SDK .NET et le helper dnlib 4.5.0, restauré automatiquement depuis NuGet officiel avec empreinte
  verrouillée, sont utilisés. **Importer les nouveaux membres .NET référencés** permet d’ajouter les helpers,
  types et champs compatibles utilisés par le remplacement. Les nouveaux types gardent leurs constructeurs,
  propriétés et événements. L’aperçu liste chaque ajout. Ajouter un champ d’instance à un type existant ou
  modifier son initialiseur reste réservé à une reconstruction complète, comme les changements de signature,
  images mixtes ou ReadyToRun. Les dépendances incompatibles ou dépassant les limites sont refusées.
  Une signature de nom fort doit être conservée par une reconstruction signée, ou supprimée explicitement
  via la case proposée ; sa suppression peut casser les dépendances. **Générer les symboles de la copie
  modifiée** produit un PDB portable correspondant aux méthodes importées.
- **PE natif x86/x64** : modifier son C, conserver sa signature et sa convention d’appel, puis
  **Compile and verify patch**. Les fonctions autonomes sans appels externes, réadressages ni métadonnées
  d’unwind sont acceptées si leur code tient dans l’emplacement d’origine. Clang (ou LLVM dans Visual Studio)
  est requis. Les cas incompatibles sont refusés.
  Le mode **Lier une fonction native plus grande avec appels et données d’exception** ajoute une section
  PE et redirige l’entrée d’origine : helpers, appels à des fonctions/imports existants, données, relocalisations
  ASLR et tables d’exception x64 sont liés. Les symboles connus sont résolus automatiquement ; le champ JSON
  permet d’associer un nom C à l’adresse d’une fonction ou d’un import existant. L’entrée doit fournir cinq
  octets complets, et le PE doit avoir un emplacement d’en-tête libre. CFG, nouveau TLS, symboles externes
  non résolus et relocalisations incompatibles nécessitent un lien complet.

**Write modified copy** crée une copie séparée avec un reçu SHA-256 ; l’original et les sorties existantes
ne peuvent pas être écrasés. Pour .NET, garder le nom du fichier original dans un nouveau dossier copie
également la configuration d’exécution et les dépendances produites par la compilation, si elles n’existent
pas déjà. Enregistrer puis préparer à nouveau le remplacement après un changement des sources.
**Analyze modified copy** permet de réouvrir le résultat. Une compilation réussie ne prouve pas
la compatibilité ABI ni l’équivalence du comportement ; une signature Authenticode existante est invalidée.

**Saved modified copies** retrouve les copies déjà créées, y compris après avoir relancé le logiciel.
**Run modified copy** lance la copie choisie avec ses arguments et une durée maximale réglable de 1 à
900 secondes. Les empreintes de l’exécutable et des dépendances copiées sont revérifiées avant le lancement.
Les sorties standard et d’erreur des compilations et des applications apparaissent pendant leur exécution.
**Cancel** et le délai maximal arrêtent également les processus enfants. Une DLL doit passer par un programme
de test ; elle n’est pas chargée dans le décompilateur. Un statut réussi indique un code de sortie nul,
sans garantir que le comportement est correct. La console capture la sortie ; elle ne fournit pas encore
de saisie interactive au programme. Le runtime .NET correspondant à l’application doit être installé.

Le panneau **Débogueur** permet maintenant de déboguer le projet .NET recompilé. Installer **NetCoreDbg**
depuis ce panneau ou l’onglet des moteurs, sélectionner le projet C# de démarrage, puis **Déboguer (F5)**.
Les sources sont enregistrées et recompilées en Debug avec leurs symboles PDB avant le lancement.
**F9** pose ou retire un point d’arrêt à la ligne du curseur dans un fichier enregistré ; les points d’arrêt
restent disponibles après un redémarrage. **F5** poursuit l’exécution, **F10** avance sans entrer dans
la fonction, **F11** entre dans la fonction, **Maj+F11** en sort et **Maj+F5** arrête le débogage.
Le panneau affiche la pile d’appels, les variables locales et les membres des objets. Cliquer sur un cadre
de pile ouvre sa ligne source ; la console de débogage affiche les sorties de l’application.

Les sources sont en lecture seule pendant la session : arrêter le débogage pour modifier et recompiler.
L’arrêt, l’annulation, le délai maximal et la fermeture du logiciel arrêtent aussi les processus enfants.
Un SDK .NET 8+ et le runtime de l’application sont nécessaires. Cette étape couvre les projets exécutables
.NET Core recompilés avec PDB portable ; les bibliothèques nécessitent un programme de test.
**Déboguer la copie modifiée** lance directement une copie .NET préparée avec ses symboles, sans la
recompiler. Les points d’arrêt, variables et machines d’état async utilisent les correspondances régénérées
des méthodes importées. Les méthodes non remplacées restent sans correspondance source régénérée.
Les sources et empreintes de la copie/dépendances doivent toujours correspondre au reçu ; conserver le
nom d’assembly original dans un nouveau dossier. Le débogage natif et .NET Framework restent à ajouter.
La console ne fournit pas de saisie interactive ni de modification des variables.

Les vérifications incluent des applications de test WinForms et WPF avec ressources intégrées, BAML,
dépendance locale et noms courts : décompilation, reconstruction, exécution et réinjection sont exercées.
Les dépendances locales sont copiées dans le projet exporté avec des HintPath relatifs. Les fichiers XAML
sont éditables lorsqu’ils sont présents ; cela ne garantit pas la récupération de toutes les interfaces
ou protections d’applications tierces obfusquées.

## Examiner les preuves et comparer deux versions

L’onglet **Investigation** permet maintenant d’analyser un dossier JavaScript/Electron,
une archive ASAR ou des fichiers JS/TS/HTML. Installer l’analyseur JS depuis cet onglet
(Node.js requis), puis rechercher une fonctionnalité, un canal IPC ou une URL : les
résultats relient fichiers, fonctions, preload, ressources et appels avec leurs preuves.
Les source maps locales et captures HAR importées complètent ces rapprochements.

Pour le natif, sélectionner une fonction analysée avec Ghidra puis **Examiner la fonction
native sélectionnée** : types, sites d’appel, instructions et dépendances de valeurs.

Dans **Comportement des versions**, capturer deux exécutables avec les mêmes entrées et
fichiers initiaux pour comparer sorties, codes de retour et fichiers créés/modifiés/supprimés.
Ouvrir **Scénario réseau et graphique** pour enregistrer les connexions TCP et rejouer des
étapes sur les contrôles Windows ou un rendu Chromium/Electron (Node.js 22+). La comparaison
inclut les requêtes HTTP du rendu, la console, les états graphiques et les captures d’écran.
**Écrans capturés** affiche les versions côte à côte. Les résultats incomplets et limites
du périmètre sont affichés ; les fichiers extérieurs au dossier de travail restent hors observation.

Voir le [guide d’investigation](app/Docs/Investigation.md) pour les limites et le mode d’emploi.

## Choisir l'IA

Onglet **AI assistant settings** :

- **Claude Code**, **Codex**, **Antigravity**, **OpenCode** : utilisent le compte déjà connecté
  dans ces programmes ; aucune clé à saisir. Ils sont lancés en lecture seule.
- **Anthropic**, **OpenAI**, **OpenRouter**, **serveur compatible OpenAI** (LM Studio, vLLM…),
  **Ollama** : clé d'API (enregistrée chiffrée avec DPAPI sous Windows) ou URL locale.

Le code envoyé à l'IA est celui de la fonction étudiée et ce que l'assistant demande via ses
outils. Avec un fournisseur en ligne, ce code quitte la machine.

## Utiliser depuis une IA (MCP)

```
claude mcp add cydecompilator -- "<dossier>\runtime\python\Scripts\python.exe" "<dossier>\app\tool.py" mcp
```

Les opérations métier déclarées sont disponibles, dont l'analyse, la reconstruction,
la compilation, Git, la réinjection, le débogage .NET et les comparaisons réseau/graphiques.
Le [guide MCP et IA](app/Docs/AIIntegration.md) détaille la connexion et les parcours.
Un [skill dédié `cydecompilator`](app/skills/cydecompilator/SKILL.md) est livré :

```powershell
runtime/python/Scripts/python.exe app/scripts/install_skill.py
```

Il installe les instructions dans le dossier de skills de Codex ; la connexion MCP
se configure séparément. Les tests vérifient le catalogue complet et des parcours
réels via MCP ; ils ne certifient pas toutes les combinaisons de moteurs et d'options.

Le panneau **AI** propose aussi **Lancer la tâche autonome** : choisir le parcours,
donner l'objectif et laisser l'assistant analyser, corriger, compiler et tester.
Les outils MCP `ai_agent` et `ai_agent_status` offrent le même mode, avec suivi,
reprise, sauvegardes Git et validation obligatoire avant de conclure.

## Mises à jour

Onglet *Engines*, section *Application updates* : *Check for updates* interroge les
[releases](https://github.com/MrMybal/CyDecompilator/releases) de ce dépôt, *Download and verify*
prépare la nouvelle version (empreinte SHA-256, identité, compilation), *Apply update* l'active en
gardant l'ancienne (*Restore previous version*). `data/` n'est jamais remplacé. Tant que le
dépôt est privé, il faut un jeton GitHub en lecture (champ *GitHub token* ou variable
d'environnement `GITHUB_TOKEN`).

## Où sont les choses

- `data/projects/` : un dossier par fichier ouvert (analyse, code en cache, renommages,
  commentaires, résultats IA).
- `data/settings/` : préférences, réglages IA, clés et jetons chiffrés.
- `data/logs/` : journal (aussi visible dans l'onglet *Application log*).
- `runtime/` : Python privé, moteurs téléchargés, mises à jour préparées.
- [`app/README.md`](app/README.md) : guide développeur (architecture, tests, releases).

## Limites connues

- Python ≥ 3.9 : pas de décompilateur libre complet ; bytecode + reconstruction par l'IA.
- DXIL : les bibliothèques de shaders (`lib_6_x`, raytracing) ne montrent que leur première fonction.
- Archives PyInstaller chiffrées (`--key`) et installeurs NSIS/Inno : détectés, pas extraits.
- Décompilateur C intégré : peu de reconstruction de types (structures vues comme
  `*(type *)(p + décalage)`) ; en ARM64 les paramètres entiers sont listés avant les flottants.
- Les gros binaires prennent du temps sous Ghidra ; le nombre de fonctions décompilées pendant
  l'analyse est réglable (onglet *Engines*).

## Licence

[GPL-3.0](LICENSE). Les moteurs téléchargés gardent leur propre licence (affichée dans l'onglet
*Engines* et dans *Options* → *Licenses*).

Ne décompiler que des logiciels que l'on a le droit d'analyser.

### Règles de reconstruction Unreal

La page **Reconstruction Unreal** expose les 26 règles du prototype Halo Anniversary et les dix profils de campagne. Les mêmes données sont accessibles depuis le CLI, MCP et l’agent intégré. La conversion reste dans le module séparé. [Guide et limites](app/Docs/UnrealReconstruction.fr.md).
