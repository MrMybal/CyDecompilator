# Cy Xbox Native — module expérimental indépendant

Préparation, analyse et expérimentation de portages Xbox / Xbox 360 vers PC par
traduction statique. **Aucun émulateur n'est lancé.** Le module ne dépend pas de
`app/`, ne modifie pas l'interface de CyDecompilator et n'y enregistre aucune opération.

Cette version est une base de recherche fonctionnelle, **pas un convertisseur
universel de jeux en EXE jouables**. Les sources reconstruites ne sont pas les
sources originales du jeu.

| Étape | Xbox originale | Xbox 360 |
|---|---|---|
| Lecture XBE / XEX2 et identité SHA-256 | Oui | Oui, métadonnées sans déchiffrement local |
| Préparation depuis fichier, dossier, ISO XDVDFS, ZIP contenant une ISO | Oui | Oui |
| Sections et adresses mémoire | Export XBE | Image via pont natif optionnel |
| Décompilation | Ghidra optionnel, pseudocode C | Traduction PowerPC vers C++ via XenonRecomp |
| Recompilation CPU vers objets PC | Backend x86 complet à développer | Clang + correctifs locaux, 438/438 unités Halo compilées |
| Services console, GPU, shaders, audio, entrée, jeu complet | À développer | Runtime ReXGlue expérimental ; jeu complet en cours de validation |

Les lecteurs rejettent les entrées tronquées, les pointeurs hors fichier, les cycles
de répertoires, les chemins ambigus et les sorties déjà présentes. Les originales
sont ouvertes en lecture seule. Chaque exécution externe conserve un journal et un
reçu JSON avec état, code de sortie et identité du binaire.

## Essai réel réalisé

Halo: Combat Evolved Anniversary, exécutable `4D5309B1`, SHA-256 commençant par
`14128458` : disque indexé, XEX extrait, 47 tables de sauts détectées, huit routines
utilitaires vérifiées, C++ généré et **438 fichiers sur 438 compilés en objets PC**
avec les corrections locales du traducteur.
Une fonction réelle a également été compilée en EXE de test et exécutée avec succès
sur 16 entrées contrôlées. Les corrections CPU passent aussi une suite native de
965 assertions sur un XEX synthétique. Cette voie CPU seule ne produit pas le jeu
complet. La voie ReXGlue a ensuite permis de lier un EXE Windows et de démarrer le
code du jeu. **Le rendu, la campagne et les commandes PC sont confirmés par
l'utilisateur** ; une mission complète et la correction visuelle des flares
dans toutes les scènes restent à valider. Le multijoueur n'est pas pris en charge. Voir le
[rapport des essais ReXGlue](docs/REXGLUE_REPORT.md).

Pour cet essai local préparé, `Play-Halo.cmd` lance une fenêtre 1152 × 648,
avec clavier/souris. F6 capture/libère le regard ; les menus reçoivent les clics
et les déplacements de souris. F2 ouvre les réglages PC, Échap met en pause et
les FPS sont affichés en haut à droite. Voir [commandes PC](docs/PC_CONTROLS.md).
Le plafond de 30 FPS est désactivé par défaut ; la visée utilise les déplacements
relatifs directement, sans conversion en stick. L'ancienne sensibilité est
sauvegardée puis remise à 1 lors de la migration du fichier de commandes.
F2 propose aussi l'interpolation des animations et l'anti-aliasing natif, dont
le SMAA 1x High par défaut. ReShade facultatif s'ouvre avec Home / Début.
Voir [animations et effets PC](docs/PC_GRAPHICS.md).
Le profil de test a été sauvegardé et ses dix missions déverrouillées.
Pour refaire cette opération sur un profil compatible, jeu fermé :
`python scripts/unlock_halo_missions.py`. Les binaires du jeu restent des entrées locales.

La voie Xbox originale a été testée avec un XBE synthétique créé localement :
préparation, sections, chargement Ghidra et décompilation d'une fonction renvoyant 42.
Aucun jeu commercial Xbox originale n'a été validé.

Voir [rapport Halo](docs/HALO_REPORT.md), [recherche et choix des moteurs](docs/RESEARCH.md)
et [contrat pour l'intégration future](docs/INTEGRATION.md).

## Lancement

Python 3.11+ ; aucune dépendance Python pour les lecteurs ou la CLI. Depuis ce dossier,
dans le dépôt actuel, remplacer `python` par `..\..\runtime\python\Scripts\python.exe`
pour employer le Python déjà disponible. L'installation par pip n'est pas nécessaire.

```powershell
python -m xbox_native --help
python -m xbox_native inspect "D:\Jeux\default.xex"
python -m xbox_native prepare "D:\Jeux\jeu.iso" "work\mon-jeu"
```

Pour un ZIP, une seule ISO doit être présente. Elle est copiée en flux sous le nom
fixe `private/disc.iso`, sans extraire les chemins de l'archive. Prévoir environ 9 Go
libres pour une ISO Xbox 360 complète. Les autres formes d'archives, GOD/STFS et les
patches XEXP nécessitent une préparation séparée. XEX1 n'est pas pris en charge.
Pour un dossier ou un disque contenant plusieurs exécutables, sélectionner un chemin
avec `--executable chemin/jeu.xex`. Sans option, la racine `default.xex` / `default.xbe`
est retenue pour un disque ; un dossier doit contenir un candidat par défaut unique.

`prepare` extrait seulement l'exécutable. Pour préparer les données du jeu pour un
runtime natif, `extract-assets` copie tous les fichiers XDVDFS dans un nouveau
dossier et produit un reçu avec leurs SHA-256. Ne pas déplacer l'ISO référencée par
un espace de travail existant.

## Runtime Xbox 360 expérimental ReXGlue

Une seconde voie utilise le SDK officiel [ReXGlue](https://github.com/rexglue/rexglue-sdk)
0.10.0 : recompilation statique CPU, services Xbox réimplémentés, traduction GPU
Xenos vers Direct3D 12, audio et entrées. Aucun processus d'émulateur n'est lancé ;
les services et le matériel graphique nécessitent cependant une couche de compatibilité.
Le fait de compiler ou d'ouvrir une fenêtre ne suffit pas à déclarer un jeu jouable.

Depuis le dossier du module, avec les outils C++ Visual Studio et LLVM installés :

```powershell
python scripts/setup_rexglue.py --directory tools/rexglue
python -m xbox_native extract-assets "D:\Jeux\jeu.iso" work/portage/game
python scripts/rex_project.py init --sdk tools/rexglue/0.10.0/win-amd64 --game work/portage/game --project work/portage/project --name MonJeu
python scripts/rex_project.py build --sdk tools/rexglue/0.10.0/win-amd64 --project work/portage/project
python scripts/rex_project.py run --project work/portage/project --game work/portage/game
```

Le téléchargement du SDK est vérifié par son SHA-256 figé. Le profil Halo est
sélectionné uniquement pour l'exécutable exact testé ; les autres jeux demandent
leur propre investigation. Les sources générées et données propriétaires restent
dans `work/`, ignoré par Git. Les reçus de compilation et de lancement conservent
`native_game_ready=false` tant qu'une validation de jeu n'a pas été réalisée.

## Xbox 360 : moteur séparé

Le script télécharge les sources officielles de XenonRecomp et ses dépendances aux
révisions figées par le dépôt, puis les compile. Il ne modifie pas la configuration
Git globale et refuse de remplacer un moteur local modifié.

Prérequis : Git, CMake 3.20+, Clang 18+ ; sous Windows, outils C++ Visual Studio,
SDK Windows et composant LLVM. La vérification des objets actuelle cible un PC x64
avec AVX2. Les autres hôtes ne sont pas validés dans cette version.

```powershell
python scripts/setup_backend.py --directory tools/xenonrecomp --build --probe --overlay
python -m xbox_native analyse work/mon-jeu --backend tools/xenonrecomp/build-clang/XenonAnalyse/XenonAnalyse.exe
python -m xbox_native probe work/mon-jeu --backend tools/xenonrecomp/probe-build/xbox-image-probe.exe
python -m xbox_native configure work/mon-jeu
```

`probe` utilise le chargeur XEX de XenonRecomp. Ce pont expose une image et les imports
pour l'analyse ; il n'exécute pas le code du jeu. Le lecteur Python seul ne déchiffre
pas le contenu XEX et ne contient pas de clé console.

Avant la traduction, vérifier `xenon.toml` : les valeurs de `helpers.toml` produites par
`probe` sont fondées sur les routines complètes, retour compris. Les tables de sauts,
limites de fonctions, exceptions et appels indirects demandent encore une analyse
par titre. Les options d'optimisation sont désactivées par défaut.

Un profil exact est disponible pour la copie Halo analysée :

```powershell
python -m xbox_native configure work/mon-halo --profile profiles/halo-ce-anniversary-14128458.toml
```

Le profil refuse les autres SHA-256. `configure` n'écrase pas une configuration
existante. Lancer `analyse` avant `configure` pour référencer automatiquement les
tables détectées dans le fichier de configuration.

```powershell
python -m xbox_native translate work/mon-jeu --backend tools/xenonrecomp/overlay-build/upstream/XenonRecomp/XenonRecomp.exe --context tools/xenonrecomp/source/XenonUtils/ppc_context.h
python scripts/check_translation.py work/mon-jeu --backend-source tools/xenonrecomp/source --jobs 4
python -m xbox_native audit work/mon-jeu
python scripts/package_cpu.py work/mon-jeu
```

Le code C++ et les objets natifs restent dans `work/<jeu>/runs/<tentative>/`.
`translated-with-blockers` signifie uniquement qu'une traduction CPU a produit des
sources : consulter les diagnostics, les arrêts explicites et le résultat réel du
compilateur. Aucun bouchon d'API renvoyant artificiellement « succès » n'est généré.
Les échecs d'étape retournent un code CLI non nul.

`--overlay` construit une copie corrigée du traducteur depuis une source amont
identifiée par SHA-256, sans modifier son checkout Git. Elle traite les branches
conditionnelles sortant d'une fonction, les quatre bits CR des branches combinées,
et huit familles d'instructions manquantes : `bdzf`, `eqv`, `lfsu`, `stfsu`,
`lhzu`, `sthu`, `lfsux` et `stfsux`. Les instructions/branches non résolues
produisent des points d'arrêt natifs explicites au lieu de continuer silencieusement.
Ces arrêts ne constituent pas une implémentation des exceptions Xbox.

`audit` recense les adresses et rapproche les branches des enregistrements `.pdata`
de l'image originale. Des sites peuvent correspondre à du remplissage ou à des
données incluses dans une section de code ; leur présence ne prouve pas leur
accessibilité à l'exécution.

`package_cpu.py` crée une archive `.lib` à partir des objets vérifiés et tente une
édition de liens complète à des fins de diagnostic. Une archive peut contenir des
imports non résolus ; ce résultat ne signifie pas que le jeu est exécutable. Le
reçu conserve l'erreur du linker et les symboles à remplacer.

`scripts/verify_halo_leaf.py` est un test particulier qui compile **et exécute** une
fonction du Halo correspondant au SHA-256 enregistré, sur une mémoire de test.
Ce test a déclenché une suppression Kaspersky lors du premier essai ; son succès
ultérieur ne constitue pas une analyse de l'alerte antivirus ni une validation du jeu.

## Xbox originale : analyse XBE

```powershell
python -m xbox_native prepare "D:\Jeux\default.xbe" work/mon-xbox
python -m xbox_native export-xbe work/mon-xbox
$env:JAVA_HOME = "C:\chemin\vers\jdk"
python -m xbox_native decompile-xbe work/mon-xbox --ghidra "C:\chemin\vers\ghidra"
```

Les scripts Ghidra recréent les sections XBE à leurs adresses x86 d'origine,
identifient le point d'entrée, analysent puis exportent les fonctions. Le pseudocode
exige ensuite un vrai backend de reconstruction et une couche d'API Xbox native.
Le module ne présente pas ce C comme automatiquement recompilable.
Ghidra 12.1.4 avec JDK 24 est la combinaison testée ; paramètres et cache restent
dans l'espace de travail de l'analyse.

## Vérifications

```powershell
python -m unittest discover -s tests -v
```

38 tests couvrent les formats synthétiques, les bornes, l'extraction, les empreintes,
les profils, les routines utilitaires complètes et le comportement des sous-processus.
Les tests ordinaires ne nécessitent aucun jeu, téléchargement ou exécution d'un
binaire console. Les essais externes réels sont consignés séparément dans le rapport.

Pour vérifier les modifications du traducteur sans jeu commercial :

```powershell
python scripts/verify_control_flow.py --backend tools/xenonrecomp/overlay-build/upstream/XenonRecomp/XenonRecomp.exe --backend-source tools/xenonrecomp/source
```

Cette suite génère son propre XEX, le traduit en C++, compile et exécute le résultat
natif. Elle vérifie les branches prises/non prises, CTR, LR, les bits CR, une boucle,
les conversions flottantes, l'ordre des octets, les adresses 64 bits et les chemins
invalides. Le test ne remplace pas une comparaison avec du matériel Xbox 360.

Le code du module relève de la licence GPL-3.0 du dépôt parent. XenonRecomp (MIT),
Ghidra (Apache-2.0) et leurs dépendances sont des composants séparés, avec leurs
licences propres. Aucun jeu, ISO, exécutable console ou source de jeu traduit n'est
inclus dans les fichiers versionnables du module. `work/`, `tools/` et `build/` sont ignorés.
