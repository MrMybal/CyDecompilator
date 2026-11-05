# Cy Unreal Reconstruction — prototype indépendant

Conduite et combat embarqué, manœuvres de platoons et graphes Anniversary :
[état et validation de la dernière étape](docs/FULL_GAMEPLAY.md).
Preuve distincte : `work/full-gameplay/delivery-proof.json`.

Nouvelle étape : [escouades, pilotage par points et flashes de tir](docs/SQUAD_PILOT_VFX.md). Preuve : `work/squad-vfx/delivery-proof.json`.

Dernière suite du portage : [mémoire des adversaires, priorités des cibles et commandes des véhicules](docs/AI_KNOWLEDGE.md). Preuve distincte : `work/ai-knowledge/delivery-proof.json`.

Adaptateur expérimental **Halo: Combat Evolved Anniversary Xbox 360 → Unreal Engine 5.8**,
étendu aux dix missions de campagne. Les règles et profils sont intégrés à la page **Reconstruction Unreal** de CyDecompilator
et aux opérations `unreal_rules` / `unreal_guide`. Extraction, import, compilation et exécution
restent dans ce module séparé. [Guide intégré](../../app/Docs/UnrealReconstruction.fr.md).
Les sources du jeu restent dans `xbox-native`.

Le portage des huit missions supplémentaires, ses contrôles et ses limites
sont décrits dans [docs/CAMPAIGN_MAPS.md](docs/CAMPAIGN_MAPS.md).

Les familles de PNJ et personnages manquants sont ajoutés aux dix missions,
avec leurs modèles Anniversary et animations récupérées :
[docs/NPC_EXPANSION.md](docs/NPC_EXPANSION.md).
La preuve du projet après cet ajout est `work/npc-expansion/delivery-proof.json` ;
les rapports des étapes précédentes conservent leurs anciens états de validation.

La reprise des armes et le portage des fonctions d'IA en **C++ Unreal**, décidés
le 21 octobre, sont suivis dans [docs/WEAPON_CPP_PORT.md](docs/WEAPON_CPP_PORT.md).
Cette nouvelle étape utilise `work/weapon-ai-parity` ; la preuve PNJ ci-dessus
décrit l'état antérieur et ne certifie pas les modifications suivantes.

La suite grenades, surchauffe et ordres de débarquement est décrite dans
[docs/COMBAT_ACTIONS.md](docs/COMBAT_ACTIONS.md). Sa preuve est séparée dans
`work/combat-actions/delivery-proof.json`.

## Projet local

Le NavMesh a été agrandi et reconstruit pour couvrir les rencontres du niveau.
Le test du premier combat A30 confirme le déplacement des sept ennemis et
des six Marines : [docs/NAVIGATION_FIX.md](docs/NAVIGATION_FIX.md).

Les corrections des raccords de terrain, des masques ARGB, des lianes et des
proxies d'ombre sont décrites dans
[docs/SURFACE_IMPORT_FIXES.md](docs/SURFACE_IMPORT_FIXES.md).

Le bilan des ajouts d'éclairage, shaders, impacts, audio et scénario est dans
[docs/PRESENTATION_REPORT.md](docs/PRESENTATION_REPORT.md), avec les résultats
des tests et les limites de campagne encore présentes.

`work/a10/HaloA10/HaloA10.uproject`

- `Open-HaloA10.cmd` : ouvrir le projet dans l'éditeur UE 5.8 installé sur `G:`.
- `Play-HaloA10.cmd` : lancer le niveau dans une fenêtre de jeu Unreal.
- `Play-HaloA30.cmd` : jouer à la deuxième carte, dans le même projet.
- `Play-HaloCampaign.cmd` : choisir parmi les dix missions.
- `Play-HaloA50.cmd`, `Play-HaloB30.cmd`, `Play-HaloB40.cmd`, `Play-HaloC10.cmd`,
  `Play-HaloC20.cmd`, `Play-HaloC40.cmd`, `Play-HaloD20.cmd`, `Play-HaloD40.cmd` :
  lancer directement chaque nouvelle map.
- Dans l'éditeur : ouvrir `/Game/Maps/A10`, puis **Play**.
- Souris : regard et tir ; clic droit : zoom ; WASD/ZQSD : déplacement ; Espace : saut ;
  Ctrl : accroupissement ; R : rechargement ; F : coup de crosse ; E : action ; G : grenade ; V : type de grenade.
  Entrée : réapparition après la mort ; F9 : recharger le checkpoint de campagne.
  Échap / Alt+F4 quittent selon le mode.

Les dernières corrections des UV, sapins, variantes, collisions et armes sont dans
[docs/ANNIVERSARY_UV_FIXES.md](docs/ANNIVERSARY_UV_FIXES.md). Entrée permet de
réapparaître après la mort au dernier checkpoint disponible, ou au départ du niveau.
Les corrections d'animations et l'ajout d'A30 sont décrits dans
[docs/A10_A30_CORRECTIONS.md](docs/A10_A30_CORRECTIONS.md). Pour tester le joueur, lancer
le jeu avec le fichier `.cmd` ou utiliser **Play** dans l'éditeur ; le déplacement libre
de la caméra de l'éditeur ne contrôle pas le personnage.

La présence d'un `.uproject` ne prouve pas que la conversion fonctionne. L'état réellement
vérifié est conservé dans `work/a10/conversion-report.json`, et les assertions du test en
jeu dans `work/a10/HaloA10/Saved/Validation/runtime.json`. Une preuve liée aux empreintes
des sources, assets et DLL est écrite dans `runtime-proof.json` après une validation complète.

Les réactions de combat fondées sur les paramètres des IA Anniversary et leurs
essais sont décrits dans [docs/AI_BEHAVIOR.md](docs/AI_BEHAVIOR.md).

## Contenu et fidélité

La géométrie provient des archives `paks360/<mission>.s3dpak`, des textures partagées du jeu et de ses
modèles Anniversary. Les positions, palettes et rencontres viennent de
`maps_original/<mission>.map`. Les placements de décor utilisent également les matrices ANIS Anniversary.
Les animations originales sont décodées puis adaptées aux
squelettes Anniversary par correspondance des noms et des axes locaux des os. Les poses
de repos différentes des bras ne sont pas ajoutées à la rotation animée. Les clips de type overlay sont combinés avec une pose d'attente
source avant export. Les conversions intermédiaires RMF, JSON et FBX sont conservées.

Le gameplay Unreal est une **nouvelle implémentation de prototype** : déplacement, saut,
accroupissement, visée, quatorze définitions d'armes avec huit présentations joueur Anniversary,
projectiles, munitions, dégâts, bouclier, portes de proximité,
navigation et combat élémentaire des équipes. La vitesse de course du joueur est lue dans
les paramètres originaux. Le code PowerPC recompilé et ReXGlue ne sont pas exécutés dans
Unreal. Les Marines/Élites/Grunts/Jackals et les quinze familles/personnages de
l'import complémentaire utilisent les modèles et séquences récupérés. Le nouvel
audit `work/npc-expansion/saved-npc-audit.json` contrôle les emplacements de PNJ
des dix niveaux sauvegardés.

Tous les modèles et textures affichés proviennent de l'édition **Anniversary**.
Le module utilise les données de jeu runtime incluses dans cette édition, sans
importer les modèles ou textures de l'affichage Classic.

Les scripts de démarrage, la première arrivée de renforts A30, les ordres de scénario,
l'audio, les checkpoints et des cinématiques sont partiellement adaptés et testés.
L'IA de combat utilise les paramètres acteur/variante récupérés, avec une navigation
et une machine de réactions réimplémentées dans Unreal. Le runtime Blam complet,
les grenades tactiques et une campagne intégralement terminable restent à porter.
Les matériaux et l'éclairage sont une approximation ; les effets et modèles non pris en
charge sont listés dans les rapports. Les familles de matériaux reconnues utilisent transparence,
découpe alpha ou mélange additif ; il reste des approximations de shaders. Les secteurs graphiques sont importés ensemble,
sans reproduire le streaming et les transitions BSP originaux. Une mission terminable
fidèle au jeu original n'est pas revendiquée par ce prototype.

## Reproduire depuis les sources

Prérequis : Windows x64, Python 3.11+, .NET SDK 9, Git, Blender 5.2, Unreal 5.8 avec les
outils C++ Visual Studio. Le Python existant du dépôt convient :
`../../runtime/python/Scripts/python.exe`. Aucun paquet n'est ajouté à ce runtime.

Depuis le dossier du module :

```powershell
$python = '..\..\runtime\python\Scripts\python.exe'
$engine = 'G:\UnrealEngine\UE_5.8'
& $python -m unreal_reconstruction tools
& $python -m unreal_reconstruction prepare
& $python -m unreal_reconstruction extract
& $python -m unreal_reconstruction convert
& $python -m unreal_reconstruction convert-props
& $python -m unreal_reconstruction build --engine $engine
& $python -m unreal_reconstruction environment --engine $engine
& $python -m unreal_reconstruction characters --engine $engine
& $python -m unreal_reconstruction firstperson --engine $engine
& $python -m unreal_reconstruction props --engine $engine
& $python -m unreal_reconstruction materials --engine $engine
& $python -m unreal_reconstruction level --engine $engine
& $python -m unreal_reconstruction audit --engine $engine
& $python -m unreal_reconstruction validate --engine $engine
& $python -m unreal_reconstruction report

# Ajouter A30 au même projet après les assets et personnages communs ci-dessus.
& $python -m unreal_reconstruction prepare --map a30
& $python -m unreal_reconstruction extract --map a30
& $python -m unreal_reconstruction convert --map a30
& $python -m unreal_reconstruction convert-props --map a30
& $python -m unreal_reconstruction convert-jackal --map a30
& $python -m unreal_reconstruction environment --map a30 --engine $engine
& $python -m unreal_reconstruction props --map a30 --engine $engine
& $python -m unreal_reconstruction jackal --map a30 --engine $engine
& $python -m unreal_reconstruction level --map a30 --engine $engine
# Les empreintes incluent les deux cartes : valider après toutes les modifications.
& $python -m unreal_reconstruction audit-surfaces --engine $engine
& $python -m unreal_reconstruction audit-surfaces --map a30 --engine $engine
& $python -m unreal_reconstruction validate --engine $engine
& $python -m unreal_reconstruction validate --map a30 --engine $engine
& $python -m unreal_reconstruction visual --map a30 --engine $engine
& $python -m unreal_reconstruction report --map a30
```

Utiliser `--game <dossier>` pour sélectionner les données et `--work <dossier>` pour une
nouvelle sortie. Par défaut, les entrées sont lues dans
`../xbox-native/work/halo-rex/game`. Le profil refuse un autre exécutable que le SHA-256
inspecté. Les originaux sont uniquement lus. Ne pas modifier les sources ou assets pendant
la validation ; toute modification invalide la preuve. `prepare` protège les modifications
locales des sources générées. `level` remplace les acteurs générés de la carte a10 ; sauvegarder
une copie de cette carte avant de personnaliser sa reconstruction.

Les étapes sont distinctes afin de reprendre après une interruption. Chaque processus
externe possède un délai maximal, un journal et un reçu sous `work/a10/logs`. Un code de
retour nul de Blender sans résultat exploitable n'est pas accepté : les erreurs Python
retournent explicitement un échec. Les opérations Unreal vérifient aussi les résultats du
domaine (assets produits, séquences attendues, niveau réellement enregistré).

Une copie source de CyAtlas 5.8 peut être indiquée avec `--engine`. Pour ne pas reconstruire
le moteur, `build` utilise alors `-Module=HaloA10 -UsePrecompiled -NoEngineChanges` ; la
compatibilité des binaires de l'éditeur demeure nécessaire. Ne pas ouvrir la DLL produite
pour une autre installation sans reconstruire le module avec l'installation choisie.

## Présentation, audio et campagne

Après extraction des deux missions, récupérer les données supplémentaires avant les
conversions FBX et les imports :

```powershell
& $python -m unreal_reconstruction recover-presentation --map a10
& $python -m unreal_reconstruction recover-presentation --map a30
& $python -m unreal_reconstruction recover-audio
& $python -m unreal_reconstruction audio --engine $engine
```

Le décodeur officiel `tools/vgmstream/vgmstream-cli.exe` et ses bibliothèques associées
sont nécessaires pour `recover-audio`. Leur version et l'empreinte de l'archive utilisée
sont consignées dans `presentation-dependencies.json`. Les banques `sounds/xbox360`
et leurs fichiers `.lst` sont lus dans le jeu possédé ; les dialogues sélectionnés
proviennent de `sounds_dialogs_french.fsb`. Aucun échantillon Classic n'est substitué.

Le niveau contient un acteur `RecoveredCampaign`. Il exécute les scripts de scénario
sur leurs volumes, personnages et portes ; les cinématiques sont ignorées, avec le
parcours rapide du tutoriel A10. Les checkpoints sont enregistrés sous
`HaloA10/Saved/Campaign`. F9 reprend un checkpoint dans la session ; le paramètre
de lancement `-CyResume` le recharge au démarrage. Les captures et sauvegardes du test
automatisé utilisent un dossier `Saved/Validation` séparé.

```powershell
& $python -m unreal_reconstruction campaign --engine $engine
& $python -m unreal_reconstruction campaign --map a30 --engine $engine
```

Ces tests exécutent les démarrages de mission et les fonctionnalités, enregistrent une
capture et le mixage audio réel, puis refusent un fichier WAV silencieux. A30 dispose
d'un délai supplémentaire pour les conversations qui précèdent le premier objectif.
Les preuves incluent les JSON de scénario et les données audio non incorporées aux
assets. Les tests de démarrage ne prouvent pas la fin des missions : les commandes
tardives non prises en charge sont consignées explicitement dans les rapports de
campagne, et les véhicules hors du début A30 restent à valider.

## Vérifications et dépendances

```powershell
..\..\runtime\python\Scripts\python.exe -m unittest discover -s tests -v
```

Les tests unitaires vérifient les refus d'entrées incompatibles, la protection des sources,
les reçus d'échec et l'invalidation des preuves. Le scénario Unreal vérifie séparément
la présence des personnages, la collision du sol, le déplacement, le tir, les munitions,
les dégâts, le combat IA et l'évolution d'une pose animée. Il garde une capture réelle.
Il ne prouve pas l'équivalence de la campagne.

`audit` évalue les poses et contrôle les axes de placement ainsi que le repère du fusil.
`visual` produit des captures de poses et du rechargement dans une scène de présentation
temporaire ; cette scène ne modifie pas les cartes enregistrées.

Le bilan de cette livraison est dans [docs/A10_REPORT.md](docs/A10_REPORT.md).

`dependencies.json` fixe les dépôts officiels et leurs révisions. `tools` applique six
adaptations locales explicites : fin de flux dans `ChunkStream`, textures initiales partagées,
matériau sans fournisseur, plages de sous-meshes de scène, noms de champs d'animations mis à jour, et listes de matrices réellement présentes sur les armes sans squelette. Les autres adaptations
Anniversary (initialisation et pages d'adresses de métadonnées) sont confinées au lecteur.
L'extracteur .NET repose sur Reclaimer ; les lecteurs Python sur les définitions Reclaimer,
Supyr Struct, Binilla et Arbytmap. Le module relève de GPL-3.0, comme son dépôt parent.
Les bibliothèques externes gardent leurs licences dans leurs dossiers séparés.

`work/`, `tools/`, `build/`, les binaires, les données et sources du jeu ne sont pas
versionnés. Cette livraison est un module source ; l'empaquetage autonome et l'intégration
à CyDecompilator restent des travaux ultérieurs.


## Arrivée A30, ennemis et HUD Anniversary

La nouvelle étape est décrite dans [docs/ARRIVAL_FIXES.md](docs/ARRIVAL_FIXES.md).
`recover-arrival` récupère le HUD partagé, les poses cinématiques et 63
enregistrements ; `convert-arrival` prépare les FBX ; `arrival` importe les
assets ; `level --map a30` place les acteurs de scénario ; `validate-arrival`
rejoue l’introduction et le premier dropship, puis contrôle les captures.
Les sept passagers de `lz_search/cship_toon` viennent du scénario d’origine.
Leur arrivée et leur départ remplacent les apparitions sans transport.

L’interface affiche le bouclier, la santé, les munitions, le radar et le
réticule à partir des textures du jeu Anniversary. Entrée passe l’introduction.
La physique de vol reste une adaptation à Unreal ; les limites précises et les
commandes de reproduction sont dans le document ci-dessus.

Pour les pixels HUD et leur validation, utiliser un Python avec l’extra
`assets` (Pillow), ou transmettre `--image-python <chemin-python-avec-Pillow>`.
Les journaux d’une partie normale ne remplacent plus les preuves de campagne.


## Mode de test du combat

Le joueur est invincible par défaut ; **F10** active/désactive ce réglage.
La réapparition restaure l'invincibilité de test. Les IA actives se
repositionnent au combat et leurs tirs ont des effets visibles.
Détails et limites : [docs/COMBAT_TEST_FIXES.md](docs/COMBAT_TEST_FIXES.md).


## Armes, inventaire et présentation des unités

La récupération des animations directionnelles, des morts, des dialogues,
des six armes et des objets placés est détaillée dans
[docs/COMBAT_PRESENTATION.md](docs/COMBAT_PRESENTATION.md).
Le rendu reste Anniversary ; cette étape ajoute des assets sous
`/Game/Recovered/Combat` et conserve les maps approuvées.

Commandes : **E** ramasse une arme ; **1/2**, **Tab** ou la molette changent
d’arme ; **R** recharge ; **G** lance une grenade. **F10** bascule
l’invincibilité de test. Les effets et les contrôleurs Unreal sont des
reconstructions ; les limites sont indiquées dans le document.
