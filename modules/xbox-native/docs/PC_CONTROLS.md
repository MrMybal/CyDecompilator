# Commandes PC du portage Halo

Version 2026-10-20.9 : `Play-Halo-Coop.cmd` active deux profils locaux pour essayer
la campagne en écran partagé, clavier/souris J1 et première manette J2. Les
réglages sont dans F2. Voir [l'état de la coop et de l'IP directe](CAMPAIGN_COOP.md).

Le lanceur local reste `Play-Halo.cmd`, en plein écran par défaut depuis la
version 2026-10-20.3 ; F2 permet de revenir en fenêtre. Le jeu n'est pas
relancé automatiquement lors de l'installation de ces changements.

| Commande | Effet |
|---|---|
| Souris libre dans les menus | Survol, clic gauche, relâchement et molette transmis à l'interface Flash du jeu |
| F2 ou bouton « Clavier / souris » en haut à gauche | Réglages des touches et de la souris |
| Échap en jeu | Impulsion Start pour la pause ; libération du curseur |
| Échap dans le panneau PC | Annuler une réaffectation ou fermer le panneau |
| F6 | Capturer/libérer le regard à la souris |
| F3 | Activer/désactiver ensemble les effets ray tracing natifs choisis dans F2 |
| Entrée pendant une cinématique skippable | Demander le passage via le mécanisme normal de scripts du jeu |
| F7 | Basculer l'effet SSRTGI expérimental, si ReShade est installé et actif |
| Home / Début | Réglages ReShade, dont HaloSSRTGI |
| F2 → Ray tracing natif DXR | Activer l'occlusion ambiante matérielle ; régler son intensité et sa portée |
| Maj maintenue + avancer, à pied | Courir (vitesse par défaut ×1,5) |
| FPS en haut à droite | Images produites par le jeu, moyennées sur 0,5 seconde |

Le panneau permet de changer la sensibilité, réaffecter les actions par une touche
ou un clic, afficher/masquer les FPS, activer le déblocage de cadence et restaurer les touches par défaut. Le bouton
« Enregistrer » conserve les réglages dans `project/data/user/pc-input.toml`.
Une réaffectation de touche est enregistrée immédiatement. Les noms AZERTY
permettent notamment d'afficher ZQSD pour les positions physiques WASD utilisées
par SDL. F2, F6, F8 et Échap restent réservés aux raccourcis PC.

Quand le panneau est ouvert depuis le regard capturé, il envoie Start pour mettre
le jeu en pause, puis une nouvelle impulsion à sa fermeture. Les entrées ordinaires
sont bloquées pendant l'édition ; les touches de pause sont fournies par un petit
périphérique synthétique indépendant. Une perte de focus annule ses impulsions.

## Pont vers les menus existants

Le pont est limité au XEX Halo identifié dans le rapport ReXGlue. Avant le
`GFxMovieRoot::Advance` recompilé à `822CB8C8`, il transmet les événements à
la fonction `HandleEvent` existante à `82ACE988`, sur le thread du jeu.
Il vérifie la table virtuelle `82006680` et active le premier curseur si nécessaire.
Les événements ont 24 octets : type, x, y, molette, bouton et index de souris.
Les types vérifiés sont 1/déplacement, 2/appui, 3/relâchement et 4/molette.
Le précédent pont inversait appui et relâchement. Le test compare désormais ses
événements à ceux produits par le véritable `NotifyMouseState` recompilé : le
drapeau de file `0x80` désigne le relâchement.

Le jeu envoie également les positions et boutons de deux souris virtuelles
Kinect à chaque image, parfois hors écran. Ces entrées annulaient les clics PC.
Quand le curseur PC est libre et utilisé, le pont réserve les entrées souris :
il filtre ces événements virtuels dans `NotifyMouseState` et `HandleEvent`.
Les appels provenant du pont restent autorisés par une garde locale au thread.
Les entrées virtuelles reprennent en mode regard ou après perte de focus.

Les coordonnées physiques de la fenêtre sont converties vers le viewport du jeu,
y compris les bandes noires. Les événements sont diffusés aux films actifs sans
rejouer un clic ancien dans un nouveau film. Les mouvements sont regroupés et
la file est bornée. Tous les registres PowerPC sont préservés autour de l'appel.
Le panneau PC intercepte ses propres clics et les clics de menu n'actionnent pas
les gâchettes de tir. En mode regard capturé, ils restent des commandes de jeu.

Le compteur FPS vient d'un compteur atomique ajouté au traitement des commandes
`XE_SWAP` du plugin graphique local. Il ne mesure pas les rafraîchissements du
panneau ImGui. Le plugin expose `rex_gpu_guest_frame_count` pour cette lecture.

## Cadence et visée

Le lanceur désactive la VSync du runtime. Cela seul ne débloquait pas le menu :
`823D7150` attend encore une durée calculée à partir de la constante 29,97 Hz.
Le correctif retire uniquement les deux seuils d'attente de présentation dans
cette fonction. Le calcul du temps réellement écoulé reste exécuté. Il désactive
aussi la VSync à demi-fréquence dans l'objet de réglages vidéo du jeu, après sa
lecture. La case F2 « Débloquer la limite de 30 FPS » permet de revenir au limiteur.
Les FPS réellement atteints dépendent de la scène et du matériel.

La souris ne produit plus un axe de stick soumis à une zone morte et à une courbe
d'accélération. Ses déplacements relatifs, y compris les fractions de pixel, sont
consommés dans le calcul de regard `82C6E3F8`, sur ses deux chemins autorisant
l'entrée du joueur. Le gain est de 0,002 radian par pixel à sensibilité 1.
Les deltas sont consommés une seule fois et ne sont pas multipliés par le temps
d'image. Les mouvements datant de plus de 150 ms sont abandonnés ; la perte de
focus, la pause et l'ouverture du panneau effacent les mouvements en attente.

## Course avec Maj

F2 permet d'activer la course et de régler son multiplicateur entre ×1 et ×2.
« Enregistrer » conserve `sprint` et `sprint_multiplier` dans `pc-input.toml`.
La course demande le regard souris capturé, un déplacement vers l'avant et un
joueur à pied, debout. Relâcher Maj, ouvrir les réglages, mettre en pause ou perdre
le focus arrête la commande de course.

Les deux chemins de physique des bipèdes chargent la vitesse de leur joueur à
`82D39310` et `82D3A6E8`. Le correctif multiplie uniquement cette vitesse désirée
pour le joueur local zéro et conserve ses modificateurs existants. Il ne change
ni les tags, ni la vitesse des ennemis, des véhicules, des armes ou du temps.
Un essai de déplacement sur la plage du Cartographe silencieux a mesuré un
rapport de vitesse horizontale de **1,498** pour le réglage ×1,5.

La version **2026-10-20.2**, affichée dans F2, corrige aussi le chemin clavier :
le pilote exigeait un accord exact de modificateurs, donc Maj rendait « Avancer »
inactif. Le module ajoute les alternatives avec Maj aux commandes simples dans
la configuration runtime, tout en affichant et sauvegardant les touches choisies
par l'utilisateur. Les accords explicitement affectés restent prioritaires.
Le verrou de course ne dépend plus de l'ancien état de pause mémorisé lorsqu'on
reprend la partie par un clic dans le menu.

## Physique des personnages

La version 2026-10-20.2 intègre des sous-pas de physique et de collisions pour les
bipèdes. **60 Hz est actif par défaut** ; F2 permet de choisir 30, 60 ou 120 Hz.
Le choix se sauvegarde dans `biped_physics_hz`. La logique de jeu, l'IA, les
scripts et les véhicules conservent leur cadence précédente. Ce réglage est
un calcul physique subdivisé, pas un déblocage de toute la simulation.

Les entrées et sorties du noyau sont converties entre unités par tick original
et par sous-pas ; les accélérations reçoivent un facteur au carré. Les deux
lectures de gravité et la force de contact au sol utilisent un facteur local
au thread, sans changer la gravité globale. Les événements de contact sont
réunis avant le retour au jeu. Cette compilation est livrée pour les essais
de l'utilisateur, sans nouvelle session longue de test en jeu.

Les anciens réglages de sensibilité du stick ne sont pas directement comparables.
Le format `input_version = 2` repart donc à sensibilité 1, conserve les touches et
sauvegarde l'ancien fichier dans `pc-input.toml.analog.bak` à la première migration.

### Version 2026-10-20.3

F2 ajoute les options plein écran, remplissage par étirement, interpolation des
caméras de cinématiques et balancement de l'arme pendant la course. Ces choix
sont enregistrés avec les autres réglages. Le lanceur utilise le plein écran
sans bandes latérales par défaut.

Le balancement abaisse légèrement l'arme et applique une oscillation latérale et
verticale aux matrices finales des bras et de l'arme. Son intensité monte et
redescend progressivement. Il dépend de la course réellement appliquée au joueur
local, pas seulement de Maj enfoncé ; il s'arrête à l'arrêt, en menu et pendant
les cinématiques. La caméra et l'origine des tirs restent inchangées.

Livraison par compilation uniquement pour cette mise à jour, sans nouvelle
session prolongée de test en jeu, conformément à la demande de l'utilisateur.

## Vérification reproductible

### Version 2026-10-20.6

Le balancement de course s'arrête immédiatement en l'air, d'après le bit physique
airborne du bipède (+4CC, bit 0), également utilisé par la production de physique
`82D39578`. Il reprend progressivement au sol. Les contrôles de course ne
réappliquent plus leur accélération aérienne.

F3 bascule le ray tracing natif et affiche son état près des FPS. F2 permet de
choisir AO, reflets expérimentaux, rebonds de couleur et diagnostic de géométrie.
Le défaut de signature qui refusait la capture dans le jeu a été corrigé.

Le lanceur prépare une version d'une image du fichier Bink d'introduction (environ
33 ms au lieu de 44,5 s). La vidéo complète est sauvegardée dans `work/intro-backups`.
`Play-Halo.cmd --show-intro` la rétablit. Le ZIP/ISO d'origine reste intact. Le
conteneur court est décodé sans erreur par FFmpeg. Pour les séquences de jeu,
Entrée publie une demande dans le chemin normal de skip (`822CD790`, indicateur
`8376FD13`) seulement si le jeu indique qu'elles peuvent être passées.

### Version 2026-10-20.5

Le ray tracing natif s'active dans F2 avec « Ray tracing natif DXR : occlusion
ambiante ». Il est indépendant de ReShade et initialement désactivé. Le bouton
« Enregistrer » conserve son état, son intensité et sa portée. F2 affiche l'état
DXR et le nombre de passes 3D capturées. Le premier mode est l'occlusion ambiante,
avec capture réelle des triangles ; les réflexions et l'éclairage complet restent
à développer. La scène de contrôle GPU passe ; l'essai des scènes de Halo est
laissé à l'utilisateur.

### Version 2026-10-20.4

L'option « Interpolation vehicules et camera de suivi » dans F2 est activée par
défaut. Elle traite les poses des véhicules et la caméra du joueur assis à bord,
avec remise à zéro à l'entrée/sortie ou au changement de véhicule. Le réglage
est sauvegardé dans `pc-input.toml`. Le traitement de caméra reste désactivé
quand on joue à pied ; la cadence de simulation des véhicules reste à 30 Hz.

L'effet ReShade facultatif HaloSSRTGI se bascule avec F7 et se règle avec Home.
Il est désactivé initialement. Il faut une profondeur de scène exploitable :
sans elle, l'effet laisse l'image intacte. Ce mode n'implémente pas DXR matériel.

Depuis la racine du dépôt, avec le projet Halo local déjà compilé :

```powershell
& runtime/python/Scripts/python.exe modules/xbox-native/scripts/check_rex_controls.py
```

Cet essai console ne crée aucune fenêtre et ne lance pas le thread principal du
jeu. Il charge son XEX comme entrée et exécute les véritables fonctions GFx
recompilées sur des objets de test. Il vérifie déplacement, clic, relâchement,
molette, conversion des coordonnées, diffusion à deux films, préservation des
registres, absence de clic de menu en mode regard, correspondance avec
`NotifyMouseState`, isolation des curseurs virtuels, visée fractionnaire sans
rejeu et conservation du temps écoulé par le déblocage FPS. Il contrôle aussi les réglages
persistants, Échap/Start, le rendu du panneau dans un contexte ImGui sans fenêtre
et la présence de l'export de comptage FPS. Le reçu est `project/input-checks.json`.

Des essais séparés du jeu réel sur un bureau isolé ont mesuré plus de 270 FPS
dans le menu après correction, contre 29,98 avant, et vérifié par lecture GPU
qu'un clic sur « Extras » ouvre effectivement cet écran. Ils utilisent des copies
du profil sous `project/runtime-probes/`. La sensation de visée avec la souris
physique et la compatibilité de tous les écrans restent à apprécier en jeu.
L'essai final reprend aussi une sauvegarde de la mission « Halo » par clic dans
les menus et montre une rotation de caméra puis son retour pour deux déplacements
opposés. Sa médiane est de 184,88 FPS dans la scène observée. Voir le reçu
`project/pc-improvements.json` et le rapport ReXGlue pour les limites de cet essai.
