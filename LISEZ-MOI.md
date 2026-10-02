<p align="center"><img src="app/assets/logo-256.png" width="160" alt="CyDecompilator"></p>

# CyDecompilator

Décompilateur multi-moteurs assisté par IA. Il ouvre presque n'importe quel binaire, montre son
code reconstruit, et une IA aide à le comprendre, le renommer et le réécrire en vrai code source.

## Lancer

- **Windows** : double-cliquer sur `CyDecompilator.exe`.
- **Linux** : `./CyDecompilator.sh` (nécessite un `runtime/python` créé sous Linux, voir `app/README.md`).

L'interface est en anglais par défaut ; le français se choisit dans l'onglet **Options**.

## Ce qu'il sait ouvrir

| Fichier | Moteur | Résultat |
|---|---|---|
| `.exe`, `.dll`, `.so`, ELF, Mach-O, firmware brut | **Ghidra** | pseudo-code C |
| `.exe`, `.dll`, ELF / `.so` Android (x86, x64, ARM64) | **Décompilateur C intégré** (CyDecompilator C) | C recompilable, sans dépendance (Ghidra reste prioritaire s'il est installé) |
| `.exe`, `.dll`, ELF (x86, x64, ARM64) | **Désassembleur intégré** (Capstone) | assembleur annoté, appels, chaînes, imports |
| Assembly .NET (`.dll`, `.exe` managés) | **ILSpy** | C# |
| `.class`, `.jar` | **Vineflower** | Java |
| `.apk`, `.dex` (et `.jar`) | **JADX** | Java + AndroidManifest |
| `.pyc` | **Python** (xdis, uncompyle6, decompyle3) | source jusqu'à Python 3.8, bytecode pour toutes les versions |
| Shaders DXBC (`.cso`, `.fxc`), DXIL SM6, SPIR-V (`.spv`) | **Moteur shader de CyDecompilator** | HLSL (SM4/5 et SM6), GLSL |

Le format est reconnu à partir du contenu du fichier, pas de son extension.

## Applications Windows (x86, x64, DLL)

- **Symboles PDB** : le PDB d'un EXE/DLL est cherché dans les dossiers locaux puis téléchargé depuis le
  serveur de symboles Microsoft (vérifié GUID + âge, mis en cache dans `data/symbols`). Les vrais noms de
  fonctions et de classes apparaissent dans la liste et dans le C de Ghidra (`FIND::SearchStream`).
- **Détails de l'exécutable** (onglet *Program*) : protections (ASLR, DEP, CFG…), version, manifeste,
  outils de compilation (Rich header), exports avec ordinaux et redirections, callbacks TLS, entropie des
  sections, overlay, signature, et ce qui a servi à le construire (Go, Rust, Delphi, Electron, Nuitka…).
- **Contenu embarqué** : bouton *Extract* quand l'exécutable contient un **bundle PyInstaller** (scripts et
  modules en `.pyc`), une **application .NET single-file** (assemblies), un fichier **UPX** (dépacké) ou une
  archive zip ajoutée. Chaque fichier extrait s'ouvre comme un nouveau projet.
- Le moteur intégré trouve aussi les fonctions appelées par pointeur (vtables, callbacks) et, en 32 bits,
  celles repérées par leur prologue.

## Premiers pas

1. Onglet **Engines** : installer les moteurs voulus (bouton *Install*). Ils sont téléchargés depuis
   leurs sources officielles et vérifiés. Un Java 21+, un .NET ou un Ghidra déjà présents sur la
   machine peuvent être utilisés via *Browse* / *Use*.
2. Onglet **Workspace** : *Open file...* (ou coller un chemin et Entrée).
3. Cliquer sur une fonction à gauche : son code s'affiche au centre. Double-clic sur un nom pour
   y aller, clic droit pour renommer ou chercher, boutons `<` `>` pour revenir.
4. Panneau **AI** à droite :
   - **Explain** : explication de la fonction ;
   - **Suggest names** (+ *Apply*) : noms parlants pour la fonction et ses variables ;
   - **Convert to source** : réécriture en vrai code (C, C++, C#, Java, Python, Rust, Go, HLSL,
     GLSL…), puis vérification par compilation et réparation automatique des erreurs ;
   - **Ask** : questions libres ; l'assistant parcourt lui-même le programme (liste, décompile,
     références, chaînes, recherche) avant de répondre ;
   - **Name functions** : nomme en lot les fonctions générées (`FUN_*`, `sub_*`).

## Choisir l'IA

Onglet **AI assistant settings** :

- **Claude Code**, **Codex**, **Antigravity**, **OpenCode** : utilisent le compte déjà connecté
  dans ces programmes ; aucune clé à saisir. Ils sont lancés en lecture seule.
- **Anthropic**, **OpenAI**, **OpenRouter**, **serveur compatible OpenAI** (LM Studio, vLLM…),
  **Ollama** : clé d'API (enregistrée chiffrée avec DPAPI Windows) ou URL locale.

Le code envoyé à l'IA est celui de la fonction étudiée et ce que l'assistant demande via ses
outils. Avec un fournisseur en ligne, ce code quitte la machine.

## Utiliser depuis une IA (MCP)

CyDecompilator est aussi un serveur MCP. Exemple pour Claude Code :

```
claude mcp add cydecompilator -- "<dossier>\runtime\python\Scripts\python.exe" "<dossier>\app\tool.py" mcp
```

Toutes les fonctions de l'interface sont disponibles (`op_open_file`, `op_decompile`,
`op_rename`, `op_ai_convert`, etc.). Voir `app/README.md`.

## Où sont les choses

- `data/projects/` : un dossier par fichier ouvert (analyse, code en cache, renommages,
  commentaires, résultats IA). Rien n'est perdu à la fermeture.
- `data/settings/` : préférences, réglages IA, clés chiffrées.
- `data/logs/` : journal (aussi visible dans l'onglet *Application log*).
- `runtime/` : Python privé, moteurs téléchargés, mises à jour préparées.

## Mises à jour

Onglet *Engines*, section *Application updates* : *Check for updates* interroge les releases
GitHub de `MrMybal/CyDecompilator`, *Download and verify* prépare la nouvelle version
(empreinte SHA-256, identité, compilation), *Apply update* l'active au prochain démarrage en
gardant l'ancienne (*Restore previous version*). `data/` n'est jamais remplacé. Tant que le
dépôt est privé, il faut un jeton GitHub en lecture (champ *GitHub token*, ou la variable
d'environnement `GITHUB_TOKEN`).

## Licence

GPL-3.0 (voir `LICENSE`). Les moteurs téléchargés gardent leur propre licence (affichée dans
l'onglet *Engines*).

## Limites connues (V1)

- Python ≥ 3.9 : pas de décompilateur libre complet ; bytecode + reconstruction par l'IA.
- DXIL : les bibliothèques de shaders (`lib_6_x`, raytracing) ne montrent que leur première fonction.
- Archives PyInstaller chiffrées (`--key`) et installeurs NSIS/Inno : détectés, pas extraits.
- Le désassembleur intégré ne produit pas de C ; pour du C sans Ghidra, choisir le moteur
  *CyDecompilator C* (x86, x64, ARM64). Le bouton *Fonctions exportées* / *Cette fonction et ses appelées*
  (onglet Programme) écrit un fichier `.c` unique fait pour être recompilé (MSVC, clang).
- Les gros binaires prennent du temps sous Ghidra ; le nombre de fonctions décompilées pendant
  l'analyse est réglable (onglet *Engines*), les autres le sont à l'ouverture.

Ne décompiler que des logiciels que l'on a le droit d'analyser.
