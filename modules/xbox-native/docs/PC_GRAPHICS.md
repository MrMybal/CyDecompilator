# Animations et effets PC

## Rendu Anniversary noir : correction 2026-10-21.1

Sur le XEX SHA-256 `1412845884eba9eb61cdc00213ca3777be19c71f6196faea69e435a350fd3f19`,
le mode remasterisé Saber exige les réglages suivants avec le plugin personnalisé :
`native_querybatch_range=256`, `readback_resolve=full`,
`gamma_render_target_as_unorm16=false`, `gpu_allow_invalid_fetch_constants=true`,
`occlusion_query_enable=true` et `query_occlusion_fake_sample_count=0`.
Le lancement intégré applique ces options à ce profil seulement. Le chemin RTV normal
convient ; passer uniquement en ROV ne résout pas cet écran noir.

Les écritures Z-pass sont des snapshots cumulatifs. Les surveys QueryBatch de Saber
ne se réduisent pas à une paire de blocs adjacents. Le gestionnaire matériel conserve
les segments traversant plusieurs listes et exclut les passes de capture RT des compteurs.
La plage positive 256 active cependant un **repli synthétique borné**, compatible avec
la visibilité de Saber ; elle ne fournit pas une occlusion géométrique exacte des flares.
La valeur 0 réactive les snapshots matériels. Les flares traversants restent à corriger.
Les readbacks complets corrigent l'exposition/HDR côté CPU mais peuvent coûter beaucoup
de performances. Ne pas les remplacer par `fast` sur la seule base d'une scène déjà chargée.

Validation visuelle en jeu : salle de réveil `a10` et plage `b30`, bascule Classic/Anniversary,
RT désactivé. Cela ne valide ni toute la campagne, ni le RT, ni la coop. Les captures et
empreintes locales sont dans `data/reports/halo-anniversary-fix.json`.

**Lancer une carte directement.** Le prototype accepte `Play-Halo.cmd --map b30` et fournit
`Play-Halo-Carte.cmd`. Il passe par le frontend de campagne, avec impulsions A temporaires,
puis remplace le nom dans **LoadLevelSolo et Saber LoadLevel**. Changer uniquement
`map_name` laisse le menu ou la scène Saber précédente ; remplacer seulement LoadLevelSolo
peut charger deux cartes différentes entre Blam et Saber. Les chaînes invitées doivent
conserver leur allocation, leur compteur de références et le contexte PPC. Les hooks sont
liés à cette empreinte XEX. Le lancement direct est solo ; la coop conserve la sélection normale.
Le `game.cfg` extrait localement désactive la vidéo de démarrage ; sa copie précédente est
conservée sous `work/gpu-occlusion/anniversary-original-game.cfg`.

Référence : [suivi officiel Xenia Canary, Halo Anniversary](https://github.com/xenia-canary/game-compatibility/issues/552),
notamment les observations QueryBatch et readback/gamma. Ces contournements documentés
ont été adaptés au runtime recompilé ; aucun processus Xenia n'est lancé.


Ces extensions concernent le Halo Anniversary `14128458…` recompilé dans le
module indépendant. Lancer `Play-Halo.cmd`, puis ouvrir les réglages avec F2.

## Occlusion et visibilité RT — version 2026-10-20.8

La session `1d519acc74f4` désactivait définitivement les requêtes d'occlusion dès
`02:03:33` après un snapshot de fin sans début (`1F7EE000`). Le backend utilisait
ensuite la visibilité fixe 1000, ce qui explique les flares à travers les objets.
Le nouveau gestionnaire écrit zéro pour un snapshot orphelin et conserve le tas
de requêtes. Une requête traversant plusieurs soumissions GPU est découpée en
segments hôtes, résolus puis additionnés après leur fence. Le lanceur impose
également zéro comme résultat de repli : un échec ne force plus un flare visible.
Cela conserve les requêtes réelles ; ce n'est pas une suppression globale des flares.
Le découpage respecte les [contraintes des requêtes D3D12](https://learn.microsoft.com/en-us/windows/win32/direct3d12/queries),
dont les paires begin/end doivent rester dans une même liste de commandes.

Le RT rejoue désormais les shaders dans leurs coordonnées écran d'origine vers
une profondeur native D32. Les intersections primaires sont validées contre
cette référence raster, qui conserve le test alpha sans dépendre des petites
tuiles de matériaux. Les intersections secondaires de matériaux masqués utilisent
aussi cette référence lorsque la surface est visible de la caméra. La capture
sélectionne un viewport perspective et une cible de profondeur ; les vues de
rapport différent, les autres cibles et les plages de profondeur réduites sont
exclues. Les triangles traversant le plan proche ne sont plus rejetés en bloc.

Limites supplémentaires : référence de profondeur 2048×2048, sélection d'une
seule vue et d'une cible par image ; les triangles hors des passes sélectionnées
restent absents. Le stencil et les plans de coupe personnalisés ne sont pas
reconstitués. Les matériaux hors visibilité caméra gardent l'approximation de
la .7. Les lumières physiques et matériaux PBR complets restent à reconstruire.

Le contrôle court compile le véritable gestionnaire de snapshots avec mémoire
simulée (fin orpheline → paire valide → visibilité nulle). Le contrôle GPU vérifie
la référence de profondeur, les découpes de texture, les couleurs HDR et la
transparence. La compilation jouable est fournie pour l'essai de l'utilisateur ;
aucune nouvelle session Halo n'est lancée automatiquement.

## Matériaux RT et débruitage — version 2026-10-20.7

La capture de triangles seule de la .6 traitait les polygones du feuillage comme
des surfaces opaques. La .7 rejoue le **pixel shader d'origine**, avec ses
textures, constantes et interpolateurs, dans un atlas HDR de matériaux. Chaque
triangle dispose d'une tuile de 16×16 pixels. Les fragments éliminés par `discard`
ou par le test alpha conservent une sentinelle ; les requêtes DXR rejettent ces
candidats puis poursuivent la recherche. L'alpha nul d'un matériau opaque reste
opaque : le mode de mélange détermine l'interprétation de l'alpha.

Les surfaces mélangées utilisent une acceptation stochastique selon leur alpha.
Les couleurs prémultipliées et les couches additives sont distinguées ; les
couches additives ne deviennent pas des obstacles pour l'occlusion ambiante.
La radiance HDR des shaders alimente les rebonds et les reflets, y compris les
contributions lumineuses déjà présentes dans ces shaders. **Le canal émissif
séparé et les lumières physiques d'origine ne sont pas encore reconstruits.**
Ce chemin n'est donc pas un rendu complet équivalent à RTX Remix.

L'illumination RT et ses guides profondeur/normales sont stockés séparément.
Deux passes bilatérales spatiales filtrent uniquement la contribution RT,
avant composition sur l'image d'origine. Il n'y a pas d'accumulation temporelle
ni de débruiteur NRD. L'occlusion est limitée à 28 % au réglage maximal ; les
pixels très lumineux sont préservés. Les reflets ajoutent une contribution et
ne remplacent plus l'image par un environnement sombre inventé.

Limites : atlas de 131 072 triangles par image, résolution de masque de 16×16
par triangle, choix de mip/effets dépendant de la position écran approximatifs,
matériaux extraits des passes RTV seulement, géométrie issue des dessins du jeu
(pas de scène persistante hors des dessins soumis). Les shaders à effets de bord
UAV/ROV sont exclus. Les dessins sous requête d'occlusion sont exclus pour ne
pas fausser les lens flares. Les cibles, viewport et scissor sont restaurés après
chaque capture.

Le lanceur active `gpu_allow_invalid_fetch_constants=true` : les journaux de la
session `6b900b252c7c` montraient que le backend refusait des descripteurs de
textures Anniversary. Ce contournement doit encore être confirmé sur ce mode ;
la capture noire fournie affichait déjà RT OFF.

Compilation et contrôle GPU court avec texture, découpe alpha, radiance HDR,
alpha nul opaque et couches transparentes ; aucune session Halo automatique.
Le résultat visuel dans les deux modes reste à vérifier par l'utilisateur.
Voir la [spécification DXR de Microsoft](https://microsoft.github.io/DirectX-Specs/d3d/Raytracing.html)
pour le traitement des candidats non opaques.

## Anti-aliasing natif

F2 propose Désactivé, FXAA, FXAA fort et **SMAA 1x High**, actif par défaut.
Le changement prend effet pendant le jeu ; « Enregistrer » conserve le choix
dans `data/user/pc-input.toml` (`antialiasing = 0/1/2/3`).

Le plugin Direct3D 12 exécute trois passes : contours, poids, mélange de voisinage.
La [référence SMAA](https://github.com/iryoku/smaa) est figée au commit
`71c806a838bdd7d517df19192a20f0c61b3ca29d`. Les tables Area/Search, la licence MIT
et les empreintes sont dans `third_party/smaa/`. `scripts/build_smaa.py` compile
les shaders avec `fxc.exe` du SDK Windows. Il s'agit de SMAA spatial 1x.

Le traitement suit la correction gamma et précède la présentation et le panneau
PC. Les captures GPU du module incluent cet anti-aliasing. Les ressources suivent
la résolution et sont libérées après leur dernière soumission GPU. Les cinq SRV
sont liés individuellement : le recycleur bindless ne garantit pas leur contiguïté.
Un échec de création des ressources est journalisé et utilise le FXAA existant.

Reconstruction depuis la racine du dépôt :

```powershell
runtime/python/Scripts/python.exe modules/xbox-native/scripts/rex_gpu_diagnostics.py --source runtime/engines/rexglue/source --sdk runtime/engines/rexglue/0.10.0/win-amd64 --fix-occlusion
```

Copier ensuite le DLL indiqué par `work/gpu-occlusion/plugin.json` dans le
répertoire `build` du projet local, jeu fermé. Le plugin conserve le correctif
d'occlusion des lens flares et le compteur des swaps.

## Interpolation des animations

La case F2 « Interpolation des animations » est active par défaut et se conserve
dans `interpolate_animations`. Positions et échelles sont interpolées linéairement,
rotations par quaternion sur le chemin court. La simulation reste à 30 Hz.

Les hooks `82C547F0` et `82C54908` traitent les copies de matrices exportées à
Saber. Les handles avec génération, tags, nombres de nœuds, changements de tick
et déplacements brusques invalident l'historique. L'export racine signale un
changement lorsque la pose visuelle évolue entre deux ticks.

Le rendu classique passait aussi directement par `object_get_node_matrices`
(`822DFBF0`). Il est maintenant couvert aux deux appels de dessin
`82CB58D8` / `82CB5968` : chaque dessin `82CB5688` possède une copie temporaire
adressable par le code invité. Elle contient les positions et rotations
intermédiaires du squelette, y compris sa translation dans le monde. Les lectures
de simulation et de collision continuent à recevoir les matrices originales.
Chaque dessin imbriqué possède son propre espace temporaire ; les historiques
Saber et classique sont distincts. Cela corrige un chemin manquant qui pouvait
laisser les ennemis avancer à 30 étapes par seconde malgré une arme fluide.

En première personne, le hook `82D14D80` est restreint à l'appel `82C7A774` :
poses locales après les couches d'animation, avant la caméra actuelle. Les octets
d'origine sont restaurés à la sortie de la conversion. Armes, graphes, retours
arrière des ticks et interruptions réinitialisent l'historique. La caméra souris
conserve son calcul direct. L'interpolation des deux derniers ticks ajoute
jusqu'à un tick de retard visuel aux poses.

`scripts/check_rex_controls.py` exécute la véritable conversion recompilée sur
des poses contrôlées et vérifie positions intermédiaires, rotation, échelle,
téléportations, remplacement d'un modèle, désactivation et restauration exacte.
Il exécute aussi le véritable getter classique et vérifie deux positions de rendu
dans un même tick, la préservation exacte des matrices sources et la pile.
Le mode facultatif `native_input_probe=true` journalise quelques poses réelles ;
il reste désactivé dans le lanceur.

### Cadence de simulation

La logique de jeu reste à **30 Hz**. Le déblocage complet n'est pas implémenté.
Depuis la version 2026-10-20.2, la version jouable subdivise la physique et les
collisions des personnages à **60 Hz par défaut**, ou 30/120 Hz au choix dans F2.
L'IA, les scripts et les véhicules ne passent pas à cette cadence supérieure.
Dans cette image, `822D1D80` calcule les ticks à partir de la constante 30
(`820009E8`) et la physique des bipèdes utilise encore `1/30`
(`82000A34`, notamment `82D393C4` / `82D3A79C`). Les scripts, animations et délais
utilisent aussi des compteurs entiers. Augmenter seulement la fréquence de
l'ordonnanceur accélérerait le jeu. Un vrai changement de cadence nécessite
d'adapter et valider ces dépendances, en plus de l'affichage interpolé.

L'[essai de conversion des unités](SIMULATION_TIMING.md) exécute maintenant les
vraies fonctions recompilées : ordonnanceur, compteur de bipède et physique
aérienne à 30/60/120 pas par seconde. Ce dernier noyau conserve vitesse et gravité
après conversion ; le déblocage complet reste à intégrer et valider.

### Affichage et cinématiques — version 2026-10-20.3

Le lanceur démarre désormais en plein écran avec `present_letterbox=false` :
l'image remplit la surface en l'étirant, y compris sur un écran ultralarge.
Ce mode ne modifie pas la projection 3D pour créer un champ de vision ultralarge.
F2 permet de revenir en fenêtre et de rétablir le format d'origine avec bandes.
La conversion des coordonnées des clics suit le mode d'affichage choisi.

Un hook dans le constructeur des caméras de rendu `822CAB58` interpole position,
orientation et champ de vision pendant les cinématiques. Il écrit les deux copies
de rendu, sans modifier la caméra de simulation ni ralentir la visée à la souris.
Les discontinuités importantes réinitialisent l'historique. Le seuil de déplacement
des poses d'objets est élargi pendant les cinématiques pour ne pas rejeter les
vaisseaux rapides comme des téléportations. Les sous-pas des bipèdes sont suspendus
pendant ces séquences pour conserver les déplacements scriptés d'origine.

Cette version est compilée pour essai par l'utilisateur. Le résultat visuel sur
le vaisseau de la cinématique d'ouverture reste à confirmer en jeu.

## Mise à jour 2026-10-20.6 : capture RT et comparaison F3

Le journal réel `runs/19868105eb7a/runtime.log` montre que la version .5
initialisait DXR mais refusait ses pipelines de capture avec `80070057`. Aucun
effet ne pouvait donc apparaître. Le geometry shader supposait SV_Position au
registre 0, alors que les vertex shaders Xbox placent d'abord leurs interpolateurs.
La version .6 lit la signature de sortie réelle et sélectionne une variante
compatible entre 0 et 16 interpolateurs. Le contrôle GPU reproduit le refus de
l'ancienne signature avec SV_Position au registre 16 et valide la nouvelle.

F3 bascule le maître de tous les effets RT natifs ; l'état reste affiché près des
FPS même si le compteur FPS est masqué. Une capture refusée est signalée comme
une erreur. F2 propose une vue de la géométrie RT pour vérifier directement la
couverture des triangles, ainsi que les effets séparés : AO, reflets expérimentaux
et rebonds diffus à partir de la couleur visible.

Les intersections des reflets et rebonds utilisent DXR sur les vrais triangles.
Leur éclairage reste approximatif : faute d'accès aux matériaux et aux lumières
d'origine, la couleur raster est échantillonnée lorsqu'un impact est visible.
Les reflets hors écran utilisent une couleur d'environnement constante et les
rebonds hors écran n'ajoutent pas de lumière. La rugosité est globale. Cette
version n'est donc pas un rendu complet de type RTX Remix : matériaux PBR,
éclairage original, transparences exactes et éclairage indirect complet restent
à intégrer. Les nouveaux effets sont explicitement expérimentaux dans F2.

L'exécutable et les shaders sont compilés. Le contrôle GPU borné passe, y compris
le cas de signature qui manquait à la version .5. Aucune nouvelle session de Halo
n'a été lancée : le rendu des scènes réelles est laissé à l'utilisateur.

## Ray tracing natif DXR — première version 2026-10-20.5

Le panneau F2 propose « Ray tracing natif DXR : occlusion ambiante », désactivé
initialement, avec intensité et portée réglables et enregistrables. Ce chemin
s'exécute dans `rexgpu-xenos-occlusion.dll`, indépendamment de ReShade. Il exige
DXR 1.1 ; une carte incompatible ou une erreur d'initialisation conserve le rendu
raster normal avec un état explicite dans F2.

Le plugin récupère les vrais triangles à la sortie du vertex shader avec une
passe de geometry shader et stream output avant clipping. Les passes doivent
écrire la profondeur, sans memexport, tessellation ni geometry shader préexistant.
Il annule la conversion NDC de ReXGlue et utilise la projection de la caméra du
jeu pour exprimer les sommets en espace vue. Aucun tampon de profondeur 2D n'est
utilisé pour recréer la géométrie. Les structures BLAS/TLAS sont reconstruites
à chaque image ; un shader SM6.5 lance les rayons primaires puis quatre rayons
d'occlusion par pixel via les requêtes DXR matérielles. Le résultat assombrit
localement la couleur raster après l'anti-aliasing, avant le présentateur.

Ce premier mode calcule l'occlusion ambiante. Les réflexions, la lumière indirecte
avec matériaux, les sources lumineuses et un rendu intégral comme RTX Remix
restent à développer. La scène contient les triangles soumis par le jeu, jusqu'à
524 288 triangles : le culling CPU, les végétations avec alpha et les passes non
capturées limitent le résultat. Le HUD, déjà composité, n'est pas encore isolé.
L'activation initiale compile des pipelines supplémentaires et la capture ajoute
un coût GPU. Le rendu sur les scènes réelles de Halo reste à valider.

Le contrôle GPU sans fenêtre a exécuté le chemin capture → BLAS/TLAS → DXR sur
une scène de contrôle de 64×64 pixels : 272 pixels occlus, 3 824 pixels non
occlus, aucun changement d'alpha. Reçu : `work/gpu-occlusion/native-rt-check.log`.
Il ne s'agit pas d'un essai du jeu. Les shaders, le plugin et l'exécutable jouable
ont été compilés, sans nouvelle session prolongée de Halo.

Reconstruction du plugin local, sans modifier le SDK :

```powershell
runtime/python/Scripts/python.exe modules/xbox-native/scripts/rex_gpu_diagnostics.py --source runtime/engines/rexglue/source --sdk runtime/engines/rexglue/0.10.0/win-amd64 --fix-occlusion
runtime/python/Scripts/python.exe modules/xbox-native/scripts/install_native_gpu.py
```

L'installation préserve une copie du plugin précédent et vérifie son reçu de
compilation. Le build du jeu réinstalle également le dernier plugin local connu.

Voir l'[API DXR de Microsoft](https://microsoft.github.io/DirectX-Specs/d3d/Raytracing.html).

### Véhicules et caméra — version 2026-10-20.4

Le constructeur de caméras de rendu `822CAB58` interpole désormais aussi la
position, l'orientation et le champ de vision du joueur dans un véhicule.
L'identification utilise la correspondance locale de `822DB338`, le handle du
joueur, son unité et son parent véhicule, en vérifiant les générations des handles.
Les changements de véhicule et les transitions cinématique/jeu effacent l'historique.
Les poses de véhicules ont une option indépendante dans F2 et un seuil de
téléportation de 16 unités par tick, au lieu des 2,5 unités des bipèdes.
La simulation véhicule et les collisions restent à leur cadence d'origine.

## Ancien effet ReShade SSRTGI facultatif

`native/reshade/HaloSSRTGI.fx` ajoute des rayons dans la profondeur visible pour
estimer un rebond diffus de lumière et l'occlusion ambiante. Il calcule à
demi-résolution avec 4/8/12 rayons, 8/12/20 étapes et une recherche d'intersection
raffinée. Le résultat est filtré selon la profondeur, sans accumulation temporelle.
La scène hors écran n'est pas disponible. Le HUD et les éléments transparents,
déjà composités dans l'image, ne sont pas séparés de cet effet.

F7 active/désactive l'effet, initialement désactivé. Home permet de choisir
HaloSSRTGI et ses réglages. Les diagnostics affichent profondeur, normales et
contribution lumineuse. Rouge dans les diagnostics signifie que ReShade ne
fournit pas de profondeur ; l'image finale reste alors inchangée. Le sens de
profondeur et l'encodage D24F peuvent nécessiter un réglage selon le chemin GPU.

Il s'agit d'un effet en espace écran, **pas de ray tracing matériel DXR**.
Cet effet n'utilise pas les structures d'accélération du nouveau chemin natif.

Installation locale :

```powershell
runtime/python/Scripts/python.exe modules/xbox-native/scripts/setup_ssrtgi.py
```

Le script conserve le preset existant et en crée une sauvegarde avant ajout du
raccourci. Son installation reste séparée du ray tracing natif. Les trois
entrées de shader ont été compilées en DXBC SM5 avec le compilateur ReShade 6.8.0
épinglé au commit `18deaa52de0c425a78b329e9cb3c497281cd00ec`.
La compilation du jeu a réussi. Aucune nouvelle session de jeu n'a été lancée :
la fluidité en véhicule et la disponibilité réelle de la profondeur restent à
confirmer par l'utilisateur.

## ReShade : couleur et netteté

[ReShade](https://reshade.me/) 6.8.0 se charge localement en proxy DXGI x64,
à côté de l'EXE. **Home / Début** ouvre ses réglages ; Arrêt défil / Scroll Lock
active ou désactive les effets. Le preset fourni est neutre et propose contraste,
saturation et netteté. Ces effets ne nécessitent pas la profondeur du jeu.

Installation ou réactivation, depuis la racine :

```powershell
runtime/python/Scripts/python.exe modules/xbox-native/scripts/setup_reshade.py
```

Désactivation de ReShade seul, jeu fermé :

```powershell
runtime/python/Scripts/python.exe modules/xbox-native/scripts/setup_reshade.py --disable
```

Le script vérifie le certificat éditeur publié par le site officiel, refuse un
proxy DXGI différent et préserve les réglages existants. Aucun pilote ni composant
Vulkan global n'est installé. Les téléchargements restent dans `work/`, exclu de
Git. Le SMAA natif fonctionne aussi lorsque ReShade est désactivé.
