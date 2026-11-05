# Halo — voie native ReXGlue

État de validation : **rendu et scène de réveil de la campagne confirmés par
l'utilisateur**, avec capture du jeu. L'utilisateur confirme ensuite que le reste
fonctionne correctement et demande les améliorations de commandes PC ci-dessous.
Une mission complète avec traces instrumentées reste à valider. Le multijoueur
n'est pas pris en charge et sa sélection a provoqué un arrêt.

Le 19 octobre, la reprise de la mission « Halo » est aussi vérifiée dans un essai
isolé avec un profil copié. Les clics réels transmis à GFx ouvrent « Extras »,
« Campaign » puis « Resume Game ». Deux mouvements relatifs de +160 et -160 pixels
sont consommés par le calcul de regard du joueur et produisent respectivement
-0,32 et +0,32 radian ; les lectures GPU montrent la rotation puis son retour.
Le ressenti de la souris physique reste à apprécier sur le bureau utilisateur.

Le plafond de présentation à 29,97 FPS a été identifié dans `823D7150`. La VSync
seule ne le supprimait pas. Les deux seuils d'attente sont maintenant optionnels,
avec conservation de la mesure de temps écoulé. Sur la RTX 3090 du poste, l'essai
final enregistre une médiane de 300,85 FPS au menu (48 mesures) et 184,88 FPS dans
la scène de campagne (50 mesures, minimum 127,91, maximum 201,88). Ces valeurs
caractérisent cette scène et cette machine, sans garantir une cadence universelle.

EXE testé : `0a1e633e33c3c95d120f9f9e188862cb95ac64c5487131b3c91ae6eb9212472e`.
Reçu détaillé : `work/halo-rex/project/pc-improvements.json`. Les essais sont sous
`runtime-probes/`, avec copies de profil, journaux et captures GPU. L'instance de
test est arrêtée par son lanceur ; aucune fenêtre n'est ouverte sur le bureau
utilisateur. Les 36 tests Python et les contrôles natifs de commandes passent.

## Identité et dépendances

- XEX : `1412845884eba9eb61cdc00213ca3777be19c71f6196faea69e435a350fd3f19`.
- Image analysée : `5c1b2f1f3f02077d51d8997d9d9f113fd09816e110b6b58531f04c2b022b869a`.
- SDK officiel [ReXGlue 0.10.0](https://github.com/rexglue/rexglue-sdk/releases/tag/v0.10.0).
- Archive Windows : SHA-256 `ad4485da853fbe932e9f5dbb643f9b5fe85dc73775ebbad4df6879fe6df0c11b`.
- Sources de référence du SDK : commit `f5337cdc947ff6d4c4196737e2c807a48f2a1fc2`.
- Clang 19.1.5, CMake/Ninja, bibliothèques MSVC et SDK Windows.

Le projet est sous `work/halo-rex/project`, avec 448 fichiers de données extraits
du disque dans `work/halo-rex/game` (7 998 712 525 octets). Les originaux restent
préservés. Les binaires, sources traduites et données du jeu sont ignorés par Git.

Le CPU est traduit statiquement en C++ puis en code machine PC. Les API Xbox sont
réimplémentées par le runtime ; le plugin Xenos traduit le matériel graphique vers
Direct3D 12. Aucun exécutable d'émulateur n'est lancé. Le runtime comporte encore
des fonctions incomplètes : sa présence ne garantit pas la compatibilité d'un jeu.

## Adaptations locales

Le profil principal et ses fichiers inclus sont limités à l'identité exacte du XEX.
Ils ajoutent des points d'entrée au traducteur, sans remplacer le comportement des
instructions du jeu par des résultats inventés.

- 21 entrées nécessaires à la validation initiale des branchements.
- Trois constructeurs statiques absents de la table native : `833FAD28`,
  `833FAD48`, `833FAD68`. Le tableau d'origine contient 863 adresses dans
  `834310DC..83431E58`, dont 860 étaient déjà enregistrées.
- 143 méthodes de tables virtuelles sans RTTI : quatre ont été rencontrées dans
  un essai natif, les autres proviennent de tables effectivement installées dans
  les objets par des instructions `lis/addi/stw`. Les entrées internes à une
  fonction `.pdata` sont exclues de cette recherche.
- 68 callbacks et relais supplémentaires : adresses construites puis stockées
  ou passées comme arguments, et séquences complètes de relais d'appel virtuel.
  Le candidat `83428768`, initialement laissé à examiner, a ensuite été appelé
  par quatre threads pendant un essai natif. Cette fonction de `PSFD00` est
  ajoutée avec ses 172 octets jusqu'au dispatch terminal ; les deux destinations
  de sa table de dispatch possèdent déjà une implémentation recompilée.

`native/rex_seh.h` inclut l'en-tête de gestion des exceptions omis par le PCH
généré du SDK. Les exceptions natives restent actives. Deux `bdz` du jeu ciblent
un mot nul à `8317EE64` ; le post-traitement remplace les retours silencieux du
générateur par des traps conditionnels. Il refuse les autres branchements externes
non examinés. Les journaux et reçus conservent les empreintes avant/après.

## Essais natifs observés

| Tentative | Résultat constaté |
|---|---|
| `660335772246` | D3D12 sur RTX 3090, audio, VFS et imports initialisés ; arrêt sur `833FAD28` non enregistré |
| `13e69e8d1b47` | Constructeurs franchis, threads de jeu créés et callback GPU installé ; arrêt sur `82A4DB18` |
| `6ea1bb3d2e46` | Thread `UI_LOADING_SCREEN_THREAD` créé ; arrêt sur `826C36E8` |
| `bceac9aecd84` | Création de pipelines graphiques, activité audio et chargement plus avancé ; arrêt des workers sur `83428768` |
| `2e111b664986` | Fenêtre interactive et scène de réveil confirmées par l'utilisateur ; sortie normale |
| `0b8bebaacb73` | Souris activée par option ; capture de sortie GPU 1152 × 648 enregistrée |
| `76320d23ba15` | Diagnostic : fin d'occlusion à `1FC90080`, début à `1FC900A0` ; le SDK abandonne alors les requêtes matérielles |
| `8cde538cfdad` | Correctif des deux enregistrements adjacents : plus de 1 000 résultats matériels lus ; arrêt lors de la sélection du multijoueur, code `C0000374` |

Le premier affichage du jeu est désormais confirmé, mais les premières traces
de démarrage seules ne suffisaient pas à le démontrer. La validation continue
porte sur une mission interactive, la souris et les effets graphiques.

## Missions et commandes de test

`Play-Halo.cmd` ouvre une fenêtre 1152 × 648, avec le curseur libéré au démarrage.
Menus : souris ou flèches, Espace pour valider, Retour arrière pour revenir.
F2 ouvre les réglages PC, Échap fournit Start pour la pause et F6 capture ou
libère le regard à la souris. SDL utilise les positions physiques : WASD devient
ZQSD sur AZERTY. Clic gauche = RT/tir ; clic droit = stick droit/zoom ; G = LT/grenade.
Les clics sont désormais transmis à l'interface GFx du jeu. Un compteur des images
du jeu est affiché en haut à droite. Voir [commandes PC et vérification](PC_CONTROLS.md).

Le profil local `data/user/4D5309B1/profile/User/63E83FFD` contient 698 octets,
une version 3 à l'offset 4 et le masque de missions à l'offset 8. La fonction
`IsMapUnlocked` à `8236A380` lit ce masque à `this+0x14` ; la charge sérialisée
commence à `this+0x0C`. Le mot initial correspond exactement au CRC32 des octets
4 à la fin. `scripts/unlock_halo_missions.py` vérifie ces conditions, sauvegarde
le profil, applique le masque `03FF`, puis recalcule le CRC. Exécuter jeu fermé.
Le reçu local `mission-unlock.json` confirme le passage `0001` → `03FF`.
Les autres données de progression sont préservées. La liste des missions doit
encore être constatée à l'écran après ce changement persistant.

Un premier correctif facultatif du seul callback de menu existe aussi, mais il
est désactivé dans le lanceur : le déblocage persistant du profil le remplace.

## Occlusion des lens flares

Le plugin officiel compare pour égalité les adresses des snapshots de début et
de fin. Le jeu utilise deux enregistrements adjacents de 32 octets. Cette égalité
échoue et le SDK renvoie ensuite sa visibilité fictive de 1 000 échantillons.
`scripts/rex_gpu_diagnostics.py --fix-occlusion` construit un plugin séparé
`rexgpu-xenos-occlusion.dll`, sans modifier le SDK installé ni son checkout.
Il accepte cette paire adjacente et écrit un snapshot initial nul, puis le résultat
matériel final pour le calcul de différence par le jeu. Il ne force pas les résultats
à zéro et ne désactive pas les flares. Le lanceur sélectionne ce plugin local.

Empreinte du premier plugin testé : `bc5f499eb6f7c97e84eeffe59d0b17c92fac777ccd497e0a0d9e9f5ee67f20a3`.
La version avec compteur des swaps est `61dd87f5a99a1f95667c3e8744b59d9844edaa4ebd1bf6592ed81cfe45728c57`.
Les résultats lus pendant le début de cet essai étaient nuls. **La correction
visuelle sur une source lumineuse visible puis masquée reste à vérifier** ; la
lecture de requêtes matérielles ne suffit pas à confirmer tout le rendu.
Le dernier avertissement d'abandon des requêtes intervient à la fermeture du titre,
après la sélection du multijoueur, et ne démontre pas un nouvel échec en cours de scène.

Le disque comprend `ReachTU1.xex` et la commande `LaunchMultiplayer()` ; un projet
séparé a été préparé, mais la demande de support compétitif a ensuite été annulée.
Il n'est pas intégré au lanceur Halo. Le journal antérieur montre `TerminateTitle` puis l'arrêt,
mais ne journalise pas le chemin du nouveau titre demandé : l'attribution exacte
du crash à cette transition reste à instrumenter. Aucun multijoueur n'est validé.

Les reçus sont `native-build.json`, `latest-run.json`, `branch-guards.json` et
`runs/<identifiant>/launch.json` avec `runtime.log`. Les sauvegardes et caches de
test sont sous `project/data/`. `rex_project.py run --wait` enregistre aussi le
code de sortie du processus. Les états de lancement ne sont pas des validations
de compatibilité et conservent `native_game_ready=false`.

## Interpolation et anti-aliasing natif — 19 octobre 2026

Le module ajoute l'interpolation des exports de matrices vers Saber et des poses
locales des bras/armes avant leur conversion par la caméra actuelle. Les rotations
utilisent des quaternions ; le compteur de simulation continue de progresser à
30 ticks par seconde. Les octets de la pose locale sont restaurés après conversion.
Les réglages se trouvent dans F2 et se conservent dans le fichier des commandes PC.

Les essais console passent la véritable conversion recompilée `82D14D80`, deux
images dans un même tick, la désactivation, la restauration bit à bit, les
téléportations et le remplacement du tag. Les 38 tests Python passent également.

L'essai réel `native-smaa-v4` reprend la mission Halo, avec ReShade désactivé.
Il mesure notamment, pour l'arme à 42 nœuds, trois valeurs rendues dans le tick
1106 : -0,031312 ; -0,030816 ; -0,030353, entre les mêmes deux positions de
simulation. Les 19 échantillons couvrent six groupes ayant plusieurs rendus par
tick ; l'écart maximal à l'interpolation linéaire est de 7,3e-7 unité.
L'essai `native-smaa-v5` démarre une autre mission sur une copie du profil et
affiche la cinématique du Pillar of Autumn. Il enregistre 32 échantillons de
personnages du monde, dont huit groupes avec plusieurs rendus par tick. L'écart
maximal de 1,5e-5 unité correspond à l'arrondi des flottants près de la coordonnée
500. Aucune mission entière ni session de combat prolongée n'est déclarée validée.

Le plugin applique **SMAA 1x High en trois passes compute**, avec les tables de
la référence MIT. Désactivé, FXAA et FXAA fort restent disponibles dans F2. Les
captures GPU et les changements à chaud ont été exercés sur les scènes réelles.
Le passage sans ReShade confirme que le SMAA est natif. Les SRV sont liés
séparément pour respecter le recycleur bindless du SDK.

ReShade officiel 6.8.0 est installé localement ; son proxy DXGI et son runtime
Direct3D 12 se chargent, et le shader couleur fourni compile. Le preset est neutre.
Le dernier essai `final-graphics-v6` confirme ce chargement conjoint avec le SMAA.
Le reçu détaillé, les empreintes et les captures restent dans
`work/halo-rex/project/graphics-improvements.json`. Les profils réels n'ont pas
été remplacés par les profils des essais. Voir [réglages et reconstruction](PC_GRAPHICS.md).

## Positions ennemies et course — 20 octobre 2026

Le rendu classique lisait les matrices originales, en dehors des exports Saber
déjà interpolés. Le nouveau hook du getter `822DFBF0` est restreint aux deux
appels de dessin et renvoie une copie temporaire par dessin `82CB5688`. Il couvre
la translation des ennemis et leurs poses ; les matrices de collision ne sont
jamais remplacées. Les historiques des deux chemins de rendu sont distincts.

L'essai isolé `enemy-sprint-v3` démarre le Cartographe silencieux sur une copie
du profil. Les échantillons nommés confirment Grunts, Élites et Rapaces.
Il contient 37 groupes ennemis avec plusieurs positions de rendu dans un même
tick pour le chemin classique, et 103 pour les exports Saber. L'écart maximal
au mélange linéaire journalisé est inférieur à 3,5e-6 unité. Le rendu classique
a été contrôlé visuellement. Le basculement vers les graphismes remastérisés
affiche des défauts noirs/cyan également présents avec l'interpolation désactivée ;
ce mode n'est donc pas déclaré visuellement validé par cet essai.

La course avec Maj multiplie la vitesse horizontale désirée du joueur local
à pied. F2 propose activation et multiplicateur ×1 à ×2, sauvegardés avec les
autres réglages. `enemy-sprint-v1` mesure un rapport médian course/marche de
1,498 pour ×1,5. Les tests console vérifient relâchement, véhicule, autre joueur,
accroupissement et remise à zéro, en plus des fonctions recompilées de rendu.

Le déblocage de la simulation complète **n'est pas réalisé**. L'ordonnanceur,
la physique à `1/30` et les compteurs de scripts/animations doivent être adaptés
ensemble pour conserver la vitesse normale du jeu. Les FPS d'affichage restent
débloqués. Le reçu local est `work/halo-rex/project/motion-improvements.json`.
