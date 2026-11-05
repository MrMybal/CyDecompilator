# Essai local : Halo Combat Evolved Anniversary

19 octobre 2026, Windows x64. Ce rapport décrit une expérience de traduction CPU,
pas un portage du jeu complet.

## Entrée et préparation

Archive trouvée dans Téléchargements :
`Halo - Combat Evolved Anniversary (World) (En,Ja,Fr,De,Es,It,Pt,Zh,Ko).zip`.

| Élément | Observation |
|---|---|
| Archive ZIP | 8 098 132 489 octets |
| ISO contenue | 8 738 846 720 octets |
| Partition XDVDFS | `0x02080000` |
| Entrées du disque | 469, fichiers et répertoires |
| Exécutable retenu | `default.xex`, 22 265 856 octets |
| Title ID / Media ID | `4D5309B1` / `00394009` |
| Base / entrée | `0x82000000` / `0x823C91C0` |
| SHA-256 de l'exécutable | `1412845884eba9eb61cdc00213ca3777be19c71f6196faea69e435a350fd3f19` |
| Type du contenu | XEX2, chiffrement 1, compression basique 1 |
| Imports | `xam.xex`, `xboxkrnl.exe` ; 335 symboles importés nommés dans l'image chargée |

L'archive originale est restée en lecture seule. L'ISO a été copiée sous
`work/halo-ce-anniversary/private/disc.iso`. La première tentative de préparation a
révélé une erreur dans le lecteur expérimental concernant les valeurs XEX immédiates
de type 1 ; elle a été corrigée et couverte par un test. Le workspace final
`work/halo` a ensuite été préparé depuis cette ISO locale, sans la recopier une
seconde fois. Les 469 entrées sont conservées dans `work/halo/disc-index.json`.

Le pont natif prend en compte un détail du chargeur amont : pour cet XEX, le total
des blocs décompressés vaut `0x019D8000`, inférieur à la taille alignée déclarée
`0x019E0000`. Il exporte uniquement la mémoire réellement allouée, sans lire les
32 Kio de remplissage déclarés en fin d'image.

## Moteur et traduction

XenonRecomp officiel, commit `ddd128bcca99fe8bfbb99bea583c972351fa6ace`,
compilé localement avec Clang 19.1.5. Ses six sous-modules sont figés aux révisions
du commit parent dans `runtime/engines/xenonrecomp/backend.json`.

XenonAnalyse a détecté 47 tables de sauts. Le pont d'analyse a trouvé puis vérifié
intégralement huit routines GPR/FPR/VMX de sauvegarde/restauration. Les adresses
sont conservées dans le profil exact `profiles/halo-ce-anniversary-14128458.toml`.

La première traduction émettait des erreurs de limites pour le dispatch à
`0x82E9F050`. Le désassemblage montre une routine débutant à `0x82E9F020`, une
table à 30 entrées à `0x82E9F054`, des cas jusqu'à `0x82E9F108` et la routine
suivante à `0x82E9F110`. Sa limite explicite `0xF0` et les helpers vérifiés ont
supprimé ces diagnostics dans la seconde traduction.

Cette seconde tentative a produit :

- 438 fichiers C++ et trois en-têtes ;
- 111 680 occurrences de définition `PPC_FUNC_IMPL` ;
- 49 appels explicites de trap/debugtrap ;
- aucun diagnostic d'erreur/avertissement dans le journal du traducteur.

Le nombre de définitions comprend les entrées que le moteur détecte ; ce n'est
pas un décompte prouvé des fonctions du code source original. Un journal sans
erreur ne prouve pas que tous les chemins sont traduits correctement.

## Compilation et exécution contrôlée

La compilation Clang de **toutes les 438 unités** a produit **437 objets natifs**.
`ppc_recomp.356.cpp` échoue sur `goto loc_8317EE64` dans la fonction
`sub_8317EBC8` : l'étiquette n'est pas définie dans la fonction générée.

L'image d'origine confirme une instruction nulle à `0x8317EE64`, juste après la
limite `.pdata` de la routine (`0x29C` octets depuis `0x8317EBC8`). Les branches
`bdz` la visent. Cette anomalie demande une décision explicite dans le backend
sur les branches hors fonction et les instructions invalides. Aucune étiquette
factice, instruction supprimée ou valeur de retour de remplacement n'a été ajoutée.

Une vérification séparée a extrait du C++ généré la routine réelle
`__imp__sub_82E9EFF0`. Elle calcule une adresse avec un index et une taille
d'enregistrement, puis charge une valeur 32 bits en grand-boutiste. Un harnais a
fourni des registres et une mémoire contrôlés. **Compilation native réussie et
16 résultats sur 16 conformes.** Aucun interpréteur PPC ou émulateur n'a exécuté
ces instructions durant ce test.

Lors des premiers essais, Kaspersky a supprimé le petit `leaf.exe` de test, comme
montré par la capture de l'utilisateur. Les premiers refus d'accès n'ont donc pas
été comptés comme réussite. Après le message de l'utilisateur indiquant l'avoir
arrêté, le nouvel essai s'est terminé avec le code 0. Aucune exception antivirus,
modification de Kaspersky ou conclusion sur la nature de son alerte n'a été faite
par le module.

Reçus locaux à consulter : `work/halo/latest-translation.json`,
`work/halo/latest-compilation.json`, `work/halo/latest-probe.json` et
`work/halo/latest-native-leaf.json`. Les chemins précis des sources, objets et logs
sont enregistrés à l'intérieur. Les résultats restent dans les dossiers ignorés.

## Ce qui reste avant un jeu PC

La reprise décrite ci-dessous résout l'erreur de compilation. Le jeu complet
n'a pas été lié ni lancé. Il reste les instructions et branches non résolues,
les imports système, la mémoire, les threads, les fichiers, les commandes GPU et
shaders, l'audio, les entrées et le chargement des données. Les scénarios de
lancement, menu, image, son et gameplay ne sont pas validés.

Le test de fonction est une preuve limitée de traduction/recompilation native ;
il ne prouve ni l'équivalence globale du processeur ni la compatibilité du jeu.

## Reprise : correction du traducteur et archive CPU native

Les résultats ci-dessus décrivent le premier moteur amont. La reprise ajoute des
modifications locales reproductibles dans `scripts/backend_overlay.py`, construites
séparément avec `setup_backend.py --build --overlay`. Le checkout amont reste
inchangé ; l'application CyDecompilator reste également séparée de ce travail.
La transformation exige le SHA-256 normalisé de `recompiler.cpp` et des points
de modification uniques. Son reçu est `runtime/engines/xenonrecomp/overlay/overlay.json`.

Le défaut de `bdz` était un `goto` vers une autre fonction. Les branches sur CTR
sortant de leur fonction émettent maintenant un appel terminal vers la destination.
La destination nulle de Halo n'est pas transformée en succès : le code indécodable
à cette adresse émet un arrêt explicite si ce chemin est exécuté.

Les chemins de décodage ou de traduction non implémentés, les appels directs sans
destination résolue et les cas de switch inconnus émettent également des arrêts
explicites. Deux macros permettent à un futur runtime de produire des diagnostics
structurés : `PPC_UNSUPPORTED_INSTRUCTION(pc, word)` et
`PPC_UNRESOLVED_BRANCH(source, target)`. Par défaut, elles interrompent l'exécution.
Elles ne simulent pas le traitement d'une exception par la console.

La première version corrigée a compilé **438 unités sur 438**. Une archive native
a été construite, puis un véritable essai de lien de toute l'archive a été lancé.
Il confirme les imports système à implémenter ; l'archive seule n'est pas un jeu.

Huit familles d'instructions supplémentaires ont ensuite été traduites :
`bdzf`, `eqv`, `lfsu`, `stfsu`, `lhzu`, `sthu`, `lfsux` et `stfsux`.
Les mises à jour de bases conservent le résultat 64 bits du calcul, tandis que
l'accès mémoire utilise l'adresse Xbox 32 bits. Les tests couvrent notamment
les déplacements négatifs, l'ordre grand-boutiste, les registres aliasés, les zéros
signés, les sous-normaux, les infinis et des NaN. Les champs CR utilisés par
`bdnzf`/`bdzf` respectent aussi le bit effectivement encodé.

Le XEX synthétique de `tests/ppc_fixture.py` et `tests/ppc_scalar_fixture.py` est
entièrement créé localement. Il est traduit, compilé et exécuté nativement :
**965 assertions réussies**. Le test de 16 entrées sur une fonction réelle de Halo
a également été refait avec succès avec ce nouveau moteur.

L'audit statique avant/après ces huit ajouts donne :

| Observation dans les sources traduites | Avant les ajouts | Après les ajouts |
|---|---:|---:|
| Sites d'instruction non nulle non prise en charge | 5 367 | 937 |
| Sites avec mot nul, incluant du remplissage | 36 551 | 36 551 |
| Branches directes sans destination résolue | 483 | 483 |
| Destinations uniques de ces branches | 144 | 144 |
| Traps explicites déjà présents dans le moteur | 49 | 49 |

Ce sont des décomptes de sites statiques, comprenant potentiellement des données
dans les sections de code ; ce n'est pas un pourcentage de compatibilité du jeu.
Les 483 branchements étaient auparavant émis sous forme de commentaires sans
traitement effectif. Parmi eux, 245 relient des adresses dans le même enregistrement
`.pdata` avec le bit d'exception activé. Les 238 autres n'ont pas de destination
couverte par `.pdata`. Aucune fusion automatique de ces fonctions n'a été tentée.

Les 49 traps restants se répartissent en 47 `vupkd3d128`, un `vpkd3d128` et un
`blrl`. La suite logique est donc la prise en charge des variantes vectorielles,
la reconstruction des entrées/continuations de fonctions et la gestion des
exceptions, en parallèle d'un vrai runtime pour les imports.

La version finale avec les huit ajouts compile également **438 unités sur 438**.
L'archive `guest-cpu.lib` obtenue contient 138 209 274 octets. Le linker, avec les
bibliothèques C/C++ natives explicitement fournies, signale exactement **335 erreurs
de symbole manquant**, toutes correspondant aux imports Xbox/XAM. Les cinq
dépendances hôtes de l'archive (`sqrt`, `sqrtf`, `log2f`, `exp2f`, `_fltused`) sont
résolues par ces bibliothèques hôtes. Aucun import console n'a été remplacé par
un bouchon pour obtenir un lien artificiellement réussi.

Les reçus supplémentaires sont `work/halo/latest-audit.json` et
`work/halo/latest-cpu-archive.json`. L'audit contient un lien vers tous les sites,
leurs adresses, les mots d'origine et les fonctions `.pdata` concernées. Le reçu
d'archive conserve les empreintes des objets, l'inventaire des symboles et le log
du linker. Les sources et données du jeu restent dans les dossiers ignorés.
# Voie XenonRecomp et vérifications CPU

Ce rapport conserve les essais du premier backend CPU. Pour la voie ultérieure
avec runtime ReXGlue, EXE Windows lié et essais de démarrage du jeu, voir
[le rapport ReXGlue](REXGLUE_REPORT.md). Aucun de ces résultats de compilation
ne doit être présenté comme un test de gameplay.

