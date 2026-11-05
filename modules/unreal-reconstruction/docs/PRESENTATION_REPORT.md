# Anniversary — éclairage, impacts, audio et campagne

> Dernière correction : [COMBAT_TEST_FIXES.md](COMBAT_TEST_FIXES.md).


> État de la livraison précédente. La mise à jour suivante (ennemis, VFX, HUD,
> introduction et premier dropship A30) est décrite dans
> [ARRIVAL_FIXES.md](ARRIVAL_FIXES.md). Pour A30, ses limites remplacent les
> mentions de cinématiques différées ci-dessous. Les reçus JSON sont la
> référence pour les mesures de la dernière reconstruction.


Livraison locale vérifiée le 20 octobre 2026 avec Unreal Engine 5.8.3 sur `G:`.
Les corrections d'import de terrain et de végétation sont détaillées dans
[SURFACE_IMPORT_FIXES.md](SURFACE_IMPORT_FIXES.md), avec les captures avant/après
et les audits des buffers Unreal. Les contrôles ci-dessous ont été renouvelés
après ces corrections.
Le module reste indépendant de l'application CyDecompilator et de `xbox-native`.
Les entrées du jeu n'ont pas été modifiées. Sauvegarde avant cette intervention :
`work/a10/backups/20261020-041438`.

## Résultat vérifié

| Vérification | A10 | A30 |
|---|---:|---:|
| Contrôles de déplacement, combat, animation et réapparition | 31/31 | 31/31 |
| Contrôles de campagne, impacts, audio et checkpoints | 13/13 | 15/15 |
| Scripts source chargés | 185 | 139 |
| Opérations de script exécutées pendant le test | 8 563 | 22 394 |
| RMS PCM16 du mixage réellement enregistré | 11 818,91 | 1 675,51 |
| Sources lumineuses ponctuelles importées | 509 | 1 185 |
| Spots importés | 309 | 25 |
| Morceaux de carte, collisions invisibles comprises | 305 | 1 853 |
| Morceaux de collision masqués | 5 | 20 |

Les **30 tests Python passent**. Les audits Unreal des animations passent sur
les deux cartes. Les preuves des tests en jeu et de campagne ont été relues après
la dernière validation : les empreintes des sources, assets, DLL et données JSON
du projet correspondent aux résultats enregistrés. Aucun appel de scénario non
pris en charge n'a été rencontré pendant les démarrages testés.

## Éclairage et matériaux

Les lumières de test ont été remplacées par les positions, couleurs HDR, rayons
et cônes extraits de Saber. A10 ne reçoit pas de soleil artificiel ; A30 utilise
le soleil et le brouillard de sa scène. Les couleurs d'ambiance dans les six
directions sont converties en cubemaps HDR. L'exposition Unreal est calibrée à
partir de la plage de lumière des matériaux source : 22,625 pour A10, 33,84375
pour A30. Cette adaptation d'exposition n'est pas une courbe de tonemapping
originale retrouvée dans Saber.

Les normal maps, masques de réflexion et masques d'émission supplémentaires sont
importés. Les textures `_br` ne sont plus utilisées comme des couleurs RGB
émissives entières : cela rendait notamment le fusil rouge. Les canaux de lumière
et de direction sont conservés séparément des masques de terrain dans huit UV,
avec précision complète pour les meshes statiques.

Le décodage ARGB des couleurs statiques est corrigé et contrôlé dans les vrais
buffers Unreal : 653 sommets A10 et 1 849 sommets A30, avec aucun écart sur les
octets des masques. Les variantes de matériau des deux cartes sont séparées,
et les découpages de végétation/décals ainsi que le proxy d'ombre du lifepod
sont traités selon leur fonction. Voir le bilan d'import pour les limites.

Deux dispositions des couleurs de sommets sont prises en charge : le format
statique et l'ancien format dynamique inversent l'ordre couleur/direction.
Lire la direction comme une couleur rendait la végétation fluorescente.

Les surfaces `visibility_hidden` restent physiques mais ne sont plus dessinées
et ne projettent plus d'ombres. Les plaques rouges d'A30 étaient des surfaces
de collision de ce type. Les coques destinées au déplacement du joueur ne
bloquent plus les rayons des armes. Les effets restent sans collision.

## Impacts et audio

Les tirs produisent une trace sur les surfaces, des étincelles temporaires sans
collision, une réponse aux boucliers et des sons d'impact. Les cartes d'effet
emploient les textures Anniversary extraites. Les teintes de réponse sont pilotées
par le nouveau runtime Unreal ; il ne s'agit pas d'un port complet du système de
particules Saber.

**8 103 SoundWave** ont été importées depuis les banques Anniversary Xbox 360 :
armes, rechargement, coup de crosse, impacts, pas, bouclier, ambiance, musique et
dialogues français. Les ambiances sont sélectionnées par les régions et BSP
source ; les ambiances de tous les intérieurs et extérieurs ne jouent pas
simultanément. Le flag source « not a loop » est respecté.

Un nom peut désigner à la fois un son et une boucle dans les caches. Ces deux
types sont distingués pour éviter une récursion. Les enregistrements de test
mesurent le mixeur Unreal, et un WAV silencieux est refusé : la présence d'un
asset audio ou d'un événement de lecture n'est pas considérée comme une preuve
de son audible. Le test hors écran active explicitement son volume hors focus.

## Scénario et sauvegardes

Le module décode les **324 scripts** et leurs **192 globales**, avec les volumes
orientés, drapeaux, noms d'objets, conversations et commandes d'IA. L'interpréteur
respecte les attentes à 30 ticks par seconde, les réveils, les conditions et les
variables. Il pilote les activations de rencontres, les objectifs, les portes et
les conversations. Les personnages d'une rencontre inactive sont immobilisés
et masqués jusqu'à leur activation.

A30 possède son contrôle holographique Anniversary. **E** actionne son groupe de
scénario, notamment celui du pont lumineux. Les objets manipulés par le scénario
sont mobiles dans Unreal. Les cadavres ne sont plus considérés comme des cibles
vivantes et une animation figée est réactivée lors d'une réapparition de vague.

Les checkpoints enregistrent le joueur, ses munitions, les personnages, les
objets et portes, les globales, les piles de scripts, les commandes d'IA et les
états de conversation. **Entrée** réapparaît après la mort ; **F9** recharge un
checkpoint ; `-CyResume` permet de le charger au lancement. Les sauvegardes de
test sont séparées des sauvegardes normales sous `Saved/Validation/Campaign`.
L'affichage des objectifs est lisible et séparé du texte d'aide.

## Portée et limites

Les tests valident les débuts de mission et les fonctionnalités citées. **Ils ne
prouvent pas que les deux campagnes sont entièrement terminables.** Les routes
enregistrées de véhicules et certaines commandes tardives doivent encore être
converties. Les appels non reconnus et références d'objets non résolues sont
consignés dans les rapports ; les objets de cinématique exclus peuvent y figurer.
Les cinématiques et le tutoriel caméra complet restent volontairement sautés.

Le rendu utilise Unreal : BRDF, réponse directionnelle des lightmaps, volumes
de lumière négative, reflets locaux, masques de détail et certaines familles de
shaders ne reproduisent pas intégralement Saber. Les données sont conservées
pour poursuivre ce travail. Une référence de texture `white` non exportée reste
signalée dans l'import A30. Les archétypes humains sans modèle dédié continuent
à employer le Marine. La navigation est vérifiée près des départs de test, et
non sur des parcours complets de mission. Le bouclier énergétique du Jackal et
les comportements IA restent des adaptations du prototype.

Il n'y a donc aucune promesse de conversion universelle ou de reproduction
intégrale du jeu à ce stade. Tous les modèles, images et échantillons de jeu
utilisés ici proviennent d'Anniversary ; aucune substitution Classic n'a été
ajoutée.

## Fichiers pour tester et reprendre

- Projet : `work/a10/HaloA10/HaloA10.uproject`.
- Lancer : `Play-HaloA10.cmd` ou `Play-HaloA30.cmd`.
- Bilans : `work/a10/conversion-report.json` et
  `work/a10/missions/a30/conversion-report.json`.
- Captures : `work/a10/HaloA10/Saved/Validation/a10-campaign-start.png` et
  `a30-campaign-start.png` dans le même dossier.
- Audio réellement enregistré : `a10-audio-mix.wav` et `a30-audio-mix.wav` dans
  ce dossier.
- Preuves : `runtime-proof.json` et `campaign-proof.json` dans le dossier de
  travail de chaque mission ; toute modification du projet les invalide.
- Reprise des étapes : commandes du README et reçus horodatés sous
  `work/a10/logs`.

Ce bilan remplace les anciennes mentions indiquant que l'audio, les impacts et
les scripts de scénario étaient entièrement absents du prototype.
